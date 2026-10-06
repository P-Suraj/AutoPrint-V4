"""Founder tools that work through the deployed API, because the database port is not reachable from the founder PC.
Reads AUTOPRINT_V4_MAINTENANCE_TOKEN from .env. Nothing here prints a secret except the shop link you ask for.

  PY scripts/ap_remote.py shops                                               every shop: on or off, computer online, jobs today
  PY scripts/ap_remote.py create-shop ABC123 "Shop name" --rates rates.json   create a shop and publish its prices
  PY scripts/ap_remote.py set-rates ABC123 --rates rates.json                 publish a new price version
  PY scripts/ap_remote.py prices ABC123                                       show the prices the shop is using now
  PY scripts/ap_remote.py shop-off ABC123                                     stop taking orders (nothing is deleted)
  PY scripts/ap_remote.py shop-on ABC123                                      take orders again
  PY scripts/ap_remote.py rename ABC123 "New shop name"                       change the name customers see
  PY scripts/ap_remote.py shop-link ABC123 --label owner                      private dashboard link for the shopkeeper
  PY scripts/ap_remote.py revoke-link ABC123 --label owner                    revoke that shop's logins with that label
  PY scripts/ap_remote.py purge ABC123 K7QD                                   delete the files of one finished order now (customer request)
  PY scripts/ap_remote.py purge ABC123 K7QD --which 2                         ...of the order before the most recent one with that code
  PY scripts/ap_remote.py add-email ABC123 owner@example.com --label owner   allow this email to sign in to the shop dashboard
  PY scripts/ap_remote.py remove-email owner@example.com                       stop allowing it
  PY scripts/ap_remote.py status                                              is the site up, can it reach the database, which database updates are applied
  PY scripts/ap_remote.py migrate                                             apply the database updates that are still pending, and list them

Reports are in scripts/ap_report.py (one shop in detail, or --all).

Prices file: copy scripts/rates.example.json, change every "paise_per_side" (100 paise = 1 rupee; the example holds
Rs 999 placeholders that this tool refuses to publish), and adjust the slabs. A slab is a range of printed sides
(pages x copies): "from_sides" must continue from the slab before it, starting at 1, and the last slab has
"to_sides": null. All four tables are needed: bw and color, each with simplex (one side per sheet) and duplex.
"""
import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://autoprint-v4.vercel.app"
HTTP = httpx                        # tests swap this for a test client
PLACEHOLDER_PAISE = 99900           # the price in scripts/rates.example.json


def token() -> str:
    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if l and not l.startswith("#") and "=" in l)
    return env["AUTOPRINT_V4_MAINTENANCE_TOKEN"]


def _answer(r) -> dict:
    if r.status_code != 200:
        raise SystemExit(f"refused ({r.status_code}): {r.text[:300]}")
    return r.json()


def post(path: str, body: dict) -> dict:
    return _answer(HTTP.post(BASE + path, json=body, headers={"X-Maintenance-Token": token()}, timeout=60))


def get(path: str) -> dict:
    return _answer(HTTP.get(BASE + path, headers={"X-Maintenance-Token": token()}, timeout=60))


def health(path: str) -> str:
    """One line about a public health address. Never raises: `status` must still print the rest when the site is down."""
    try:
        r = HTTP.get(BASE + path, timeout=30)
    except httpx.HTTPError as exc:
        return f"NO ANSWER ({type(exc).__name__})"
    try:
        body = r.json()
    except ValueError:
        body = {}
    return f"{body.get('status', 'no status in the answer')} (HTTP {r.status_code})"


def render_status(d: dict) -> str:
    out = [f"Database updates applied: {len(d['applied'])}"]
    out += [f"    {m['id']:<44}{str(m['applied_at'])[:16].replace('T', ' ')}" for m in d["applied"]]
    if d["pending"]:
        out.append(f"PENDING, not applied yet: {len(d['pending'])}")
        out += [f"    {m}" for m in d["pending"]]
        out.append("Apply them with:  PY scripts/ap_remote.py migrate")
    else:
        out.append("Nothing pending: the database matches the code that is live.")
    if d["not_in_this_deployment"]:
        out.append("WARNING: the database has updates the live code does not know (an older version of the site is live):")
        out += [f"    {m}" for m in d["not_in_this_deployment"]]
    return "\n".join(out)


def render_migrate(d: dict) -> str:
    if not d["applied_now"]:
        return f"Nothing to apply. The database already has all {len(d['applied_total'])} updates (latest: {d['applied_total'][-1]})."
    return "\n".join([f"Applied now: {len(d['applied_now'])}"] + [f"    {m}" for m in d["applied_now"]]
                     + [f"The database now has {len(d['applied_total'])} updates (latest: {d['applied_total'][-1]})."])


def render_purge(r: dict) -> str:
    out = [f"files deleted now {r['documents_deleted_now']}, files remaining {r['documents_remaining']}"]
    if r["orders_matched"] > 1:
        out.append(f"NOTE: {r['orders_matched']} orders of this shop used this code in the last 30 days. Only ONE was purged "
                   "(marked below). If the customer meant another one, run the command again with --which N.")
        out += [f"    --which {m['which']}   started {str(m['created_at'])[:16].replace('T', ' ')} UTC   {m['status']}"
                + ("   <- purged now" if m["purged_now"] else "") for m in r["matches"]]
    return "\n".join(out)


def rupees(paise: int) -> str:
    whole, rest = divmod(paise, 100)
    return f"Rs {whole}" if rest == 0 else f"Rs {whole}.{rest:02d}"


