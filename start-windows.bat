@echo off
REM Portable launcher for Windows. Double-click to run.
REM Needs Python 3 installed (https://www.python.org/downloads/) + internet on first run.
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "VENV=.venv-windows"
set "PYEXE=%VENV%\Scripts\python.exe"

if not exist "%PYEXE%" (
  echo [setup] First run: building the environment. This takes a minute...
  set "BOOT=python"
  where py >nul 2>&1 && set "BOOT=py -3"
  !BOOT! -m venv "%VENV%"
  if not exist "%PYEXE%" (
    echo.
    echo Could not create the environment.
    echo Install Python 3 from https://www.python.org/downloads/ and tick
    echo "Add Python to PATH" during install, then run this again.
    pause
    exit /b 1
  )
  "%PYEXE%" -m pip install --disable-pip-version-check -q -r requirements.txt
)

if not exist ".env" (
  echo No .env found. Copy .env.portable to .env and fill in your token and xAI key.
  echo See PORTABLE.md for the steps.
  pause
  exit /b 1
)

echo [start] Launching the crew. Close this window to stop the bot.
"%PYEXE%" bot.py
pause
