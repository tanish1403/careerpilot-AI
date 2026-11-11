@echo off
setlocal
cd /d "%~dp0\..\.."
where python >nul 2>nul || (echo Python 3.11+ is required & exit /b 1)
if not exist .venv python -m venv .venv || exit /b 1
call .venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1
call .venv\Scripts\python.exe -m pip install -e services\api[dev] || exit /b 1
if not exist .env copy .env.example .env >nul
if not exist data mkdir data
pushd services\api
..\..\.venv\Scripts\python.exe -m alembic upgrade heads || (popd & exit /b 1)
popd
where npm >nul 2>nul && (pushd apps\web & call npm install & popd) || echo npm not found: skipping frontend install
echo Setup complete. Run scripts\windows\start.cmd
endlocal
