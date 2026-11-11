@echo off
setlocal
cd /d "%~dp0\..\..\services\api"
..\..\.venv\Scripts\python.exe -m pytest -q tests %*
endlocal
