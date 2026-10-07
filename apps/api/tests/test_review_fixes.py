"""Tests for the security-review fixes that were changed without a test of their own: the page range (ASCII only,
stored in one normal form), purge of one order among several with the same code, the limiter's secret, the upload
limit per address, and the read-only migration status with its founder command."""
import dataclasses
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from fastapi.testclient import TestClient

import pdfs
from app.main import create_app
from app.pricing import PricingError, normalise_pages, parse_page_range, price_job
from app.settings import ConfigError, Settings
from conftest import Flow
from dbtools import MIGRATIONS, build_database, drop_database
from sample_data import RULES

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import ap_remote  # noqa: E402

TOKEN = {"X-Maintenance-Token": "m" * 40}


def err(r):
    return r.json()["error"]["code"]


# ------------------------------------------------------------------ page range

@pytest.mark.parametrize("text", [
    "١-٣",            # Arabic-Indic digits: int() reads them, a print program may not
    "１-３",            # full-width digits
    "1-3\n",           # a line break after a valid range
    "1-3\n-print-to-default",
    "1\t-3", "1,\n2", "\t1-3", "1-3\r",
    "1 - 3",           # spaces are allowed around commas only
    "1234567",         # more than six digits
    "1-", "-3", "1,,2", "a", "1;2",
])
def test_a_page_range_with_anything_but_plain_digits_commas_hyphens_and_spaces_is_refused(text):
    with pytest.raises(PricingError) as e:
        parse_page_range(text, 9)
    assert e.value.code == "invalid_page_range"


def test_a_page_range_is_priced_and_stored_in_one_normal_form():
    assert normalise_pages([]) == ""
    assert normalise_pages([4]) == "4"
    assert normalise_pages([1, 2, 3, 5, 8, 9]) == "1-3,5,8-9"
    price = lambda r: price_job(page_count=9, copies=1, color=False, duplex=False, page_range=r, rules=RULES)  # noqa: E731
    repeated = price("1,1,1")
    assert (repeated.selected_pages, repeated.page_range) == (1, "1")           # priced as one page, printed as one page
    assert price(" 5 , 1-3 ,2").page_range == "1-3,5"
    assert price("1-9").page_range == "1-9" and price("1-9").selected_pages == 9
    for whole in (None, "", "   "):
        assert price(whole).page_range is None and price(whole).selected_pages == 9


def test_the_quote_stores_the_normal_form_and_never_the_text_the_customer_typed(flow, raw_db):
    flow.create_order()
    doc = flow.upload(pdfs.blank(6))
    assert flow.finalize(doc).status_code == 200
    q = flow.quote([{"document_id": doc, "options": {"page_range": " 4 ,1-2, 2,1"}}])
    assert q.status_code == 201, q.text
    assert raw_db.one("SELECT page_range FROM ap.quote_items WHERE quote_id = %s", (q.json()["quote_id"],)) == "1-2,4"
    whole = flow.quote([{"document_id": doc, "options": {"page_range": "  "}}])
    assert whole.status_code == 201, whole.text
    assert raw_db.one("SELECT page_range FROM ap.quote_items WHERE quote_id = %s", (whole.json()["quote_id"],)) is None
    for bad in ("١-٣", "1-2\n"):
        r = flow.quote([{"document_id": doc, "options": {"page_range": bad}}])
        assert r.status_code in (400, 422) and err(r) in ("invalid_page_range", "invalid_request"), r.text


# ------------------------------------------------------------------ purge one order among several with the same code

def test_purge_takes_one_order_only_the_most_recent_unless_told_otherwise(settings, shop, raw_db, monkeypatch, capsys):
    older, newer = shop.submitted_order(), shop.submitted_order()
    for o in (older, newer):                                                       # both finished, so a purge is allowed
        raw_db.run("UPDATE ap.jobs SET status = 'rejected' WHERE order_id = %s", (o["order_id"],))
    raw_db.run("UPDATE ap.orders SET status = 'closed', short_code = 'PRG7', created_at = now() - interval '2 hours' WHERE id = %s", (older["order_id"],))
    raw_db.run("UPDATE ap.orders SET status = 'closed', short_code = 'PRG7' WHERE id = %s", (newer["order_id"],))
    left = lambda o: raw_db.one("SELECT count(*) FROM ap.documents WHERE order_id = %s AND deleted_at IS NULL", (o["order_id"],))  # noqa: E731
    with TestClient(create_app(dataclasses.replace(settings, maintenance_token="m" * 40))) as c:
        body = {"shop_code": shop.code, "order": "PRG7"}
        for bad in (0, -1, "1", True, 1.5):
            assert c.post("/v1/internal/purge", headers=TOKEN, json={**body, "which": bad}).status_code in (400, 422)
        assert c.post("/v1/internal/purge", headers=TOKEN, json={**body, "which": 3}).status_code == 404
        assert (left(older), left(newer)) == (1, 1)                                # nothing deleted by a refused call

        first = c.post("/v1/internal/purge", headers=TOKEN, json=body)
        assert first.status_code == 200, first.text
        r = first.json()
        assert (r["orders_matched"], r["purged"], r["documents_deleted_now"], r["documents_remaining"]) == (2, 1, 1, 0)
        assert [m["purged_now"] for m in r["matches"]] == [True, False]
        assert (left(older), left(newer)) == (1, 0)                                # only the most recent one lost its file

        for mod_attr, value in (("HTTP", c), ("BASE", ""), ("token", lambda: "m" * 40)):
            monkeypatch.setattr(ap_remote, mod_attr, value)
        assert ap_remote.main(["purge", shop.code, "PRG7", "--which", "2"]) == 0
        out = capsys.readouterr().out
        assert "files deleted now 1" in out and "Only ONE was purged" in out and "--which 2" in out and "<- purged now" in out
        assert (left(older), left(newer)) == (0, 0)


