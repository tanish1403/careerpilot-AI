@echo off
setlocal
cd /d "%~dp0\..\.."
if not exist .venv\Scripts\python.exe (echo Run scripts\windows\setup.cmd first & exit /b 1)
.venv\Scripts\python.exe scripts\dev.py %*
endlocal
