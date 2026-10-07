"""Phase 3 gate: the customer API against a real database and real file storage."""
import logging
import re
import time
import uuid
from pathlib import Path

import pytest

import pdfs
from app.main import run_maintenance_once
from dbtools import sha


def err(r):
    return r.json()["error"]["code"]


# ------------------------------------------------------------------ health and shop lookup
def test_health_and_readiness(client):
    assert client.get("/health").json()["status"] == "live"
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_shop_lookup_is_case_insensitive_and_reports_agent_status(client, shop, raw_db):
    r = client.get(f"/v1/shops/{shop.code.lower()}")
    assert r.status_code == 200
    assert r.json() == {"code": shop.code, "name": "Test Shop", "accepting_orders": True, "agent_online": False,
                        "color_available": True}
    device = shop.device()                                     # enrollment alone is not "online"
    assert client.get(f"/v1/shops/{shop.code}").json()["agent_online"] is False
    raw_db.run("UPDATE ap.devices SET last_seen_at = now() WHERE id = %s", (device,))
    assert client.get(f"/v1/shops/{shop.code}").json()["agent_online"] is True
    raw_db.run("UPDATE ap.devices SET last_seen_at = now() - interval '2 minutes' WHERE id = %s", (device,))
    assert client.get(f"/v1/shops/{shop.code}").json()["agent_online"] is False


def test_unknown_shop(client):
    r = client.get("/v1/shops/ZZZ999")
    assert r.status_code == 404 and err(r) == "shop_not_found"
    assert client.post("/v1/shops/ZZZ999/orders").status_code == 404


def test_rates_endpoint_and_missing_rate_card(client, shop, raw_db):
    r = client.get(f"/v1/shops/{shop.code}/rates")
    assert r.status_code == 200 and r.json()["bw"]["simplex"][0]["paise_per_side"] == 200
    raw_db.run("UPDATE ap.rate_cards SET retired_at = now() WHERE shop_id = %s", (shop.id,))
    r = client.get(f"/v1/shops/{shop.code}/rates")
    assert r.status_code == 409 and err(r) == "no_rate_card"


# ------------------------------------------------------------------ the happy path, end to end
def test_three_pages_black_and_white_costs_six_rupees_and_reaches_the_shop(flow, raw_db):
    done = flow.full(pdfs.blank(3))
    assert done["quote"]["total_paise"] == 600
    assert done["quote"]["items"][0] == {"document_id": done["doc"], "selected_pages": 3, "printed_sides": 3,
                                          "paise_per_side": 200, "amount_paise": 600}
    sub = done["submit"]
    assert sub["payment_mode"] == "pay_at_counter" and sub["payment_status"] == "not_required" and sub["amount_paise"] == 600
    view = flow.view().json()
    assert view["status"] == "submitted" and view["can_cancel"] is True and len(view["jobs"]) == 1
    assert view["jobs"][0]["status"] == "awaiting_approval"
    assert view["jobs"][0]["customer_message"] == "Waiting for the shop to approve your print."
    assert view["approval_expires_at"] is not None and re.fullmatch(r"[A-Z0-9]{4}", view["short_code"])
    types = [r[0] for r in raw_db.rows("SELECT type FROM ap.events WHERE order_id = %s ORDER BY id", (flow.order_id,))]
    assert types == ["order.created", "document.registered", "document.validated", "quote.created", "order.submitted"]


def test_settings_change_the_price(flow):
    flow.create_order()
    doc = flow.upload(pdfs.blank(10))
    flow.finalize(doc)
    cases = [({}, 2000), ({"copies": 3}, 6000), ({"duplex": True}, 1200), ({"color": True}, 10000),
             ({"page_range": "2-4"}, 600), ({"copies": 2, "page_range": "1-2,5", "duplex": True, "color": True}, 4800)]
    for options, expected in cases:
        q = flow.quote([{"document_id": doc, "options": options}])
        assert q.status_code == 201 and q.json()["total_paise"] == expected, (options, q.text)


