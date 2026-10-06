"""The migrate endpoint applies only the repo's files, is token-protected, and is safe to repeat."""
import uuid
from dataclasses import replace

import psycopg2
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from dbtools import MIGRATIONS, build_database, drop_database


def test_migrate_applies_pending_files_once_and_is_idempotent(tmp_path):
    # a database that has everything except the newest migration, as the live one did before it was applied.
    # Newest is 0018 (cap on waiting jobs): drop the function it replaces so the migration has something to create.
    newest = MIGRATIONS[-1].stem
    assert newest == "0018_waiting_jobs_cap", "update this test when a newer migration is added"
    name = "v4_mig_" + uuid.uuid4().hex[:8]
    url = build_database(name)
    c = psycopg2.connect(url); c.autocommit = True
    cur = c.cursor()
    cur.execute("DROP FUNCTION ap.submit_order(uuid, uuid)")
    cur.execute("CREATE TABLE ap.schema_migrations (id text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    for f in MIGRATIONS[:-1]:
        cur.execute("INSERT INTO ap.schema_migrations (id) VALUES (%s)", (f.stem,))
    s = Settings(database_url=url, local_storage_dir=str(tmp_path / "f"), signing_key="k" * 40, maintenance_token="m" * 40,
                 background_maintenance=False).validate()
    try:
        with TestClient(create_app(s)) as client:
            assert client.post("/v1/internal/migrate").status_code == 401
            assert client.post("/v1/internal/migrate", headers={"X-Maintenance-Token": "nope"}).status_code == 401
            ok = client.post("/v1/internal/migrate", headers={"X-Maintenance-Token": "m" * 40})
            assert ok.status_code == 200, ok.text
            assert ok.json()["applied_now"] == [newest]
            again = client.post("/v1/internal/migrate", headers={"X-Maintenance-Token": "m" * 40}).json()
            assert again["applied_now"] == [] and again["applied_total"][-1] == newest
        cur.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = %s AND p.proname = %s", ("ap", "submit_order"))
        assert cur.fetchone()[0] == 1                                             # and the migration really created the function
    finally:
        c.close()
        drop_database(name)


def test_a_failing_migration_changes_nothing_and_is_not_recorded(tmp_path, monkeypatch):
    name = "v4_mig_" + uuid.uuid4().hex[:8]
    url = build_database(name)
    c = psycopg2.connect(url); c.autocommit = True
    cur = c.cursor()
    cur.execute("CREATE TABLE ap.schema_migrations (id text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    for f in MIGRATIONS:
        cur.execute("INSERT INTO ap.schema_migrations (id) VALUES (%s)", (f.stem,))
    bad_dir = tmp_path / "m"; bad_dir.mkdir()
    for f in MIGRATIONS:
        (bad_dir / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    (bad_dir / "0005_broken.sql").write_text("CREATE TABLE ap.half_made (id int); SELECT 1/0;", encoding="utf-8")
    from app import migrate
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", bad_dir)
    try:
        try:
            migrate.apply_pending(url)
            raise AssertionError("expected a failure")
        except psycopg2.Error:
            pass
        cur.execute("SELECT to_regclass('ap.half_made')")
        assert cur.fetchone()[0] is None                                   # the half-made table was rolled back
        cur.execute("SELECT count(*) FROM ap.schema_migrations WHERE id = '0005_broken'")
        assert cur.fetchone()[0] == 0
    finally:
        c.close()
        drop_database(name)
