"""PostgreSQL access: a small pool and one helper for calling ap.* functions.

Every business rule is a SQL function that runs in one transaction (decision D-7). This module
only moves arguments in and results out; it contains no business logic.

The pool. psycopg2's own pool closes every connection it is handed back when its minimum size is 0, so each
statement paid for a new connection (measured locally: 4 statements, 4 backend processes, about 64 ms each;
more over TLS to a hosted pooler). This one keeps idle connections and hands the most recent one back out:
  * nothing connects until the first statement, so the process starts and /health answers with the database down
  * a connection that sat idle longer than `max_idle_seconds` is thrown away instead of trusted. A serverless
    process is frozen between requests and the far end may have dropped the socket meanwhile; reconnecting is
    cheaper than finding out halfway through a statement
  * a connection the server has closed while it sat idle (database restart, pooler idle limit) is noticed before it
    is used: the server's goodbye makes the socket readable, which is checked without a round trip, and a new
    connection takes its place. Nothing was sent on the dead one, so this cannot run anything twice
  * a statement is never retried here. If a connection dies under a statement nobody can know whether it
    committed, so the caller gets the error (the API answers 503) and the connection is discarded
  * at most `max_conn` connections; further callers wait up to `acquire_timeout` and then get PoolBusy

The statement timeout. One stuck statement (a lock that is never released, a runaway query) must not hold a pooled
connection for good, so every statement sent through this module carries a time limit; past it PostgreSQL cancels
the statement (the API answers 503). The limit is set with set_config(..., is_local => true) in the SAME message as
the statement, so it costs no extra round trip and lives only for that one transaction.

Transaction pooling (Supabase's pooler on port 6543 hands the server connection to someone else after every
transaction). Nothing here may depend on session state, and nothing does:
  * no server-side prepared statements: psycopg2 sends plain text queries with the values already filled in
  * no session-level SET: the time limit is transaction-local (above); a startup option or a plain SET would either
    be refused by the pooler or leak to whoever gets the server connection next
  * no LISTEN, no temporary tables, no session advisory locks: the SQL uses pg_advisory_xact_lock and
    pg_try_advisory_xact_lock only, which end with the transaction
  * each statement is one message and therefore one transaction; `transaction()` uses an explicit BEGIN ... COMMIT
"""
from __future__ import annotations

import hashlib
import logging
import select
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extensions
import psycopg2.extras

log = logging.getLogger("autoprint.db")
psycopg2.extras.register_uuid()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PoolBusy(Exception):
    """Every connection is in use and none came free in time. The API answers 503 (try again)."""


class InvalidText(ValueError):
    """A value from a request cannot be stored as PostgreSQL text: it holds a NUL character or is not valid Unicode.
    The API answers 422 (the request is not valid). Raised before anything is sent to the database."""