def test_the_server_prices_the_customer_cannot(flow):
    flow.create_order()
    doc = flow.upload(pdfs.blank(3))
    flow.finalize(doc)
    r = flow.quote([{"document_id": doc, "options": {"copies": 1}, "amount_paise": 1}])      # extra field is refused
    assert r.status_code == 422 and err(r) == "invalid_request"


# ------------------------------------------------------------------ access control
def test_every_order_route_needs_the_right_secret(flow, client, shop):
    flow.create_order()
    other = type(flow)(client, shop); other.create_order()
    doc = flow.upload(pdfs.blank(1))
    routes = [("get", f"/v1/orders/{flow.order_id}"), ("post", f"/v1/orders/{flow.order_id}/cancel"),
              ("post", f"/v1/orders/{flow.order_id}/documents/{doc}/finalize")]
    for method, url in routes:
        none = getattr(client, method)(url)
        assert none.status_code == 422 and err(none) == "invalid_request"            # header missing
        wrong = getattr(client, method)(url, headers={"X-Order-Secret": "0" * 64})
        assert wrong.status_code == 404 and err(wrong) == "order_not_found"
        theirs = getattr(client, method)(url, headers=other.h)                       # another order's valid secret
        assert theirs.status_code == 404 and err(theirs) == "order_not_found"
    assert flow.view().status_code == 200


def test_secret_is_never_returned_again_or_stored(flow, raw_db):
    body = flow.create_order()
    assert "order_secret" in body
    assert "order_secret" not in flow.view().json() and flow.secret not in flow.view().text
    stored = raw_db.one("SELECT secret_hash FROM ap.orders WHERE id = %s", (flow.order_id,))
    assert stored == sha(flow.secret)


def test_contract_version_mismatch_is_refused(client, shop):
    r = client.get(f"/v1/shops/{shop.code}", headers={"X-AutoPrint-Contract-Version": "99"})
    assert r.status_code == 426 and err(r) == "contract_mismatch"
    ok = client.get(f"/v1/shops/{shop.code}", headers={"X-AutoPrint-Contract-Version": "1"})
    assert ok.status_code == 200 and ok.headers["X-AutoPrint-Contract-Version"] == "1"


# ------------------------------------------------------------------ the upload path (V3's worst incident)
def test_upload_is_a_raw_put_and_multipart_is_caught(flow):
    flow.create_order()
    good = pdfs.blank(2)
    # raw bytes: works
    assert flow.finalize(flow.upload(good)).json()["page_count"] == 2
    # the V3 bug: a browser sends FormData to the raw URL; the stored object is not a PDF
    wrapped = pdfs.multipart_wrapped(good)
    doc = flow.upload(wrapped)
    r = flow.finalize(doc)
    assert r.status_code == 422 and err(r) == "file_not_pdf", r.text


def test_signed_url_rules(flow, client):
    flow.create_order()
    reg = flow.register(100).json()
    url = reg["upload_url"]
    path = url.split("http://testserver", 1)[1]
    assert client.put(path.replace("sig=", "sig=00"), content=b"x" * 100).status_code == 401      # bad signature
    expired = re.sub(r"exp=\d+", "exp=1", path)
    assert client.put(expired, content=b"x" * 100).status_code == 401                              # expired
    assert client.put(path, content=b"x" * 101).status_code == 413                                 # over the declared maximum
    traversal = path.replace("/v1/dev-storage/orders/", "/v1/dev-storage/orders/../../")
    assert client.put(traversal, content=b"x").status_code in (401, 404, 422)
    assert client.put(path, content=b"x" * 100).status_code == 200


def test_finalize_before_upload_waits_instead_of_rejecting(flow):
    flow.create_order()
    doc = flow.register(1000).json()["document_id"]
    r = flow.finalize(doc)
    assert r.status_code == 409 and err(r) == "upload_missing"
    assert flow.view().json()["status"] == "draft"


def test_size_mismatch_rejects_and_deletes_the_object(flow, settings):
    flow.create_order()
    reg = flow.register(5000).json()
    flow.c.put(reg["upload_url"], content=pdfs.blank(1), headers=reg["upload_headers"])           # smaller than declared
    r = flow.finalize(reg["document_id"])
    assert r.status_code == 422 and err(r) == "upload_size_mismatch"
    assert not list(Path(settings.local_storage_dir).rglob("*.pdf"))
    assert flow.finalize(reg["document_id"]).status_code == 409                                    # now rejected, not retryable


