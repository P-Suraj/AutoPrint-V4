"""Device-initiated pairing: the PC shows a code, the founder approves it, no secret travels back."""
import secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import ap_admin  # noqa: E402

from dbtools import sha  # noqa: E402


def err(r):
    return r.json()["error"]["code"]


def new_pairing(client, name="COUNTER-PC"):
    poll, secret = secrets.token_hex(32), secrets.token_hex(32)
    r = client.post("/v1/agent/pair/start", json={"display_name": name, "poll_token": poll, "device_secret": secret})
    assert r.status_code == 201, r.text
    return poll, secret, r.json()


def test_full_pairing_then_the_new_device_works(client, shop, raw_db, api_db_url):
    poll, secret, start = new_pairing(client)
    code = start["pair_code"]
    assert len(code) == 9 and code[4] == "-"
    assert client.post("/v1/agent/pair/poll", json={"poll_token": poll}).json() == {"status": "pending", "device_id": None, "shop_code": None, "shop_name": None}

    import psycopg2
    conn = psycopg2.connect(api_db_url)
    shown = ap_admin.show_pairing(conn, code.lower())                         # lower case and the dash are accepted
    assert shown["result"] == "ok" and shown["display_name"] == "COUNTER-PC" and shown["approved"] is False
    approved = ap_admin.approve_pairing(conn, code, shop.code)
    assert approved["result"] == "ok" and approved["shop_code"] == shop.code
    conn.close()

    done = client.post("/v1/agent/pair/poll", json={"poll_token": poll}).json()
    assert done["status"] == "approved" and done["shop_code"] == shop.code and done["device_id"]
    assert "device_secret" not in done and secret not in str(done)             # no secret ever comes back

    h = {"X-Device-Id": done["device_id"], "X-Device-Secret": secret}        # the secret the PC generated itself works
    assert client.get("/v1/agent/jobs", headers=h).status_code == 200
    assert client.get("/v1/agent/jobs", headers={**h, "X-Device-Secret": "0" * 64}).status_code == 401
    assert raw_db.one("SELECT credential_hash FROM ap.devices WHERE id=%s", (done["device_id"],)) == sha(secret)


def test_a_code_is_single_use_and_unknown_codes_are_refused(client, shop, api_db_url):
    import psycopg2
    conn = psycopg2.connect(api_db_url)
    _, _, start = new_pairing(client)
    assert ap_admin.approve_pairing(conn, start["pair_code"], shop.code)["result"] == "ok"
    assert ap_admin.approve_pairing(conn, start["pair_code"], shop.code)["result"] == "pairing_already_approved"
    assert ap_admin.approve_pairing(conn, "ZZZZZZZZ", shop.code)["result"] == "pairing_not_found"
    _, _, other = new_pairing(client)
    assert ap_admin.approve_pairing(conn, other["pair_code"], "NOP000")["result"] == "shop_not_found"
    conn.close()


def test_expired_pairing_cannot_be_approved_and_polls_as_expired(client, shop, raw_db, api_db_url):
    import psycopg2
    poll, _, start = new_pairing(client)
    raw_db.run("UPDATE ap.pairings SET expires_at = now() - interval '1 second' WHERE poll_hash=%s", (sha(poll),))
    conn = psycopg2.connect(api_db_url)
    assert ap_admin.approve_pairing(conn, start["pair_code"], shop.code)["result"] == "pairing_expired"
    conn.close()
    assert client.post("/v1/agent/pair/poll", json={"poll_token": poll}).json()["status"] == "expired"


def test_unknown_poll_token_and_malformed_input(client):
    assert client.post("/v1/agent/pair/poll", json={"poll_token": "a" * 64}).status_code == 404
    assert client.post("/v1/agent/pair/poll", json={"poll_token": "short"}).status_code == 422
    r = client.post("/v1/agent/pair/start", json={"display_name": "PC", "poll_token": "x" * 64, "device_secret": "y" * 64})
    assert r.status_code == 422 and err(r) == "invalid_request"


def test_tokens_and_secrets_are_stored_only_as_hashes(client, raw_db):
    poll, secret, _ = new_pairing(client)
    row = raw_db.one("SELECT poll_hash, credential_hash FROM ap.pairings WHERE poll_hash=%s", (sha(poll),))
    assert row == (sha(poll), sha(secret))
    dump = " ".join(str(c) for c in raw_db.one("SELECT to_jsonb(p)::text FROM ap.pairings p WHERE poll_hash=%s", (sha(poll),)))
    assert poll not in dump and secret not in dump


def test_pairing_start_is_rate_limited_globally(client, raw_db):
    raw_db.run("DELETE FROM ap.pairings WHERE created_at > now() - interval '2 minutes'")
    for _ in range(60):
        raw_db.run("INSERT INTO ap.pairings (code, poll_hash, credential_hash, display_name, expires_at) "
                   "VALUES (substr(upper(md5(random()::text)),1,8), md5(random()::text)||md5(random()::text), 'x', 'PC', now()+interval '1 hour')")
    poll, secret = secrets.token_hex(32), secrets.token_hex(32)
    r = client.post("/v1/agent/pair/start", json={"display_name": "PC", "poll_token": poll, "device_secret": secret})
    assert r.status_code == 503 and err(r) == "try_again"
    raw_db.run("DELETE FROM ap.pairings")                                    # leave a clean table for other tests
