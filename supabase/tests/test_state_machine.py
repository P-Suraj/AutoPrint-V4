"""Phase 2 gate: transitions, tenant isolation, idempotency, and concurrency, on a real database."""
import uuid

import psycopg2
import pytest

from dbtools import run_in_threads, sha


def claim(db, device_id, lease=300):
    return db.call("claim_next_job", device_id, lease)


def approved_job(shop, db, device_id=None):
    device_id = device_id or shop.device()
    order = shop.submitted_order()
    job_id = order["job_ids"][0]
    assert db.call("approve_job", job_id, device_id)["result"] == "ok"
    return order, job_id, device_id


# ------------------------------------------------------------------ migrations
def test_migrations_apply_to_empty_database_twice(db_url):
    from dbtools import build_database, drop_database
    for i in range(2):
        name = "v4_fresh_" + uuid.uuid4().hex[:8]
        build_database(name)
        drop_database(name)


# ------------------------------------------------------------------ happy path up to the print
def test_submit_creates_job_payment_and_events(shop, db):
    order = shop.submitted_order(pages=(3,))
    assert db.one("SELECT status FROM ap.orders WHERE id=%s", (order["order_id"],)) == "submitted"
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (order["job_ids"][0],)) == "awaiting_approval"
    assert db.one("SELECT status FROM ap.payments WHERE order_id=%s", (order["order_id"],)) == "not_required"
    types = [r[0] for r in db.rows("SELECT type FROM ap.events WHERE order_id=%s ORDER BY id", (order["order_id"],))]
    assert types[0] == "order.created" and "quote.created" in types and types[-1] == "order.submitted"


def test_submit_is_idempotent(shop, db):
    order = shop.submitted_order()
    again = db.call("submit_order", order["order_id"], order["quote_id"])
    assert again["result"] == "ok" and again.get("idempotent") is True
    assert db.one("SELECT count(*) FROM ap.jobs WHERE order_id=%s", (order["order_id"],)) == 1


def test_secrets_are_stored_only_as_hashes(shop, db):
    order = shop.submitted_order()
    stored = db.one("SELECT secret_hash FROM ap.orders WHERE id=%s", (order["order_id"],))
    assert stored == sha(order["secret"]) and order["secret"] not in stored
    assert str(db.one("SELECT ap.order_for_secret(%s)", (sha(order["secret"]),))) == str(order["order_id"])
    assert db.one("SELECT ap.order_for_secret(%s)", (sha("wrong"),)) is None


# ------------------------------------------------------------------ quote validation
def test_quote_rejects_wrong_total_and_foreign_documents(shop, make_shop, db):
    other = make_shop()
    a = shop.submitted_order()
    secret = uuid.uuid4().hex
    o = db.call("create_order", shop.code, sha(secret))
    d = db.call("register_document", o["order_id"], "x.pdf", 100, f"k/{uuid.uuid4().hex}")
    db.call("finalize_document", d["document_id"], sha("x"), 100, 2)
    item = {"document_id": str(d["document_id"]), "copies": 1, "color": False, "duplex": False, "page_range": None,
            "selected_pages": 2, "printed_sides": 2, "amount_paise": 400}
    assert db.call("create_quote", o["order_id"], [item], 999)["result"] == "total_mismatch"
    foreign = dict(item, document_id=str(a["doc_ids"][0]))
    assert db.call("create_quote", o["order_id"], [foreign], 400)["result"] == "document_not_ready"
    too_many = dict(item, selected_pages=3, amount_paise=600)
    assert db.call("create_quote", o["order_id"], [too_many], 600)["result"] == "invalid_items"
    assert db.call("create_quote", o["order_id"], [item, item], 800)["result"] == "invalid_items"


def test_unvalidated_document_cannot_be_priced(shop, db):
    o = db.call("create_order", shop.code, sha(uuid.uuid4().hex))
    d = db.call("register_document", o["order_id"], "x.pdf", 100, f"k/{uuid.uuid4().hex}")
    item = {"document_id": str(d["document_id"]), "copies": 1, "color": False, "duplex": False, "page_range": None,
            "selected_pages": 1, "printed_sides": 1, "amount_paise": 200}
    assert db.call("create_quote", o["order_id"], [item], 200)["result"] == "document_not_ready"


