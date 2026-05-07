"""
HP LaserJet M1132 MFP Scanner — Web App
Runs on localhost:5555, opens in browser.
Scanning done via PowerShell for reliable WIA device handling.

Self-healing strategy (defense in depth):
  1. Restart WIA service on startup (clears stale handles from previous run)
  2. Serialize /scan calls with a lock (prevents concurrent COM races)
  3. On scan failure: auto-restart WIA + retry once before reporting error
  4. Manual /reset endpoint + UI button as last-resort recovery
  5. Append every scan attempt to scan_log.txt for diagnostics
  6. PowerShell scan.ps1 explicitly releases all COM objects in finally
"""

import base64
import ctypes
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from PIL import Image

app = Flask(__name__)

# ── State ───────────────────────────────────────────────────────────
scanned_pages: list[bytes] = []
scan_lock = threading.Lock()              # prevents concurrent /scan calls
scan_counter = 0                          # diagnostic counter for the log
SCRIPT_DIR = Path(__file__).parent
SCAN_PS1 = SCRIPT_DIR / "scan.ps1"
SETTINGS_FILE = SCRIPT_DIR / "settings.json"
LOG_FILE = SCRIPT_DIR / "scan_log.txt"

DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Scans")
INTENT_MAP = {"color": 1, "grayscale": 2, "bw": 4}

# Proactive self-healing: the HP M1132 WIA driver is known to lock after ~10-15
# scans. Restart the WIA service before every Nth scan to stay under that limit.
SCANS_BEFORE_PROACTIVE_RESET = 10

# Error fragments that mean "scanner is locked/busy" — worth restarting WIA + retrying.
RECOVERABLE_ERRORS = (
    "busy",
    "0x80210006",      # WIA_ERROR_BUSY
    "0x80210007",      # WIA_ERROR_OFFLINE
    "0x8021000c",      # WIA_ERROR_DEVICE_LOCKED
    "device is in use",
    "no scanner found",
    "scanner is in use",
    "transfer cancelled",
)

# CREATE_NO_WINDOW so background PowerShell doesn't flash a console.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


# ── Logging ─────────────────────────────────────────────────────────

def log(msg: str):
    """Append a timestamped line to scan_log.txt and print to stdout."""
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}"
    print(f"[LOG] {line}")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ── Admin / WIA control ─────────────────────────────────────────────

def is_admin() -> bool:
    """Check if the Flask process has admin rights (needed for service restart)."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _sc(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sc"] + args,
        capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW,
    )


def restart_wia(reason: str = "manual") -> tuple[bool, str]:
    """Restart WIA. If the service refuses to stop (process holding handle),
    kill the svchost hosting it and start it back up."""
    if not is_admin():
        msg = "WIA restart skipped — app is not running as admin"
        log(f"wia_restart | {reason} | SKIPPED (no admin)")
        return False, msg

    try:
        # 1. Ask the service to stop. Don't fail if this errors — we'll check state next.
        _sc(["stop", "stisvc"])

        # 2. Poll up to 10s for the service to actually transition to STOPPED.
        stopped = False
        for _ in range(10):
            time.sleep(1)
            q = _sc(["query", "stisvc"])
            if "STOPPED" in q.stdout.upper():
                stopped = True
                break

        # 3. If still not stopped, find the host svchost PID and kill it.
        #    sc queryex outputs a "PID : <n>" line.
        if not stopped:
            qx = _sc(["queryex", "stisvc"])
            pid = None
            for line in qx.stdout.splitlines():
                s = line.strip()
                if s.upper().startswith("PID"):
                    _, _, val = s.partition(":")
                    val = val.strip()
                    if val.isdigit() and val != "0":
                        pid = val
                    break
            if pid:
                log(f"wia_restart | {reason} | stop hung — killing host PID {pid}")
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW,
                )
                time.sleep(2)
            else:
                log(f"wia_restart | {reason} | stop hung and no host PID found")

        # 4. Start the service. Error 1056 = already running, treat as success.
        start = _sc(["start", "stisvc"])
        out = (start.stdout + start.stderr).upper()
        if start.returncode == 0 or "1056" in out:
            log(f"wia_restart | {reason} | OK")
            time.sleep(1.5)
            return True, "WIA service restarted"
        err = (start.stderr or start.stdout).strip() or "unknown error"
        log(f"wia_restart | {reason} | FAILED start: {err}")
        return False, err
    except Exception as e:
        log(f"wia_restart | {reason} | EXCEPTION: {e}")
        return False, str(e)


# ── Cyber unplug/replug: escalation when WIA restart isn't enough ──
# The HP M1132 has a known firmware bug where the scanner endpoint
# stops responding after sleep or heavy use. WIA service restart
# alone doesn't always recover it — but a USB re-enumeration via
# Disable-PnpDevice/Enable-PnpDevice does. Equivalent to physically
# unplugging and replugging the USB cable.

def _find_scanner_instance_id() -> str | None:
    """Return the PnP InstanceId of the first WIA scanner, or None."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -Class Image -PresentOnly | "
             "Select-Object -First 1 -ExpandProperty InstanceId"],
            capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW,
        )
        return (result.stdout or "").strip() or None
    except Exception:
        return None


