"""The demo SQL files are pasted into a live database by a person, so they are tested here first."""
import uuid
from pathlib import Path

import pytest

from dbtools import Db, build_database, drop_database, sha

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture
def fresh():
    name = "v4_demo_" + uuid.uuid4().hex[:8]
    url = build_database(name)
    d = Db(url)
    yield d
    d.close()
    drop_database(name)


def run_file(db, name):
    cur = db.conn.cursor()
    cur.execute((SCRIPTS / name).read_text(encoding="utf-8"))
    return cur


def submit_job(db):
    o = db.call("create_order", "TST001", sha(uuid.uuid4().hex))
    d = db.call("register_document", o["order_id"], "x.pdf", 1000, f"k/{uuid.uuid4().hex}")
    db.call("finalize_document", d["document_id"], sha(uuid.uuid4().hex), 1000, 3)
    item = {"document_id": str(d["document_id"]), "copies": 1, "color": False, "duplex": False, "page_range": None,
            "selected_pages": 3, "printed_sides": 3, "amount_paise": 600}
    q = db.call("create_quote", o["order_id"], [item], 600)
    assert q["result"] == "ok", q
    return o, db.call("submit_order", o["order_id"], q["quote_id"])


def test_the_three_demo_steps_work_in_order(fresh):
    run_file(fresh, "demo_1_create_test_shop.sql")
    assert fresh.one("SELECT count(*) FROM ap.devices") == 1
    order, sub = submit_job(fresh)
    job_id = sub["job_ids"][0]

    cur = run_file(fresh, "demo_2_approve_latest.sql")
    assert cur.fetchone()[0] == {"result": "ok"}
    assert fresh.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "approved"

    cur = run_file(fresh, "demo_3_pretend_it_printed.sql")
    assert cur.fetchone()[0] == "completed"
    assert fresh.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "completed"
    assert fresh.one("SELECT status FROM ap.orders WHERE id=%s", (order["order_id"],)) == "closed"


def test_step_2_with_nothing_waiting_is_harmless(fresh):
    run_file(fresh, "demo_1_create_test_shop.sql")
    cur = run_file(fresh, "demo_2_approve_latest.sql")
    assert cur.fetchone()[0]["result"] == "job_not_found"


def test_step_1_cannot_run_twice(fresh):
    run_file(fresh, "demo_1_create_test_shop.sql")
    with pytest.raises(Exception):
        run_file(fresh, "demo_1_create_test_shop.sql")
