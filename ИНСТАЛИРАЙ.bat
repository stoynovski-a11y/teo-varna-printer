@echo off
echo ============================================
echo   HP Scanner - Install
echo ============================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is NOT installed!
    echo.
    echo 1. Go to https://www.python.org/downloads/
    echo 2. Download and install Python
    echo 3. CHECK "Add Python to PATH" during install!
    echo 4. Restart the computer
    echo 5. Run this file again
    echo.
    pause
    exit /b 1
)

echo Python found:
python --version
echo.
echo Installing packages...
echo.

pip install flask pywin32 Pillow

echo.
echo ============================================
echo   Done! Now double-click START SCANNER.bat
echo ============================================
echo.
pause
