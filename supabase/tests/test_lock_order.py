"""Lock order under real concurrency (migrations 0013 and 0014): order first, then job, then attempt.

Two kinds of test, both on a real PostgreSQL with separate connections:
  * staged: one connection takes the order lock exactly as cancel, reject and resolve do first; the other call is
    started and the test WAITS until PostgreSQL shows it blocked on a lock; then the first connection carries on.
    With the old function bodies this interleaving is a certain deadlock (checked by hand against 0002's
    report_outcome and 0002's claim_next_job: one side got DeadlockDetected every time). It must now pass every time.
  * raced: the two calls are fired at the same instant from two threads, many rounds, and nothing may raise.
"""
import threading
import time

import psycopg2
import pytest

from dbtools import Db, run_in_threads

ROUNDS = 12


def printing_job(shop, db):
    """An order with one job that a device has claimed and handed to the spooler."""
    device = shop.device()
    order = shop.submitted_order()
    job = order["job_ids"][0]
    assert db.call("approve_job", job, device)["result"] == "ok"
    c = db.call("claim_next_job", device, 300)
    assert c["result"] == "claimed"
    assert db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)["result"] == "ok"
    return order, job, device, c


def approved_job_without_a_file(shop, db):
    """An approved job whose document is already deleted: the branch of claim_next_job that closes the order."""
    device = shop.device()
    order = shop.submitted_order()
    job = order["job_ids"][0]
    assert db.call("approve_job", job, device)["result"] == "ok"
    db.run("SELECT ap.mark_document_deleted(%s)", (order["doc_ids"][0],))
    return order, job, device


def wait_until_blocked(db, pid, seconds=10.0):
    """True once backend `pid` is waiting for a lock. This is what makes the staged tests exact instead of lucky."""
    end = time.time() + seconds
    while time.time() < end:
        if db.one("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (pid,)) == "Lock":
            return True
        time.sleep(0.02)
    return False


def staged(db_url, db, order_id, blocked_call, holder_sql, holder_args):
    """holder: BEGIN, lock the order. other: start `blocked_call(conn)`, wait until it is blocked.
    holder: run its function in the same transaction, COMMIT. Returns (holder result, other result or exception)."""
    holder = psycopg2.connect(db_url)                       # not autocommit: one open transaction
    other = Db(db_url)
    out = {}
    try:
        cur = holder.cursor()
        cur.execute("SELECT 1 FROM ap.orders WHERE id = %s FOR UPDATE", (order_id,))
        pid = other.one("SELECT pg_backend_pid()")

        def run():
            try:
                out["other"] = blocked_call(other)
            except Exception as exc:                         # surfaced to the test
                out["other"] = exc

        t = threading.Thread(target=run)
        t.start()
        assert wait_until_blocked(db, pid), "the second call never waited for a lock: the staging did not happen"
        cur.execute(holder_sql, holder_args)                 # a deadlock would be reported here or in the thread
        held = cur.fetchone()[0]
        holder.commit()
        t.join(20)
        assert not t.is_alive()
        return held, out["other"]
    finally:
        holder.close()
        other.close()


# ------------------------------------------------------------------ 0013: report_outcome against cancel, reject, resolve
@pytest.mark.parametrize("who,sql,expect", [
    ("cancel", "SELECT ap.cancel_order(%(order)s)", "too_late"),
    ("reject", "SELECT ap.reject_job(%(job)s, %(device)s, NULL)", "not_actionable"),
    ("resolve", "SELECT ap.resolve_job(%(job)s, %(device)s, 'failed', NULL)", "not_actionable"),
])
def test_outcome_report_waits_for_the_order_instead_of_deadlocking(shop, db, db_url, who, sql, expect):
    order, job, device, c = printing_job(shop, db)
    held, reported = staged(
        db_url, db, order["order_id"],
        lambda conn: conn.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {"printed": False}),
        sql, {"order": order["order_id"], "job": job, "device": device})
    assert not isinstance(reported, Exception), f"{who}: {reported!r}"
    assert held["result"] == expect                          # the job was printing when the other side looked
    assert reported == {"result": "ok", "job_status": "failed"}      # and the outcome was not lost
    assert db.one("SELECT status FROM ap.jobs WHERE id = %s", (job,)) == "failed"
    assert db.one("SELECT status FROM ap.orders WHERE id = %s", (order["order_id"],)) == "closed"
    assert db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id = %s", (job,)) == 1


