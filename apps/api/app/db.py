"""PostgreSQL access: a small pool and one helper for calling ap.* functions.

Every business rule is a SQL function that runs in one transaction (decision D-7). This module
only moves arguments in and results out; it contains no business logic.
"""
from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extras
import psycopg2.pool

log = logging.getLogger("autoprint.db")
psycopg2.extras.register_uuid()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Database:
    def __init__(self, url: str, min_conn: int = 0, max_conn: int = 10):
        # min_conn=0: connect on first use, so the process starts and /health answers even when the
        # database is unreachable. /health/ready then reports the database honestly instead of the
        # whole function crashing at import.
        self._pool = psycopg2.pool.ThreadedConnectionPool(min_conn, max_conn, url, connect_timeout=10)

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        conn = self._pool.getconn()
        broken = False
        try:
            conn.autocommit = True          # each statement is its own transaction
            yield conn
        except psycopg2.OperationalError:
            broken = True
            raise
        finally:
            self._pool.putconn(conn, close=broken or bool(conn.closed))

    def call(self, fn: str, *args: Any) -> dict:
        """Call ap.<fn>(args) and return its jsonb result as a dict."""
        marks = ", ".join(["%s"] * len(args))
        params = [psycopg2.extras.Json(a) if isinstance(a, (dict, list)) else a for a in args]
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT ap.{fn}({marks})", params)
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
                conn.rollback()
                raise
            finally:
                conn.autocommit = True

    def one(self, sql: str, params: tuple = ()) -> Any:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row

    def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def ping(self) -> bool:
        try:
            return self.one("SELECT 1") == (1,)
        except Exception:
            log.exception("database ping failed")
            return False

    def close(self) -> None:
        self._pool.closeall()
