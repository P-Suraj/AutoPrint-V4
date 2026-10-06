"""Founder tools that work through the deployed API, because the database port is not reachable from the founder PC.
Reads AUTOPRINT_V4_MAINTENANCE_TOKEN from .env. Nothing here prints a secret except the shop link you ask for.

  PY scripts/ap_remote.py create-shop ABC123 "Shop name" --rates rates.json   create a shop and publish its prices
  PY scripts/ap_remote.py set-rates ABC123 --rates rates.json                 publish a new price version
  PY scripts/ap_remote.py shop-link ABC123 --label owner                      private dashboard link for the shopkeeper
  PY scripts/ap_remote.py revoke-link ABC123 --label owner                    revoke that shop's logins with that label
  PY scripts/ap_remote.py purge ABC123 K7QD                                   delete the files of one finished order now (customer request)
  PY scripts/ap_remote.py add-email ABC123 owner@example.com --label owner   allow this email to sign in to the shop dashboard
  PY scripts/ap_remote.py remove-email owner@example.com                       stop allowing it
  PY scripts/ap_remote.py report ABC123 [--hours 24]                          counts, outcomes, computer online?   (see ap_report.py)
"""
import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://autoprint-v4.vercel.app"


def post(path: str, body: dict) -> dict:
    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if l and not l.startswith("#") and "=" in l)
    r = httpx.post(BASE + path, json=body, headers={"X-Maintenance-Token": env["AUTOPRINT_V4_MAINTENANCE_TOKEN"]}, timeout=60)
    if r.status_code != 200:
        raise SystemExit(f"refused ({r.status_code}): {r.text[:300]}")
    return r.json()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-shop"); a.add_argument("code"); a.add_argument("name"); a.add_argument("--rates")
    a = sub.add_parser("set-rates"); a.add_argument("code"); a.add_argument("--rates", required=True)
    a = sub.add_parser("shop-link"); a.add_argument("code"); a.add_argument("--label", default="owner")
    a = sub.add_parser("purge"); a.add_argument("code"); a.add_argument("order", help="the 4-character order code the customer sees")
    a = sub.add_parser("add-email"); a.add_argument("code"); a.add_argument("email"); a.add_argument("--label", default="owner")
    a = sub.add_parser("remove-email"); a.add_argument("email")
    a = sub.add_parser("revoke-link"); a.add_argument("code"); a.add_argument("--label", required=True)
    args = p.parse_args()

    if args.cmd in ("create-shop", "set-rates"):
        body = {"code": args.code, "name": getattr(args, "name", "")}
        if args.rates:
            body["rules"] = json.loads(Path(args.rates).read_text(encoding="utf-8"))
        r = post("/v1/internal/shop", body)
        print(("created" if r["created"] else "existing"), "shop", r["code"], "| rate card version:", r["rate_card_version"])
        print("customer link:", f"{BASE}/s/{r['code']}")
    elif args.cmd == "shop-link":
        r = post("/v1/internal/shop-login", {"shop_code": args.code, "label": args.label})
        print("Private dashboard link (shown once; hand it over in person or in a private chat):")
        print(f"  {BASE}/shop#key={r['key']}")
    elif args.cmd == "purge":
        r = post("/v1/internal/purge", {"shop_code": args.code, "order": args.order})
        print(f"orders matched {r['orders_matched']}, files deleted now {r['documents_deleted_now']}, files remaining {r['documents_remaining']}")
    elif args.cmd == "add-email":
        post("/v1/internal/shop-email", {"shop_code": args.code, "email": args.email, "label": args.label})
        print(f"{args.email} can now sign in to the dashboard of shop {args.code.upper()} at {BASE}/shop")
    elif args.cmd == "remove-email":
        post("/v1/internal/shop-email", {"email": args.email, "remove": True})
        print("removed")
    elif args.cmd == "revoke-link":
        print(post("/v1/internal/shop-login", {"shop_code": args.code, "revoke_label": args.label}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
