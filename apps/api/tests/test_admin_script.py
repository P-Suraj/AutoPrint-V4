"""Founder scripts work against the real schema."""
import json
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import ap_admin  # noqa: E402

from app.db import sha256_hex  # noqa: E402
from sample_data import RULES as RULES_OK  # noqa: E402


@pytest.fixture
def conn(api_db_url):
    c = psycopg2.connect(api_db_url)
    yield c
    c.close()


def code():
    return "".join(__import__("random").choices("ABCDEFGHJKLMNPQRSTUVWXYZ", k=3)) + "".join(__import__("random").choices("0123456789", k=3))


def test_create_shop_and_versioned_rates(conn):
    shop = code()
    ap_admin.create_shop(conn, shop.lower(), "  Test  ")
    assert ap_admin.set_rates(conn, shop, RULES_OK) == 1
    assert ap_admin.set_rates(conn, shop, RULES_OK) == 2
    with conn.cursor() as cur:
        cur.execute("SELECT version, retired_at IS NULL FROM ap.rate_cards r JOIN ap.shops s ON s.id=r.shop_id WHERE s.code=%s ORDER BY version", (shop,))
        assert cur.fetchall() == [(1, False), (2, True)]
    conn.commit()


def test_bad_rate_card_is_refused_and_changes_nothing(conn):
    shop = code(); ap_admin.create_shop(conn, shop, "Shop"); ap_admin.set_rates(conn, shop, RULES_OK)
    bad = json.loads(json.dumps(RULES_OK)); bad["bw"]["simplex"][0]["paise_per_side"] = -5
    with pytest.raises(Exception):
        ap_admin.set_rates(conn, shop, bad)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ap.rate_cards r JOIN ap.shops s ON s.id=r.shop_id WHERE s.code=%s AND r.retired_at IS NULL", (shop,))
        assert cur.fetchone()[0] == 1
    conn.commit()


def test_issued_code_enrolls_exactly_once_and_is_stored_only_as_a_hash(conn):
    shop = code(); ap_admin.create_shop(conn, shop, "Shop")
    issued = ap_admin.issue_code(conn, shop, 30)
    assert len(issued) == 12
    with conn.cursor() as cur:
        cur.execute("SELECT code_hash FROM ap.enrollment_codes ec JOIN ap.shops s ON s.id=ec.shop_id WHERE s.code=%s", (shop,))
        assert cur.fetchone()[0] == sha256_hex(issued) and issued not in cur.fetchall().__repr__()
        cur.execute("SELECT ap.consume_enrollment(%s, 'PC', %s)", (sha256_hex(issued), sha256_hex(uuid.uuid4().hex)))
        assert cur.fetchone()[0]["result"] == "ok"
        cur.execute("SELECT ap.consume_enrollment(%s, 'PC', %s)", (sha256_hex(issued), sha256_hex("x")))
        assert cur.fetchone()[0]["result"] == "invalid_code"
    conn.commit()


def test_revoke_device(conn):
    shop = code(); ap_admin.create_shop(conn, shop, "Shop")
    issued = ap_admin.issue_code(conn, shop)
    with conn.cursor() as cur:
        cur.execute("SELECT ap.consume_enrollment(%s, 'PC', %s)", (sha256_hex(issued), sha256_hex("s")))
        device = cur.fetchone()[0]["device_id"]
    conn.commit()
    ap_admin.revoke_device(conn, device)
    with pytest.raises(SystemExit):
        ap_admin.revoke_device(conn, device)               # already revoked