def test_unknown_or_inactive_shop(db):
    assert db.call("create_order", "ZZZ999", sha("a"))["result"] == "shop_not_found"


# ------------------------------------------------------------------ approval and tenant isolation
def test_approve_is_idempotent_and_reject_after_approve_refused(shop, db):
    order, job_id, device = approved_job(shop, db)
    assert db.call("approve_job", job_id, device).get("idempotent") is True
    assert db.call("reject_job", job_id, device, "x")["result"] == "not_actionable"


def test_other_shops_device_cannot_see_or_approve_job(shop, make_shop, db):
    other_device = make_shop().device()
    order = shop.submitted_order()
    assert db.call("approve_job", order["job_ids"][0], other_device)["result"] == "job_not_found"
    assert db.call("reject_job", order["job_ids"][0], other_device)["result"] == "job_not_found"
    assert db.call("resolve_job", order["job_ids"][0], other_device, "failed")["result"] == "job_not_found"


def test_other_shops_device_cannot_claim_job(shop, make_shop, db):
    own, other = shop.device(), make_shop().device()
    approved_job(shop, db, own)
    assert claim(db, other)["result"] == "no_job"


def test_revoked_device_is_refused_everywhere(shop, db):
    order, job_id, device = approved_job(shop, db)
    db.run("UPDATE ap.devices SET status='revoked', revoked_at=now() WHERE id=%s", (device,))
    for call in (lambda: claim(db, device), lambda: db.call("approve_job", job_id, device),
                 lambda: db.call("reject_job", job_id, device)):
        assert call()["result"] == "unauthorized"
    assert db.call("authenticate_device", device, sha("whatever"))["result"] == "unauthorized"


def test_authenticate_device_checks_credential(shop, db):
    secret, code = uuid.uuid4().hex, uuid.uuid4().hex
    db.call("issue_enrollment_code", shop.code, sha(code), 30)
    device = db.call("consume_enrollment", sha(code), "PC", sha(secret))["device_id"]
    assert db.call("authenticate_device", device, sha(secret))["result"] == "ok"
    assert db.call("authenticate_device", device, sha("bad"))["result"] == "unauthorized"


def test_enrollment_code_is_single_use_and_expires(shop, db):
    code = uuid.uuid4().hex
    db.call("issue_enrollment_code", shop.code, sha(code), 30)
    assert db.call("consume_enrollment", sha(code), "PC", sha("s1"))["result"] == "ok"
    assert db.call("consume_enrollment", sha(code), "PC", sha("s2"))["result"] == "invalid_code"
    code2 = uuid.uuid4().hex
    db.call("issue_enrollment_code", shop.code, sha(code2), 30)
    db.run("UPDATE ap.enrollment_codes SET expires_at = now() - interval '1 second' WHERE code_hash=%s", (sha(code2),))
    assert db.call("consume_enrollment", sha(code2), "PC", sha("s3"))["result"] == "invalid_code"


# ------------------------------------------------------------------ claim
def test_unapproved_job_is_never_claimed(shop, db):
    device = shop.device()
    shop.submitted_order()
    assert claim(db, device)["result"] == "no_job"


