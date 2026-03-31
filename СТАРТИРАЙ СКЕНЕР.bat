@echo off
echo ============================================
echo   HP Scanner - Starting...
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
