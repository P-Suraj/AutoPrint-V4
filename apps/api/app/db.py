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
  * a statement is never retried here. If a connection dies under a statement nobody can know whether it
    committed, so the caller gets the error (the API answers 503) and the connection is discarded
  * at most `max_conn` connections; further callers wait up to `acquire_timeout` and then get PoolBusy
"""
from __future__ import annotations

import hashlib
import logging
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


class Database:
    def __init__(self, url: str, max_conn: int = 10, max_idle_seconds: float = 30.0, acquire_timeout: float = 10.0):
        self._url = url
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
                if conn.closed or now - since > self._max_idle:
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

    # -- statements ----------------------------------------------------------
    def call(self, fn: str, *args: Any) -> dict:
        """Call ap.<fn>(args) and return its jsonb result as a dict."""
        marks = ", ".join(["%s"] * len(args))
        params = [psycopg2.extras.Json(a) if isinstance(a, (dict, list)) else a for a in args]
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT ap.{fn}({marks})", params)
            return cur.fetchone()[0]

    def call_scalar(self, fn: str, *args: Any) -> Any:
        """Call ap.<fn>(args) and return its single value as is (boolean, number)."""
        marks = ", ".join(["%s"] * len(args))
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT ap.{fn}({marks})", list(args))
            return cur.fetchone()[0]

    def transaction(self, fn):
        """Run fn(cursor) as one all-or-nothing transaction (the pool is otherwise autocommit)."""
        with self._conn() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
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
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row

    def rows(self, sql: str, params: Any = ()) -> list[tuple]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
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

