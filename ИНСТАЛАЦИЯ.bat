@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo    HP Скенер - Инсталация
echo ============================================
echo.

REM ---- 1. Check Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python не е инсталиран.
    echo.
    echo    1. Ще отворя страницата за изтегляне.
    echo    2. Свали и инсталирай Python.
    echo    3. ВАЖНО: сложи отметка "Add Python to PATH".
    echo    4. Рестартирай компютъра.
    echo    5. Стартирай отново този файл.
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python:
python --version
echo.

REM ---- 2. Pick install location ----
set "INSTALL_DIR=%LOCALAPPDATA%\HPScanner"
echo Инсталация в: %INSTALL_DIR%
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
echo.

REM ---- 3. Download latest code from GitHub as ZIP ----
set "ZIP_URL=https://github.com/stoynovski-a11y/teo-varna-printer/archive/refs/heads/main.zip"
set "ZIP_FILE=%TEMP%\hpscanner.zip"
set "EXTRACT_DIR=%TEMP%\hpscanner-extract"

echo [..] Сваляне на най-новата версия от GitHub...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_FILE%'"
if %errorlevel% neq 0 (
    echo [X] Неуспешно сваляне. Провери интернет връзката.
    pause
    exit /b 1
)
echo [OK] Свалено.

if exist "%EXTRACT_DIR%" rmdir /s /q "%EXTRACT_DIR%"
echo [..] Разархивиране...
powershell -NoProfile -Command "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%EXTRACT_DIR%' -Force"
echo [OK] Разархивирано.
echo.

REM ---- 4. Copy files (preserve user's data folder + settings) ----
echo [..] Копиране в %INSTALL_DIR%...
robocopy "%EXTRACT_DIR%\teo-varna-printer-main" "%INSTALL_DIR%" /E /XD data /XF settings.json /NFL /NDL /NJH /NJS /NC /NS >nul
echo [OK] Копирано.
echo.

REM ---- 5. Install Python packages ----
echo [..] Инсталиране на Python пакети...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install --upgrade -r "%INSTALL_DIR%\requirements.txt"
if %errorlevel% neq 0 (
    echo [X] Неуспешна инсталация на пакети.
    pause
    exit /b 1
)
echo [OK] Пакети инсталирани.
echo.

REM ---- 6. Create Desktop shortcut with "Run as administrator" flag ----
echo [..] Създаване на пряк път на работния плот...
set "DESKTOP_LNK=%USERPROFILE%\Desktop\HP Скенер.lnk"
set "TARGET=%INSTALL_DIR%\СТАРТИРАЙ СКЕНЕР.bat"
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%DESKTOP_LNK%'); $sc.TargetPath = '%TARGET%'; $sc.WorkingDirectory = '%INSTALL_DIR%'; $sc.IconLocation = 'imageres.dll,108'; $sc.Save(); $b = [IO.File]::ReadAllBytes('%DESKTOP_LNK%'); $b[0x15] = $b[0x15] -bor 0x20; [IO.File]::WriteAllBytes('%DESKTOP_LNK%', $b)"
echo [OK] Икона на работния плот: HP Скенер
echo.

REM ---- 7. Auto-launch on Windows boot via Startup folder ----
echo [..] Настройка за автоматично стартиране при включване на Windows...
set "STARTUP_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\HP Скенер.lnk"
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%STARTUP_LNK%'); $sc.TargetPath = '%TARGET%'; $sc.WorkingDirectory = '%INSTALL_DIR%'; $sc.WindowStyle = 7; $sc.Save(); $b = [IO.File]::ReadAllBytes('%STARTUP_LNK%'); $b[0x15] = $b[0x15] -bor 0x20; [IO.File]::WriteAllBytes('%STARTUP_LNK%', $b)"
echo [OK] Ще стартира автоматично при всяко включване.
echo.

REM ---- 8. Cleanup ----
del "%ZIP_FILE%" 2>nul
rmdir /s /q "%EXTRACT_DIR%" 2>nul

echo ============================================
echo    Готово!
echo ============================================
echo.
echo  - Икона на работния плот: HP Скенер
echo  - Стартира автоматично при всяко включване на Windows
echo  - Скенерът се отваря в браузъра на: http://localhost:5555
echo.
echo Натисни клавиш за да затвориш...
pause >nul
