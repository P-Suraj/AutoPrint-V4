"""Database round trips on the customer path are pinned here, so they cannot silently grow back.

On the live site every statement travels to a connection pooler in another process, so each one is latency the
customer feels. Counted by wrapping the one place every statement goes through (Database._conn: one connection
taken from the pool per statement). The founder routes that use Database.transaction() are not measured here.

The second half checks that doing several steps in one statement changed nothing a caller can see: the same
refusals in the same order, the same counting by the limiter, and a broken limiter still lets customers through.
"""
from pathlib import Path

import pytest

from app.db import Database
from dbtools import MIGRATIONS
from pdfs import blank as make_pdf

EXPECTED = {"new order": 1, "register document": 1, "quote": 2, "submit": 1}
OPTS = {"copies": 1, "color": False, "duplex": False, "page_range": None}


class Trips:
    def __init__(self):
        self.n = 0

    def during(self, action):
        before = self.n
        result = action()
        return result, self.n - before


@pytest.fixture
def trips(monkeypatch):
    t = Trips()
    original = Database._conn

    def counted(self):
        t.n += 1
        return original(self)

    monkeypatch.setattr(Database, "_conn", counted)
    return t


@pytest.fixture(autouse=True)
def clean_limiter(raw_db):
    """The counters are shared by the whole test session and some tests here fill them on purpose."""
    raw_db.run("DELETE FROM ap.rate_limits")
    yield
    raw_db.run("DELETE FROM ap.rate_limits")


def migration(prefix: str) -> str:
    (path,) = [m for m in MIGRATIONS if m.name.startswith(prefix)]
    return Path(path).read_text(encoding="utf-8")


def hits(raw_db) -> int:
    return raw_db.one("SELECT COALESCE(sum(hits), 0) FROM ap.rate_limits")


# ------------------------------------------------------------------ the numbers

def test_round_trips_on_the_customer_path(flow, trips, raw_db):
    _, n = trips.during(flow.create_order)
    assert n == EXPECTED["new order"]

    data = make_pdf(2)
    reg, n = trips.during(lambda: flow.register(len(data)))
    assert reg.status_code == 201, reg.text
    assert n == EXPECTED["register document"]
    body = reg.json()
    assert flow.c.put(body["upload_url"], content=data, headers=body["upload_headers"]).status_code == 200
    assert flow.finalize(body["document_id"]).status_code == 200

    q, n = trips.during(lambda: flow.quote([{"document_id": body["document_id"], "options": OPTS}]))
    assert q.status_code == 201, q.text
    assert n == EXPECTED["quote"]

    s, n = trips.during(lambda: flow.submit(q.json()["quote_id"]))
    assert s.status_code == 200, s.text
    assert n == EXPECTED["submit"]
    paid = raw_db.rows("SELECT mode::text, status::text, amount_paise FROM ap.payments WHERE order_id = %s", (flow.order_id,))[0]
    assert (s.json()["payment_mode"], s.json()["payment_status"], s.json()["amount_paise"]) == tuple(paid)
    assert s.json()["amount_paise"] == q.json()["total_paise"]

    again, n = trips.during(lambda: flow.submit(q.json()["quote_id"]))            # the same quote sent twice: same answer
    assert again.status_code == 200 and again.json() == s.json()
    assert n == EXPECTED["submit"]


def test_refusals_cost_no_more_than_one_round_trip(flow, trips):
    flow.create_order()
    flow.secret = "0" * 64
    for call in (lambda: flow.register(10),
                 lambda: flow.quote([{"document_id": "00000000-0000-0000-0000-000000000000", "options": OPTS}]),
                 lambda: flow.submit("00000000-0000-0000-0000-000000000000")):
        r, n = trips.during(call)
        assert r.status_code == 404 and r.json()["error"]["code"] == "order_not_found"
        assert n == 1


def test_submit_works_before_migration_0019_with_one_more_round_trip(flow, trips, raw_db):
    """The API is deployed before the migration is applied: against the older ap.submit_order (no payment in its
    answer) the API reads the payment itself, as it always did."""
    raw_db.conn.cursor().execute(migration("0018_"))      # no parameters: the file holds % signs
    try:
        flow.create_order()
        doc = flow.upload(make_pdf(1))
        assert flow.finalize(doc).status_code == 200
        q = flow.quote([{"document_id": doc, "options": OPTS}])
        s, n = trips.during(lambda: flow.submit(q.json()["quote_id"]))
        assert s.status_code == 200, s.text
        assert n == 2
        assert s.json()["payment_mode"] == "pay_at_counter" and s.json()["payment_status"] == "not_required"
        assert s.json()["amount_paise"] == q.json()["total_paise"]
        again, n = trips.during(lambda: flow.submit(q.json()["quote_id"]))
        assert again.json() == s.json() and n == 2
    finally:
        raw_db.conn.cursor().execute(migration("0019_"))