def load_rates(path: str) -> dict:
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    prices = [slab.get("paise_per_side") for table in rules.values() if isinstance(table, dict)
              for slabs in table.values() if isinstance(slabs, list) for slab in slabs if isinstance(slab, dict)]
    if PLACEHOLDER_PAISE in prices:
        raise SystemExit(f"{path} still has the Rs 999 placeholder price from rates.example.json. "
                         "Put the shop's real prices in every \"paise_per_side\" first. Nothing was changed.")
    return rules


def render_prices(d: dict) -> str:
    shop = d["shop"]
    out = [f"{shop['name']} ({shop['code']}) - {'taking orders' if shop['is_active'] else 'SWITCHED OFF'}",
           f"Price list version {d['version']} (of {d['versions_published']} published), since {str(d['published_at'])[:10]}.",
           "A side is one printed face: pages x copies. The slab the whole job falls in sets the price of every side."]
    for key, title in [("bw", "Black and white"), ("color", "Colour")]:
        for sides, how in [("simplex", "one side per sheet"), ("duplex", "both sides of the sheet")]:
            out.append(f"{title}, {how}:")
            for slab in d["rules"][key][sides]:
                upto = f"{slab['from_sides']} to {slab['to_sides']} sides" if slab["to_sides"] is not None else f"{slab['from_sides']} sides and more"
                out.append(f"    {upto:<24}{rupees(slab['paise_per_side'])} per side")
    return "\n".join(out)


def render_shops(d: dict) -> str:
    import ap_report                # same folder; one place formats the all-shops list
    return ap_report.render_all(d)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("shops")
    a = sub.add_parser("create-shop"); a.add_argument("code"); a.add_argument("name"); a.add_argument("--rates")
    a = sub.add_parser("set-rates"); a.add_argument("code"); a.add_argument("--rates", required=True)
    a = sub.add_parser("prices"); a.add_argument("code")
    a = sub.add_parser("shop-on"); a.add_argument("code")
    a = sub.add_parser("shop-off"); a.add_argument("code")
    a = sub.add_parser("rename"); a.add_argument("code"); a.add_argument("name")
    a = sub.add_parser("shop-link"); a.add_argument("code"); a.add_argument("--label", default="owner")
    a = sub.add_parser("purge"); a.add_argument("code"); a.add_argument("order", help="the 4-character order code the customer sees")
    a.add_argument("--which", type=int, default=1, help="1 = the most recent order with that code (default), 2 = the one before, ...")
    sub.add_parser("status")
    sub.add_parser("migrate")
    a = sub.add_parser("add-email"); a.add_argument("code"); a.add_argument("email"); a.add_argument("--label", default="owner")
    a = sub.add_parser("remove-email"); a.add_argument("email")
    a = sub.add_parser("revoke-link"); a.add_argument("code"); a.add_argument("--label", required=True)
    args = p.parse_args(argv)

    if args.cmd == "shops":
        print(render_shops(get("/v1/internal/shops")))
    elif args.cmd in ("create-shop", "set-rates"):
        body = {"code": args.code, "name": getattr(args, "name", "")}
        if args.rates:
            body["rules"] = load_rates(args.rates)
        r = post("/v1/internal/shop", body)
        print(("created" if r["created"] else "existing"), "shop", r["code"], "| rate card version:", r["rate_card_version"])
        print("customer link:", f"{BASE}/s/{r['code']}")
    elif args.cmd == "prices":
        print(render_prices(get(f"/v1/internal/shop/{args.code.strip().upper()}/rates")))
    elif args.cmd in ("shop-on", "shop-off"):
        r = post("/v1/internal/shop-update", {"code": args.code, "is_active": args.cmd == "shop-on"})
        if r["is_active"]:
            print(f"{r['name']} ({r['code']}) is taking orders" + ("." if r["is_active_changed"] else " (it already was)."))
        else:
            print(f"{r['name']} ({r['code']}) is switched off" + ("." if r["is_active_changed"] else " (it already was)."))
            print("Customers are told the shop is not taking orders, and the shopkeeper's dashboard link does not work until "
                  "you switch it on again. The shop computer still shows and prints orders that were already sent.")
    elif args.cmd == "rename":
        r = post("/v1/internal/shop-update", {"code": args.code, "name": args.name})
        print(f"shop {r['code']} is now called: {r['name']}" + ("" if r["renamed"] else " (unchanged)"))
        print("The printed counter sign shows the old name: print it again.")
    elif args.cmd == "shop-link":
        r = post("/v1/internal/shop-login", {"shop_code": args.code, "label": args.label})
        print("Private dashboard link (shown once; hand it over in person or in a private chat):")
        print(f"  {BASE}/shop#key={r['key']}")
    elif args.cmd == "purge":
        print(render_purge(post("/v1/internal/purge", {"shop_code": args.code, "order": args.order, "which": args.which})))
    elif args.cmd == "add-email":
        post("/v1/internal/shop-email", {"shop_code": args.code, "email": args.email, "label": args.label})
        print(f"{args.email} can now sign in to the dashboard of shop {args.code.upper()} at {BASE}/shop")
    elif args.cmd == "remove-email":
        post("/v1/internal/shop-email", {"email": args.email, "remove": True})
        print("removed")
    elif args.cmd == "status":
        print("Site:", health("/health"))
        print("Site can reach the database:", health("/health/ready"))
        print(render_status(get("/v1/internal/status")))
    elif args.cmd == "migrate":
        print(render_migrate(post("/v1/internal/migrate", {})))
    elif args.cmd == "revoke-link":
        print(post("/v1/internal/shop-login", {"shop_code": args.code, "revoke_label": args.label}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