# ------------------------------------------------------------------ the limiter's secret

def test_the_limiter_is_salted_even_when_no_signing_key_is_set():
    base = dict(database_url="postgresql://u@h/d", storage_backend="supabase", supabase_url="https://x.supabase.co")
    assert Settings(**base, signing_key="s" * 40, supabase_secret_key="k", maintenance_token="t").limiter_secret == "s" * 40
    production = Settings(**base, supabase_secret_key="secret-key", maintenance_token="t")
    assert production.validate().limiter_secret == "secret-key"                  # what the live site has: no signing key
    assert Settings(**base, maintenance_token="t").limiter_secret == "t"
    with pytest.raises(ConfigError):
        Settings(**base).validate()


def test_the_bucket_name_depends_on_the_server_secret(settings, shop, raw_db):
    """The same address must give a different stored bucket under a different secret: without the secret the
    hash could be turned back into the address by trying every address."""
    raw_db.run("DELETE FROM ap.rate_limits")
    seen = []
    for key in ("a" * 40, "b" * 40):
        with TestClient(create_app(dataclasses.replace(settings, signing_key=key))) as c:
            assert c.post(f"/v1/shops/{shop.code}/orders", headers={"X-Forwarded-For": "203.0.113.200"}).status_code == 201
        seen.append({r[0] for r in raw_db.rows("SELECT bucket FROM ap.rate_limits")} - set().union(*seen))
    assert seen[0] and seen[1] and not (seen[0] & seen[1])


# ------------------------------------------------------------------ uploads per address

def test_one_address_can_register_120_files_an_hour_and_others_are_unaffected(settings, shop):
    with TestClient(create_app(dataclasses.replace(settings, signing_key="u" * 40))) as c:   # its own buckets
        ip = {"X-Forwarded-For": "203.0.113.120"}
        codes = []
        for _ in range(7):                                                         # 20 files per order, 7 orders
            o = c.post(f"/v1/shops/{shop.code}/orders", headers=ip).json()
            for _ in range(20):
                codes.append(c.post(f"/v1/orders/{o['order_id']}/documents", headers={**ip, "X-Order-Secret": o["order_secret"]},
                                    json={"file_name": "a.pdf", "byte_size": 1000, "content_type": "application/pdf"}).status_code)
                if len(codes) == 122:
                    break
        assert codes[:120] == [201] * 120 and codes[120:] == [429, 429]
        other = {"X-Forwarded-For": "198.51.100.120"}
        o = c.post(f"/v1/shops/{shop.code}/orders", headers=other).json()
        assert c.post(f"/v1/orders/{o['order_id']}/documents", headers={**other, "X-Order-Secret": o["order_secret"]},
                      json={"file_name": "a.pdf", "byte_size": 1000, "content_type": "application/pdf"}).status_code == 201


# ------------------------------------------------------------------ migration status

def test_status_lists_applied_and_pending_updates_and_changes_nothing(tmp_path, monkeypatch, capsys):
    name = "v4_stat_" + uuid.uuid4().hex[:8]
    url = build_database(name)
    conn = psycopg2.connect(url); conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE TABLE ap.schema_migrations (id text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    for f in MIGRATIONS[:-2]:
        cur.execute("INSERT INTO ap.schema_migrations (id) VALUES (%s)", (f.stem,))
    cur.execute("INSERT INTO ap.schema_migrations (id) VALUES ('9999_from_a_newer_site')")
    s = Settings(database_url=url, local_storage_dir=str(tmp_path / "f"), signing_key="k" * 40, maintenance_token="m" * 40,
                 background_maintenance=False).validate()
    try:
        with TestClient(create_app(s)) as c:
            assert c.get("/v1/internal/status").status_code == 401
            assert c.get("/v1/internal/status", headers={"X-Maintenance-Token": "nope"}).status_code == 401
            r = c.get("/v1/internal/status", headers=TOKEN)
            assert r.status_code == 200, r.text
            d = r.json()
            assert [m["id"] for m in d["applied"]] == [f.stem for f in MIGRATIONS[:-2]] + ["9999_from_a_newer_site"]
            assert d["pending"] == [f.stem for f in MIGRATIONS[-2:]]
            assert d["not_in_this_deployment"] == ["9999_from_a_newer_site"]
            cur.execute("SELECT count(*) FROM ap.schema_migrations")
            assert cur.fetchone()[0] == len(MIGRATIONS) - 1                        # read-only: nothing was applied

            for mod_attr, value in (("HTTP", c), ("BASE", ""), ("token", lambda: "m" * 40)):
                monkeypatch.setattr(ap_remote, mod_attr, value)
            assert ap_remote.main(["status"]) == 0
            out = capsys.readouterr().out
            assert "Site: live (HTTP 200)" in out and "PENDING, not applied yet: 2" in out
            assert MIGRATIONS[-1].stem in out and "9999_from_a_newer_site" in out and "m" * 40 not in out
            cur.execute("DELETE FROM ap.schema_migrations WHERE id = '9999_from_a_newer_site'")
            assert ap_remote.main(["migrate"]) == 0
            out = capsys.readouterr().out
            assert "Applied now: 2" in out and MIGRATIONS[-1].stem in out
            assert ap_remote.main(["migrate"]) == 0
            assert "Nothing to apply" in capsys.readouterr().out
            assert ap_remote.main(["status"]) == 0
            assert "Nothing pending" in capsys.readouterr().out
    finally:
        conn.close()
        drop_database(name)
