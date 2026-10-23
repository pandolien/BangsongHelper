@echo off
cd /d "%~dp0"

rem NOTE: keep this file ASCII only. Korean text breaks cmd.exe parsing.
rem
rem  1) update.bat runs first (downloads the newest program, KEEPS your settings).
rem     To turn the automatic update off, create an empty file named no_update.txt next to this file.
rem  2) Then start_app.bat starts the program (installs Python / libraries on the first run).
rem
rem The block below is read by cmd.exe all at once, so the update can safely replace this very file.
rem A bare exit /b would lose the exit code, so it is passed on with call exit /b %%errorlevel%% instead.
rem Do not put round brackets inside the block, cmd.exe would end the block early.
(
    if not exist "no_update.txt" if exist "update.bat" call "%~dp0update.bat" /nopause /quiet
    call "%~dp0start_app.bat" %*
    call exit /b %%errorlevel%%
)
