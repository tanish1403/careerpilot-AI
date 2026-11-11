"""End-to-end smoke test (Playwright, Python). Starts the backend on a temp data dir and checks
health, first-run setup, login and the dashboard API; with CP_E2E_UI=1 (and node_modules installed)
also loads the Vite dev server and checks the app shell renders.

  .venv/bin/python tests/browser/h_e2e_smoke.py        (Windows: .venv\\Scripts\\python.exe ...)
Needs: pip install playwright && playwright install chromium. Exit code 0 = pass.
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"timeout waiting for {url}")


def kill(p: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    else:
        p.terminate()


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="cp_e2e_")
    port = free_port()
    env = {**os.environ, "CAREERPILOT_DATA_DIR": tmp, "CAREERPILOT_SCHEDULER_ENABLED": "false",
           "CAREERPILOT_CORS_ORIGINS": '["http://127.0.0.1:5199"]'}
    procs = [subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "careerpilot.api.app:app", "--host", "127.0.0.1",
         "--port", str(port)], cwd=ROOT / "services" / "api", env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    base = f"http://127.0.0.1:{port}/api/v1"
    try:
        wait_for(f"{base}/health")
        with sync_playwright() as pw:
            req = pw.request.new_context()
            assert req.get(f"{base}/health").ok, "health"
            st = req.get(f"{base}/auth/status").json()
            assert st["setup_required"] is True, st
            assert req.get(f"{base}/dashboard").status == 401, "dashboard must require auth"
            cred = {"username": "smoke", "password": "smoke-test-pass-1"}
            assert req.post(f"{base}/auth/setup", data=cred).ok, "setup"
            assert req.post(f"{base}/auth/setup", data=cred).status == 409, "setup is one-shot"
            assert req.post(f"{base}/auth/login",
                            data={**cred, "password": "wrong-password"}).status == 401
            tok = req.post(f"{base}/auth/login", data=cred).json()["token"]
            hdr = {"Authorization": f"Bearer {tok}"}
            dash = req.get(f"{base}/dashboard", headers=hdr)
            assert dash.ok and "counts" in dash.json(), "dashboard"
            feats = req.get(f"{base}/features").json()
            print(f"features reported: {len(feats)}")
            if os.environ.get("CP_E2E_UI") == "1" and shutil.which("npm") \
                    and (ROOT / "apps" / "web" / "node_modules").exists():
                web_env = {**os.environ, "VITE_API_URL": f"http://127.0.0.1:{port}"}
                procs.append(subprocess.Popen(
                    [shutil.which("npm"), "run", "dev", "--", "--port", "5199", "--host",
                     "127.0.0.1"], cwd=ROOT / "apps" / "web", env=web_env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=os.name == "nt"))
                wait_for("http://127.0.0.1:5199/")
                browser = pw.chromium.launch()
                page = browser.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto("http://127.0.0.1:5199/")
                page.wait_for_load_state("networkidle")
                assert page.inner_text("body").strip(), "app shell rendered empty"
                assert not errors, errors
                browser.close()
                print("ui shell ok")
        print("E2E SMOKE PASSED")
        return 0
    finally:
        for p in procs:
            kill(p)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
