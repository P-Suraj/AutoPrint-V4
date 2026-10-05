"""Whole chain on the LIVE deployment: customer upload -> shop app approves -> real engine -> virtual printer -> customer sees the result.

The customer is this script (same HTTP calls as the web app). The shop is the C# test LiveE2ETests, which uses the real
agent, the real SumatraPDF and the real Windows spooler. The printer is the local virtual printer, so this proves the whole
software chain, NOT physical printing. Creates one order on shop TST001, and removes its own login and device afterwards.
Usage:  apps/api/.venv/Scripts/python.exe e2e/run_live_e2e.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps" / "api" / "tests"))
import pdfs  # noqa: E402

BASE = os.environ.get("AP_E2E_BASE", "https://autoprint-v4.vercel.app")
SHOP = "TST001"
PRINTER = "AutoPrint-Spike-PDF"
SUMATRA = str(ROOT / "spikes" / "_out" / "sumatra_portable" / "SumatraPDF-3.6.1-64.exe")
PRINTER_OUT = ROOT / "spikes" / "_out" / "spike_out.pdf"
DOTNET = r"C:\Program Files\dotnet\dotnet.exe"


def env_file():
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if l and not l.startswith("#") and "=" in l)


def stamp():
    return (PRINTER_OUT.stat().st_mtime, PRINTER_OUT.stat().st_size) if PRINTER_OUT.exists() else (0, 0)


def main():
    env = env_file()
    # the database port is not reachable from this PC, so the founder endpoint (maintenance token) issues the login
    admin = {"X-Maintenance-Token": env["AUTOPRINT_V4_MAINTENANCE_TOKEN"]}
    r = httpx.post(BASE + "/v1/internal/shop-login", headers=admin, json={"shop_code": SHOP, "label": "e2e-run"}, timeout=60)
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    out = Path(tempfile.gettempdir()) / "ap_e2e_timeline.json"
    out.unlink(missing_ok=True)
    before = stamp()
    penv = dict(os.environ, AP_E2E_BASE=BASE, AP_E2E_SHOP_KEY=key, AP_E2E_PRINTER=PRINTER, AP_SUMATRA=SUMATRA, AP_E2E_OUT=str(out))
    shop_side = subprocess.Popen([DOTNET, "test", str(ROOT / "apps/desktop/tests/AutoPrint.Core.Tests"), "--filter", "FullyQualifiedName~LiveE2ETests", "-v", "q"],
                                 env=penv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    c = httpx.Client(base_url=BASE, timeout=30)
    marks = {}
    status = None
    try:
        t0 = time.time()
        while time.time() - t0 < 150:
            devs = c.get("/v1/shop/devices", headers={"X-Shop-Key": key}).json()["devices"]
            if any(d["name"] == "E2E-TEST-PC" and not d["revoked"] for d in devs):
                break
            time.sleep(1)
        else:
            raise SystemExit("the shop computer never connected")
        marks["shop computer connected after"] = time.time() - t0

        data = pdfs.blank(2)
        s0 = time.time()
        o = c.post(f"/v1/shops/{SHOP}/orders").json()
        h = {"X-Order-Secret": o["order_secret"]}
        reg = c.post(f"/v1/orders/{o['order_id']}/documents", headers=h,
                     json={"file_name": f"e2e_{int(s0)}.pdf", "byte_size": len(data), "content_type": "application/pdf"}).json()
        put = httpx.put(reg["upload_url"], content=data, headers=reg["upload_headers"], timeout=60)
        assert put.status_code == 200, put.text
        fin = c.post(f"/v1/orders/{o['order_id']}/documents/{reg['document_id']}/finalize", headers=h)
        assert fin.status_code == 200, fin.text
        q = c.post(f"/v1/orders/{o['order_id']}/quote", headers=h, json={"items": [{"document_id": reg["document_id"], "options": {}}]})
        assert q.status_code == 201, q.text
        sub = c.post(f"/v1/orders/{o['order_id']}/submit", headers=h, json={"quote_id": q.json()["quote_id"]})
        assert sub.status_code == 200, sub.text
        submitted = time.time()
        marks["customer: new order to submitted"] = submitted - s0

        last = None
        v = {}
        while time.time() - submitted < 120:
            v = c.get(f"/v1/orders/{o['order_id']}", headers=h).json()
            status = v["jobs"][0]["status"]
            if status != last:
                marks[f"customer sees '{status}' after"] = time.time() - submitted
                last = status
            if status in ("completed", "failed", "needs_attention", "rejected"):
                break
            time.sleep(0.5)
        marks["order view (raw)"] = json.dumps(v)[:300]
    finally:
        try:
            shop_out, _ = shop_side.communicate(timeout=200)
        except subprocess.TimeoutExpired:
            shop_side.kill(); shop_out = "(timed out)"
        httpx.post(BASE + "/v1/internal/shop-login", headers=admin, json={"revoke_label": "e2e-run"}, timeout=60)

    after = stamp()
    pages = None
    if after != before:
        from pypdf import PdfReader
        pages = len(PdfReader(str(PRINTER_OUT)).pages)

    print("\n=== customer side ===")
    for k, val in marks.items():
        print(f"  {k}: {val:.1f}s" if isinstance(val, float) else f"  {k}: {val}")
    print("=== shop side timeline ===")
    if out.exists():
        for e in json.loads(out.read_text()):
            print(f"  {e['s']:6.2f}s  {e['what']}")
    print("=== virtual printer output ===")
    print("  file changed:", after != before, "| pages in the printed file:", pages, "(sent 2)")
    ok = status == "completed" and after != before and pages == 2 and shop_side.returncode == 0
    print("=== verdict ===")
    print("  PASS" if ok else f"  FAIL (customer status={status}, dotnet exit={shop_side.returncode})")
    if not ok:
        print(shop_out[-1500:])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
