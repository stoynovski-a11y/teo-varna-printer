@echo off
:: ------------------------------------------------------------------
::  HP Scanner launcher — self-elevates to admin so the app can
::  restart the WIA service automatically when the scanner gets stuck.
:: ------------------------------------------------------------------

:: Self-elevate: if not admin, relaunch this same .bat with UAC prompt.
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Requesting administrator rights so the scanner can self-recover...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================
echo   HP Scanner - Starting (Admin)
echo ============================================
echo.
echo The scanner will open in your browser.
echo DO NOT close this window while scanning!
echo.

cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Run INSTALL first!
    pause
    exit /b 1
)

python app.py

if %errorlevel% neq 0 (
    echo.
    echo Something went wrong. Try running INSTALL first.
    echo.
    pause
)