def test_finalize_is_idempotent(flow):
    flow.create_order()
    doc = flow.upload(pdfs.blank(4))
    first, second = flow.finalize(doc), flow.finalize(doc)
    assert first.status_code == second.status_code == 200 and first.json() == second.json()


def test_oversize_declared_file_is_refused_before_any_upload(flow):
    flow.create_order()
    r = flow.register(26_214_401)
    assert r.status_code == 413 and err(r) == "file_too_large"
    assert flow.register(26_214_400).status_code == 201


# ------------------------------------------------------------------ PDF validation corpus
VALID_CORPUS = [
    pytest.param(lambda: pdfs.blank(1), 1, id="one-page"),
    pytest.param(lambda: pdfs.blank(10), 10, id="ten-pages"),
    pytest.param(lambda: pdfs.blank(200), 200, id="two-hundred-pages"),
    pytest.param(lambda: pdfs.handmade(b"BT /F1 12 Tf 10 10 Td (hello) Tj ET"), 1, id="handmade-minimal"),
    pytest.param(lambda: pdfs.handmade(b"q Q", pages=3), 3, id="handmade-three-pages"),
    pytest.param(lambda: pdfs.with_leading_junk(pdfs.blank(2)), 2, id="leading-whitespace-before-header"),
    pytest.param(lambda: pdfs.noisy_containing_js(1), 1, id="V3-bug-random-data-with-JS-1MB"),
    pytest.param(lambda: pdfs.noisy_containing_js(8), 1, id="V3-bug-random-data-with-JS-8MB"),
    pytest.param(lambda: pdfs.noisy_containing_js(24), 1, id="V3-bug-random-data-with-JS-24MB"),
]


@pytest.mark.parametrize("make,pages", VALID_CORPUS)
def test_valid_pdfs_are_accepted_with_the_right_page_count(flow, make, pages):
    flow.create_order()
    r = flow.finalize(flow.upload(make()))
    assert r.status_code == 200, r.text
    assert r.json()["page_count"] == pages
    assert len(r.json()["sha256"]) == 64


INVALID_CORPUS = [
    pytest.param(lambda: pdfs.encrypted(), "pdf_encrypted", id="encrypted"),
    pytest.param(lambda: pdfs.with_javascript(), "pdf_unreadable", id="embedded-javascript-action"),
    pytest.param(lambda: pdfs.truncated(pdfs.blank(30)), "pdf_unreadable", id="truncated-file"),
    pytest.param(lambda: pdfs.plain_text(), "file_not_pdf", id="plain-text-renamed-pdf"),
    pytest.param(lambda: pdfs.png_like(), "file_not_pdf", id="png-renamed-pdf"),
    pytest.param(lambda: b"%PDF-1.7", "pdf_unreadable", id="header-only"),
    pytest.param(lambda: pdfs.multipart_wrapped(pdfs.blank(2)), "file_not_pdf", id="multipart-envelope-around-a-pdf"),
    pytest.param(lambda: b"x" * 200 + pdfs.blank(1), "file_not_pdf", id="junk-before-header"),
]


@pytest.mark.parametrize("make,code", INVALID_CORPUS)
def test_unacceptable_files_get_a_clear_reason_and_are_deleted(flow, settings, make, code):
    flow.create_order()
    r = flow.finalize(flow.upload(make()))
    assert r.status_code == 422 and err(r) == code, r.text
    assert not list(Path(settings.local_storage_dir).rglob("*.pdf"))


# ------------------------------------------------------------------ quote and submit rules
def test_invalid_print_options(flow):
    flow.create_order()
    doc = flow.upload(pdfs.blank(5))
    flow.finalize(doc)
    for bad, code in [("6", "invalid_page_range"), ("0-2", "invalid_page_range"), ("a-b", "invalid_page_range"), ("3-1", "invalid_page_range")]:
        r = flow.quote([{"document_id": doc, "options": {"page_range": bad}}])
        assert r.status_code == 422 and err(r) == code, (bad, r.text)
    assert err(flow.quote([{"document_id": doc, "options": {"copies": 101}}])) == "invalid_request"
    assert err(flow.quote([{"document_id": doc, "options": {"copies": 0}}])) == "invalid_request"


