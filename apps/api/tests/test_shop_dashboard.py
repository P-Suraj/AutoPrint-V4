"""Shop owner logins: a private link key lets the shopkeeper approve their own computers, and nothing else."""
import secrets
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import ap_admin  # noqa: E402

from test_pairing import new_pairing  # noqa: E402


def err(r):
    return r.json()["error"]["code"]


def key_for(api_db_url, shop_code, label="owner"):
    conn = psycopg2.connect(api_db_url)
    try:
        return ap_admin.issue_shop_link(conn, shop_code, label)
    finally:
        conn.close()


def H(key):
    return {"X-Shop-Key": key}


def test_unknown_or_missing_key_is_refused(client, shop):
    assert client.get("/v1/shop/me", headers=H("0" * 64)).status_code == 401
    assert client.get("/v1/shop/me").status_code == 422
    assert client.get("/v1/shop/devices", headers=H("not-a-key")).status_code == 401


def test_shopkeeper_connects_their_own_computer_without_the_founder(client, shop, api_db_url):
    key = key_for(api_db_url, shop.code)
    me = client.get("/v1/shop/me", headers=H(key)).json()
    assert me["shop_code"] == shop.code

    poll, secret, start = new_pairing(client, "COUNTER-PC")
    look = client.get(f"/v1/shop/pair/{start['pair_code']}", headers=H(key))
    assert look.status_code == 200 and look.json()["display_name"] == "COUNTER-PC" and look.json()["approved"] is False

    ok = client.post("/v1/shop/pair/approve", headers=H(key), json={"pair_code": start["pair_code"]})
    assert ok.status_code == 200, ok.text
    done = client.post("/v1/agent/pair/poll", json={"poll_token": poll}).json()
    assert done["status"] == "approved" and done["shop_code"] == shop.code

    # the new computer is listed, and it can talk to the server with the secret it made itself
    devs = client.get("/v1/shop/devices", headers=H(key)).json()["devices"]
    assert [d["name"] for d in devs] == ["COUNTER-PC"]
    jobs = client.get("/v1/agent/jobs", headers={"X-Device-Id": done["device_id"], "X-Device-Secret": secret})
    assert jobs.status_code == 200

    # a second approval of the same code is refused
    again = client.post("/v1/shop/pair/approve", headers=H(key), json={"pair_code": start["pair_code"]})
    assert err(again) == "pairing_already_approved"


def test_a_shop_key_cannot_touch_another_shops_computers(client, shop, api_db_url):
    from dbtools import Shop
    key = key_for(api_db_url, shop.code)
    poll, secret, start = new_pairing(client)
    client.post("/v1/shop/pair/approve", headers=H(key), json={"pair_code": start["pair_code"]})
    device_id = client.post("/v1/agent/pair/poll", json={"poll_token": poll}).json()["device_id"]

    conn = psycopg2.connect(api_db_url); conn.autocommit = True
    other_code = "OTH" + str(secrets.randbelow(900) + 100)
    ap_admin.create_shop(conn, other_code, "Other Shop")
    other_key = ap_admin.issue_shop_link(conn, other_code, "owner")
    conn.close()

    assert client.post(f"/v1/shop/devices/{device_id}/revoke", headers=H(other_key)).status_code == 404
    assert client.get("/v1/shop/devices", headers=H(other_key)).json()["devices"] == []
    assert client.post(f"/v1/shop/devices/{device_id}/revoke", headers=H(key)).status_code == 204
    # a disconnected computer is locked out immediately
    assert client.get("/v1/agent/jobs", headers={"X-Device-Id": device_id, "X-Device-Secret": secret}).status_code == 401


def test_a_revoked_login_stops_working(client, shop, api_db_url):
    key = key_for(api_db_url, shop.code)
    assert client.get("/v1/shop/me", headers=H(key)).status_code == 200
    conn = psycopg2.connect(api_db_url); conn.autocommit = True
    cur = conn.cursor(); cur.execute("UPDATE ap.shop_logins SET revoked_at = now()"); conn.close()
    assert client.get("/v1/shop/me", headers=H(key)).status_code == 401


def test_only_the_hash_of_the_key_is_stored(client, shop, api_db_url):
    key = key_for(api_db_url, shop.code)
    conn = psycopg2.connect(api_db_url); cur = conn.cursor()
    cur.execute("SELECT credential_hash, method FROM ap.shop_logins")
    rows = cur.fetchall(); conn.close()
    assert all(key not in h and len(h) == 64 for h, _ in rows) and rows[-1][1] == "link"


def test_founder_endpoint_issues_and_revokes_logins_with_the_maintenance_token(settings, shop):
    import dataclasses
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(dataclasses.replace(settings, maintenance_token="m" * 40))) as client:
        _founder_endpoint_checks(client, shop)


def _founder_endpoint_checks(client, shop):
    token = {"X-Maintenance-Token": "m" * 40}
    assert client.post("/v1/internal/shop-login", json={"shop_code": shop.code}).status_code == 401
    assert client.post("/v1/internal/shop-login", headers={"X-Maintenance-Token": "x"}, json={"shop_code": shop.code}).status_code == 401
    r = client.post("/v1/internal/shop-login", headers=token, json={"shop_code": shop.code, "label": "e2e"})
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    assert client.get("/v1/shop/me", headers=H(key)).json()["shop_code"] == shop.code
    assert client.post("/v1/internal/shop-login", headers=token, json={"shop_code": "NOP000"}).status_code == 404
    assert client.post("/v1/internal/shop-login", headers=token, json={"revoke_label": "e2e"}).json() == {"revoked": 1}
    assert client.get("/v1/shop/me", headers=H(key)).status_code == 401
