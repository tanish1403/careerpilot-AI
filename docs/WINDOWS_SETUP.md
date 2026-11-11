# Windows setup (CMD, no WSL)

Status: **untested on real Windows.** The scripts follow Windows conventions and are exercised only via Linux CI-style runs of the
shared Python code; the CI matrix includes `windows-latest` for the backend tests.

1. Install Python 3.11+ (tick "Add to PATH") and Node 20+. Optional: MiKTeX/TeX Live (`xelatex`), Tesseract.
2. In the repo root: `scripts\windows\setup.cmd` (creates `.venv`, installs the package, copies `.env.example` to `.env`,
   runs `alembic upgrade heads`, runs `npm install` if npm exists).
3. `scripts\windows\start.cmd` (add `--api-only` to skip Vite). Open http://localhost:5173. `stop.cmd` stops both.
4. `scripts\windows\test.cmd` runs pytest; `scripts\windows\backup.cmd` writes a backup into `data\backups`.
5. For autofill: `.venv\Scripts\python.exe -m pip install playwright` then `.venv\Scripts\python.exe -m playwright install chromium`.

Troubleshooting: if `python` is not found, reopen CMD after installing; if port 8000 is busy use `start.cmd --port 8001`
(and set `VITE_API_URL`). Report problems with the OS version and script output.
