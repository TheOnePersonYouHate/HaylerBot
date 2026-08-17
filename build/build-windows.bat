@echo off
REM Build the standalone Windows .exe. Needs Python 3 + internet (one-time).
setlocal
cd /d "%~dp0\.."
set "PYEXE=.venv-build\Scripts\python.exe"
if not exist "%PYEXE%" (
  echo [setup] Creating a build environment...
  where py >nul 2>&1 && (py -3 -m venv .venv-build) || (python -m venv .venv-build)
)
"%PYEXE%" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
"%PYEXE%" -m PyInstaller --clean --noconfirm --workpath .build-work naval-bot.spec
if not exist "dist\HaylerBot.exe" ( echo BUILD FAILED & pause & exit /b 1 )
copy /Y characters.yaml dist\ >nul
if exist .env.portable copy /Y .env.portable dist\ >nul
echo.
echo === Build complete ===
echo Standalone folder: dist\  (HaylerBot.exe + characters.yaml + .env.portable)
echo Copy .env.portable to .env in dist\, fill it in, then double-click HaylerBot.exe.
pause
