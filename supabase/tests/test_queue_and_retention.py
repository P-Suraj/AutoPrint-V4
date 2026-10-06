"""Migrations 0014 to 0018 on a real database: the shop queue under a flood, the cap on waiting jobs, files past
their retention deadline, and what is left in the rows once a file is deleted."""
import uuid

import psycopg2

from dbtools import MIGRATIONS, Db, Shop, build_database, drop_database, sha
import dbtools

OPEN = ("awaiting_approval", "approved", "printing", "needs_attention")


def poll(db, device):
    cred = db.one("SELECT credential_hash FROM ap.devices WHERE id = %s", (device,))
    res = db.call("agent_poll", device, cred, None)
    assert res["result"] == "ok"
    return res["jobs"]


def quoted_order(shop, db, files):
    """A draft order with `files` validated one-page documents and a quote, not yet submitted."""
    o = db.call("create_order", shop.code, sha(uuid.uuid4().hex))
    items = []
    for i in range(files):
        d = db.call("register_document", o["order_id"], f"f{i}.pdf", 1000, f"orders/{o['order_id']}/{uuid.uuid4().hex}.pdf")
        assert db.call("finalize_document", d["document_id"], sha(uuid.uuid4().hex), 1000, 1)["result"] == "ok"
        items.append({"document_id": str(d["document_id"]), "copies": 1, "color": False, "duplex": False, "page_range": None,
                      "selected_pages": 1, "printed_sides": 1, "amount_paise": 200})
    q = db.call("create_quote", o["order_id"], items, 200 * files)
    assert q["result"] == "ok", q
    return o["order_id"], q["quote_id"]


# ------------------------------------------------------------------ 0017: the queue under a flood
def test_a_flood_of_many_file_orders_cannot_push_a_waiting_job_off_the_shop_screen(shop, db):
    device = shop.device()
    real = shop.submitted_order()                                     # the real customer, first in
    finished = []
    for _ in range(45):                                               # a busy morning: 45 jobs already dealt with
        o = shop.submitted_order()
        assert db.call("reject_job", o["job_ids"][0], device, None)["result"] == "ok"
        finished.append(str(o["job_ids"][0]))
    flood = [shop.submitted_order(pages=(1,) * 20) for _ in range(7)]  # then 140 jobs from one script
    jobs = poll(db, device)

    open_jobs = [j for j in jobs if j["status"] in OPEN]
    done_jobs = [j for j in jobs if j["status"] not in OPEN]
    assert len(open_jobs) == 141                                      # every waiting job is there (the old limit was 60 in all)
    assert open_jobs[0]["job_id"] == str(real["job_ids"][0])          # and the one waiting longest is on top
    assert jobs[:141] == open_jobs                                    # open first, finished after
    assert [j["created_at"] for j in open_jobs] == sorted(j["created_at"] for j in open_jobs)   # oldest first
    assert {j["job_id"] for j in open_jobs} >= {str(i) for o in flood for i in o["job_ids"]}
    assert len(done_jobs) == 40                                       # only the finished group is cut
    assert [j["job_id"] for j in done_jobs] == finished[::-1][:40]    # most recently finished first
    assert set(jobs[0]) == {"job_id", "order_short_code", "document_name", "page_count", "copies", "color", "duplex", "page_range",
                            "amount_paise", "status", "created_at", "approval_expires_at", "attempt_count"}   # same fields as before


def test_queue_shows_every_open_state_and_only_a_day_of_finished_jobs(shop, db):
    device = shop.device()
    waiting, attention, old, printing, approved = (shop.submitted_order() for _ in range(5))
    for o in (attention, old, printing, approved):                    # claimed in the order they were approved
        assert db.call("approve_job", o["job_ids"][0], device)["result"] == "ok"
    for o, outcome in ((attention, "uncertain"), (old, "failed")):
        c = db.call("claim_next_job", device, 300)
        assert c["job_id"] == str(o["job_ids"][0])
        assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, outcome, {})["result"] == "ok"
    assert db.call("claim_next_job", device, 300)["job_id"] == str(printing["job_ids"][0])
    db.run("UPDATE ap.jobs SET updated_at = now() - interval '25 hours' WHERE id = %s", (old["job_ids"][0],))
    # an open job is never dropped for being old; a finished one is, after 24 hours
    db.run("UPDATE ap.jobs SET created_at = now() - interval '3 days', updated_at = now() - interval '3 days' WHERE id = %s", (waiting["job_ids"][0],))
    jobs = poll(db, device)
    assert [(j["job_id"], j["status"]) for j in jobs] == [
        (str(waiting["job_ids"][0]), "awaiting_approval"), (str(attention["job_ids"][0]), "needs_attention"),
        (str(printing["job_ids"][0]), "printing"), (str(approved["job_ids"][0]), "approved")]     # oldest first, whatever the state
    assert str(old["job_ids"][0]) not in {j["job_id"] for j in jobs}


