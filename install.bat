@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem ==========================================================================
rem  chezzControl installer
rem    1) Find Python 3.10+
rem    2) If missing, install Python 3.12 (winget first, then python.org)
rem    3) Create the project virtual environment (.venv)
rem    4) Install libraries from requirements.txt
rem  NOTE: keep this file ASCII only. Korean text breaks cmd.exe parsing.
rem ==========================================================================

set "PY_VERSION=3.12.10"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-amd64.exe"
set "PY_USER_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "PYTHON="

echo ============================================
echo   chezzControl setup
echo ============================================
echo.

echo [1/4] Looking for Python...
call :FindPython
if defined PYTHON (
    echo       Found: !PYTHON!
    goto :MakeVenv
)
echo       Python not found. Installing...
echo.

echo [2/4] Installing Python %PY_VERSION% ... (this can take a few minutes)
where winget > nul 2>&1
if not errorlevel 1 (
    echo       Using winget.
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
)

call :FindPython
if not defined PYTHON (
    echo       winget did not work. Downloading from python.org...
    set "PY_INSTALLER=%TEMP%\python-%PY_VERSION%-amd64.exe"
    curl -L --fail -o "!PY_INSTALLER!" "%PY_URL%"
    if errorlevel 1 (
        echo [ERROR] Could not download the Python installer. Check your internet connection.
        goto :Error
    )
    rem /quiet = no window, InstallAllUsers=0 = current user only (no admin needed)
    "!PY_INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
    del "!PY_INSTALLER!" > nul 2>&1
    call :FindPython
)

if not defined PYTHON (
    echo [ERROR] Python installation failed.
    echo         Install it from https://www.python.org/downloads/
    echo         and CHECK "Add python.exe to PATH" on the first screen, then run this again.
    goto :Error
)
echo       Installed: !PYTHON!
echo.

:MakeVenv
echo [3/4] Preparing virtual environment (.venv)...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" > nul 2>&1
    if errorlevel 1 (
        echo       Existing .venv is broken. Recreating...
        rmdir /s /q ".venv"
    ) else (
        echo       Already exists.
    )
)
if not exist ".venv\Scripts\python.exe" (
    "!PYTHON!" -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create .venv
        goto :Error
    )
    echo       Created.
)
echo.

echo [4/4] Installing libraries...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo [ERROR] Library installation failed. Check your internet connection.
    goto :Error
)

echo.
echo ============================================
echo   Setup complete. Now run run.bat
echo ============================================
if /i not "%~1"=="/nopause" pause
exit /b 0

:Error
echo.
pause
exit /b 1


rem --------------------------------------------------------------------------
rem  :FindPython - put a working Python 3.10+ path into PYTHON.
rem  Windows may have a fake "python" that only opens the Store,
rem  so we actually run it and check the version.
rem --------------------------------------------------------------------------
:FindPython
set "PYTHON="
for %%C in ("py -3" "python") do (
    if not defined PYTHON (
        %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" > nul 2>&1
        if not errorlevel 1 (
            for /f "delims=" %%P in ('%%~C -c "import sys; print(sys.executable)"') do set "PYTHON=%%P"
        )
    )
)
rem Just installed and PATH not refreshed yet: check the default install folder.
if not defined PYTHON if exist "%PY_USER_EXE%" set "PYTHON=%PY_USER_EXE%"
exit /b 0
