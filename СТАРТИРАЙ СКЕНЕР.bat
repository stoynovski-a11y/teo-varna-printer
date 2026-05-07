@echo off
REM ------------------------------------------------------------------
REM  HP Scanner - launcher
REM  - Self-elevates to admin (so app can restart WIA service)
REM  - Auto-updates code from GitHub on each launch (silent if offline)
REM  - Starts Flask app
REM ------------------------------------------------------------------

REM ---- Self-elevate: if not admin, relaunch with UAC prompt ----
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================
echo    HP Scanner - starting (Admin)
echo ============================================
echo.

cd /d "%~dp0"

REM ---- Disable USB Selective Suspend on the active power plan ----
REM Sleeping the USB endpoint is the #1 trigger of the M1132 firmware
REM lockup. Idempotent — safe to run every launch.
REM   2a737441-... = "USB settings" subgroup
REM   48e6b7a6-... = "USB selective suspend setting"
REM   value 0      = Disabled
powercfg -setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0 >nul 2>&1
powercfg -setdcvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0 >nul 2>&1
powercfg -setactive SCHEME_CURRENT >nul 2>&1

REM ---- Auto-update from GitHub (skip silently if offline) ----
echo [..] Checking for updates...
set "ZIP_URL=https://github.com/stoynovski-a11y/teo-varna-printer/archive/refs/heads/main.zip"
set "ZIP_FILE=%TEMP%\hpscanner-update.zip"
set "EXTRACT_DIR=%TEMP%\hpscanner-update"

powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_FILE%' -TimeoutSec 10 -ErrorAction Stop } catch { exit 1 }" 2>nul
if %errorlevel% equ 0 (
    if exist "%EXTRACT_DIR%" rmdir /s /q "%EXTRACT_DIR%"
    powershell -NoProfile -Command "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%EXTRACT_DIR%' -Force" 2>nul
    if exist "%EXTRACT_DIR%\teo-varna-printer-main\app.py" (
        robocopy "%EXTRACT_DIR%\teo-varna-printer-main" "%~dp0" app.py scan.ps1 requirements.txt /NFL /NDL /NJH /NJS /NC /NS >nul
        robocopy "%EXTRACT_DIR%\teo-varna-printer-main\templates" "%~dp0templates" /E /NFL /NDL /NJH /NJS /NC /NS >nul
        echo [OK] Updated to latest version.
    )
    del "%ZIP_FILE%" 2>nul
    rmdir /s /q "%EXTRACT_DIR%" 2>nul
) else (
    echo [!] No internet - starting with local version.
)
echo.

REM ---- Sanity check Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python not found. Run INSTALL.bat first.
    pause
    exit /b 1
)

echo ============================================
echo Scanner running at: http://localhost:5555
echo Do NOT close this window while scanning!
echo ============================================
echo.

python app.py

if %errorlevel% neq 0 (
    echo.
    echo Something went wrong. Try running INSTALL.bat again.
    echo.
    pause
)
