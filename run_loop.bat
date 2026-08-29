@echo off
cd /d "%~dp0"
where py >nul 2>&1 && set PY=py -3 || set PY=python
echo EDGE DESK paper log — tests first, then every 30 minutes. Close this window to stop.
%PY% -m pip install -q -r requirements.txt
%PY% -m src.test_core
if errorlevel 1 (
  echo Tests failed. Not starting the loop.
  pause
  exit /b 1
)
echo Never places a live Kalshi order.
%PY% -m src.main --loop 30
pause