@pytest.mark.parametrize("who", ["cancel", "reject", "resolve"])
def test_outcome_report_racing_cancel_reject_and_resolve_never_fails(shop, db, new_conn, who):
    a, b = new_conn(), new_conn()
    for _ in range(ROUNDS):
        order, job, device, c = printing_job(shop, db)
        other = {"cancel": lambda: b.call("cancel_order", order["order_id"]),
                 "reject": lambda: b.call("reject_job", job, device, None),
                 "resolve": lambda: b.call("resolve_job", job, device, "failed", None)}[who]
        reported, answered = run_in_threads([
            lambda: a.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {}), other])
        assert not isinstance(reported, Exception), repr(reported)
        assert not isinstance(answered, Exception), repr(answered)
        assert reported == {"result": "ok", "job_status": "needs_attention"}
        status = db.one("SELECT status FROM ap.jobs WHERE id = %s", (job,))
        if who == "resolve":
            # either the shopkeeper was first (the job was still printing: refused) or second (resolved as failed)
            assert (answered["result"], status) in {("not_actionable", "needs_attention"), ("ok", "failed")}
        else:
            assert answered["result"] == {"cancel": "too_late", "reject": "not_actionable"}[who]
            assert status == "needs_attention"
        assert db.one("SELECT attempt_count FROM ap.jobs WHERE id = %s", (job,)) == 1      # never a second attempt
        assert db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id = %s", (job,)) == 1


# ------------------------------------------------------------------ 0014: claim_next_job against a customer cancel
def test_claim_of_a_job_whose_file_is_gone_waits_for_the_order_instead_of_deadlocking(shop, db, db_url):
    order, job, device = approved_job_without_a_file(shop, db)
    cancelled, claimed = staged(db_url, db, order["order_id"], lambda conn: conn.call("claim_next_job", device, 300),
                                "SELECT ap.cancel_order(%s)", (order["order_id"],))
    assert not isinstance(claimed, Exception), repr(claimed)
    assert cancelled == {"result": "ok"} and claimed == {"result": "no_job"}
    assert db.one("SELECT status FROM ap.jobs WHERE id = %s", (job,)) == "cancelled"
    assert db.one("SELECT status FROM ap.orders WHERE id = %s", (order["order_id"],)) == "cancelled"
    assert db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id = %s", (job,)) == 0


def test_claim_of_a_printable_job_waits_for_a_cancel_in_progress_and_then_finds_nothing(shop, db, db_url):
    device = shop.device()
    order = shop.submitted_order()
    job = order["job_ids"][0]
    assert db.call("approve_job", job, device)["result"] == "ok"
    cancelled, claimed = staged(db_url, db, order["order_id"], lambda conn: conn.call("claim_next_job", device, 300),
                                "SELECT ap.cancel_order(%s)", (order["order_id"],))
    assert cancelled == {"result": "ok"} and claimed == {"result": "no_job"}           # the cancel was first: nothing prints
    assert db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id = %s", (job,)) == 0


def test_claim_racing_cancel_on_a_job_whose_file_is_gone_never_fails(shop, db, new_conn):
    a, b = new_conn(), new_conn()
    for _ in range(ROUNDS):
        order, job, device = approved_job_without_a_file(shop, db)
        claimed, cancelled = run_in_threads([lambda: a.call("claim_next_job", device, 300),
                                             lambda: b.call("cancel_order", order["order_id"])])
        assert not isinstance(claimed, Exception), repr(claimed)
        assert not isinstance(cancelled, Exception), repr(cancelled)
        assert claimed == {"result": "no_job"}                                          # there is no file: never a print
        job_status = db.one("SELECT status FROM ap.jobs WHERE id = %s", (job,))
        order_status = db.one("SELECT status FROM ap.orders WHERE id = %s", (order["order_id"],))
        # the customer was first (cancelled) or the claim was first (failed, order closed, cancel refused)
        assert (cancelled["result"], job_status, order_status) in {("ok", "cancelled", "cancelled"),
                                                                    ("order_not_cancellable", "failed", "closed")}
        assert db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id = %s", (job,)) == 0


def test_two_computers_claiming_at_once_still_get_one_job_each(shop, db, new_conn):
    """The claim no longer locks the job first, so two claims can look at the same oldest job. The second one must
    go on to the next job, not come back empty-handed, and the two must never get the same job."""
    d1, d2 = shop.device("PC 1"), shop.device("PC 2")
    a, b = new_conn(), new_conn()
    for _ in range(ROUNDS):
        jobs = set()
        for _ in range(2):
            order = shop.submitted_order()
            assert db.call("approve_job", order["job_ids"][0], d1)["result"] == "ok"
            jobs.add(str(order["job_ids"][0]))
        r1, r2 = run_in_threads([lambda: a.call("claim_next_job", d1, 300), lambda: b.call("claim_next_job", d2, 300)])
        assert not isinstance(r1, Exception) and not isinstance(r2, Exception), (r1, r2)
        assert r1["result"] == "claimed" and r2["result"] == "claimed", (r1["result"], r2["result"])
        assert {r1["job_id"], r2["job_id"]} == jobs
        for r, d in ((r1, d1), (r2, d2)):                                              # free both computers for the next round
            assert db.call("report_outcome", r["attempt_id"], r["attempt_token"], d, "failed", {})["result"] == "ok"


def test_claim_order_is_still_oldest_approved_first(shop, db):
    device = shop.device()
    first, second = shop.submitted_order(), shop.submitted_order()
    assert db.call("approve_job", second["job_ids"][0], device)["result"] == "ok"
    assert db.call("approve_job", first["job_ids"][0], device)["result"] == "ok"
    assert db.call("claim_next_job", device, 300)["job_id"] == str(second["job_ids"][0])   # approved first, printed first
