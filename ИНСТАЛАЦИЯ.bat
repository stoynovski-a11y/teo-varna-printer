@echo off
setlocal enabledelayedexpansion

echo ============================================
echo    HP Scanner - Install
echo ============================================
echo.

REM ---- 1. Check Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python is not installed.
    echo.
    echo    1. Opening Python download page...
    echo    2. Download and install Python.
    echo    3. IMPORTANT: tick "Add Python to PATH" during install.
    echo    4. Restart your computer.
    echo    5. Run this file again.
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python found:
python --version
echo.

REM ---- 2. Pick install location ----
set "INSTALL_DIR=%LOCALAPPDATA%\HPScanner"
echo Installing to: %INSTALL_DIR%
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
echo.

REM ---- 3. Download latest code from GitHub as ZIP ----
set "ZIP_URL=https://github.com/stoynovski-a11y/teo-varna-printer/archive/refs/heads/main.zip"
set "ZIP_FILE=%TEMP%\hpscanner.zip"
set "EXTRACT_DIR=%TEMP%\hpscanner-extract"

echo [..] Downloading latest version from GitHub...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_FILE%'"
if %errorlevel% neq 0 (
    echo [X] Download failed. Check your internet connection.
    pause
    exit /b 1
)
echo [OK] Downloaded.

if exist "%EXTRACT_DIR%" rmdir /s /q "%EXTRACT_DIR%"
echo [..] Extracting...
powershell -NoProfile -Command "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%EXTRACT_DIR%' -Force"
echo [OK] Extracted.
echo.

REM ---- 4. Copy files (preserve user data folder + settings) ----
echo [..] Copying to %INSTALL_DIR%...
robocopy "%EXTRACT_DIR%\teo-varna-printer-main" "%INSTALL_DIR%" /E /XD data /XF settings.json /NFL /NDL /NJH /NJS /NC /NS >nul
echo [OK] Copied.
echo.

REM ---- 5. Install Python packages ----
echo [..] Installing Python packages...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install --upgrade -r "%INSTALL_DIR%\requirements.txt"
if %errorlevel% neq 0 (
    echo [X] Package installation failed.
    pause
    exit /b 1
)
echo [OK] Packages installed.
echo.

REM ---- 6. Create Desktop shortcut with "Run as administrator" flag ----
echo [..] Creating desktop shortcut...
set "DESKTOP_LNK=%USERPROFILE%\Desktop\HP Scanner.lnk"
set "TARGET=%INSTALL_DIR%\START SCANNER.bat"
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%DESKTOP_LNK%'); $sc.TargetPath = '%TARGET%'; $sc.WorkingDirectory = '%INSTALL_DIR%'; $sc.IconLocation = 'imageres.dll,108'; $sc.Save(); $b = [IO.File]::ReadAllBytes('%DESKTOP_LNK%'); $b[0x15] = $b[0x15] -bor 0x20; [IO.File]::WriteAllBytes('%DESKTOP_LNK%', $b)"
echo [OK] Desktop icon: HP Scanner
echo.

REM ---- 7. Auto-launch on Windows boot via Startup folder ----
echo [..] Setting up auto-launch on Windows boot...
set "STARTUP_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\HP Scanner.lnk"
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%STARTUP_LNK%'); $sc.TargetPath = '%TARGET%'; $sc.WorkingDirectory = '%INSTALL_DIR%'; $sc.WindowStyle = 7; $sc.Save(); $b = [IO.File]::ReadAllBytes('%STARTUP_LNK%'); $b[0x15] = $b[0x15] -bor 0x20; [IO.File]::WriteAllBytes('%STARTUP_LNK%', $b)"
echo [OK] Will auto-launch on each Windows boot.
echo.

REM ---- 8. Cleanup ----
del "%ZIP_FILE%" 2>nul
rmdir /s /q "%EXTRACT_DIR%" 2>nul

echo ============================================
echo    Done!
echo ============================================
echo.
echo  - Desktop icon: HP Scanner
echo  - Auto-launches on every Windows boot
echo  - Scanner opens in browser at: http://localhost:5555
echo.
echo Press any key to close...
pause >nul
