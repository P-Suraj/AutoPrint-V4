"""The connection pool, the statement time limit and the text check in app/db.py, against a real PostgreSQL.

A "database restart" is played by terminating the pool's server processes (pg_terminate_backend): to a client that is
exactly what a restart or a pooler dropping an idle connection looks like (a goodbye message, then a closed socket).
The test server itself is shared with other test runs and is never restarted here.
"""
import re
import threading
import time
import uuid
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest

from app import db as dbmod
from app.db import Database, InvalidText, PoolBusy

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def pool(api_db_url):
    made = []

    def make(**kw):
        d = Database(api_db_url, **kw)
        made.append(d)
        return d

    yield make
    for d in made:
        d.close()


def pid(db):
    return db.one("SELECT pg_backend_pid()")[0]


def in_threads(n, fn):
    """Run fn(i) in n threads at once; returns results (or the exception) in order."""
    out = [None] * n
    gate = threading.Barrier(n)

    def run(i):
        gate.wait()
        try:
            out[i] = fn(i)
        except Exception as exc:
            out[i] = exc

    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    return out


def kill(raw_db, *pids):
    for p in pids:
        raw_db.run("SELECT pg_terminate_backend(%s)", (p,))
    end = time.time() + 5
    while time.time() < end and raw_db.one("SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(%s)", (list(pids),)):
        time.sleep(0.02)
    time.sleep(0.1)                                   # let the goodbye reach the client's socket


# ------------------------------------------------------------------ reuse
def test_nothing_connects_until_the_first_statement_and_then_one_connection_is_reused(pool):
    db = pool()
    assert db.connections_opened == 0
    pids = {pid(db) for _ in range(25)}
    assert db.call_scalar("sha256_hex", "x") and db.rows("SELECT 1") == [(1,)]
    assert len(pids) == 1 and db.connections_opened == 1


def test_statements_at_the_same_time_get_a_connection_each_and_those_are_reused_afterwards(pool):
    db = pool()
    first = in_threads(4, lambda i: db.one("SELECT pg_backend_pid(), pg_sleep(0.3)")[0])
    assert len(set(first)) == 4 and db.connections_opened == 4
    again = in_threads(4, lambda i: db.one("SELECT pg_backend_pid(), pg_sleep(0.3)")[0])
    assert set(again) == set(first) and db.connections_opened == 4


# ------------------------------------------------------------------ idle connections older than 30 seconds
def test_a_connection_idle_for_more_than_30_seconds_is_thrown_away_not_trusted(pool, raw_db, monkeypatch):
    db = pool()                                       # the default limit, as in production
    first = pid(db)
    real = time.time
    monkeypatch.setattr(dbmod.time, "time", lambda: real() + 29)
    assert pid(db) == first and db.connections_opened == 1            # 29 s: still trusted
    monkeypatch.setattr(dbmod.time, "time", lambda: real() + 29 + 31)  # handed back at +29, now 31 s later
    second = pid(db)
    assert second != first and db.connections_opened == 2
    monkeypatch.undo()
    end = real() + 5
    while real() < end and raw_db.one("SELECT count(*) FROM pg_stat_activity WHERE pid = %s", (first,)):
        time.sleep(0.02)
    assert raw_db.one("SELECT count(*) FROM pg_stat_activity WHERE pid = %s", (first,)) == 0   # really closed, not leaked


# ------------------------------------------------------------------ a connection the server closed
def test_a_connection_the_server_closed_while_idle_is_replaced_without_a_failed_statement(pool, raw_db):
    db = pool()
    first = pid(db)
    kill(raw_db, first)
    second = pid(db)                                  # no exception: the dead connection was noticed before use
    assert second != first and db.connections_opened == 2
    assert pid(db) == second and db.connections_opened == 2


def test_after_a_database_restart_every_request_works_again_without_one_failure(pool, raw_db):
    db = pool()
    before = in_threads(5, lambda i: db.one("SELECT pg_backend_pid(), pg_sleep(0.2)")[0])
    assert len(set(before)) == 5
    kill(raw_db, *before)                             # every pooled connection is gone at once
    after = in_threads(5, lambda i: [db.one("SELECT pg_backend_pid()")[0] for _ in range(4)])
    assert not [r for r in after if isinstance(r, Exception)], after
    assert not {p for r in after for p in r} & set(before)
    assert db.connections_opened <= 10


