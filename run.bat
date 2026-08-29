@echo off
cd /d "%~dp0"
where py >nul 2>&1 && set PY=py -3 || set PY=python
%PY% -m src.test_core
if errorlevel 1 (
  echo Tests failed. Install Python 3.10+ from python.org and tick "Add to PATH".
  pause
  exit /b 1
)
%PY% -m src.main --once
pause