# ------------------------------------------------------------------ nothing a caller can see has changed

def test_a_refused_new_order_counts_the_first_limit_only_and_creates_nothing(client, shop, raw_db):
    raw_db.run("DELETE FROM ap.rate_limits")
    h = {"X-Forwarded-For": "198.51.100.77"}
    for _ in range(60):
        assert client.post(f"/v1/shops/{shop.code}/orders", headers=h).status_code == 201
    assert sorted(r[0] for r in raw_db.rows("SELECT sum(hits) FROM ap.rate_limits GROUP BY bucket")) == [60, 60]
    orders = raw_db.one("SELECT count(*) FROM ap.orders WHERE shop_id = %s", (shop.id,))
    r = client.post(f"/v1/shops/{shop.code}/orders", headers=h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    # the address limit refused it: its counter moved, the shop's counter did not, and no order was made
    assert sorted(r[0] for r in raw_db.rows("SELECT sum(hits) FROM ap.rate_limits GROUP BY bucket")) == [60, 61]
    assert raw_db.one("SELECT count(*) FROM ap.orders WHERE shop_id = %s", (shop.id,)) == orders
    # another address is still served, and is counted against the shop
    assert client.post(f"/v1/shops/{shop.code}/orders", headers={"X-Forwarded-For": "198.51.100.78"}).status_code == 201
    assert sorted(r[0] for r in raw_db.rows("SELECT sum(hits) FROM ap.rate_limits GROUP BY bucket")) == [1, 61, 61]


def test_a_new_order_for_an_unknown_shop_is_still_counted_and_refused(client, raw_db):
    raw_db.run("DELETE FROM ap.rate_limits")
    r = client.post("/v1/shops/ZZZ999/orders")
    assert r.status_code == 404 and r.json()["error"]["code"] == "shop_not_found"
    assert hits(raw_db) == 2


def test_register_checks_the_limit_then_the_secret_then_the_size(flow, raw_db, settings):
    flow.create_order()
    raw_db.run("DELETE FROM ap.rate_limits")
    documents = lambda: raw_db.one("SELECT count(*) FROM ap.documents WHERE order_id = %s", (flow.order_id,))
    too_big = settings.max_upload_bytes + 1

    right = flow.secret
    flow.secret = "f" * 64
    wrong = flow.register(too_big)                       # a wrong secret is never told anything about the file
    assert wrong.status_code == 404 and wrong.json()["error"]["code"] == "order_not_found"
    wrong = flow.register(10, name="a\x00b.pdf")         # nor that the name could not be stored
    assert wrong.status_code == 404 and wrong.json()["error"]["code"] == "order_not_found"
    assert hits(raw_db) == 2 and documents() == 0        # both were counted by the limiter all the same

    flow.secret = right
    big = flow.register(too_big)
    assert big.status_code == 413 and big.json()["error"]["code"] == "file_too_large"
    bad = flow.register(10, name="a\x00b.pdf")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"
    assert hits(raw_db) == 4 and documents() == 0

    ok = flow.register(10)
    assert ok.status_code == 201 and documents() == 1 and hits(raw_db) == 5

    raw_db.run("UPDATE ap.rate_limits SET hits = 120")   # the hour's allowance is used up
    r = flow.register(10)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    flow.secret = "f" * 64
    assert flow.register(10).status_code == 429          # the limit is answered before the secret is looked at
    assert documents() == 1


def test_quote_checks_the_limit_then_the_secret_then_the_price_list(flow, raw_db, shop):
    flow.create_order()
    doc = flow.upload(make_pdf(3))
    assert flow.finalize(doc).status_code == 200
    pending = flow.register(10).json()["document_id"]    # registered, never uploaded: not ready to be priced
    items = [{"document_id": doc, "options": OPTS}]
    raw_db.run("DELETE FROM ap.rate_limits")
    quotes = lambda: raw_db.one("SELECT count(*) FROM ap.quotes WHERE order_id = %s", (flow.order_id,))

    right = flow.secret
    flow.secret = "e" * 64
    r = flow.quote(items)
    assert r.status_code == 404 and r.json()["error"]["code"] == "order_not_found"
    flow.secret = right
    assert hits(raw_db) == 1 and quotes() == 0

    r = flow.quote([{"document_id": pending, "options": OPTS}])
    assert r.status_code == 409 and r.json()["error"]["code"] == "document_not_ready"
    r = flow.quote([{"document_id": doc, "options": {**OPTS, "page_range": "9"}}])
    assert r.status_code == 422 and quotes() == 0        # page 9 of a 3 page file

    good = flow.quote(items)
    assert good.status_code == 201 and good.json()["items"][0]["selected_pages"] == 3 and quotes() == 1

    raw_db.run("UPDATE ap.rate_cards SET retired_at = now() WHERE shop_id = %s", (shop.id,))
    try:
        r = flow.quote(items)
        assert r.status_code == 409 and r.json()["error"]["code"] == "no_rate_card"
        flow.secret = "e" * 64                           # a wrong secret is not told the shop has no price list
        assert flow.quote(items).json()["error"]["code"] == "order_not_found"
        flow.secret = right
    finally:
        raw_db.run("UPDATE ap.rate_cards SET retired_at = NULL WHERE shop_id = %s", (shop.id,))

    raw_db.run("UPDATE ap.rate_limits SET hits = 300")
    r = flow.quote(items)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert quotes() == 1


def test_submit_with_a_wrong_secret_changes_nothing(flow, raw_db):
    flow.create_order()
    doc = flow.upload(make_pdf(1))
    assert flow.finalize(doc).status_code == 200
    quote_id = flow.quote([{"document_id": doc, "options": OPTS}]).json()["quote_id"]
    right = flow.secret

    other = type(flow)(flow.c, flow.shop)                # the secret of a different, real order does not open this one
    other.create_order()
    for secret in ("d" * 64, other.secret):
        flow.secret = secret
        r = flow.submit(quote_id)
        assert r.status_code == 404 and r.json()["error"]["code"] == "order_not_found"
    assert raw_db.one("SELECT status::text FROM ap.orders WHERE id = %s", (flow.order_id,)) == "draft"
    assert raw_db.one("SELECT count(*) FROM ap.jobs WHERE order_id = %s", (flow.order_id,)) == 0

    flow.secret = right
    assert flow.submit(quote_id).status_code == 200
    assert raw_db.one("SELECT count(*) FROM ap.jobs WHERE order_id = %s", (flow.order_id,)) == 1


def test_a_broken_limiter_still_lets_customers_through(flow, trips, raw_db):
    """The counter is only a brake. If it fails (here: its function is gone) the combined statement fails as a whole,
    nothing is committed, and the API does the steps one by one as before, skipping the limiter."""
    raw_db.run("ALTER FUNCTION ap.rate_hit(text, integer, integer) RENAME TO rate_hit_gone")
    try:
        _, n = trips.during(flow.create_order)
        assert n == 4                                    # the failed attempt, two failed limiter calls, the order
        doc = flow.upload(make_pdf(1))
        assert flow.finalize(doc).status_code == 200
        q = flow.quote([{"document_id": doc, "options": OPTS}])
        assert q.status_code == 201, q.text
        assert raw_db.one("SELECT count(*) FROM ap.orders WHERE secret_hash = encode(sha256(%s::bytea), 'hex')",
                          (flow.secret,)) == 1           # the failed attempt left no second order behind
        flow.secret = "c" * 64                           # and the secret is still checked
        assert flow.register(10).status_code == 404
        assert flow.quote([{"document_id": doc, "options": OPTS}]).status_code == 404
    finally:
        raw_db.run("ALTER FUNCTION ap.rate_hit_gone(text, integer, integer) RENAME TO rate_hit")


def test_many_customers_at_once_are_all_answered(client, shop, raw_db):
    """Each combined statement holds the limiter's row until it ends. Requests that share a counter (one address,
    one shop) must queue briefly and all be served: no deadlock, no error, and the counters add up."""
    from concurrent.futures import ThreadPoolExecutor

    def customer(i):
        codes = []
        r = client.post(f"/v1/shops/{shop.code}/orders")
        codes.append(r.status_code)
        h = {"X-Order-Secret": r.json()["order_secret"]}
        for _ in range(3):
            codes.append(client.post(f"/v1/orders/{r.json()['order_id']}/documents", headers=h,
                                     json={"file_name": "a.pdf", "byte_size": 10, "content_type": "application/pdf"}).status_code)
        codes.append(client.post(f"/v1/orders/{r.json()['order_id']}/quote", headers=h,
                                 json={"items": [{"document_id": "00000000-0000-0000-0000-000000000000", "options": OPTS}]}).status_code)
        return codes

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(customer, range(8)))
    assert results == [[201, 201, 201, 201, 409]] * 8
    assert sorted(r[0] for r in raw_db.rows("SELECT sum(hits) FROM ap.rate_limits GROUP BY bucket")) == [8, 8, 8, 24]
