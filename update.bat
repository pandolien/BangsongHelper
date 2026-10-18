@echo off
setlocal
cd /d "%~dp0"

rem ==========================================================================
rem  BangsongHelper updater
rem    - Downloads the newest program files with git, KEEPING your settings
rem      (data\init.json, donation / mission records, Log folder).
rem    - Needs a folder made with "git clone" (a zip download cannot update itself).
rem  NOTE: keep this file ASCII only. Korean text breaks cmd.exe parsing.
rem ==========================================================================

echo ============================================
echo   BangsongHelper update
echo ============================================
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo [ERROR] git is not installed. Install Git for Windows, or download the new version manually.
    goto :End
)
if not exist ".git" (
    echo [ERROR] This folder was not made with "git clone", so it cannot update itself.
    echo         Download the new version into a new folder and just start it - your old
    echo         settings are offered for import on first start.
    goto :End
)

rem 1) Save a copy of the settings first (data\init.backup.json is never uploaded)
if exist "data\init.json" (
    copy /y "data\init.json" "data\init.backup.json" >nul
    echo [1/3] Settings backed up: data\init.backup.json
)

rem 2) Put the tracked template back so the update cannot collide with your edits
git checkout -- data/init.json >nul 2>nul

echo [2/3] Downloading the update...
git pull --ff-only
set "PULL_RESULT=%errorlevel%"

rem 3) Always put YOUR settings back (even when the update failed)
if exist "data\init.backup.json" (
    copy /y "data\init.backup.json" "data\init.json" >nul
    echo [3/3] Your settings were restored.
)

if not "%PULL_RESULT%"=="0" (
    echo.
    echo [ERROR] The update failed. Your settings are safe. Check the messages above.
    goto :End
)

echo.
echo Update finished. Start the program with run.bat
echo (libraries are checked and installed automatically on start)

:End
echo.
pause
exit /b %PULL_RESULT%
