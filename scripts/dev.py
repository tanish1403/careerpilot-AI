"""Cross-platform dev launcher: API (uvicorn) + optional web dev server.

  python scripts/dev.py [--api-only] [--port 8000]      start
  python scripts/dev.py --stop                          stop processes started by this launcher
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIDFILE = ROOT / "data" / "dev.pids"


def _kill(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def stop() -> int:
    if PIDFILE.exists():
        for line in PIDFILE.read_text().split():
            if line.isdigit():
                _kill(int(line))
        PIDFILE.unlink(missing_ok=True)
        print("Stopped.")
    else:
        print("Nothing to stop.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-only", action="store_true")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--stop", action="store_true")
    a = ap.parse_args()
    if a.stop:
        return stop()
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    procs = [subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "careerpilot.api.app:app", "--host", "127.0.0.1",
         "--port", str(a.port)], cwd=ROOT / "services" / "api")]
    web = ROOT / "apps" / "web"
    npm = shutil.which("npm")
    if not a.api_only and npm and (web / "package.json").exists():
        procs.append(subprocess.Popen([npm, "run", "dev"], cwd=web, shell=os.name == "nt"))
    PIDFILE.write_text("\n".join(str(p.pid) for p in procs))
    print(f"API http://127.0.0.1:{a.port}  (Ctrl+C to stop)")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            _kill(p.pid)
        PIDFILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
