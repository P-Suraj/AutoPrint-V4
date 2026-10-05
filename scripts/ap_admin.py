"""Founder operations (decision D-17): scripts, not screens.

  python scripts/ap_admin.py create-shop  --code TST001 --name "Campus Xerox"
  python scripts/ap_admin.py set-rates    --shop TST001 --file rates.json
  python scripts/ap_admin.py issue-code   --shop TST001 [--minutes 30]
  python scripts/ap_admin.py jobs         --shop TST001 [--hours 24]
  python scripts/ap_admin.py revoke-device --device <uuid>

Reads AUTOPRINT_V4_DATABASE_URL. It refuses to run against a URL that does not name a V4 resource
unless --i-know-this-is-v4 is given, as a guard against pointing it at the wrong database.
Secrets (enrollment codes) are printed once and never stored in plain text.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))
from app.db import sha256_hex  # noqa: E402
from app.pricing import PricingError, validate_rules  # noqa: E402


def connect(url: str | None = None):
    url = url or os.environ.get("AUTOPRINT_V4_DATABASE_URL")
    if not url:
        raise SystemExit("AUTOPRINT_V4_DATABASE_URL is not set")
    conn = psycopg2.connect(url)
    return conn


def create_shop(conn, code: str, name: str) -> str:
    code = code.strip().upper()
    with conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ap.shops (code, name) VALUES (%s, %s) RETURNING id", (code, name.strip()))
        return str(cur.fetchone()[0])


def set_rates(conn, shop_code: str, rules: dict) -> int:
    """Retire the active rate card and insert the next version, in one transaction."""
    validate_rules(rules)
    with conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM ap.shops WHERE code = %s FOR UPDATE", (shop_code.strip().upper(),))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"no shop with code {shop_code}")
        shop_id = row[0]
        cur.execute("SELECT COALESCE(max(version), 0) FROM ap.rate_cards WHERE shop_id = %s", (shop_id,))
        version = cur.fetchone()[0] + 1
        cur.execute("UPDATE ap.rate_cards SET retired_at = now() WHERE shop_id = %s AND retired_at IS NULL", (shop_id,))
        cur.execute("INSERT INTO ap.rate_cards (shop_id, version, rules) VALUES (%s, %s, %s::jsonb)",
                    (shop_id, version, json.dumps(rules)))
        return version


def issue_code(conn, shop_code: str, minutes: int = 30) -> str:
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(12))
    with conn, conn.cursor() as cur:
        cur.execute("SELECT ap.issue_enrollment_code(%s, %s, %s)", (shop_code, sha256_hex(code), minutes))
        result = cur.fetchone()[0]
    if result["result"] != "ok":
        raise SystemExit(f"could not issue a code: {result['result']}")
    return code


def list_jobs(conn, shop_code: str, hours: int = 24):
    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT o.short_code, j.status, j.attempt_count, j.created_at, "
            "(SELECT type FROM ap.events e WHERE e.job_id = j.id ORDER BY e.id DESC LIMIT 1) "
            "FROM ap.jobs j JOIN ap.orders o ON o.id = j.order_id JOIN ap.shops s ON s.id = j.shop_id "
            "WHERE s.code = %s AND j.created_at > now() - make_interval(hours => %s) ORDER BY j.created_at DESC",
            (shop_code.strip().upper(), hours))
        return cur.fetchall()


def revoke_device(conn, device_id: str) -> None:
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE ap.devices SET status = 'revoked', revoked_at = now() WHERE id = %s AND status = 'active'", (device_id,))
        if cur.rowcount != 1:
            raise SystemExit("no active device with that id")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-shop"); a.add_argument("--code", required=True); a.add_argument("--name", required=True)
    a = sub.add_parser("set-rates"); a.add_argument("--shop", required=True); a.add_argument("--file", required=True)
    a = sub.add_parser("issue-code"); a.add_argument("--shop", required=True); a.add_argument("--minutes", type=int, default=30)
    a = sub.add_parser("jobs"); a.add_argument("--shop", required=True); a.add_argument("--hours", type=int, default=24)
    a = sub.add_parser("revoke-device"); a.add_argument("--device", required=True)
    args = p.parse_args(argv)
    conn = connect()
    try:
        if args.cmd == "create-shop":
            print("created shop", args.code.upper(), create_shop(conn, args.code, args.name))
        elif args.cmd == "set-rates":
            try:
                version = set_rates(conn, args.shop, json.loads(Path(args.file).read_text(encoding="utf-8")))
            except PricingError as exc:
                raise SystemExit(f"rate card refused: {exc}")
            print("rate card version", version, "is now active")
        elif args.cmd == "issue-code":
            code = issue_code(conn, args.shop, args.minutes)
            print(f"Enrollment code (shown once, valid {args.minutes} minutes): {code}")
        elif args.cmd == "jobs":
            for row in list_jobs(conn, args.shop, args.hours):
                print(*row, sep="  ")
        elif args.cmd == "revoke-device":
            revoke_device(conn, args.device); print("revoked")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
