"""Applies pending migration files from supabase/migrations, each in its own transaction.

Only files shipped in this repository are ever run; no SQL comes from a request. Applied migrations are
recorded in ap.schema_migrations (the id is the file name without .sql), so running it twice is safe.
"""
from __future__ import annotations

from pathlib import Path

import psycopg2

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "supabase" / "migrations"


def apply_pending(database_url: str) -> dict:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError("no migration files found in this deployment")
    conn = psycopg2.connect(database_url, connect_timeout=10)
    conn.autocommit = False
    applied_now: list[str] = []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM ap.schema_migrations")
            done = {r[0] for r in cur.fetchall()}
        conn.rollback()
        for f in files:
            if f.stem in done:
                continue
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(7002)")      # two callers cannot apply the same file
                cur.execute("SELECT 1 FROM ap.schema_migrations WHERE id = %s", (f.stem,))
                if cur.fetchone():
                    conn.rollback()
                    continue
                cur.execute(f.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO ap.schema_migrations (id) VALUES (%s)", (f.stem,))
            conn.commit()
            applied_now.append(f.stem)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM ap.schema_migrations ORDER BY id")
            everything = [r[0] for r in cur.fetchall()]
        conn.rollback()
        return {"applied_now": applied_now, "applied_total": everything}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
