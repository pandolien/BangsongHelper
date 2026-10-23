@echo off
setlocal
cd /d "%~dp0"

rem ==========================================================================
rem  BangsongHelper updater
rem    - Downloads the newest program files with git, KEEPING your settings
rem      (data\init.json, your game pairs in data\game_map.txt, records, Log folder).
rem    - Needs a folder made with "git clone" (a zip download cannot update itself).
rem    - run.bat calls this automatically on every start:  update.bat /nopause /quiet
rem      (create an empty file named no_update.txt next to run.bat to turn that off)
rem  NOTE: keep this file ASCII only. Korean text breaks cmd.exe parsing.
rem ==========================================================================

set "NOPAUSE="
set "QUIET="
if /i "%~1"=="/nopause" set "NOPAUSE=1"
if /i "%~2"=="/nopause" set "NOPAUSE=1"
if /i "%~1"=="/quiet" set "QUIET=1"
if /i "%~2"=="/quiet" set "QUIET=1"
set "RESULT=0"

if not defined QUIET (
    echo ============================================
    echo   BangsongHelper update
    echo ============================================
    echo.
)

where git >nul 2>nul
if errorlevel 1 (
    echo [update] git is not installed - skipping the update.
    goto :End
)
if not exist ".git" (
    echo [update] This folder was not made with "git clone" - skipping the update.
    goto :End
)

for /f %%H in ('git rev-parse --short HEAD 2^>nul') do set "OLD_HEAD=%%H"

rem 1) Save a copy of your settings and game pairs first (the backups are never uploaded)
if exist "data\init.json" copy /y "data\init.json" "data\init.backup.json" >nul
if exist "data\game_map.txt" copy /y "data\game_map.txt" "data\game_map.backup.txt" >nul

rem 2) Put the tracked originals back so the update cannot collide with your edits
git checkout -- data/init.json >nul 2>nul
git checkout -- data/game_map.txt >nul 2>nul

rem 3) Download (gives up if the network stalls)
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 pull --ff-only
set "RESULT=%errorlevel%"

rem 4) Always put YOUR settings back (even when the update failed)
if exist "data\init.backup.json" copy /y "data\init.backup.json" "data\init.json" >nul

rem    Game pairs: new pairs from the update + the ones you made (yours win)
if exist "data\game_map.backup.txt" (
    set "MERGED="
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" update_helper.py merge-game-map "data\game_map.backup.txt" "data\game_map.txt" && set "MERGED=1"
    ) else (
        py -3 update_helper.py merge-game-map "data\game_map.backup.txt" "data\game_map.txt" >nul 2>nul && set "MERGED=1"
    )
    if not defined MERGED copy /y "data\game_map.backup.txt" "data\game_map.txt" >nul
)

for /f %%H in ('git rev-parse --short HEAD 2^>nul') do set "NEW_HEAD=%%H"
if not "%RESULT%"=="0" (
    echo [update] The update failed - the program will keep working as before. Your settings are safe.
) else if not "%OLD_HEAD%"=="%NEW_HEAD%" (
    echo [update] Updated: %OLD_HEAD% to %NEW_HEAD%
) else (
    echo [update] Already up to date.
)

:End
if not defined NOPAUSE (
    echo.
    pause
)
exit /b %RESULT%