def test_claim_returns_instructions_and_stores_only_token_hash(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    assert c["result"] == "claimed" and c["job_id"] == str(job_id)
    assert c["options"] == {"copies": 1, "color": False, "duplex": False, "page_range": None}
    assert c["spooler_job_name"].startswith("apjob_") and len(c["attempt_token"]) == 64
    assert db.one("SELECT attempt_token_hash FROM ap.print_attempts WHERE id=%s", (c["attempt_id"],)) == sha(c["attempt_token"])
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "printing"


def test_device_is_busy_until_attempt_ends(shop, db):
    device = shop.device()
    for _ in range(2):
        o = shop.submitted_order()
        db.call("approve_job", o["job_ids"][0], device)
    first = claim(db, device)
    assert first["result"] == "claimed"
    assert claim(db, device)["result"] == "busy"


def test_two_devices_never_claim_the_same_job(shop, new_conn):
    d1, d2 = shop.device("A"), shop.device("B")
    order = shop.submitted_order()
    shop.db.call("approve_job", order["job_ids"][0], d1)
    c1, c2 = new_conn(), new_conn()
    results = run_in_threads([lambda: c1.call("claim_next_job", d1, 300), lambda: c2.call("claim_next_job", d2, 300)])
    outcomes = sorted(r["result"] for r in results)
    assert outcomes == ["claimed", "no_job"], results
    assert shop.db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id=%s", (order["job_ids"][0],)) == 1


def test_many_simultaneous_claims_produce_exactly_one_attempt(shop, new_conn):
    devices = [shop.device(f"PC{i}") for i in range(6)]
    order = shop.submitted_order()
    shop.db.call("approve_job", order["job_ids"][0], devices[0])
    conns = [new_conn() for _ in devices]
    results = run_in_threads([(lambda c=c, d=d: c.call("claim_next_job", d, 300)) for c, d in zip(conns, devices)])
    assert sum(1 for r in results if r["result"] == "claimed") == 1
    assert shop.db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id=%s", (order["job_ids"][0],)) == 1


# ------------------------------------------------------------------ cancellation vs claim (decision F-9)
def test_cancel_before_claim_wins(shop, db):
    order, job_id, device = approved_job(shop, db)
    assert db.call("cancel_order", order["order_id"])["result"] == "ok"
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "cancelled"
    assert claim(db, device)["result"] == "no_job"
    assert db.call("cancel_order", order["order_id"]).get("idempotent") is True


def test_cancel_after_claim_is_too_late_and_printing_continues(shop, db):
    order, job_id, device = approved_job(shop, db)
    claim(db, device)
    assert db.call("cancel_order", order["order_id"])["result"] == "too_late"
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "printing"


def test_cancel_racing_claim_has_exactly_one_winner(shop, new_conn):
    wins = {"cancelled": 0, "claimed": 0}
    for _ in range(15):
        device = shop.device()
        order = shop.submitted_order()
        job_id = order["job_ids"][0]
        shop.db.call("approve_job", job_id, device)
        a, b = new_conn(), new_conn()
        r = run_in_threads([lambda: a.call("claim_next_job", device, 300), lambda: b.call("cancel_order", order["order_id"])])
        status = shop.db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,))
        attempts = shop.db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id=%s", (job_id,))
        if status == "cancelled":
            assert attempts == 0 and r[1]["result"] == "ok"
            wins["cancelled"] += 1
        else:
            assert status == "printing" and attempts == 1 and r[0]["result"] == "claimed" and r[1]["result"] == "too_late"
            wins["claimed"] += 1
        shop.db.run("UPDATE ap.devices SET status='revoked' WHERE id=%s", (device,))  # keep later claims unambiguous
    assert wins["cancelled"] + wins["claimed"] == 15


# ------------------------------------------------------------------ attempt ownership
def test_wrong_token_or_wrong_device_cannot_touch_attempt(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    other = shop.device("Other")
    assert db.call("mark_sent", c["attempt_id"], "wrong-token", device)["result"] == "stale_attempt"
    assert db.call("mark_sent", c["attempt_id"], c["attempt_token"], other)["result"] == "stale_attempt"
    assert db.call("report_outcome", c["attempt_id"], "wrong", device, "failed", {})["result"] == "stale_attempt"
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "printing"


def test_completed_is_refused_without_sent_and_without_evidence(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    # not yet sent to the spooler
    assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "completed", {"basis": "x"})["result"] == "stale_attempt"
    assert db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)["result"] == "ok"
    assert db.call("mark_sent", c["attempt_id"], c["attempt_token"], device).get("idempotent") is True
    # sent, but evidence does not satisfy the rule
    assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "completed", {})["result"] == "evidence_insufficient"
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "printing"


