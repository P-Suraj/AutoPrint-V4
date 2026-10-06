"""Whole chain on THIS PC only: customer upload -> shop app approves -> real engine -> virtual printer -> customer sees the result.

Same run as run_live_e2e.py, but against an API started here with a scratch database and local file storage, so it
needs no internet, touches no live data and uses no real secret. It proves the current working tree end to end before
a release. It does NOT prove the deployed site or physical printing.
Usage:  apps/api/.venv/Scripts/python.exe e2e/run_local_chain.py
"""
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "supabase" / "tests"))
sys.path.insert(0, str(ROOT / "e2e"))
from dbtools import build_database, drop_database  # noqa: E402

PORT = 8011
BASE = f"http://127.0.0.1:{PORT}"
RULES = {"bw": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 200}],
                "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 120}]},
         "color": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 1000}],
                   "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 800}]}}


def main() -> int:
    s = socket.socket()
    if s.connect_ex(("127.0.0.1", PORT)) == 0:
        raise SystemExit(f"port {PORT} is already in use; stop whatever is using it first")
    s.close()
    name = "v4_chain_" + uuid.uuid4().hex[:8]
    url = build_database(name)
    tmp = Path(tempfile.mkdtemp(prefix="ap_chain_"))
    token = secrets.token_hex(24)                                # throwaway: lives only for this run
    env = dict(os.environ, AUTOPRINT_V4_DATABASE_URL=url, AUTOPRINT_V4_STORAGE_BACKEND="local",
               AUTOPRINT_V4_LOCAL_STORAGE_DIR=str(tmp / "files"), AUTOPRINT_V4_SIGNING_KEY="e" * 40,
               AUTOPRINT_V4_PUBLIC_BASE_URL=BASE, AUTOPRINT_V4_MAINTENANCE_TOKEN=token)
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.asgi:app", "--port", str(PORT), "--log-level", "warning"],
                           cwd=ROOT / "apps" / "api", env=env)
    try:
        end = time.time() + 60
        while True:
            try:
                if httpx.get(BASE + "/health/ready", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.time() > end:
                raise SystemExit("the local API did not start")
            time.sleep(0.5)
        r = httpx.post(BASE + "/v1/internal/shop", headers={"X-Maintenance-Token": token},
                       json={"code": "TST001", "name": "Local Chain Test Shop", "rules": RULES}, timeout=30)
        assert r.status_code == 200, r.text

        os.environ["AP_E2E_BASE"] = BASE
        import run_live_e2e                                       # reads AP_E2E_BASE when imported
        run_live_e2e.env_file = lambda: {"AUTOPRINT_V4_MAINTENANCE_TOKEN": token}
        return run_live_e2e.main()
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(api.pid)], capture_output=True) if os.name == "nt" else api.terminate()
        time.sleep(1)
        drop_database(name)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
