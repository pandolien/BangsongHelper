@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem ==========================================================================
rem  Build the user guide PDF from guide.html (uses Chrome or Edge, headless)
rem  Output: ..\chzzkControl_*.pdf (overwrites the existing guide PDF)
rem  NOTE: keep this file ASCII only. Korean text breaks cmd.exe parsing.
rem ==========================================================================

set "BROWSER="
for %%B in ("%ProgramFiles%\Google\Chrome\Application\chrome.exe" "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe") do (
    if not defined BROWSER if exist "%%~B" set "BROWSER=%%~B"
)
if not defined BROWSER (
    echo [ERROR] Chrome or Edge not found.
    exit /b 1
)

"%BROWSER%" --headless=new --disable-gpu --user-data-dir="%TEMP%\chzzk_pdf_profile" --no-first-run --no-pdf-header-footer --print-to-pdf="%~dp0guide.pdf" "file:///%~dp0guide.html"
if not exist "guide.pdf" (
    echo [ERROR] PDF was not created.
    exit /b 1
)

rem Copy over the existing guide PDF (its name has Korean, so match by wildcard).
set "TARGET="
for %%F in ("..\chzzkControl_*.pdf") do set "TARGET=%%~fF"
if not defined TARGET set "TARGET=%~dp0..\chzzkControl_guide.pdf"
copy /y "guide.pdf" "!TARGET!" > nul
del "guide.pdf"
echo Done: !TARGET!
