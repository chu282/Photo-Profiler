@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\python.exe" -c "import exifread, PIL" >nul 2>&1
    if not errorlevel 1 goto launch
)
where python >nul 2>&1
if errorlevel 1 (
    echo Install Python 3.10 or newer from python.org, then run this file again.
    pause
    exit /b 1
)
if not exist ".temp" mkdir ".temp"
set "TEMP=%~dp0.temp"
set "TMP=%~dp0.temp"
echo Setting up Photo Profiler...
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
:launch
start "" ".venv\Scripts\pythonw.exe" "%~dp0portable.py"
exit /b 0
:failed
echo Setup failed. Check your internet connection and try again.
pause
exit /b 1
