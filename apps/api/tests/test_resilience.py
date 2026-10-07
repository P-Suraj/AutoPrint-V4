"""What the API answers when something it depends on fails, through the real application and a real database:
database, file store and pool errors (503 try_again), a claim whose download link cannot be made, a file that
cannot be deleted, a damaged PDF, NUL characters in input, and the cache headers."""
import dataclasses
import logging
import threading
import time
import uuid

import httpx
import psycopg2
import psycopg2.errors
import pytest
from fastapi.testclient import TestClient

import pdfs
from app import main
from app.db import Database
from app.main import create_app
from app.settings import Settings
from app.storage import LocalStorage
from conftest import Flow
from test_agent_api import Agent

TOKEN = {"X-Maintenance-Token": "m" * 40}


def err(r):
    return r.json()["error"]["code"]


class FlakyStorage(LocalStorage):
    """The real local file store, with switches that make chosen calls fail the way an unreachable store does."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fail_uploads = False
        self.fail_download_links = 0          # how many of the next calls fail
        self.undeletable: set[str] = set()    # object keys
        self.nothing_deletable = False
        self.download_links_asked = 0

    @staticmethod
    def _down():
        raise httpx.ConnectError("could not reach files.internal.example")

    def create_upload(self, key, max_bytes):
        if self.fail_uploads:
            self._down()
        return super().create_upload(key, max_bytes)

    def create_download_url(self, key):
        self.download_links_asked += 1
        if self.fail_download_links > 0:
            self.fail_download_links -= 1
            self._down()
        return super().create_download_url(key)

    def delete(self, key):
        if self.nothing_deletable or key in self.undeletable:
            self._down()
        super().delete(key)


@pytest.fixture
def rig(settings, monkeypatch):
    """The application with a file store and a pool the test can reach. Returns (client, storage, database)."""
    made = {}

    def storage_for(s):
        made["storage"] = FlakyStorage(s.local_storage_dir, s.public_base_url, s.signing_key, s.upload_url_ttl_seconds, s.download_url_ttl_seconds)
        return made["storage"]

    class Pool(Database):
        def __init__(self, url):
            super().__init__(url, **made.get("pool_options", {}))
            made["db"] = self

    monkeypatch.setattr(main, "make_storage", storage_for)
    monkeypatch.setattr(main, "Database", Pool)

    def build(**pool_options):
        made["pool_options"] = pool_options
        # its own signing key: these tests must not use up the per-address limits the other test files share
        client = TestClient(create_app(dataclasses.replace(settings, signing_key="r" * 40, maintenance_token="m" * 40)),
                            raise_server_exceptions=False)
        client.__enter__()
        made.setdefault("clients", []).append(client)
        return client, made["storage"], made["db"]

    yield build
    for c in made.get("clients", []):
        c.__exit__(None, None, None)


def approved(client, shop, raw_db, pages=2):
    agent = Agent(client, shop, raw_db)
    flow = Flow(client, shop)
    flow.full(pdfs.blank(pages))
    job = flow.view().json()["jobs"][0]["job_id"]
    assert agent.post(f"/jobs/{job}/approve").status_code == 200
    return agent, flow, job


# ------------------------------------------------------------------ 503 try_again
def test_database_that_cannot_be_reached_answers_503_try_again_and_health_stays_up(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="autoprint")
    s = Settings(database_url="postgresql://postgres@127.0.0.1:1/nothing", local_storage_dir=str(tmp_path / "f"),
                 signing_key="k" * 40, background_maintenance=False).validate()
    with TestClient(create_app(s), raise_server_exceptions=False) as c:
        assert c.get("/health").status_code == 200                                # the process is alive without a database
        r = c.get("/v1/shops/ABC123")
        assert r.status_code == 503 and err(r) == "try_again" and r.headers["retry-after"] == "2"
        assert r.headers["cache-control"] == "no-store" and "X-AutoPrint-Contract-Version" in r.headers
        ready = c.get("/health/ready")
        assert ready.status_code == 503 and ready.json()["database"] == "failed"
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "dependency failure OperationalError" in text and "/v1/shops/{shop_code}" in text
    assert "127.0.0.1" not in text and "nothing" not in text                      # the error text (host, database) is never logged


def test_file_store_that_cannot_be_reached_answers_503_and_names_nothing(rig, shop, caplog):
    caplog.set_level(logging.DEBUG, logger="autoprint")
    client, storage, _ = rig()
    flow = Flow(client, shop)
    flow.create_order()
    storage.fail_uploads = True
    r = flow.register(1000)
    assert r.status_code == 503 and err(r) == "try_again" and r.headers["retry-after"] == "2"
    assert "files.internal.example" not in r.text
    assert "files.internal.example" not in "\n".join(rec.getMessage() for rec in caplog.records)
    storage.fail_uploads = False
    assert flow.register(1000).status_code == 201                                 # trying again works


def test_every_connection_in_use_answers_503_not_500(rig, shop):
    client, _, db = rig(max_conn=1, acquire_timeout=0.3)
    holder = threading.Thread(target=lambda: db.one("SELECT pg_sleep(1.5)"))
    holder.start()
    time.sleep(0.3)
    r = client.get(f"/v1/shops/{shop.code}")
    assert r.status_code == 503 and err(r) == "try_again"
    holder.join(10)
    assert client.get(f"/v1/shops/{shop.code}").status_code == 200


def test_a_stuck_statement_is_cut_off_answers_503_and_does_not_keep_the_connection(rig, shop, api_db_url):
    client, _, db = rig(statement_timeout_ms=400, max_conn=1, acquire_timeout=5)
    flow = Flow(client, shop)
    flow.create_order()
    blocker = psycopg2.connect(api_db_url)                                        # someone holds the order row and never lets go
    try:
        blocker.cursor().execute("SELECT 1 FROM ap.orders WHERE id = %s FOR UPDATE", (flow.order_id,))
        started = time.time()
        r = flow.cancel()
        assert r.status_code == 503 and err(r) == "try_again" and time.time() - started < 3
        assert client.get(f"/v1/shops/{shop.code}").status_code == 200            # the only connection is free again
    finally:
        blocker.rollback()
        blocker.close()
    assert flow.cancel().status_code == 200                                       # and trying again works


def test_a_deadlock_reported_by_the_database_answers_503(rig, shop, monkeypatch):
    client, _, _ = rig()
    flow = Flow(client, shop)
    flow.create_order()
    real = Database.call

    def call(self, fn, *args):
        if fn == "cancel_order":
            raise psycopg2.errors.DeadlockDetected("deadlock detected: process 1 waits for secret-table")
        return real(self, fn, *args)
    monkeypatch.setattr(Database, "call", call)
    r = flow.cancel()
    assert r.status_code == 503 and err(r) == "try_again" and "secret-table" not in r.text


# ------------------------------------------------------------------ the claim when the download link cannot be made
def test_claim_closes_the_attempt_as_failed_when_no_download_link_can_be_made_and_never_retries_by_itself(rig, shop, raw_db):
    client, storage, _ = rig()
    agent, flow, job = approved(client, shop, raw_db)
    storage.fail_download_links = 2                                               # both tries of this one claim
    r = agent.post("/claim")
    assert r.status_code == 503 and err(r) == "try_again"
    assert storage.download_links_asked == 2
    assert raw_db.rows("SELECT status::text, attempt_count FROM ap.jobs WHERE id = %s", (job,)) == [("failed", 1)]
    assert raw_db.rows("SELECT status::text, evidence, finished_at IS NOT NULL FROM ap.print_attempts WHERE job_id = %s", (job,)) \
        == [("failed", {"reason": "download_link_unavailable", "printed": False}, True)]

    # the file store is fine again, but nothing prints until a person says so
    for _ in range(3):
        assert agent.post("/claim").json() == dict.fromkeys(
            ["job_id", "attempt_id", "attempt_token", "spooler_job_name", "lease_expires_at", "document", "options"], None) | {"status": "no_job"}
    assert raw_db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id = %s", (job,)) == 1
    assert agent.poll().json()["jobs"][0]["status"] == "failed"                   # the shopkeeper sees it at once, not after the lease
    assert flow.view().json()["jobs"][0]["status"] == "failed"

    assert agent.post(f"/jobs/{job}/resolve", json={"resolution": "retry"}).status_code == 200      # "Print again"
    c = agent.post("/claim").json()
    assert c["status"] == "claimed" and c["job_id"] == job and c["document"]["download_url"].startswith("http")
    assert raw_db.one("SELECT attempt_count FROM ap.jobs WHERE id = %s", (job,)) == 2
    assert raw_db.one("SELECT count(*) FROM ap.events WHERE job_id = %s AND type = 'job.resolved'", (job,)) == 1


def test_claim_survives_one_failed_try_for_the_download_link(rig, shop, raw_db):
    client, storage, _ = rig()
    agent, _, job = approved(client, shop, raw_db)
    storage.fail_download_links = 1
    c = agent.post("/claim")
    assert c.status_code == 200 and c.json()["status"] == "claimed" and storage.download_links_asked == 2
    assert raw_db.rows("SELECT status::text, attempt_count FROM ap.jobs WHERE id = %s", (job,)) == [("printing", 1)]
    assert raw_db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id = %s", (job,)) == 1


# ------------------------------------------------------------------ a file that cannot be deleted
def due_documents(client, shop, raw_db, n):
    """n uploaded files whose retention deadline has passed, oldest deadline first. Returns [(document id, key)]."""
    out = []
    for i in range(n):
        flow = Flow(client, shop)
        flow.create_order()
        doc = flow.upload(pdfs.blank(1))
        raw_db.run("UPDATE ap.documents SET delete_after = now() - make_interval(hours => %s) WHERE id = %s", (10 * (n - i), doc))
        out.append((doc, raw_db.one("SELECT object_key FROM ap.documents WHERE id = %s", (doc,))))
    return out


def test_one_file_that_cannot_be_deleted_does_not_block_the_files_behind_it(rig, shop, raw_db, caplog):
    caplog.set_level(logging.DEBUG, logger="autoprint")
    client, storage, _ = rig()
    docs = due_documents(client, shop, raw_db, 3)
    stuck_doc, stuck_key = docs[0]                                                # the oldest: first in every cleanup run
    storage.undeletable.add(stuck_key)

    r = client.post("/v1/internal/maintenance", headers=TOKEN)
    assert r.status_code == 200 and r.json()["documents_failed"] == 1 and r.json()["documents_deleted"] >= 2
    assert storage.exists(stuck_key)
    assert raw_db.rows("SELECT status::text, deleted_at FROM ap.documents WHERE id = %s", (stuck_doc,)) == [("pending_upload", None)]
    for doc, key in docs[1:]:
        assert not storage.exists(key)
        assert raw_db.one("SELECT status FROM ap.documents WHERE id = %s", (doc,)) == "deleted"
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert f"could not delete document {stuck_doc}: ConnectError" in text and stuck_key not in text and "files.internal" not in text

    again = client.post("/v1/internal/maintenance", headers=TOKEN).json()         # still stuck: counted again, nothing else harmed
    assert again["documents_failed"] == 1 and again["documents_deleted"] == 0
    storage.undeletable.clear()
    healed = client.post("/v1/internal/maintenance", headers=TOKEN).json()        # the next run after the store recovers
    assert healed["documents_failed"] == 0 and healed["documents_deleted"] == 1 and not storage.exists(stuck_key)


def test_the_shop_poll_still_delivers_the_queue_when_cleanup_cannot_delete_anything(rig, shop, raw_db):
    client, storage, _ = rig()
    agent, _, job = approved(client, shop, raw_db)
    docs = due_documents(client, shop, raw_db, 2)
    storage.nothing_deletable = True
    raw_db.run("UPDATE ap.system_state SET last_sweep_at = '-infinity'")           # this poll is the one that cleans up
    r = agent.poll()
    assert r.status_code == 200 and [j["job_id"] for j in r.json()["jobs"]] == [job]
    assert raw_db.one("SELECT last_sweep_at > now() - interval '1 minute' FROM ap.system_state") is True
    assert all(storage.exists(key) for _, key in docs)                            # nothing deleted, nothing marked
    assert raw_db.one("SELECT count(*) FROM ap.documents WHERE id = ANY(%s::uuid[]) AND deleted_at IS NULL", ([d for d, _ in docs],)) == 2
    storage.nothing_deletable = False
    assert client.post("/v1/internal/maintenance", headers=TOKEN).json()["documents_failed"] == 0
    assert not any(storage.exists(key) for _, key in docs)


# ------------------------------------------------------------------ damaged PDFs
def self_pointing_pdf() -> bytes:
    """A PDF whose page tree object is nothing but a pointer to itself. The reader does not answer with its own
    'cannot read' error for this one; it trips over it with a different error type."""
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"2 0 R"]
    buf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(buf)
    buf += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(buf)


def assert_refused_cleanly(flow, raw_db, storage, doc):
    r = flow.finalize(doc)
    assert r.status_code == 422 and err(r) == "pdf_unreadable", r.text
    assert raw_db.rows("SELECT status::text, reject_reason FROM ap.documents WHERE id = %s", (doc,)) == [("rejected", "pdf_unreadable")]
    assert not storage.exists(raw_db.one("SELECT object_key FROM ap.documents WHERE id = %s", (doc,)))    # not left in the store
    again = flow.finalize(doc)
    assert again.status_code == 409 and err(again) == "document_not_pending"       # settled: not stuck in "pending"
    good = flow.upload(pdfs.blank(1))
    assert flow.finalize(good).status_code == 200                                  # the customer can go on with another file


def test_a_damaged_pdf_that_makes_the_reader_give_up_is_refused_cleanly(rig, shop, raw_db, monkeypatch):
    """pypdf's LimitReachedError is not one of its PdfReadError types; it used to surface as HTTP 500 with the document
    left in 'pending' for good. The reader is made to raise exactly that error here (no small file that triggers it
    was found), through the whole real route."""
    from pypdf.errors import LimitReachedError, PdfReadError
    from app import pdf_validation
    assert not issubclass(LimitReachedError, PdfReadError)

    class GivesUp:
        def __init__(self, *a, **k):
            raise LimitReachedError("Detected cycle in /Pages hierarchy when retrieving page.")
    client, storage, _ = rig()
    flow = Flow(client, shop)
    flow.create_order()
    doc = flow.upload(pdfs.blank(2))
    monkeypatch.setattr(pdf_validation, "PdfReader", GivesUp)
    r = flow.finalize(doc)
    assert r.status_code == 422 and err(r) == "pdf_unreadable", r.text
    monkeypatch.undo()
    assert raw_db.rows("SELECT status::text, reject_reason FROM ap.documents WHERE id = %s", (doc,)) == [("rejected", "pdf_unreadable")]
    assert not storage.exists(raw_db.one("SELECT object_key FROM ap.documents WHERE id = %s", (doc,)))


def test_a_real_damaged_file_that_trips_the_reader_with_an_unexpected_error_is_refused_cleanly(rig, shop, raw_db):
    import io
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    data = self_pointing_pdf()
    with pytest.raises(Exception) as raw:                                          # what the reader itself does with this file
        len(PdfReader(io.BytesIO(data), strict=False).pages)
    assert not isinstance(raw.value, PdfReadError)                                 # not its normal "cannot read" error
    client, storage, _ = rig()
    flow = Flow(client, shop)
    flow.create_order()
    assert_refused_cleanly(flow, raw_db, storage, flow.upload(data))


# ------------------------------------------------------------------ cache headers
def test_answers_are_never_stored_except_the_price_list_for_one_minute(rig, shop, raw_db):
    client, _, _ = rig()
    agent, flow, job = approved(client, shop, raw_db)
    no_store = [client.get(f"/v1/shops/{shop.code}"), flow.view(), agent.poll(),
                client.get(f"/v1/agent/jobs/{job}/document", headers=agent.h),      # carries a signed link
                client.post(f"/v1/shops/{shop.code}/orders"),                        # carries an order secret
                client.get("/v1/shops/NOP000"),                                      # errors too: 404,
                client.get("/v1/agent/jobs"),                                        # 422,
                client.get(f"/v1/orders/{uuid.uuid4()}", headers={"X-Order-Secret": "x"}),
                client.get("/v1/shop/me", headers={"X-Shop-Key": "nope"}),           # 401,
                client.get(f"/v1/shops/{shop.code}", headers={"X-AutoPrint-Contract-Version": "1"}),
                client.get("/v1/internal/shops", headers=TOKEN)]
    for r in no_store:
        assert r.headers.get("cache-control") == "no-store", (r.request.method, r.request.url.path, r.status_code)
    assert {r.status_code for r in no_store} >= {200, 201, 401, 404, 422}

    rates = client.get(f"/v1/shops/{shop.code}/rates")
    assert rates.status_code == 200 and rates.headers["cache-control"] == "private, max-age=60"
    assert client.get("/v1/shops/NOP000/rates").headers["cache-control"] in ("no-store", "private, max-age=60")
    assert "cache-control" not in client.get("/health").headers                    # nothing private there


# ------------------------------------------------------------------ NUL characters and broken text
def test_nul_characters_in_paths_and_text_get_a_clean_refusal_never_a_500(rig, shop, raw_db):
    client, _, _ = rig()
    agent, flow, job = approved(client, shop, raw_db)
    c = agent.post("/claim").json()
    key = client.post("/v1/internal/shop-login", headers=TOKEN, json={"shop_code": shop.code}).json()["key"]
    draft = Flow(client, shop)
    draft.create_order()
    nul = "a\x00b"
    calls = [
        ("GET", "/v1/shops/ABC%00123", {}),
        ("GET", "/v1/shops/AB%00/rates", {}),
        ("POST", "/v1/shops/AB%00/orders", {}),
        ("POST", f"/v1/orders/{draft.order_id}/documents", {"headers": draft.h, "json": {"file_name": f"scan{nul}.pdf", "byte_size": 100, "content_type": "application/pdf"}}),
        ("POST", "/v1/agent/enroll", {"json": {"enrollment_code": "ABCDEFGH1234", "display_name": nul}}),
        ("POST", "/v1/agent/pair/start", {"json": {"display_name": nul, "poll_token": "a" * 64, "device_secret": "b" * 64}}),
        ("POST", f"/v1/agent/jobs/{job}/reject", {"headers": agent.h, "json": {"reason": nul}}),
        ("POST", f"/v1/agent/jobs/{job}/resolve", {"headers": agent.h, "json": {"resolution": "failed", "note": nul}}),
        ("POST", f"/v1/agent/attempts/{c['attempt_id']}/outcome",
         {"headers": agent.h, "json": {"attempt_token": c["attempt_token"], "outcome": "failed", "evidence": {"driver": nul}}}),
        ("POST", f"/v1/agent/attempts/{c['attempt_id']}/outcome",
         {"headers": agent.h, "json": {"attempt_token": c["attempt_token"], "outcome": "failed", "evidence": {nul: [1, {"x": nul}]}}}),
        ("POST", f"/v1/agent/attempts/{c['attempt_id']}/sent", {"headers": agent.h, "json": {"attempt_token": "\x00" * 64}}),
        ("GET", "/v1/shop/pair/ABCD%00EFG", {"headers": {"X-Shop-Key": key}}),
        ("POST", "/v1/shop/pair/approve", {"headers": {"X-Shop-Key": key}, "json": {"pair_code": "ABCD\x00EFG"}}),
        ("POST", "/v1/internal/shop", {"headers": TOKEN, "json": {"code": "NUL001", "name": nul}}),
        ("POST", "/v1/internal/shop-update", {"headers": TOKEN, "json": {"code": shop.code, "name": nul}}),
        ("POST", "/v1/internal/shop-login", {"headers": TOKEN, "json": {"shop_code": shop.code, "label": nul}}),
        ("POST", "/v1/internal/shop-login", {"headers": TOKEN, "json": {"shop_code": shop.code, "revoke_label": nul}}),
        ("POST", "/v1/internal/shop-email", {"headers": TOKEN, "json": {"shop_code": shop.code, "email": "a@b.co", "label": nul}}),
        ("POST", "/v1/internal/purge", {"headers": TOKEN, "json": {"shop_code": shop.code, "order": "A\x00BC"}}),
        ("GET", "/v1/internal/report/AB%00", {"headers": TOKEN}),
        ("GET", "/v1/internal/shop/AB%00/rates", {"headers": TOKEN}),
    ]
    for method, path, kw in calls:
        r = client.request(method, path, **kw)
        assert 400 <= r.status_code < 500, (method, path, r.status_code, r.text)
        assert r.status_code != 409 or "attempts" in path, (path, r.text)
        assert "error" in r.json(), (path, r.text)
    # nothing above changed anything: the job is still printing and its attempt is still open
    assert raw_db.one("SELECT status FROM ap.jobs WHERE id = %s", (job,)) == "printing"
    assert raw_db.one("SELECT count(*) FROM ap.shops WHERE code = 'NUL001'") == 0
    # and ordinary text in other scripts is still accepted
    ok = draft.register(100, name="పరీక్ష notes – final.pdf")
    assert ok.status_code == 201, ok.text
