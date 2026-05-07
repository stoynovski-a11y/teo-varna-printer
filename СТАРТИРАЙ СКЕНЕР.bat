@echo off
chcp 65001 >nul

REM ------------------------------------------------------------------
REM  HP Скенер - launcher
REM  - Self-elevates to admin (so app can restart WIA service)
REM  - Auto-updates code from GitHub on every launch (silent if offline)
REM  - Starts Flask app
REM ------------------------------------------------------------------

REM ---- Self-elevate: if not admin, relaunch with UAC prompt ----
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Иска се администраторски достъп...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================
echo    HP Скенер - стартиране (Admin)
echo ============================================
echo.

cd /d "%~dp0"

REM ---- Auto-update from GitHub (skip if offline) ----
echo [..] Проверка за обновяване...
set "ZIP_URL=https://github.com/stoynovski-a11y/teo-varna-printer/archive/refs/heads/main.zip"
set "ZIP_FILE=%TEMP%\hpscanner-update.zip"
set "EXTRACT_DIR=%TEMP%\hpscanner-update"

powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_FILE%' -TimeoutSec 10 -ErrorAction Stop } catch { exit 1 }" 2>nul
if %errorlevel% equ 0 (
    if exist "%EXTRACT_DIR%" rmdir /s /q "%EXTRACT_DIR%"
    powershell -NoProfile -Command "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%EXTRACT_DIR%' -Force" 2>nul
    if exist "%EXTRACT_DIR%\teo-varna-printer-main\app.py" (
        REM Update only the app code; leave the .bat scripts and user data alone.
        robocopy "%EXTRACT_DIR%\teo-varna-printer-main" "%~dp0" app.py scan.ps1 requirements.txt /NFL /NDL /NJH /NJS /NC /NS >nul
        robocopy "%EXTRACT_DIR%\teo-varna-printer-main\templates" "%~dp0templates" /E /NFL /NDL /NJH /NJS /NC /NS >nul
        echo [OK] Обновено до последната версия.
    )
    del "%ZIP_FILE%" 2>nul
    rmdir /s /q "%EXTRACT_DIR%" 2>nul
) else (
    echo [!] Няма интернет - стартирам с локалната версия.
)
echo.

REM ---- Sanity check Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python не е намерен. Стартирай ИНСТАЛАЦИЯ.bat
    pause
    exit /b 1
)

echo ============================================
echo Скенерът се отваря на: http://localhost:5555
echo НЕ затваряй този прозорец докато сканираш!
echo ============================================
echo.

python app.py

if %errorlevel% neq 0 (
    echo.
    echo Нещо се обърка. Стартирай отново ИНСТАЛАЦИЯ.bat
    echo.
    pause
)
