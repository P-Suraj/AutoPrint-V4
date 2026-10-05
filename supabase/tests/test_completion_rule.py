"""The completion rule (docs/PRINT_SPIKE_REPORT.md). Every spike observation has a case here."""
import copy

import pytest

from test_state_machine import approved_job, claim

GOOD = {
    "rule_version": 1, "spooler_job_seen": True, "printing_seen": True, "left_queue": True,
    "flags_seen": ["SPOOLING", "PRINTING", "RETAINED"], "max_pages_printed": 3, "expected_pages": 3,
}


def supports(db, evidence):
    return db.one("SELECT ap.evidence_supports_completion(%s::jsonb)", (__import__("json").dumps(evidence),))


def test_good_evidence_is_accepted(db):
    assert supports(db, GOOD) is True


def test_missed_last_page_increment_is_still_accepted(db):
    # spike: 4 of 37 jobs left the queue before the final PagesPrinted sample
    assert supports(db, dict(GOOD, max_pages_printed=2, expected_pages=3)) is True


@pytest.mark.parametrize("change", [
    {"spooler_job_seen": False},          # spike: Sumatra killed before spooling
    {"left_queue": False},                # spike: paused queue, job stays
    {"printing_seen": False},
    {"max_pages_printed": 0},
    {"flags_seen": ["SPOOLING", "DELETING"]},           # spike: cancelled at the spooler also leaves the queue
    {"flags_seen": ["PRINTING", "ERROR"]},
    {"flags_seen": ["PRINTING", "OFFLINE"]},
    {"flags_seen": ["PRINTING", "PAPEROUT"]},
    {"flags_seen": ["PRINTING", "USER_INTERVENTION"]},
    {"flags_seen": ["PRINTING", "BLOCKED_DEVQ"]},
    {"flags_seen": "PRINTING"},           # wrong type
    {"rule_version": 2},                  # unknown rule version is never trusted
    {"spooler_job_seen": "true"},         # strings are not booleans
])
def test_each_missing_or_bad_signal_blocks_completion(db, change):
    assert supports(db, dict(GOOD, **change)) is False


@pytest.mark.parametrize("missing", ["rule_version", "spooler_job_seen", "printing_seen", "left_queue", "flags_seen", "max_pages_printed"])
def test_every_required_field_is_required(db, missing):
    e = copy.deepcopy(GOOD)
    del e[missing]
    assert supports(db, e) is False


def test_empty_and_non_object_evidence_refused(db):
    assert supports(db, {}) is False
    assert db.one("SELECT ap.evidence_supports_completion(NULL)") is False
    assert db.one("SELECT ap.evidence_supports_completion('[]'::jsonb)") is False


def test_full_lifecycle_to_completed_closes_the_order(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    assert db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)["result"] == "ok"
    r = db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "completed", GOOD)
    assert r == {"result": "ok", "job_status": "completed"}
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "completed"
    assert db.one("SELECT status FROM ap.orders WHERE id=%s", (order["order_id"],)) == "closed"
    assert db.one("SELECT evidence->>'rule_version' FROM ap.print_attempts WHERE id=%s", (c["attempt_id"],)) == "1"


def test_cancelled_at_spooler_cannot_be_reported_completed(shop, db):
    order, job_id, device = approved_job(shop, db)
    c = claim(db, device)
    db.call("mark_sent", c["attempt_id"], c["attempt_token"], device)
    cancelled = dict(GOOD, flags_seen=["SPOOLING", "DELETING"], max_pages_printed=0)
    assert db.call("report_outcome", c["attempt_id"], c["attempt_token"], device, "completed", cancelled)["result"] == "evidence_insufficient"
    assert db.one("SELECT status FROM ap.jobs WHERE id=%s", (job_id,)) == "printing"