def check_text(value: Any) -> None:
    """Raises InvalidText when a string anywhere inside `value` cannot be sent to PostgreSQL."""
    if isinstance(value, str):
        if "\x00" in value:
            raise InvalidText()
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:                     # a lone surrogate (half of a character pair)
            raise InvalidText() from None
    elif isinstance(value, dict):
        for k, v in value.items():
            check_text(k)
            check_text(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            check_text(v)


DEFAULT_STATEMENT_TIMEOUT_MS = 10_000                  # hot paths take milliseconds; the host stops a request at 30 s


class Database:
    def __init__(self, url: str, max_conn: int = 10, max_idle_seconds: float = 30.0, acquire_timeout: float = 10.0,
                 statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS):
        self._url = url
        self._statement_timeout_ms = int(statement_timeout_ms)       # 0 switches the limit off
        self._local = threading.local()                # a per-thread override, see statement_timeout()
        self._max_idle = max_idle_seconds
        self._acquire_timeout = acquire_timeout
        self._slots = threading.BoundedSemaphore(max_conn)
        self._lock = threading.Lock()
        self._idle: list[tuple[Any, float]] = []       # (connection, when it was handed back), newest last
        self._closed = False
        self.connections_opened = 0                    # for tests and diagnostics; never reset

    # -- pool ----------------------------------------------------------------
    def _connect(self) -> Any:
        # keepalives are client-side socket options: they bound how long a statement can hang on a dead socket
        conn = psycopg2.connect(self._url, connect_timeout=10, keepalives=1, keepalives_idle=30,
                                keepalives_interval=10, keepalives_count=3)
        conn.autocommit = True                         # each statement is its own transaction
        with self._lock:
            self.connections_opened += 1
        return conn

    @staticmethod
    def _discard(conn: Any) -> None:
        try:
            conn.close()
        except Exception:                              # closing a dead connection must never raise into a request
            pass

    @staticmethod
    def _server_hung_up(conn: Any) -> bool:
        """True when the server has said or done something on a connection that should be silent: in practice it
        closed it. No round trip: only asks the operating system whether the socket has anything to read."""
        try:
            readable, _, _ = select.select([conn.fileno()], [], [], 0)
        except (OSError, ValueError, psycopg2.Error):
            return True
        return bool(readable)

    def _acquire(self) -> Any:
        if not self._slots.acquire(timeout=self._acquire_timeout):
            raise PoolBusy()
        try:
            now = time.time()                          # wall clock: it keeps moving while a serverless process is frozen
            while True:
                with self._lock:
                    item = self._idle.pop() if self._idle else None
                if item is None:
                    return self._connect()
                conn, since = item
                if conn.closed or now - since > self._max_idle or self._server_hung_up(conn):
                    self._discard(conn)
                    continue
                return conn
        except BaseException:
            self._slots.release()
            raise

    def _release(self, conn: Any, broken: bool) -> None:
        try:
            keep = not broken and not conn.closed and not self._closed
            if keep and conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                keep = False                           # left inside a transaction or an error: do not reuse it
            if keep:
                with self._lock:
                    self._idle.append((conn, time.time()))
            else:
                self._discard(conn)
        except Exception:
            self._discard(conn)
        finally:
            self._slots.release()

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        conn = self._acquire()
        broken = False
        try:
            yield conn
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            broken = True
            raise
        finally:
            self._release(conn, broken)

    # -- statement timeout ---------------------------------------------------
    def _timeout_ms(self) -> int:
        return getattr(self._local, "timeout_ms", self._statement_timeout_ms)

    def _limit(self) -> str:
        """Goes in front of a statement, in the same message: one round trip, one transaction, nothing left behind."""
        ms = self._timeout_ms()
        return f"SELECT set_config('statement_timeout', '{int(ms)}', true); " if ms > 0 else ""

    @contextmanager
    def statement_timeout(self, ms: int) -> Iterator[None]:
        """Statements this thread runs inside the block get this limit instead of the default (the founder report
        reads many rows and may take longer than a customer request is allowed to)."""
        previous = getattr(self._local, "timeout_ms", None)
        self._local.timeout_ms = int(ms)
        try:
            yield
        finally:
            if previous is None:
                del self._local.timeout_ms
            else:
                self._local.timeout_ms = previous

    # -- statements ----------------------------------------------------------
    def call(self, fn: str, *args: Any) -> dict:
        """Call ap.<fn>(args) and return its jsonb result as a dict."""
        check_text(args)
        marks = ", ".join(["%s"] * len(args))
        params = [psycopg2.extras.Json(a) if isinstance(a, (dict, list)) else a for a in args]
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"{self._limit()}SELECT ap.{fn}({marks})", params)
            return cur.fetchone()[0]

    def call_scalar(self, fn: str, *args: Any) -> Any:
        """Call ap.<fn>(args) and return its single value as is (boolean, number)."""
        check_text(args)
        marks = ", ".join(["%s"] * len(args))
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"{self._limit()}SELECT ap.{fn}({marks})", list(args))
            return cur.fetchone()[0]

    def transaction(self, fn):
        """Run fn(cursor) as one all-or-nothing transaction (the pool is otherwise autocommit)."""
        with self._conn() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    ms = self._timeout_ms()
                    if ms > 0:                         # one more round trip; only the founder tools use transaction()
                        cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(ms),))
                    result = fn(cur)
                conn.commit()
                return result
            except BaseException:
                try:
                    conn.rollback()
                except psycopg2.Error:
                    pass                               # the connection is gone; the original error is the one to report
                raise
            finally:
                if not conn.closed:
                    conn.autocommit = True

    def one(self, sql: str, params: Any = ()) -> Any:
        check_text(params)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(self._limit() + sql, params)
            row = cur.fetchone()
            return row

    def rows(self, sql: str, params: Any = ()) -> list[tuple]:
        check_text(params)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(self._limit() + sql, params)
            return cur.fetchall()

    def ping(self) -> bool:
        try:
            return self.one("SELECT 1") == (1,)
        except Exception as exc:
            log.error("database ping failed: %s", type(exc).__name__)      # the type only: the message can name the host
            return False

    def close(self) -> None:
        self._closed = True
        with self._lock:
            idle, self._idle = self._idle, []
        for conn, _ in idle:
            self._discard(conn)

