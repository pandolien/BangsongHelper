@echo off
cd /d "%~dp0"

rem NOTE: keep this file ASCII only. Korean text breaks cmd.exe parsing.
rem This is the real launcher. Double-click run.bat (it updates first, then calls this file).

rem 1) First run or libraries missing -> run install.bat (installs Python too if needed)
if not exist ".venv\Scripts\python.exe" goto :Install
".venv\Scripts\python.exe" -c "import socketio, requests, PySide6" 2> nul
if errorlevel 1 goto :Install
goto :Run

:Install
echo [SETUP] Running install.bat first...
call "%~dp0install.bat" /nopause
if errorlevel 1 (
    echo [ERROR] Setup failed. Check the messages above.
    pause
    exit /b 1
)

:Run
rem 2) Start the program (add a command like "run.bat status" for CLI mode,
rem    or "run.bat --test" to use data\init_test.json instead of data\init.json)
".venv\Scripts\python.exe" main.py %*
set "EXIT_CODE=%errorlevel%"
rem When double-clicked and something went wrong, keep the window open to read the error.
if not "%EXIT_CODE%"=="0" if "%~1"=="" pause
if not "%EXIT_CODE%"=="0" if /i "%~1"=="--test" if "%~2"=="" pause
exit /b %EXIT_CODE%