def test_document_must_be_finalized_before_pricing(flow):
    flow.create_order()
    doc = flow.upload(pdfs.blank(2))                       # uploaded, not finalized
    r = flow.quote([{"document_id": doc, "options": {}}])
    assert r.status_code == 409 and err(r) == "document_not_ready"
    assert err(flow.quote([{"document_id": str(uuid.uuid4()), "options": {}}])) == "document_not_ready"


def test_submit_is_idempotent_and_blocks_further_changes(flow):
    done = flow.full(pdfs.blank(2))
    again = flow.submit(done["quote"]["quote_id"])
    assert again.status_code == 200 and again.json()["job_ids"] == done["submit"]["job_ids"]
    assert err(flow.register(100)) == "order_not_draft"
    assert err(flow.quote([{"document_id": done["doc"], "options": {}}])) == "order_not_draft"


def test_quote_from_another_order_cannot_be_submitted(flow, client, shop):
    first = flow.full(pdfs.blank(1))
    other = type(flow)(client, shop); other.create_order()
    r = other.submit(first["quote"]["quote_id"])
    assert r.status_code == 404 and err(r) == "quote_not_found"


def test_shop_without_rate_card_cannot_quote(flow, raw_db, shop):
    flow.create_order()
    doc = flow.upload(pdfs.blank(1)); flow.finalize(doc)
    raw_db.run("UPDATE ap.rate_cards SET retired_at = now() WHERE shop_id = %s", (shop.id,))
    r = flow.quote([{"document_id": doc, "options": {}}])
    assert r.status_code == 409 and err(r) == "no_rate_card"


# ------------------------------------------------------------------ cancellation (decision F-9)
def test_cancel_before_claim_then_status_reflects_it(flow):
    flow.full(pdfs.blank(1))
    r = flow.cancel()
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    v = flow.view().json()
    assert v["status"] == "cancelled" and v["can_cancel"] is False and v["jobs"][0]["status"] == "cancelled"
    assert flow.cancel().status_code == 200                       # idempotent


def test_cancel_after_claim_is_too_late(flow, shop, raw_db):
    flow.full(pdfs.blank(1))
    device = shop.device()
    job_id = flow.view().json()["jobs"][0]["job_id"]
    assert raw_db.call("approve_job", job_id, device)["result"] == "ok"
    assert raw_db.call("claim_next_job", device, 300)["result"] == "claimed"
    v = flow.view().json()
    assert v["can_cancel"] is False and v["jobs"][0]["status"] == "printing"
    assert v["jobs"][0]["customer_message"] == "Sending to the printer."
    r = flow.cancel()
    assert r.status_code == 409 and err(r) == "too_late"


def test_customer_text_after_completion_never_says_printed(flow, shop, raw_db):
    flow.full(pdfs.blank(1))
    device = shop.device()
    job_id = flow.view().json()["jobs"][0]["job_id"]
    raw_db.call("approve_job", job_id, device)
    c = raw_db.call("claim_next_job", device, 300)
    raw_db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)
    ev = {"rule_version": 2, "spooler_job_seen": True, "printing_seen": True, "left_queue": True,
          "flags_seen": ["PRINTING"], "max_pages_printed": 1}
    assert raw_db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "completed", ev)["result"] == "ok"
    v = flow.view().json()
    assert v["status"] == "closed" and v["jobs"][0]["customer_message"] == "Sent to printer. Collect it at the counter."
    assert "printed" not in v["jobs"][0]["customer_message"].lower()


