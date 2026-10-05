"""Database tests run against a real PostgreSQL. No mocks.

AP_TEST_PG: connection URL of a server where the test user may create databases.
Default is the throwaway instance described in docs/RUNBOOK.md (port 55432).
Each test session builds a fresh database from supabase/migrations/*.sql, in order.
"""
import hashlib
import os
import random
import string
import threading
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest

psycopg2.extras.register_uuid()

ADMIN_URL = os.environ.get("AP_TEST_PG", "postgresql://postgres@127.0.0.1:55432/postgres")
MIGRATIONS = sorted((Path(__file__).parent.parent / "migrations").glob("*.sql"))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _db_url(name: str) -> str:
    return ADMIN_URL.rsplit("/", 1)[0] + "/" + name


def build_database(name: str) -> str:
    admin = psycopg2.connect(ADMIN_URL)
    admin.autocommit = True
    admin.cursor().execute(f'CREATE DATABASE "{name}"')
    admin.close()
    conn = psycopg2.connect(_db_url(name))
    conn.autocommit = True
    for f in MIGRATIONS:
        conn.cursor().execute(f.read_text(encoding="utf-8"))
    conn.close()
    return _db_url(name)


def drop_database(name: str) -> None:
    admin = psycopg2.connect(ADMIN_URL)
    admin.autocommit = True
    admin.cursor().execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin.close()


class Db:
    """One autocommit connection: every statement is its own transaction, as in production."""

    def __init__(self, url: str):
        self.conn = psycopg2.connect(url)
        self.conn.autocommit = True

    def call(self, fn: str, *args):
        placeholders = ", ".join(["%s"] * len(args))
        cur = self.conn.cursor()
        cur.execute(f"SELECT ap.{fn}({placeholders})", [psycopg2.extras.Json(a) if isinstance(a, (dict, list)) else a for a in args])
        return cur.fetchone()[0]

    def one(self, sql: str, args=()):
        cur = self.conn.cursor()
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row and len(row) == 1 else row

    def rows(self, sql: str, args=()):
        cur = self.conn.cursor()
        cur.execute(sql, args)
        return cur.fetchall()

    def run(self, sql: str, args=()):
        self.conn.cursor().execute(sql, args)

    def close(self):
        self.conn.close()


@pytest.fixture(scope="session")
def db_url():
    name = "v4_test_" + uuid.uuid4().hex[:10]
    url = build_database(name)
    yield url
    drop_database(name)


@pytest.fixture
def db(db_url):
    d = Db(db_url)
    yield d
    d.close()


@pytest.fixture
def new_conn(db_url):
    """Factory for extra connections (concurrency tests)."""
    made = []

    def make():
        d = Db(db_url)
        made.append(d)
        return d

    yield make
    for d in made:
        d.close()


def random_code() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=3)) + "".join(random.choices(string.digits, k=3))


class Shop:
    def __init__(self, db: Db):
        self.db = db
        self.code = random_code()
        self.id = db.one("INSERT INTO ap.shops (code, name) VALUES (%s, %s) RETURNING id", (self.code, "Test Shop"))
        db.run("INSERT INTO ap.rate_cards (shop_id, version, rules) VALUES (%s, 1, '{\"v\":1}')", (self.id,))

    def device(self, name="Counter PC"):
        secret = uuid.uuid4().hex
        code = uuid.uuid4().hex
        assert self.db.call("issue_enrollment_code", self.code, sha(code), 30)["result"] == "ok"
        res = self.db.call("consume_enrollment", sha(code), name, sha(secret))
        assert res["result"] == "ok"
        return res["device_id"]

    def submitted_order(self, pages=(3,), copies=1, color=False, duplex=False, page_range=None):
        """Create, upload, price and submit an order. Returns a dict of ids."""
        secret = uuid.uuid4().hex
        o = self.db.call("create_order", self.code, sha(secret))
        assert o["result"] == "ok", o
        items, doc_ids, total = [], [], 0
        for i, p in enumerate(pages, start=1):
            d = self.db.call("register_document", o["order_id"], f"file{i}.pdf", 1000 * p, f"orders/{o['order_id']}/{uuid.uuid4().hex}.pdf")
            assert d["result"] == "ok", d
            f = self.db.call("finalize_document", d["document_id"], sha(f"doc{uuid.uuid4().hex}"), 1000 * p, p)
            assert f["result"] == "ok", f
            amount = p * copies * 200
            total += amount
            doc_ids.append(d["document_id"])
            items.append({"document_id": str(d["document_id"]), "copies": copies, "color": color, "duplex": duplex,
                          "page_range": page_range, "selected_pages": p, "printed_sides": p * copies, "amount_paise": amount})
        q = self.db.call("create_quote", o["order_id"], items, total)
        assert q["result"] == "ok", q
        s = self.db.call("submit_order", o["order_id"], q["quote_id"])
        assert s["result"] == "ok", s
        return {"order_id": o["order_id"], "secret": secret, "quote_id": q["quote_id"], "job_ids": s["job_ids"],
                "doc_ids": doc_ids, "total": total, "short_code": o["short_code"]}


@pytest.fixture
def shop(db):
    return Shop(db)


@pytest.fixture
def make_shop(db):
    return lambda: Shop(db)


def run_in_threads(funcs):
    """Run callables simultaneously; return their results in order."""
    results = [None] * len(funcs)
    barrier = threading.Barrier(len(funcs))

    def wrap(i, f):
        barrier.wait()
        try:
            results[i] = f()
        except Exception as exc:  # surfaced to the test
            results[i] = exc

    ts = [threading.Thread(target=wrap, args=(i, f)) for i, f in enumerate(funcs)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return results