# ------------------------------------------------------------------ 0018: at most 150 jobs waiting per shop
def test_a_shop_takes_no_more_than_150_waiting_jobs_and_takes_orders_again_when_the_queue_moves(shop, make_shop, db):
    device = shop.device()
    for _ in range(7):
        shop.submitted_order(pages=(1,) * 20)                         # 140 waiting
    order, quote = quoted_order(shop, db, 11)                         # 151 would be one too many
    refused = db.call("submit_order", order, quote)
    assert refused["result"] == "shop_not_accepting"
    assert db.one("SELECT status FROM ap.orders WHERE id = %s", (order,)) == "draft"            # nothing changed
    assert db.one("SELECT count(*) FROM ap.jobs WHERE order_id = %s", (order,)) == 0
    assert db.one("SELECT accepted_at FROM ap.quotes WHERE id = %s", (quote,)) is None

    exact, exact_quote = quoted_order(shop, db, 10)                   # 150 exactly is allowed
    assert db.call("submit_order", exact, exact_quote)["result"] == "ok"
    assert db.call("submit_order", exact, exact_quote).get("idempotent") is True               # sending it again is still "ok"
    assert db.call("submit_order", order, quote)["result"] == "shop_not_accepting"

    other = make_shop()                                               # another shop is not affected
    assert other.submitted_order()["job_ids"]

    waiting = db.rows("SELECT id FROM ap.jobs WHERE shop_id = %s AND status = 'awaiting_approval' LIMIT 11", (shop.id,))
    for (job,) in waiting:                                            # the shopkeeper works through 11 of them
        assert db.call("approve_job", job, device)["result"] == "ok"
    assert db.call("submit_order", order, quote)["result"] == "ok"    # approved jobs do not count: there is room again


# ------------------------------------------------------------------ 0014 and 0016: a file past its deadline
def test_a_file_past_its_retention_deadline_is_neither_downloadable_nor_printable_even_before_cleanup(shop, db):
    device = shop.device()
    o = shop.submitted_order()
    job, doc = o["job_ids"][0], o["doc_ids"][0]
    assert db.call("approve_job", job, device)["result"] == "ok"
    assert db.call("job_document", job, device)["result"] == "ok"
    db.run("UPDATE ap.documents SET delete_after = now() - interval '1 second' WHERE id = %s", (doc,))
    assert db.one("SELECT deleted_at FROM ap.documents WHERE id = %s", (doc,)) is None           # the cleanup has not run
    assert db.call("job_document", job, device) == {"result": "document_not_found"}
    assert db.call("claim_next_job", device, 300) == {"result": "no_job"}
    assert db.one("SELECT status FROM ap.jobs WHERE id = %s", (job,)) == "failed"
    assert db.one("SELECT data->>'reason' FROM ap.events WHERE job_id = %s AND type = 'job.failed'", (job,)) == "document_unavailable"
    assert db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id = %s", (job,)) == 0


