@echo off
rem Double-clic : lance Mini-terminal en mode demo (donnees simulees) et ouvre le navigateur.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\lancer.ps1" -Demo
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)
