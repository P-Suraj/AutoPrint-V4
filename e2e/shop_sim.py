"""Plays the shop side in end-to-end tests by calling the same SQL functions the desktop app will use.

  shop_sim.py setup                  -> prints JSON {shop_code, device_id}
  shop_sim.py approve <SHORT> <SHOP> -> approves the awaiting job of that order
  shop_sim.py print   <SHORT> <SHOP> -> claims it, marks it sent, reports completed with rule-v1 evidence

Needs AUTOPRINT_V4_DATABASE_URL. Test use only.
"""
import hashlib
import json
import os
import random
import string
import sys
import uuid

import psycopg2

GOOD = {"rule_version": 2, "spooler_job_seen": True, "printing_seen": True, "left_queue": True,
        "flags_seen": ["SPOOLING", "PRINTING"], "max_pages_printed": 3, "expected_pages": 3}
RULES = {"bw": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 200}],
                "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 120}]},
         "color": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 1000}],
                   "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 800}]}}


def sha(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def connect():
    c = psycopg2.connect(os.environ["AUTOPRINT_V4_DATABASE_URL"])
    c.autocommit = True
    return c


def fn(cur, name, *args):
    cur.execute(f"SELECT ap.{name}({', '.join(['%s'] * len(args))})", [psycopg2.extras.Json(a) if isinstance(a, (dict, list)) else a for a in args])
    return cur.fetchone()[0]


def device_for(cur, shop_code):
    cur.execute("SELECT d.id FROM ap.devices d JOIN ap.shops s ON s.id = d.shop_id WHERE s.code = %s AND d.status = 'active' LIMIT 1", (shop_code,))
    return cur.fetchone()[0]


def job_for(cur, short, shop_code):
    cur.execute("SELECT j.id FROM ap.jobs j JOIN ap.orders o ON o.id = j.order_id JOIN ap.shops s ON s.id = j.shop_id "
                "WHERE o.short_code = %s AND s.code = %s ORDER BY j.created_at DESC LIMIT 1", (short, shop_code))
    return cur.fetchone()[0]


def main(argv):
    import psycopg2.extras  # noqa: F401  (registers Json)
    psycopg2.extras.register_uuid()
    conn = connect()
    cur = conn.cursor()
    if argv[0] == "setup":
        code = "".join(random.choices(string.ascii_uppercase, k=3)) + "".join(random.choices(string.digits, k=3))
        cur.execute("INSERT INTO ap.shops (code, name) VALUES (%s, 'E2E Copy Centre') RETURNING id", (code,))
        shop_id = cur.fetchone()[0]
        cur.execute("INSERT INTO ap.rate_cards (shop_id, version, rules) VALUES (%s, 1, %s::jsonb)", (shop_id, json.dumps(RULES)))
        enroll, secret = uuid.uuid4().hex, uuid.uuid4().hex
        fn(cur, "issue_enrollment_code", code, sha(enroll), 30)
        res = fn(cur, "consume_enrollment", sha(enroll), "E2E PC", sha(secret))
        print(json.dumps({"shop_code": code, "device_id": res["device_id"]}))
    elif argv[0] == "approve":
        short, shop = argv[1], argv[2]
        print(json.dumps(fn(cur, "approve_job", job_for(cur, short, shop), device_for(cur, shop))))
    elif argv[0] == "print":
        short, shop = argv[1], argv[2]
        device = device_for(cur, shop)
        c = fn(cur, "claim_next_job", device, 300)
        assert c["result"] == "claimed", c
        fn(cur, "mark_sent", c["attempt_id"], c["attempt_token"], device)
        print(json.dumps(fn(cur, "report_outcome", c["attempt_id"], c["attempt_token"], device, "completed", GOOD)))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
