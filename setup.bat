@echo off
cd /d "%~dp0"
where py >nul 2>&1 && set PY=py -3 || set PY=python
echo Installing tzdata (needed on Windows)...
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo pip failed. Install Python 3.10+ from python.org and tick "Add to PATH".
  pause
  exit /b 1
)
echo Setup ok. Double-click run.bat or run_loop.bat
pause
