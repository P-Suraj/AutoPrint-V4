"""Shop owner logins: a private link key lets the shopkeeper approve their own computers, and nothing else."""
import secrets
import sys
from pathlib import Path

import psycopg2
import pdfs  # noqa: F401  (sample PDFs)

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
    # revoking is per shop: the same label at another shop is untouched, and a shop code is required
    other = type(shop)(shop.db)
    other_key = client.post("/v1/internal/shop-login", headers=token, json={"shop_code": other.code, "label": "e2e"}).json()["key"]
    assert client.post("/v1/internal/shop-login", headers=token, json={"revoke_label": "e2e"}).status_code == 404
    assert client.get("/v1/shop/me", headers=H(key)).status_code == 200
    assert client.post("/v1/internal/shop-login", headers=token, json={"shop_code": shop.code, "revoke_label": "e2e"}).json() == {"revoked": 1}
    assert client.get("/v1/shop/me", headers=H(key)).status_code == 401
    assert client.get("/v1/shop/me", headers=H(other_key)).json()["shop_code"] == other.code


def test_founder_report_shows_counts_devices_and_no_document_names(settings, shop, flow, client, api_db_url):
    import dataclasses
    from fastapi.testclient import TestClient
    from app.main import create_app
    import pdfs
    flow.full(pdfs.blank(2))
    key = key_for(api_db_url, shop.code)
    poll, secret, start = new_pairing(client, "COUNTER-PC")
    client.post("/v1/shop/pair/approve", headers=H(key), json={"pair_code": start["pair_code"]})
    with TestClient(create_app(dataclasses.replace(settings, maintenance_token="m" * 40))) as c:
        assert c.get(f"/v1/internal/report/{shop.code}").status_code == 401
        r = c.get(f"/v1/internal/report/{shop.code}", headers={"X-Maintenance-Token": "m" * 40})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["counts"] == {"awaiting_approval": 1} and body["shop"]["code"] == shop.code
        assert len(body["jobs"]) == 1 and body["jobs"][0]["status"] == "awaiting_approval"
        assert body["devices"][0]["name"] == "COUNTER-PC" and body["devices"][0]["status"] == "active"
        assert "doc.pdf" not in r.text and "file_name" not in r.text
        assert c.get("/v1/internal/report/NOP000", headers={"X-Maintenance-Token": "m" * 40}).status_code == 404


def test_founder_can_create_a_shop_and_publish_rates_without_the_database_port(settings):
    import dataclasses
    from fastapi.testclient import TestClient
    from app.main import create_app
    tok = {"X-Maintenance-Token": "m" * 40}
    code = "ZQ" + secrets.choice("ABCDEFGHJK") + str(secrets.randbelow(900) + 100)
    rules = {"bw": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 200}], "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 120}]},
             "color": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 1000}], "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 800}]}}
    with TestClient(create_app(dataclasses.replace(settings, maintenance_token="m" * 40))) as c:
        assert c.post("/v1/internal/shop", json={"code": code, "name": "X"}).status_code == 401
        assert c.post("/v1/internal/shop", headers=tok, json={"code": "bad", "name": "X"}).status_code == 404
        assert c.post("/v1/internal/shop", headers=tok, json={"code": code, "name": "Nameless", "rules": {"bw": {}}}).status_code == 409
        assert c.get(f"/v1/shops/{code}").status_code == 404                         # the bad rate card created nothing
        r = c.post("/v1/internal/shop", headers=tok, json={"code": code, "name": "New Print Shop", "rules": rules})
        assert r.status_code == 200 and r.json() == {"code": code, "created": True, "rate_card_version": 1}
        assert c.get(f"/v1/shops/{code}").json()["name"] == "New Print Shop"
        assert c.get(f"/v1/shops/{code}/rates").status_code == 200
        again = c.post("/v1/internal/shop", headers=tok, json={"code": code, "rules": rules}).json()
        assert again == {"code": code, "created": False, "rate_card_version": 2}


def test_purge_deletes_the_files_of_a_finished_order_but_not_of_a_live_one(settings, shop, flow, raw_db):
    import dataclasses
    from fastapi.testclient import TestClient
    from app.main import create_app
    tok = {"X-Maintenance-Token": "m" * 40}
    parts = flow.full(pdfs.blank(2))
    short = flow.view().json()["short_code"]
    # another order whose file is already due for the normal cleanup: a purge must leave it alone
    bystander = shop.submitted_order()
    raw_db.run("UPDATE ap.documents SET delete_after = now() - interval '1 minute' WHERE id = %s", (bystander["doc_ids"][0],))
    with TestClient(create_app(dataclasses.replace(settings, maintenance_token="m" * 40))) as c:
        assert c.post("/v1/internal/purge", json={"shop_code": shop.code, "order": short}).status_code == 401
        live = c.post("/v1/internal/purge", headers=tok, json={"shop_code": shop.code, "order": short})
        assert live.status_code == 409                                              # still waiting for approval: nothing deleted
        assert raw_db.one("SELECT count(*) FROM ap.documents WHERE deleted_at IS NULL") >= 1
        assert flow.cancel().status_code == 200                                     # the job is now final
        done = c.post("/v1/internal/purge", headers=tok, json={"shop_code": shop.code, "order": short})
        assert done.status_code == 200, done.text
        assert done.json()["documents_remaining"] == 0 and done.json()["documents_deleted_now"] == 1
        assert raw_db.one("SELECT deleted_at FROM ap.documents WHERE id = %s", (bystander["doc_ids"][0],)) is None
        assert c.post("/v1/internal/purge", headers=tok, json={"shop_code": shop.code, "order": "ZZZZ"}).status_code == 404
    raw_db.run("UPDATE ap.documents SET delete_after = now() + interval '1 hour' WHERE id = %s", (bystander["doc_ids"][0],))


def test_rate_limits_stop_a_flood_of_orders_but_not_normal_use(settings, shop):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(settings)) as c:
        ip_a = {"X-Forwarded-For": "203.0.113.7"}
        codes = [c.post(f"/v1/shops/{shop.code}/orders", headers=ip_a).status_code for _ in range(62)]
        assert codes[:60] == [201] * 60                                              # a busy campus address is fine
        assert codes[60:] == [429, 429]                                              # the flood is stopped
        r = c.post(f"/v1/shops/{shop.code}/orders", headers=ip_a)
        assert r.json()["error"]["code"] == "rate_limited"
        assert c.post(f"/v1/shops/{shop.code}/orders", headers={"X-Forwarded-For": "198.51.100.9"}).status_code == 201   # others are unaffected


def test_pairing_codes_are_limited_per_address(client):
    ip = {"X-Forwarded-For": "203.0.113.50"}
    results = []
    for _ in range(14):
        body = {"display_name": "PC", "poll_token": secrets.token_hex(32), "device_secret": secrets.token_hex(32)}
        results.append(client.post("/v1/agent/pair/start", json=body, headers=ip).status_code)
    assert results[:12] == [201] * 12 and results[12:] == [429, 429]


def test_the_limiter_never_stores_an_address(settings, shop, raw_db):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(settings)) as c:
        c.post(f"/v1/shops/{shop.code}/orders", headers={"X-Forwarded-For": "203.0.113.77"})
    assert raw_db.one("SELECT count(*) FROM ap.rate_limits WHERE position('203.0.113' in bucket) > 0") == 0