def test_a_statement_whose_connection_dies_under_it_is_reported_and_never_run_again(pool, raw_db):
    """The statement had started. Nobody can know whether it took effect, so the pool must not send it a second
    time. A sequence shows how often it ran: sequences do not roll back."""
    seq = "pool_seq_" + uuid.uuid4().hex[:10]
    raw_db.run(f"CREATE SEQUENCE public.{seq}")
    db = pool()
    try:
        box = {}

        def victim():
            try:
                box["r"] = db.one(f"SELECT nextval('public.{seq}'), pg_sleep(20)")
            except Exception as exc:
                box["r"] = exc

        t = threading.Thread(target=victim)
        t.start()
        end = time.time() + 10
        target = None
        while time.time() < end and target is None:
            target = raw_db.one("SELECT pid FROM pg_stat_activity WHERE query LIKE %s AND state = 'active' AND pid <> pg_backend_pid()",
                                (f"%nextval('public.{seq}')%",))
            time.sleep(0.02)
        assert target is not None
        time.sleep(0.2)                               # the statement is inside pg_sleep now
        kill(raw_db, target)
        t.join(15)
        assert isinstance(box["r"], (psycopg2.OperationalError, psycopg2.InterfaceError)), box["r"]
        assert raw_db.one(f"SELECT last_value FROM public.{seq}") == 1          # ran once; was not sent again
        assert db.connections_opened == 1                                         # and no second connection was tried for it
        assert db.one("SELECT 1") == (1,) and db.connections_opened == 2          # the next statement gets a new one
    finally:
        raw_db.run(f"DROP SEQUENCE public.{seq}")


def test_database_that_cannot_be_reached_fails_each_call_and_never_uses_up_the_pool():
    db = Database("postgresql://postgres@127.0.0.1:1/nothing", max_conn=2, acquire_timeout=0.2)
    try:
        for _ in range(3):                            # more calls than connections: a failed connect must free its place
            with pytest.raises(psycopg2.OperationalError):
                db.one("SELECT 1")
        assert db.ping() is False
    finally:
        db.close()


# ------------------------------------------------------------------ all connections in use
def test_pool_busy_when_every_connection_is_in_use_and_fine_again_afterwards(pool):
    db = pool(max_conn=2, acquire_timeout=0.3)
    holders = [threading.Thread(target=lambda: db.one("SELECT pg_sleep(1.5)")) for _ in range(2)]
    [t.start() for t in holders]
    time.sleep(0.4)
    started = time.time()
    with pytest.raises(PoolBusy):
        db.one("SELECT 1")
    assert 0.2 < time.time() - started < 1.2           # waited for its turn, then gave up; did not hang
    [t.join(10) for t in holders]
    assert db.one("SELECT 1") == (1,) and db.connections_opened == 2


# ------------------------------------------------------------------ transactions
def test_transaction_commits_as_one_and_rolls_back_as_one_and_the_connection_is_reused(pool, raw_db):
    table = "pool_t_" + uuid.uuid4().hex[:10]
    raw_db.run(f"CREATE TABLE public.{table} (n int)")
    db = pool()
    try:
        def both(cur):
            cur.execute(f"INSERT INTO public.{table} VALUES (1)")
            cur.execute(f"INSERT INTO public.{table} VALUES (2)")
            return "done"

        def half(cur):
            cur.execute(f"INSERT INTO public.{table} VALUES (3)")
            raise RuntimeError("stop")

        assert db.transaction(both) == "done"
        with pytest.raises(RuntimeError):
            db.transaction(half)
        assert raw_db.rows(f"SELECT n FROM public.{table} ORDER BY n") == [(1,), (2,)]
        assert db.one("SELECT 1") == (1,) and db.connections_opened == 1
    finally:
        raw_db.run(f"DROP TABLE public.{table}")


# ------------------------------------------------------------------ statement time limit
def test_a_statement_over_its_time_limit_is_cancelled_and_the_pool_keeps_working(pool):
    db = pool(statement_timeout_ms=300)
    started = time.time()
    with pytest.raises(psycopg2.errors.QueryCanceled) as e:
        db.one("SELECT pg_sleep(5)")
    assert time.time() - started < 2 and isinstance(e.value, psycopg2.OperationalError)     # the API answers 503 for this
    assert db.one("SELECT 1") == (1,)
    with pytest.raises(psycopg2.errors.QueryCanceled):
        db.call_scalar("sha256_hex", "x") and db.rows("SELECT pg_sleep(5)")
    with pytest.raises(psycopg2.errors.QueryCanceled):
        db.transaction(lambda cur: cur.execute("SELECT pg_sleep(5)"))
    assert db.one("SELECT 1") == (1,)