def test_failed_and_uncertain_outcomes(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)
    r = db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {"reason": "spooler_state_unclear"})
    assert r == {"result": "ok", "job_status": "needs_attention"}
    # a repeated identical report is idempotent; a conflicting one is refused and logged
    assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {}).get("idempotent") is True
    assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {})["result"] == "stale_attempt"
    assert db.one("SELECT count(*) FROM ap.events WHERE attempt_id=%s AND type='attempt.late_report'", (c["attempt_id"],)) == 1


def test_oversized_or_malformed_evidence_refused(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {"x": "y" * 5000})["result"] == "invalid_evidence"
    assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "bogus", {})["result"] == "invalid_outcome"


# ------------------------------------------------------------------ human resolution; never an automatic retry
def test_uncertain_job_is_never_reprinted_automatically(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {})
    assert claim(db, device)["result"] == "no_job"
    assert db.call("sweep")["stale_attempts"] == 0
    assert claim(db, device)["result"] == "no_job"
    assert db.one("SELECT count(*) FROM ap.print_attempts WHERE job_id=%s", (job_id,)) == 1


def test_lease_expiry_marks_needs_attention_not_retry(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)
    db.run("UPDATE ap.print_attempts SET lease_expires_at = now() - interval '1 second' WHERE id=%s", (c["attempt_id"],))
    assert db.call("sweep")["stale_attempts"] == 1
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "needs_attention"
    assert db.one("SELECT status FROM ap.print_attempts WHERE id=%s", (c["attempt_id"],)) == "uncertain"
    # a late report from the old attempt cannot change the outcome
    r = db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {})
    assert r["result"] == "stale_attempt"
    assert claim(db, device)["result"] == "no_job"


def test_renew_lease_extends_and_refuses_expired(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device, 60)
    assert db.call("renew_lease", c["attempt_id"], c["attempt_token"], device, 600)["result"] == "ok"
    db.run("UPDATE ap.print_attempts SET lease_expires_at = now() - interval '1 second' WHERE id=%s", (c["attempt_id"],))
    assert db.call("renew_lease", c["attempt_id"], c["attempt_token"], device, 600)["result"] == "stale_attempt"


def test_only_explicit_human_retry_creates_a_second_attempt(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "failed", {"reason": "paper_jam"})
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "failed"
    assert claim(db, device)["result"] == "no_job"
    assert db.call("resolve_job", job_id, device, "retry", "jam cleared")["result"] == "ok"
    c2 = claim(db, device)
    assert c2["result"] == "claimed" and c2["attempt_id"] != c["attempt_id"]
    assert c2["spooler_job_name"] != c["spooler_job_name"]
    assert db.one("SELECT attempt_count FROM ap.jobs WHERE id=%s", (job_id,)) == 2


def test_resolve_needs_attention_as_completed_or_failed(shop, db):
    for resolution, expected in (("completed", "completed"), ("failed", "failed")):
        order, job_id, device = approved_job(shop, db)
        c = claim(db, device)
        db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "uncertain", {})
        assert db.call("resolve_job", job_id, device, resolution)["result"] == "ok"
        assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == expected
        assert db.one("SELECT status FROM ap.orders WHERE id=%s", (order["order_id"],)) == "closed"


def test_resolve_refused_for_printing_and_unknown_resolution(shop, db):
    order, job_id, device = approved_job(shop, db)
    claim(db, device)
    assert db.call("resolve_job", job_id, device, "completed")["result"] == "not_actionable"
    assert db.call("resolve_job", job_id, device, "nonsense")["result"] == "invalid_resolution"


# ------------------------------------------------------------------ expiry (decision O-10) and retention (decision O-5)
def test_unapproved_job_expires_after_window_and_cannot_be_approved(shop, db):
    device = shop.device()
    order = shop.submitted_order()
    db.run("UPDATE ap.orders SET expires_at = now() - interval '1 second' WHERE id=%s", (order["order_id"],))
    assert db.call("approve_job", order["job_ids"][0], device)["result"] == "order_expired"
    db.call("sweep")
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (order["job_ids"][0],)) == "expired"
    assert db.one("SELECT status FROM ap.orders WHERE id=%s", (order["order_id"],)) == "closed"


