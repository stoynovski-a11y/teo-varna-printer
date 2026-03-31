"""
HP LaserJet M1132 MFP Scanner — Web App
Runs on localhost:5555, opens in browser.
Scanning done via PowerShell for reliable WIA device handling.
"""

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from PIL import Image

app = Flask(__name__)

# ── State ───────────────────────────────────────────────────────────
scanned_pages: list[bytes] = []  # PNG bytes for each page
SCRIPT_DIR = Path(__file__).parent
SCAN_PS1 = SCRIPT_DIR / "scan.ps1"
SETTINGS_FILE = SCRIPT_DIR / "settings.json"

# Default save directory
DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Scans")

# WIA intent constants
INTENT_MAP = {"color": 1, "grayscale": 2, "bw": 4}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text())
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


# ── Routes ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
def scan():
    data = request.json or {}
    dpi = int(data.get("dpi", 200))
    color = data.get("color", "grayscale")
    intent = INTENT_MAP.get(color, 2)

    tmp = os.path.join(tempfile.gettempdir(), f"hp_scan_{len(scanned_pages)}.bmp")

    print(f"[SCAN] Starting scan at {dpi} DPI, intent={intent}...")

    try:
        result = subprocess.run(
            [
                "powershell", "-ExecutionPolicy", "Bypass",
                "-File", str(SCAN_PS1),
                "-DPI", str(dpi),
                "-ColorIntent", str(intent),
                "-OutputPath", tmp,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = result.stdout.strip()
        print(f"[SCAN] PowerShell output: {output}")

        if result.stderr:
            print(f"[SCAN] PowerShell stderr: {result.stderr.strip()}")

        if output.startswith("ERROR:"):
            error_msg = output[6:]
            print(f"[SCAN] Scan failed: {error_msg}")
            return jsonify(ok=False, error=error_msg)

        if output != "OK" or not os.path.exists(tmp):
            return jsonify(ok=False, error=f"Unexpected result: {output}")

        file_size = os.path.getsize(tmp)
        print(f"[SCAN] BMP saved: {file_size} bytes")

        img = Image.open(tmp)
        print(f"[SCAN] Image: {img.size}, mode={img.mode}")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        img.close()
        os.remove(tmp)

        scanned_pages.append(png_bytes)
        n = len(scanned_pages)
        print(f"[SCAN] Page {n} saved ({len(png_bytes)} bytes PNG)")

        thumb_b64 = make_thumbnail(png_bytes)
        print(f"[SCAN] Done!")

        return jsonify(
            ok=True,
            page=n,
            thumbnail=f"data:image/png;base64,{thumb_b64}",
        )

    except subprocess.TimeoutExpired:
        print("[SCAN] ERROR: Scan timed out after 120 seconds")
        return jsonify(ok=False, error="Scan timed out. Try turning the printer off and on.")
    except Exception as e:
        print(f"[SCAN] ERROR: {e}")
        return jsonify(ok=False, error=str(e))


@app.route("/pages", methods=["GET"])
def get_pages():
    thumbnails = []
    for png_bytes in scanned_pages:
        thumbnails.append(f"data:image/png;base64,{make_thumbnail(png_bytes)}")
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
        images = []
        for png_bytes in scanned_pages:
            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            images.append(img)

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
        images = []
        for png_bytes in scanned_pages:
            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            images.append(img)

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
                "powershell", "-ExecutionPolicy", "Bypass", "-Command",
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$d.Description = 'Choose folder for scanned files'; "
                f"$d.SelectedPath = '{get_save_dir()}'; "
                "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath } "
                "else { Write-Output 'CANCEL' }"
            ],
            capture_output=True,
            text=True,
            timeout=60,
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
    import threading

    port = 5555
    url = f"http://localhost:{port}"
    print(f"\n  HP Scanner running at: {url}\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
