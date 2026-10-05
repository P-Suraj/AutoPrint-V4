"""Every legal row in ap.allowed_transitions is driven through the real functions, and the test
fails if a row exists with no scenario (or a scenario exists for a row that was removed)."""
import uuid

import pytest

from dbtools import sha
from test_completion_rule import GOOD
from test_state_machine import approved_job, claim

COVERED: set = set()


def cover(entity, frm, to, actor):
    COVERED.add((entity, frm, to, actor))


def job_status(db, job_id):
    return db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,))


def attempt_status(db, attempt_id):
    return db.one("SELECT status FROM ap.print_attempts WHERE id=%s", (attempt_id,))


def order_status(db, order_id):
    return db.one("SELECT status FROM ap.orders WHERE id=%s", (order_id,))


def expire_order(db, order_id):
    db.run("UPDATE ap.orders SET expires_at = now() - interval '1 second' WHERE id=%s", (order_id,))


def printing(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    return order, job_id, device, c


def sent(shop, db):
    order, job_id, device, c = printing(shop, db)
    db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)
    return order, job_id, device, c


# ---------------------------------------------------------------- order
def test_order_transitions(shop, db):
    # draft -> submitted
    o = shop.submitted_order()
    assert order_status(db, o["order_id"]) == "submitted"; cover("order", "draft", "submitted", "customer")
    # draft -> cancelled
    d = db.call("create_order", shop.code, sha(uuid.uuid4().hex))
    assert db.call("cancel_order", d["order_id"])["result"] == "ok"
    assert order_status(db, d["order_id"]) == "cancelled"; cover("order", "draft", "cancelled", "customer")
    # draft -> expired
    d2 = db.call("create_order", shop.code, sha(uuid.uuid4().hex))
    expire_order(db, d2["order_id"]); db.call("sweep")
    assert order_status(db, d2["order_id"]) == "expired"; cover("order", "draft", "expired", "system")
    # submitted -> cancelled
    o2 = shop.submitted_order()
    db.call("cancel_order", o2["order_id"])
    assert order_status(db, o2["order_id"]) == "cancelled"; cover("order", "submitted", "cancelled", "customer")
    # submitted -> closed
    o3 = shop.submitted_order(); device = shop.device()
    db.call("reject_job", o3["job_ids"][0], device)
    assert order_status(db, o3["order_id"]) == "closed"; cover("order", "submitted", "closed", "system")


# ---------------------------------------------------------------- job
def test_job_transitions_before_printing(shop, db):
    device = shop.device()
    a = shop.submitted_order(); db.call("approve_job", a["job_ids"][0], device)
    assert job_status(db, a["job_ids"][0]) == "approved"; cover("job", "awaiting_approval", "approved", "device")
    b = shop.submitted_order(); db.call("reject_job", b["job_ids"][0], device)
    assert job_status(db, b["job_ids"][0]) == "rejected"; cover("job", "awaiting_approval", "rejected", "device")
    c = shop.submitted_order(); db.call("cancel_order", c["order_id"])
    assert job_status(db, c["job_ids"][0]) == "cancelled"; cover("job", "awaiting_approval", "cancelled", "customer")
    d = shop.submitted_order(); expire_order(db, d["order_id"]); db.call("sweep")
    assert job_status(db, d["job_ids"][0]) == "expired"; cover("job", "awaiting_approval", "expired", "system")
    e = shop.submitted_order(); db.call("approve_job", e["job_ids"][0], device); db.call("cancel_order", e["order_id"])
    assert job_status(db, e["job_ids"][0]) == "cancelled"; cover("job", "approved", "cancelled", "customer")


def test_job_transitions_while_printing(shop, db):
    order, job_id, device, c = printing(shop, db)
    assert job_status(db, job_id) == "printing"; cover("job", "approved", "printing", "device")
    db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "completed", GOOD)
    assert job_status(db, job_id) == "completed"; cover("job", "printing", "completed", "device")

    order, job_id, device, c = printing(shop, db)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {})
    assert job_status(db, job_id) == "failed"; cover("job", "printing", "failed", "device")

    order, job_id, device, c = printing(shop, db)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {})
    assert job_status(db, job_id) == "needs_attention"; cover("job", "printing", "needs_attention", "device")

    order, job_id, device, c = printing(shop, db)
    db.run("UPDATE ap.print_attempts SET lease_expires_at = now() - interval '1 second' WHERE id=%s", (c["attempt_id"],))
    db.call("sweep")
    assert job_status(db, job_id) == "needs_attention"; cover("job", "printing", "needs_attention", "system")