def reset_scanner_device(reason: str = "manual") -> bool:
    """Disable then re-enable the scanner PnP device.
    Functionally identical to USB reseat; resets the printer's USB endpoint."""
    if not is_admin():
        log(f"device_reset | {reason} | SKIPPED (no admin)")
        return False

    instance_id = _find_scanner_instance_id()
    if not instance_id:
        log(f"device_reset | {reason} | SKIPPED (no scanner found)")
        return False

    log(f"device_reset | {reason} | resetting {instance_id}")
    try:
        ps_safe = instance_id.replace("'", "''")
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Disable-PnpDevice -InstanceId '{ps_safe}' -Confirm:$false; "
             f"Start-Sleep 3; "
             f"Enable-PnpDevice -InstanceId '{ps_safe}' -Confirm:$false"],
            capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW,
        )
        time.sleep(3)  # let device come back up
        log(f"device_reset | {reason} | OK")
        return True
    except Exception as e:
        log(f"device_reset | {reason} | EXCEPTION: {e}")
        return False


# ── Settings ────────────────────────────────────────────────────────

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_settings(data: dict):
    current = load_settings()
    current.update(data)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2))


def get_save_dir() -> str:
    d = load_settings().get("save_dir", DEFAULT_SAVE_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def make_thumbnail(png_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(png_bytes))
    img.thumbnail((400, 566))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── Core scan operation (runs PowerShell once) ──────────────────────

# Tracks the in-flight scan subprocess so /reset can kill it if the
# scanner firmware locks up mid-Transfer.
_running_scan_proc: subprocess.Popen | None = None


def _kill_tree(pid: int) -> None:
    """taskkill /T /F kills the process AND all descendants. Use this instead
    of proc.kill() because PowerShell hangs in COM calls keep child handles
    open, which deadlocks proc.communicate() draining pipes."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=10, creationflags=NO_WINDOW,
        )
    except Exception as e:
        log(f"_kill_tree | PID {pid} | failed: {e}")


def _run_scan_once(dpi: int, intent: int) -> tuple[bool, str | None, str | None]:
    """Run scan.ps1 once. Returns (ok, output_path, error_msg).

    Implementation note: stdout goes to a file instead of subprocess.PIPE,
    because PIPE-based communicate() deadlocks if PowerShell's COM call
    hangs (child processes keep pipe handles open even after kill())."""
    global _running_scan_proc
    timestamp = datetime.now().strftime("%H%M%S%f")
    tmp = os.path.join(tempfile.gettempdir(), f"hp_scan_{timestamp}.bmp")
    out_file = os.path.join(tempfile.gettempdir(), f"hp_scan_{timestamp}.out")
    if os.path.exists(tmp):
        os.remove(tmp)

    log(f"scan exec | spawning powershell (dpi={dpi}, intent={intent})")
    out_handle = open(out_file, "w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(SCAN_PS1),
                "-DPI", str(dpi),
                "-ColorIntent", str(intent),
                "-OutputPath", tmp,
            ],
            stdout=out_handle,
            stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )
        _running_scan_proc = proc
        try:
            try:
                proc.wait(timeout=90)
                log(f"scan exec | powershell exited rc={proc.returncode}")
            except subprocess.TimeoutExpired:
                log(f"scan exec | TIMEOUT after 90s — killing PID {proc.pid} + tree")
                _kill_tree(proc.pid)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                return False, None, "timeout"
        finally:
            _running_scan_proc = None
    finally:
        try:
            out_handle.close()
        except Exception:
            pass

    try:
        with open(out_file, "r", encoding="utf-8", errors="replace") as f:
            stdout = f.read()
    except OSError:
        stdout = ""
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass

    output = (stdout or "").strip()
    log(f"scan exec | output: {output[:120]!r}")

    if output.startswith("ERROR:"):
        return False, None, output[6:].strip()
    if not output:
        return False, None, "killed by reset"
    if output != "OK" or not os.path.exists(tmp):
        return False, None, f"unexpected output: {output[:200]}"
    return True, tmp, None


def _is_recoverable(err: str) -> bool:
    el = (err or "").lower()
    return any(token in el for token in RECOVERABLE_ERRORS)


# ── Routes ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
def scan():
    global scan_counter

    # Single scan at a time — prevents concurrent COM races.
    if not scan_lock.acquire(blocking=False):
        return jsonify(ok=False, error="A scan is already in progress. Wait for it to finish.")

    try:
        data = request.json or {}
        dpi = int(data.get("dpi", 200))
        color = data.get("color", "grayscale")
        intent = INTENT_MAP.get(color, 2)

        # Proactive WIA restart every N scans — prevents the firmware lockup
        # that historically broke the app every few days.
        if scan_counter > 0 and scan_counter % SCANS_BEFORE_PROACTIVE_RESET == 0:
            log(f"proactive_reset | {scan_counter} scans since last restart — refreshing WIA")
            restart_wia(reason=f"proactive every {SCANS_BEFORE_PROACTIVE_RESET}")

        scan_counter += 1
        n = scan_counter
        log(f"scan {n} | start | dpi={dpi} color={color}")

        t0 = time.time()
        ok, tmp, err = _run_scan_once(dpi, intent)
        dt = time.time() - t0

        # Auto-recovery ladder for the M1132 firmware lockup:
        #   tier 1: WIA service restart + retry
        #   tier 2: device re-enumeration (Disable/Enable PnP) + retry
        if not ok and _is_recoverable(err or ""):
            log(f"scan {n} | FAILED ({dt:.1f}s): {err} — tier 1 recovery (WIA)")
            restart_wia(reason=f"scan {n} failure")

            t0 = time.time()
            ok, tmp, err = _run_scan_once(dpi, intent)
            dt = time.time() - t0

            if not ok and _is_recoverable(err or ""):
                log(f"scan {n} | tier 1 retry FAILED ({dt:.1f}s): {err} — tier 2 (device reset)")
                reset_scanner_device(reason=f"scan {n} second failure")

                t0 = time.time()
                ok, tmp, err = _run_scan_once(dpi, intent)
                dt = time.time() - t0

            if ok:
                log(f"scan {n} | recovery OK ({dt:.1f}s)")
            else:
                log(f"scan {n} | all recovery failed ({dt:.1f}s): {err}")

        if not ok:
            user_err = err or "unknown error"
            if "timeout" in user_err.lower():
                user_err = "Scan timed out. Try the Reset Scanner button, or power cycle the printer."
            return jsonify(ok=False, error=user_err)

        # Convert BMP → PNG, append to session pages.
        try:
            img = Image.open(tmp)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            img.close()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

        scanned_pages.append(png_bytes)
        page_num = len(scanned_pages)
        log(f"scan {n} | OK ({dt:.1f}s) | page {page_num} | {len(png_bytes)} bytes")

        return jsonify(
            ok=True,
            page=page_num,
            thumbnail=f"data:image/png;base64,{make_thumbnail(png_bytes)}",
        )

    finally:
        scan_lock.release()


@app.route("/reset", methods=["POST"])
def reset():
    """Manual recovery: kill any in-flight scan and restart the WIA service.
    Bypasses the scan lock — the whole point of this button is that the user
    presses it because the scanner is hung."""
    log("manual /reset | requested")

    # 1. If a scan is in flight, kill its whole PowerShell process tree.
    # /scan handler's finally block will release scan_lock once Popen returns.
    proc = _running_scan_proc
    if proc is not None and proc.poll() is None:
        log(f"manual /reset | killing in-flight scan process tree PID {proc.pid}")
        _kill_tree(proc.pid)
        time.sleep(1)

    # 2. Restart WIA — does NOT need scan_lock; it's an OS-level operation.
    ok, msg = restart_wia(reason="manual /reset")

    # 3. Always also do a device re-enumeration. Users press Reset because
    #    something is genuinely broken — the extra ~5s is worth the higher
    #    success rate for M1132 firmware lockups.
    if ok:
        reset_scanner_device(reason="manual /reset")
        return jsonify(ok=True, message="Scanner reset (WIA service + USB device).")
    if "not running as admin" in msg.lower():
        return jsonify(
            ok=False,
            error=(
                "Cannot restart scanner — the app is not running as administrator.\n\n"
                "Close this window, right-click 'СТАРТИРАЙ СКЕНЕР.bat', "
                "and choose 'Run as administrator'."
            ),
        )
    return jsonify(ok=False, error=msg)


@app.route("/pages", methods=["GET"])
def get_pages():
    thumbnails = [f"data:image/png;base64,{make_thumbnail(b)}" for b in scanned_pages]
    return jsonify(ok=True, pages=thumbnails)


@app.route("/delete-page", methods=["POST"])
def delete_page():
    data = request.json or {}
    idx = data.get("index", -1)
    if 0 <= idx < len(scanned_pages):
        scanned_pages.pop(idx)
        return jsonify(ok=True, remaining=len(scanned_pages))
    return jsonify(ok=False, error="Invalid page index")


@app.route("/clear", methods=["POST"])
def clear():
    scanned_pages.clear()
    return jsonify(ok=True)


@app.route("/save-pdf", methods=["POST"])
def save_pdf():
    if not scanned_pages:
        return jsonify(ok=False, error="No pages scanned")

    data = request.json or {}
    filename = data.get("filename", "").strip()
    if not filename:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"scan_{timestamp}"
    if not filename.endswith(".pdf"):
        filename += ".pdf"

    save_dir = get_save_dir()
    filepath = os.path.join(save_dir, filename)

    try:
        images = [Image.open(io.BytesIO(b)).convert("RGB") for b in scanned_pages]
        images[0].save(filepath, "PDF", save_all=True, append_images=images[1:])
        scanned_pages.clear()
        return jsonify(ok=True, path=filepath, filename=filename)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/quick-save", methods=["POST"])
def quick_save():
    """Save immediately with auto-generated filename, no dialog."""
    if not scanned_pages:
        return jsonify(ok=False, error="No pages scanned")

    save_dir = get_save_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"scan_{timestamp}.pdf"
    filepath = os.path.join(save_dir, filename)

    try:
        images = [Image.open(io.BytesIO(b)).convert("RGB") for b in scanned_pages]
        images[0].save(filepath, "PDF", save_all=True, append_images=images[1:])
        scanned_pages.clear()
        return jsonify(ok=True, path=filepath, filename=filename)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/save-images", methods=["POST"])
def save_images():
    """Save each page as a separate PNG file."""
    if not scanned_pages:
        return jsonify(ok=False, error="No pages scanned")

    save_dir = get_save_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    saved = []
    try:
        for i, png_bytes in enumerate(scanned_pages):
            fname = f"scan_{timestamp}_p{i+1}.png"
            fpath = os.path.join(save_dir, fname)
            with open(fpath, "wb") as f:
                f.write(png_bytes)
            saved.append(fname)
        scanned_pages.clear()
        return jsonify(ok=True, files=saved, folder=save_dir)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/get-save-dir", methods=["GET"])
def get_save_dir_route():
    return jsonify(ok=True, path=get_save_dir())


@app.route("/set-save-dir", methods=["POST"])
def set_save_dir_route():
    """Set save directory. Uses Windows folder picker via PowerShell."""
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$d.Description = 'Choose folder for scanned files'; "
                f"$d.SelectedPath = '{get_save_dir().replace(chr(39), chr(39)+chr(39))}'; "
                "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath } "
                "else { Write-Output 'CANCEL' }"
            ],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=NO_WINDOW,
        )
        folder = result.stdout.strip()
        if folder and folder != "CANCEL":
            save_settings({"save_dir": folder})
            return jsonify(ok=True, path=folder)
        return jsonify(ok=False, error="Cancelled")
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/open-folder", methods=["POST"])
def open_folder():
    try:
        os.startfile(get_save_dir())
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route("/open-file", methods=["POST"])
def open_file():
    data = request.json or {}
    path = data.get("path", "")
    if path and os.path.exists(path):
        try:
            os.startfile(path)
            return jsonify(ok=True)
        except Exception as e:
            return jsonify(ok=False, error=str(e))
    return jsonify(ok=False, error="File not found")


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser

    log("=" * 50)
    log(f"app start | admin={is_admin()}")

    # Fresh WIA state every launch — clears stale handles from prior session.
    # Run in a background thread so a hung Stop doesn't delay the Flask server.
    if is_admin():
        threading.Thread(target=restart_wia, args=("startup",), daemon=True).start()
    else:
        log("startup | not admin — auto-recovery DISABLED. Re-run as admin for self-healing.")
        print("\n  ⚠️  Not running as administrator.")
        print("  Auto-recovery is disabled. Reset Scanner button will not work.")
        print("  Right-click 'СТАРТИРАЙ СКЕНЕР.bat' and choose 'Run as administrator'.\n")

    port = 5555
    url = f"http://localhost:{port}"
    print(f"\n  HP Scanner running at: {url}\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
