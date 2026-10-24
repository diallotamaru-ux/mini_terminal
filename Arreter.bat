@echo off
rem Double-clic : arrete l'API et l'interface de Mini-terminal et libere les ports 8000 et 5173.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\arreter.ps1"
echo.
pause
