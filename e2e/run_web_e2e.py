"""Customer web end-to-end: real browser -> real API -> real PostgreSQL -> real file storage.

Starts a scratch database, the API (uvicorn) and the Vite dev server, creates a shop, runs the Playwright
tests, then stops everything. The 'shop' is played by e2e/shop_sim.py through the same SQL functions the
desktop app will call. Run:  apps/api/.venv/Scripts/python.exe e2e/run_web_e2e.py
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "supabase" / "tests"))
sys.path.insert(0, str(ROOT / "apps" / "api" / "tests"))
from dbtools import build_database, drop_database  # noqa: E402
import pdfs  # noqa: E402

PY = sys.executable
API_PORT, WEB_PORT = 8000, 5173
NPX = shutil.which("npx") or "npx"


def wait_port(port: int, name: str, seconds: int = 60) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"{name} did not start on port {port}")


def dashboard_key(database_url: str, shop_code: str) -> str:
    """A shopkeeper's private-link key for the scratch shop (it dies with the scratch database)."""
    import hashlib
    import secrets
    import psycopg2
    key = secrets.token_hex(32)
    conn = psycopg2.connect(database_url)
    try:
        conn.autocommit = True
        conn.cursor().execute("SELECT ap.shop_login_create(%s, 'link', %s, 'walk')", (shop_code, hashlib.sha256(key.encode()).hexdigest()))
    finally:
        conn.close()
    return key


def main() -> int:
    for port in (API_PORT, WEB_PORT):
        s = socket.socket()
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"port {port} is already in use; stop whatever is using it first")
        s.close()
    name = "v4_e2e_" + uuid.uuid4().hex[:8]
    url = build_database(name)
    tmp = Path(tempfile.mkdtemp(prefix="ap_e2e_"))
    (tmp / "three.pdf").write_bytes(pdfs.blank(3))
    (tmp / "notes.txt").write_text("not a pdf")
    env = dict(os.environ, AUTOPRINT_V4_DATABASE_URL=url, AUTOPRINT_V4_STORAGE_BACKEND="local",
               AUTOPRINT_V4_LOCAL_STORAGE_DIR=str(tmp / "files"), AUTOPRINT_V4_SIGNING_KEY="e" * 40,
               AUTOPRINT_V4_PUBLIC_BASE_URL=f"http://127.0.0.1:{WEB_PORT}")      # signed URLs go through the dev proxy: same origin
    procs = []
    try:
        procs.append(subprocess.Popen([PY, "-m", "uvicorn", "app.asgi:app", "--port", str(API_PORT), "--log-level", "warning"],
                                      cwd=ROOT / "apps" / "api", env=env))
        # E2E_TOOL=perf measures the production build, served the way the host serves it (vite preview); everything else uses the dev server
        web = ["vite", "--port", str(WEB_PORT), "--strictPort", "--host", "127.0.0.1"]
        if os.environ.get("E2E_TOOL") == "perf":
            subprocess.run([NPX, "vite", "build"], cwd=ROOT / "apps" / "web", env=env, shell=os.name == "nt", check=True)
            web.insert(1, "preview")
        procs.append(subprocess.Popen([NPX, *web], cwd=ROOT / "apps" / "web", env=env, shell=os.name == "nt"))
        wait_port(API_PORT, "API"); wait_port(WEB_PORT, "web dev server")
        setup = subprocess.run([PY, str(ROOT / "e2e" / "shop_sim.py"), "setup"], env=env, capture_output=True, text=True, check=True)
        import json
        shop = json.loads(setup.stdout)["shop_code"]
        run_env = dict(env, E2E_SHOP_CODE=shop, E2E_PDF=str(tmp / "three.pdf"), E2E_TEXT_FILE=str(tmp / "notes.txt"),
                       E2E_PYTHON=PY, E2E_SHOP_SIM=str(ROOT / "e2e" / "shop_sim.py"))
        if os.environ.get("E2E_TOOL") == "walk" and not os.environ.get("E2E_SHOP_KEY"):
            run_env["E2E_SHOP_KEY"] = dashboard_key(url, shop)      # so the walk can show the shopkeeper's pages too
        result = subprocess.run([NPX, "playwright", "test"], cwd=ROOT / "apps" / "web", env=run_env, shell=os.name == "nt")
        return result.returncode
    finally:
        for p in procs:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True) if os.name == "nt" else p.terminate()
        time.sleep(1)
        drop_database(name)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
