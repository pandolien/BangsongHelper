@echo off
setlocal
cd /d "%~dp0"

rem ==========================================================================
rem  Build chzzkControl.exe (PyInstaller)
rem    Result: dist\chzzkControl\chzzkControl.exe
rem            dist\chzzkControl\data\  (init_upload.json, game_map.txt only)
rem    Your data\init.json (keys / tokens) is NEVER copied.
rem  NOTE: keep this file ASCII only. Korean text breaks cmd.exe parsing.
rem ==========================================================================

if not exist ".venv\Scripts\python.exe" (
    echo [SETUP] Running install.bat first...
    call "%~dp0install.bat" /nopause
    if errorlevel 1 goto :Error
)

echo [1/3] Installing PyInstaller...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check "pyinstaller>=6.6"
if errorlevel 1 goto :Error

echo [2/3] Building exe... (takes a minute)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean chzzkControl.spec
if errorlevel 1 goto :Error

echo [3/3] Copying data templates and docs...
set "OUT=dist\chzzkControl"
if not exist "%OUT%\data" mkdir "%OUT%\data"
copy /y "data\init_upload.json" "%OUT%\data\" > nul
copy /y "data\game_map.txt" "%OUT%\data\" > nul
copy /y "README.md" "%OUT%\" > nul
copy /y "docs\*.pdf" "%OUT%\" > nul

echo.
echo ============================================
echo   Done: %OUT%\chzzkControl.exe
echo   Zip the whole "%OUT%" folder to share it.
echo ============================================
if /i not "%~1"=="/nopause" pause
exit /b 0

:Error
echo [ERROR] Build failed. Check the messages above.
if /i not "%~1"=="/nopause" pause
exit /b 1
