"""Founder report for one shop, through the deployed API (the database port is not reachable from the founder PC).
Usage:  apps/api/.venv/Scripts/python.exe scripts/ap_report.py TST001 [--hours 24]
Reads AUTOPRINT_V4_MAINTENANCE_TOKEN from .env. Shows no document names or customer data."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("shop")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--base", default="https://autoprint-v4.vercel.app")
    a = p.parse_args()
    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if l and not l.startswith("#") and "=" in l)
    r = httpx.get(f"{a.base}/v1/internal/report/{a.shop}", params={"hours": a.hours},
                  headers={"X-Maintenance-Token": env["AUTOPRINT_V4_MAINTENANCE_TOKEN"]}, timeout=60)
    if r.status_code != 200:
        print("could not get the report:", r.status_code, r.text[:200]); return 1
    d = r.json()
    print(f"{d['shop']['name']} ({d['shop']['code']}), last {d['window_hours']} h")
    print("jobs:", ", ".join(f"{k} {v}" for k, v in sorted(d["counts"].items())) or "none", "| need a look:", d["attention"])
    for j in d["jobs"][:30]:
        print(f"  {j['order']}  {j['status']:<16} attempts {j['attempts']}  {j['created_at'][:19]}  open {j['seconds_to_final_state']}s")
    print("computers:")
    now = datetime.now(timezone.utc)
    for c in d["devices"]:
        seen = c["last_seen_at"]
        ago = f"{int((now - datetime.fromisoformat(seen)).total_seconds())} s ago" if seen else "never"
        online = " ONLINE" if seen and (now - datetime.fromisoformat(seen)).total_seconds() < 45 and c["status"] == "active" else ""
        print(f"  {c['name']:<22} {c['status']:<8} last seen {ago}{online}  v{c['agent_version'] or '?'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
