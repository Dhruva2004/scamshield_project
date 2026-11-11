"""
ScamShield AI - scripts/run_dev.py
=================================
Start the backend and the frontend together with one command.

    python scripts/run_dev.py

Both child processes are supervised: if one dies, the other is stopped so you
never end up with a half-running stack. Ctrl+C stops both.

Why not two terminals? You can use two - this script is a convenience for
demos, where you want one command on screen.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _spawn(command: list[str], name: str) -> subprocess.Popen:
    print(f"[run] starting {name}: {' '.join(command)}")
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(PROJECT_ROOT))
    env.setdefault("PYTHONUNBUFFERED", "1")
    return subprocess.Popen(command, cwd=PROJECT_ROOT, env=env)


def main() -> int:
    backend = _spawn(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "0.0.0.0", "--port", "8000", "--reload"],
        "backend (FastAPI)",
    )
    # Give the API a moment to bind before the UI starts polling it.
    time.sleep(3)
    frontend = _spawn(
        [sys.executable, "-m", "streamlit", "run", "frontend/app.py",
         "--server.port", "8501", "--server.address", "0.0.0.0"],
        "frontend (Streamlit)",
    )

    print("\n[run] API docs  : http://localhost:8000/docs")
    print("[run] Dashboard : http://localhost:8501")
    print("[run] Press Ctrl+C to stop both.\n")

    def _shutdown(signum, _frame):
        print(f"\n[run] received signal {signum}, stopping…")
        for process in (frontend, backend):
            if process.poll() is None:
                process.terminate()
        for process in (frontend, backend):
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Supervise: exit if either process dies.
    while True:
        if backend.poll() is not None:
            print("[run] backend exited - stopping frontend")
            _shutdown(signal.SIGTERM, None)
        if frontend.poll() is not None:
            print("[run] frontend exited - stopping backend")
            _shutdown(signal.SIGTERM, None)
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
