@echo off
setlocal
cd /d "%~dp0\..\.."
if not exist .venv\Scripts\python.exe (echo Run setup.cmd first & exit /b 1)
.venv\Scripts\python.exe -c "from careerpilot.core.system.backup import create_backup as c; print(c())"
endlocal