def test_the_time_limit_lives_only_inside_its_own_statement_as_transaction_pooling_needs(pool):
    """Supabase's pooler (port 6543) gives the server connection to someone else after every transaction. The limit
    must therefore not be a session setting: it would be lost, or leak to the next client."""
    db = pool()
    assert db.one("SELECT current_setting('statement_timeout')") == ("10s",)       # the default, inside the statement
    conn = db._idle[-1][0]                            # the very server session that statement ran on
    with conn.cursor() as cur:
        cur.execute("SHOW statement_timeout")
        assert cur.fetchone() == ("0",)               # nothing was left behind on the session
    assert conn.notices == []                         # and the server had nothing to warn about
    assert pool(statement_timeout_ms=0)._limit() == ""


def test_a_longer_limit_can_be_given_for_one_block_and_only_for_the_calling_thread(pool):
    db = pool(statement_timeout_ms=300)
    seen = {}
    with db.statement_timeout(4000):
        assert db.one("SELECT current_setting('statement_timeout'), pg_sleep(0.6)")[0] == "4s"
        t = threading.Thread(target=lambda: seen.setdefault("other", db.one("SELECT current_setting('statement_timeout')")[0]))
        t.start(); t.join(10)
        with db.statement_timeout(1000):
            assert db.one("SELECT current_setting('statement_timeout')") == ("1s",)
        assert db.one("SELECT current_setting('statement_timeout')") == ("4s",)
    assert seen["other"] == "300ms"
    assert db.one("SELECT current_setting('statement_timeout')") == ("300ms",)


def test_nothing_in_the_api_or_the_sql_depends_on_session_state():
    """A guard for transaction pooling: none of these may ever appear in the API code or in a migration."""
    forbidden = [r"\bLISTEN\b", r"\bNOTIFY\b", r"\bPREPARE\b", r"\bDEALLOCATE\b", r"pg_advisory_lock\(", r"pg_try_advisory_lock\(",
                 r"\bSET\s+SESSION\b", r"\bSET\s+statement_timeout\b", r"\bSET\s+search_path\b", r"\bTEMP(ORARY)?\s+TABLE\b",
                 r"\bDECLARE\s+\w+\s+CURSOR\b", r"cursor\(\s*name", r"cursor\(\s*['\"]", r"WITH\s+HOLD"]
    files = list((ROOT / "apps" / "api" / "app").glob("*.py")) + list((ROOT / "supabase" / "migrations").glob("*.sql"))
    assert len(files) > 20
    for f in files:
        text = "\n".join(line for line in f.read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith(("--", "#")))
        if f.name == "db.py":
            text = text.split('"""', 2)[2]            # its module text explains these very words
        for pattern in forbidden:
            assert not re.search(pattern, text, re.I), f"{f.name} uses session state: {pattern}"


# ------------------------------------------------------------------ text PostgreSQL cannot store
def test_text_with_a_nul_or_broken_unicode_is_refused_before_anything_is_sent(pool):
    db = pool()
    for bad in ("a\x00b", "half \ud83d pair"):
        with pytest.raises(InvalidText):
            db.one("SELECT %s", (bad,))
        with pytest.raises(InvalidText):
            db.rows("SELECT %(v)s", {"v": bad})
        with pytest.raises(InvalidText):
            db.call("order_view", bad)
        with pytest.raises(InvalidText):
            db.call_scalar("sha256_hex", bad)
        with pytest.raises(InvalidText):
            db.call("report_outcome", uuid.uuid4(), "t", uuid.uuid4(), "failed", {"deep": [{"er": bad}]})
        with pytest.raises(InvalidText):
            db.call("report_outcome", uuid.uuid4(), "t", uuid.uuid4(), "failed", {bad: 1})
    assert db.connections_opened == 0
    assert db.one("SELECT %s", ("plain text, తెలుగు, 100%",)) == ("plain text, తెలుగు, 100%",)
