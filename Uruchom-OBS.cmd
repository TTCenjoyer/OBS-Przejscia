@echo off
rem Dwuklik: instaluje/aktualizuje dodatki i uruchamia OBS dla turnieju TTC (ustawienia w launcher.json).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uruchom-OBS.ps1" %*
if errorlevel 1 (
  echo.
  pause
)