def test_job_transitions_by_human_resolution(shop, db):
    for resolution, expected, frm in (("completed", "completed", "needs_attention"), ("failed", "failed", "needs_attention"),
                                      ("retry", "approved", "needs_attention")):
        order, job_id, device, c = printing(shop, db)
        db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {})
        assert job_status(db, job_id) == "needs_attention"
        assert db.call("resolve_job", job_id, device, resolution)["result"] == "ok"
        assert job_status(db, job_id) == expected; cover("job", frm, expected, "device")
    order, job_id, device, c = printing(shop, db)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {})
    db.call("resolve_job", job_id, device, "retry")
    assert job_status(db, job_id) == "approved"; cover("job", "failed", "approved", "device")


# ---------------------------------------------------------------- attempt
def test_attempt_transitions(shop, db):
    order, job_id, device, c = printing(shop, db)
    db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)
    assert attempt_status(db, c["attempt_id"]) == "sent_to_spooler"; cover("attempt", "claimed", "sent_to_spooler", "device")
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "completed", GOOD)
    assert attempt_status(db, c["attempt_id"]) == "completed"; cover("attempt", "sent_to_spooler", "completed", "device")

    order, job_id, device, c = sent(shop, db)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {})
    assert attempt_status(db, c["attempt_id"]) == "failed"; cover("attempt", "sent_to_spooler", "failed", "device")

    order, job_id, device, c = sent(shop, db)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {})
    assert attempt_status(db, c["attempt_id"]) == "uncertain"; cover("attempt", "sent_to_spooler", "uncertain", "device")

    order, job_id, device, c = sent(shop, db)
    db.run("UPDATE ap.print_attempts SET lease_expires_at = now() - interval '1 second' WHERE id=%s", (c["attempt_id"],))
    db.call("sweep")
    assert attempt_status(db, c["attempt_id"]) == "uncertain"; cover("attempt", "sent_to_spooler", "uncertain", "system")

    order, job_id, device, c = printing(shop, db)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {})
    assert attempt_status(db, c["attempt_id"]) == "failed"; cover("attempt", "claimed", "failed", "device")

    order, job_id, device, c = printing(shop, db)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {})
    assert attempt_status(db, c["attempt_id"]) == "uncertain"; cover("attempt", "claimed", "uncertain", "device")

    order, job_id, device, c = printing(shop, db)
    db.run("UPDATE ap.print_attempts SET lease_expires_at = now() - interval '1 second' WHERE id=%s", (c["attempt_id"],))
    db.call("sweep")
    assert attempt_status(db, c["attempt_id"]) == "uncertain"; cover("attempt", "claimed", "uncertain", "system")


# ---------------------------------------------------------------- the table and the scenarios must match
def test_every_allowed_transition_has_a_scenario_and_nothing_else_does(db):
    # runs last in this file by name ordering within the module; the scenario tests above fill COVERED
    table = {tuple(r) for r in db.rows("SELECT entity, from_status, to_status, actor::text FROM ap.allowed_transitions")}
    assert COVERED == table, f"uncovered: {sorted(table - COVERED)}; stale scenarios: {sorted(COVERED - table)}"


# ---------------------------------------------------------------- illegal moves are refused from every job state
@pytest.mark.parametrize("state", ["awaiting_approval", "approved", "printing", "completed", "failed", "needs_attention", "rejected", "cancelled", "expired"])
def test_actions_that_are_not_allowed_in_a_state_change_nothing(shop, db, state):
    device = shop.device()
    order = shop.submitted_order(); job_id = order["job_ids"][0]
    db.run("UPDATE ap.jobs SET status=%s WHERE id=%s", (state, job_id))
    forbidden = {
        "approve_job":  {"awaiting_approval", "approved"},
        "reject_job":   {"awaiting_approval", "rejected"},
        "resolve_job":  {"needs_attention", "failed"},
    }
    for fn, ok_states in forbidden.items():
        if state in ok_states:
            continue
        args = (job_id, device, "completed") if fn == "resolve_job" else (job_id, device)
        r = db.call(fn, *args)
        assert r["result"] in ("not_actionable", "order_expired"), (fn, state, r)
        assert job_status(db, job_id) == state, f"{fn} changed a {state} job"
