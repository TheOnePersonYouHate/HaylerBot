@echo off
REM Double-click launcher: runs run.ps1 (bypasses execution policy for this run).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
pause
