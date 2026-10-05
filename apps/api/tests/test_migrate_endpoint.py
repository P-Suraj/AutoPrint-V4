"""The migrate endpoint applies only the repo's files, is token-protected, and is safe to repeat."""
import uuid
from dataclasses import replace

import psycopg2
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from dbtools import MIGRATIONS, build_database, drop_database


def test_migrate_applies_pending_files_once_and_is_idempotent(tmp_path):
    # a database that has only 0001-0003 applied, as the real one did before 0004
    name = "v4_mig_" + uuid.uuid4().hex[:8]
    url = build_database(name)
    c = psycopg2.connect(url); c.autocommit = True
    cur = c.cursor()
    cur.execute("DROP FUNCTION ap.agent_poll(uuid, text, text); DROP FUNCTION ap.order_view(text); DROP FUNCTION ap.job_document(uuid, uuid); DROP TABLE ap.system_state")
    cur.execute("CREATE TABLE ap.schema_migrations (id text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    for f in MIGRATIONS[:3]:
        cur.execute("INSERT INTO ap.schema_migrations (id) VALUES (%s)", (f.stem,))
    s = Settings(database_url=url, local_storage_dir=str(tmp_path / "f"), signing_key="k" * 40, maintenance_token="m" * 40,
                 background_maintenance=False).validate()
    try:
        with TestClient(create_app(s)) as client:
            assert client.post("/v1/internal/migrate").status_code == 401
            assert client.post("/v1/internal/migrate", headers={"X-Maintenance-Token": "nope"}).status_code == 401
            ok = client.post("/v1/internal/migrate", headers={"X-Maintenance-Token": "m" * 40})
            assert ok.status_code == 200, ok.text
            assert ok.json()["applied_now"] == ["0004_agent_and_views"]
            again = client.post("/v1/internal/migrate", headers={"X-Maintenance-Token": "m" * 40}).json()
            assert again["applied_now"] == [] and again["applied_total"][-1] == "0004_agent_and_views"
        cur.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname='ap' AND proname IN ('agent_poll','order_view','job_document')")
        assert cur.fetchone()[0] == 3
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