def test_approved_jobs_survive_the_approval_window(shop, db):
    device = shop.device()
    order = shop.submitted_order(pages=(2, 2))
    a, b = order["job_ids"]
    db.call("approve_job", a, device)
    db.run("UPDATE ap.orders SET expires_at = now() - interval '1 second' WHERE id=%s", (order["order_id"],))
    db.call("sweep")
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (a,)) == "approved"
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (b,)) == "expired"
    assert db.one("SELECT status FROM ap.orders WHERE id=%s", (order["order_id"],)) == "submitted"


def test_abandoned_draft_expires_and_its_documents_are_due_for_deletion(shop, db):
    o = db.call("create_order", shop.code, sha(uuid.uuid4().hex))
    d = db.call("register_document", o["order_id"], "x.pdf", 100, f"k/{uuid.uuid4().hex}")
    # the order was created 2 hours ago and never submitted
    db.run("UPDATE ap.orders SET created_at = now() - interval '2 hours', expires_at = now() - interval '1 second' WHERE id=%s", (o["order_id"],))
    db.run("UPDATE ap.documents SET created_at = now() - interval '2 hours' WHERE id=%s", (d["document_id"],))
    db.call("sweep")
    assert db.one("SELECT status FROM ap.orders WHERE id=%s", (o["order_id"],)) == "expired"
    due = [str(r[0]) for r in db.rows("SELECT document_id FROM ap.documents_due_for_deletion(1000)")]
    assert str(d["document_id"]) in due
    db.call("mark_document_deleted", d["document_id"])
    assert db.one("SELECT status FROM ap.documents WHERE id=%s", (d["document_id"],)) == "deleted"
    assert str(d["document_id"]) not in [str(r[0]) for r in db.rows("SELECT document_id FROM ap.documents_due_for_deletion(1000)")]


def test_retention_windows_follow_the_decision(shop, db):
    # draft: 1 hour; submitted: hard cap; final: 24 hours, never beyond the hard cap
    o = db.call("create_order", shop.code, sha(uuid.uuid4().hex))
    d = db.call("register_document", o["order_id"], "x.pdf", 100, f"k/{uuid.uuid4().hex}")
    hrs = lambda: db.one("SELECT extract(epoch FROM (delete_after - created_at))/3600 FROM ap.documents WHERE id=%s", (d["document_id"],))
    assert abs(hrs() - 1) < 0.01
    order = shop.submitted_order()
    device = shop.device()
    doc = order["doc_ids"][0]
    cap = db.one("SELECT extract(epoch FROM (delete_after - (SELECT created_at FROM ap.orders WHERE id=%s)))/3600 FROM ap.documents WHERE id=%s", (order["order_id"], doc))
    assert abs(cap - 48) < 0.01
    db.call("cancel_order", order["order_id"])
    after = db.one("SELECT extract(epoch FROM (delete_after - now()))/3600 FROM ap.documents WHERE id=%s", (doc,))
    assert 23.9 < after <= 24.01


def test_order_secret_stops_working_after_hard_cap(shop, db):
    order = shop.submitted_order()
    db.run("UPDATE ap.orders SET created_at = now() - interval '3 days', access_until = now() - interval '1 second' WHERE id=%s", (order["order_id"],))
    assert db.one("SELECT ap.order_for_secret(%s)", (sha(order["secret"]),)) is None
    assert db.call("cancel_order", order["order_id"])["result"] == "order_not_found"


# ------------------------------------------------------------------ events
def test_events_are_append_only(shop, db):
    order = shop.submitted_order()
    with pytest.raises(psycopg2.Error):
        db.run("UPDATE ap.events SET type='x' WHERE order_id=%s", (order["order_id"],))
    with pytest.raises(psycopg2.Error):
        db.run("DELETE FROM ap.events WHERE order_id=%s", (order["order_id"],))


def test_events_hold_no_secrets(shop, db):
    order = shop.submitted_order()
    device = shop.device()
    db.call("approve_job", order["job_ids"][0], device)
    c = claim(db, device)
    dump = " ".join(str(r[0]) for r in db.rows("SELECT data::text FROM ap.events"))
    assert c["attempt_token"] not in dump and order["secret"] not in dump