# ------------------------------------------------------------------ 0015: what a deleted document leaves behind
def test_a_deleted_document_keeps_neither_its_name_nor_its_checksum(shop, db):
    device = shop.device()
    o = shop.submitted_order()
    job, doc = o["job_ids"][0], o["doc_ids"][0]
    db.run("UPDATE ap.documents SET original_name = 'ravi-passport-scan.pdf' WHERE id = %s", (doc,))
    assert db.call("approve_job", job, device)["result"] == "ok"
    c = db.call("claim_next_job", device, 300)
    assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {})["result"] == "ok"
    bystander = shop.submitted_order()
    assert poll(db, device)[0]["document_name"] == "ravi-passport-scan.pdf"                     # while the file exists

    db.run("SELECT ap.mark_document_deleted(%s)", (doc,))
    assert db.rows("SELECT status::text, original_name, sha256, deleted_at IS NOT NULL, page_count FROM ap.documents WHERE id = %s", (doc,)) \
        == [("deleted", "deleted file", None, True, 3)]
    assert db.one("SELECT artifact_sha256 FROM ap.print_attempts WHERE job_id = %s", (job,)) == ""
    everything = str(db.rows("SELECT * FROM ap.documents WHERE order_id = %s", (o["order_id"],))) + \
        str(db.rows("SELECT * FROM ap.events WHERE order_id = %s", (o["order_id"],))) + \
        str(db.rows("SELECT * FROM ap.print_attempts WHERE job_id = %s", (job,)))
    assert "passport" not in everything
    assert db.rows("SELECT original_name <> 'deleted file', sha256 IS NOT NULL FROM ap.documents WHERE id = %s", (bystander["doc_ids"][0],)) \
        == [(True, True)]                                                                        # other documents are untouched

    # the job that needed a person is still listed and can still be answered; only the name is gone
    listed = {j["job_id"]: j for j in poll(db, device)}
    assert listed[str(job)]["document_name"] == "deleted file" and listed[str(job)]["status"] == "needs_attention"
    view = db.call("order_view", sha(o["secret"]))
    assert view["result"] == "ok" and view["jobs"][0]["document_name"] == "deleted file"
    assert db.call("resolve_job", job, device, "retry", None)["result"] == "ok"                 # "print again" on a deleted file...
    assert db.call("claim_next_job", device, 300) == {"result": "no_job"}                       # ...cannot print: no file
    assert db.one("SELECT status FROM ap.jobs WHERE id = %s", (job,)) == "failed"
    db.run("SELECT ap.mark_document_deleted(%s)", (doc,))                                        # calling it twice changes nothing
    assert db.one("SELECT count(*) FROM ap.documents WHERE id = %s AND status = 'deleted'", (doc,)) == 1


def test_migration_0015_cleans_rows_that_were_deleted_before_it(monkeypatch):
    """A database as the live one is today (everything up to 0014 applied, old deleted documents still named)."""
    upto = [m for m in MIGRATIONS if m.name[:4] <= "0014"]
    rest = [m for m in MIGRATIONS if m.name[:4] > "0014"]
    assert rest and rest[0].name.startswith("0015_")
    monkeypatch.setattr(dbtools, "MIGRATIONS", upto)
    name = "v4_back_" + uuid.uuid4().hex[:8]
    url = build_database(name)
    try:
        db = Db(url)
        shop = Shop(db)
        device = shop.device()
        gone, kept = shop.submitted_order(), shop.submitted_order()
        for o in (gone, kept):
            assert db.call("approve_job", o["job_ids"][0], device)["result"] == "ok"
            c = db.call("claim_next_job", device, 300)
            assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {})["result"] == "ok"
        db.run("SELECT ap.mark_document_deleted(%s)", (gone["doc_ids"][0],))                    # the old function: the name stays
        assert db.one("SELECT original_name FROM ap.documents WHERE id = %s", (gone["doc_ids"][0],)) == "file1.pdf"
        for m in rest:
            db.conn.cursor().execute(m.read_text(encoding="utf-8"))
        assert db.rows("SELECT original_name, sha256 FROM ap.documents WHERE id = %s", (gone["doc_ids"][0],)) == [("deleted file", None)]
        assert db.one("SELECT artifact_sha256 FROM ap.print_attempts WHERE job_id = %s", (gone["job_ids"][0],)) == ""
        assert db.one("SELECT original_name FROM ap.documents WHERE id = %s", (kept["doc_ids"][0],)) == "file1.pdf"
        assert len(db.one("SELECT sha256 FROM ap.documents WHERE id = %s", (kept["doc_ids"][0],))) == 64
        assert len(db.one("SELECT artifact_sha256 FROM ap.print_attempts WHERE job_id = %s", (kept["job_ids"][0],))) == 64
        db.close()
    finally:
        drop_database(name)
