@echo off
cd /d "%~dp0"
where py >nul 2>&1 && set PY=py -3 || set PY=python
echo EDGE DESK paper log — every 30 minutes. Close this window to stop.
echo Never places a live Kalshi order.
%PY% -m src.main --loop 30
pause