# ------------------------------------------------------------------ retention (decision O-5)
def test_maintenance_deletes_expired_documents_from_storage_and_marks_them(flow, settings, raw_db, api_db_url):
    from app.db import Database
    from app.main import make_storage
    flow.create_order()
    doc = flow.upload(pdfs.blank(1))
    key = raw_db.one("SELECT object_key FROM ap.documents WHERE id = %s", (doc,))
    path = Path(settings.local_storage_dir) / key
    assert path.exists()
    raw_db.run("UPDATE ap.orders SET created_at = now() - interval '2 hours', expires_at = now() - interval '1 second' WHERE id = %s", (flow.order_id,))
    raw_db.run("UPDATE ap.documents SET created_at = now() - interval '2 hours' WHERE id = %s", (doc,))
    db = Database(api_db_url)
    try:
        result = run_maintenance_once(db, make_storage(settings))
    finally:
        db.close()
    assert result["documents_deleted"] >= 1 and not path.exists()
    assert raw_db.one("SELECT status FROM ap.documents WHERE id = %s", (doc,)) == "deleted"
    assert raw_db.one("SELECT status FROM ap.orders WHERE id = %s", (flow.order_id,)) == "expired"
    assert flow.view().json()["status"] == "expired"


def test_expired_order_cannot_be_extended_or_submitted(flow, raw_db):
    flow.create_order()
    doc = flow.upload(pdfs.blank(1)); flow.finalize(doc)
    q = flow.quote([{"document_id": doc, "options": {}}]).json()
    raw_db.run("UPDATE ap.orders SET expires_at = now() - interval '1 second' WHERE id = %s", (flow.order_id,))
    r = flow.submit(q["quote_id"])
    assert r.status_code == 410 and err(r) == "order_expired"


# ------------------------------------------------------------------ failure handling and logging
def test_unexpected_failure_is_a_generic_500_without_detail(client, shop, monkeypatch):
    from app import db as dbmod

    def boom(self, *a, **k):
        raise RuntimeError("password=hunter2 host=internal-db")
    monkeypatch.setattr(dbmod.Database, "one", boom)
    from fastapi.testclient import TestClient
    r = TestClient(client.app, raise_server_exceptions=False).get(f"/v1/shops/{shop.code}")
    assert r.status_code == 500 and err(r) == "internal_error"
    assert "hunter2" not in r.text and "internal-db" not in r.text


def test_logs_never_contain_secrets_signed_urls_or_file_names(flow, caplog):
    caplog.set_level(logging.DEBUG, logger="autoprint")          # the API's own loggers only
    flow.create_order()
    reg = flow.register(len(pdfs.blank(1)), name="my-passport-scan.pdf").json()
    flow.c.put(reg["upload_url"], content=pdfs.blank(1), headers=reg["upload_headers"])
    flow.finalize(reg["document_id"])
    text = "\n".join(r.getMessage() for r in caplog.records)
    sig = re.search(r"sig=([0-9a-f]+)", reg["upload_url"]).group(1)
    for forbidden in (flow.secret, sig, "my-passport-scan", reg["upload_url"]):
        assert forbidden not in text, f"log leaked {forbidden[:12]}..."
    assert "POST /v1/orders/{order_id}/documents" in text          # the route template is logged, not the URL



# ------------------------------------------------------------------ scheduled maintenance for serverless hosts
def test_maintenance_endpoint_needs_the_token(api_db_url, tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.settings import Settings
    s = Settings(database_url=api_db_url, local_storage_dir=str(tmp_path / "f"), public_base_url="http://testserver",
                 signing_key="k" * 40, maintenance_token="t" * 40, background_maintenance=False).validate()
    with TestClient(create_app(s)) as c:
        assert c.post("/v1/internal/maintenance").status_code == 401
        assert c.post("/v1/internal/maintenance", headers={"X-Maintenance-Token": "wrong"}).status_code == 401
        ok = c.post("/v1/internal/maintenance", headers={"X-Maintenance-Token": "t" * 40})
        assert ok.status_code == 200 and "stale_attempts" in ok.json() and "documents_deleted" in ok.json()
    unset = replace(s, maintenance_token="")
    with TestClient(create_app(unset)) as c:
        assert c.post("/v1/internal/maintenance", headers={"X-Maintenance-Token": ""}).status_code == 401   # disabled when no token is set
