"""Founder reports: pilot metrics for one shop, and a one-line status for every shop.

Everything is computed in SQL from the real tables and ap.events. Plain SELECTs only: they take no row locks and
use the (shop_id, time) indexes, so the shop poll and the customer pages are not slowed while a report runs.

Privacy: no document names, no file keys, no customer text (a shopkeeper's reject reason or note is free text and
is left out). Order short codes are the only per-order detail, and only in the short "recent jobs" list.

What cannot be shown, and why (also returned to the caller in "cannot_show"):
  * when a single job expired or was cancelled is taken from jobs.updated_at; there is no per-job event for it
  * why a computer was away (PC off, asleep, no internet, shop closed) is not recorded anywhere
  * time a computer was away before migration 0011 was applied was never recorded; only last_seen_at existed
  * whether paper really came out twice: the database only knows what the shop app and the shopkeeper reported
"""
from __future__ import annotations

from typing import Any, Optional

from app.db import Database

OFFLINE_GAP_SECONDS = 120          # must match ap.touch_device (migration 0011)
MAX_WINDOW_HOURS = 24 * 90

# One shop's jobs created inside the window, the events of those jobs, and their print attempts.
_JOBS = """
WITH j AS (
  SELECT j.id, j.status::text AS status, j.attempt_count, j.created_at, j.updated_at, o.submitted_at
    FROM ap.jobs j JOIN ap.orders o ON o.id = j.order_id
   WHERE j.shop_id = %(shop)s AND j.created_at > %(start)s),
ev AS (
  SELECT e.job_id,
         min(e.at) FILTER (WHERE e.type = 'job.approved') AS first_approved,
         min(e.at) FILTER (WHERE e.type IN ('job.approved', 'job.rejected')) AS first_decision,
         min(e.at) FILTER (WHERE e.type = 'job.claimed') AS first_claimed,
         count(*) FILTER (WHERE e.type IN ('attempt.uncertain', 'attempt.lease_expired')) AS uncertain,
         count(*) FILTER (WHERE e.type = 'attempt.late_report') AS late_reports,
         count(*) FILTER (WHERE e.type = 'job.resolved') AS resolutions,
         count(*) FILTER (WHERE e.type = 'job.resolved' AND e.data->>'resolution' = 'retry') AS retries,
         count(*) FILTER (WHERE e.type = 'job.resolved' AND e.data->>'resolution' = 'completed') AS said_printed,
         count(*) FILTER (WHERE e.type = 'job.resolved' AND e.data->>'resolution' = 'failed') AS said_not_printed,
         count(DISTINCT e.attempt_id) FILTER (WHERE e.type = 'attempt.completed'
                 OR (e.type = 'attempt.late_report' AND e.data->>'reported' = 'completed')
                 OR (e.type = 'job.resolved' AND e.data->>'resolution' = 'completed')) AS attempts_ended_as_printed
    FROM ap.events e
   WHERE e.shop_id = %(shop)s AND e.at > %(start)s AND e.job_id IS NOT NULL
   GROUP BY e.job_id),
att AS (
  SELECT a.job_id, count(*) FILTER (WHERE a.sent_at IS NOT NULL) AS reached_spooler
    FROM ap.print_attempts a JOIN j ON j.id = a.job_id GROUP BY a.job_id)
"""

_SUMMARY = _JOBS + """
SELECT count(*),
       count(*) FILTER (WHERE j.attempt_count >= 1),
       count(*) FILTER (WHERE j.status = 'completed'),
       count(*) FILTER (WHERE j.status = 'completed' AND j.attempt_count = 1 AND COALESCE(ev.resolutions, 0) = 0),
       count(*) FILTER (WHERE COALESCE(ev.uncertain, 0) > 0),
       count(*) FILTER (WHERE j.attempt_count > 1),
       count(*) FILTER (WHERE COALESCE(att.reached_spooler, 0) > 1),
       count(*) FILTER (WHERE COALESCE(ev.attempts_ended_as_printed, 0) > 1),
       count(*) FILTER (WHERE j.attempt_count > 1 + COALESCE(ev.retries, 0)),
       count(*) FILTER (WHERE COALESCE(ev.resolutions, 0) > 0),
       COALESCE(sum(ev.said_printed), 0)::int, COALESCE(sum(ev.said_not_printed), 0)::int, COALESCE(sum(ev.retries), 0)::int,
       COALESCE(sum(ev.late_reports), 0)::int
  FROM j LEFT JOIN ev ON ev.job_id = j.id LEFT JOIN att ON att.job_id = j.id
"""

_TIMINGS = _JOBS + """,
o AS (
  SELECT o.id, o.created_at, o.submitted_at FROM ap.orders o WHERE o.shop_id = %(shop)s AND o.created_at > %(start)s),
oe AS (
  SELECT e.order_id, min(e.at) FILTER (WHERE e.type = 'document.validated') AS uploaded,
         min(e.at) FILTER (WHERE e.type = 'quote.created') AS priced
    FROM ap.events e
   WHERE e.shop_id = %(shop)s AND e.at > %(start)s AND e.type IN ('document.validated', 'quote.created')
   GROUP BY e.order_id),
docs AS (
  SELECT r.at AS registered, v.at AS validated
    FROM ap.events r JOIN ap.events v ON v.order_id = r.order_id AND v.type = 'document.validated'
                                     AND v.data->>'document_id' = r.data->>'document_id'
   WHERE r.shop_id = %(shop)s AND r.at > %(start)s AND r.type = 'document.registered'),
d (step, secs) AS (
            SELECT 'order_created_to_file_uploaded', EXTRACT(EPOCH FROM oe.uploaded - o.created_at) FROM o JOIN oe ON oe.order_id = o.id
  UNION ALL SELECT 'file_upload_and_check', EXTRACT(EPOCH FROM validated - registered) FROM docs
  UNION ALL SELECT 'file_uploaded_to_first_price', EXTRACT(EPOCH FROM oe.priced - oe.uploaded) FROM oe
  UNION ALL SELECT 'first_price_to_submitted', EXTRACT(EPOCH FROM o.submitted_at - oe.priced) FROM o JOIN oe ON oe.order_id = o.id
  UNION ALL SELECT 'order_created_to_submitted', EXTRACT(EPOCH FROM o.submitted_at - o.created_at) FROM o
  UNION ALL SELECT 'submitted_to_approved', EXTRACT(EPOCH FROM ev.first_approved - j.submitted_at) FROM j JOIN ev ON ev.job_id = j.id
  UNION ALL SELECT 'shopkeeper_response', EXTRACT(EPOCH FROM ev.first_decision - j.submitted_at) FROM j JOIN ev ON ev.job_id = j.id
  UNION ALL SELECT 'approved_to_claimed', EXTRACT(EPOCH FROM ev.first_claimed - ev.first_approved) FROM ev JOIN j ON j.id = ev.job_id
  UNION ALL SELECT 'claimed_to_sent_to_spooler', EXTRACT(EPOCH FROM a.sent_at - a.created_at) FROM ap.print_attempts a JOIN j ON j.id = a.job_id
  UNION ALL SELECT 'sent_to_spooler_to_outcome', EXTRACT(EPOCH FROM a.finished_at - a.sent_at)
              FROM ap.print_attempts a JOIN j ON j.id = a.job_id WHERE a.evidence->>'reason' IS DISTINCT FROM 'lease_expired'
  UNION ALL SELECT 'customer_wait_to_sent_to_printer', EXTRACT(EPOCH FROM j.updated_at - j.submitted_at) FROM j WHERE j.status = 'completed'
  UNION ALL SELECT 'customer_wait_to_any_final_state', EXTRACT(EPOCH FROM j.updated_at - j.submitted_at)
              FROM j WHERE j.status IN ('completed', 'failed', 'rejected', 'cancelled', 'expired'))
SELECT step, count(*),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY secs), percentile_cont(0.9) WITHIN GROUP (ORDER BY secs), max(secs)
  FROM d WHERE secs IS NOT NULL AND secs >= 0 GROUP BY step
"""

# The order the steps are shown in, with the words a non-developer reads.
STEPS = [
    ("order_created_to_file_uploaded", "Customer: page opened to file uploaded"),
    ("file_upload_and_check", "Customer: one file, upload and check"),
    ("file_uploaded_to_first_price", "Customer: file uploaded to first price shown"),
    ("first_price_to_submitted", "Customer: first price shown to order sent"),
    ("order_created_to_submitted", "Customer: page opened to order sent (whole)"),
    ("submitted_to_approved", "Shop: order sent to approved"),
    ("shopkeeper_response", "Shop: order sent to approve or reject (response time)"),
    ("approved_to_claimed", "App: approved to picked up by the shop computer"),
    ("claimed_to_sent_to_spooler", "App: picked up to handed to Windows printing"),
    ("sent_to_spooler_to_outcome", "Printer: handed to Windows to result reported"),
    ("customer_wait_to_sent_to_printer", "Customer wait: order sent to 'Sent to printer'"),
    ("customer_wait_to_any_final_state", "Customer wait: order sent to any final answer"),
]

CANNOT_SHOW = [
    "When one job expired or was cancelled comes from the job's last change time; there is no separate event for it.",
    "Why a computer was away (PC off, asleep, no internet, shop closed) is not recorded.",
    "Whether paper really came out twice. The duplicate signs below are what the shop app and the shopkeeper reported.",
    "Reject reasons and shopkeeper notes are left out on purpose: they are free text and may name a customer or a document.",
]


def _rate(part: int, whole: int) -> Optional[float]:
    return round(part / whole, 4) if whole else None


def _round(v: Any) -> Optional[float]:
    return None if v is None else round(float(v), 1)


def offline_tracking(db: Database) -> Optional[Any]:
    """When offline gaps started being recorded (migration 0011), or None when that migration is not applied."""
    if not db.one("SELECT to_regprocedure('ap.touch_device(uuid,text)') IS NOT NULL")[0]:
        return None
    return db.one("SELECT offline_tracked_since FROM ap.system_state")[0]


def shop_report(db: Database, shop_code: str, hours: int, tz: str, online_seconds: int) -> Optional[dict]:
    hours = max(1, min(hours, MAX_WINDOW_HOURS))
    head = db.one("SELECT s.id, s.code, s.name, s.is_active, now(), now() - make_interval(hours => %s), "
                  "(SELECT min(created_at) FROM ap.jobs WHERE shop_id = s.id) FROM ap.shops s WHERE s.code = %s", (hours, shop_code))
    if head is None:
        return None
    shop_id, code, name, is_active, now, start, first_job_at = head
    p = {"shop": shop_id, "start": start, "tz": tz, "online": online_seconds}

    counts = dict(db.rows("SELECT status::text, count(*) FROM ap.jobs WHERE shop_id = %(shop)s AND created_at > %(start)s GROUP BY 1", p))
    orders = db.rows("SELECT status::text, submitted_at IS NOT NULL, count(*) FROM ap.orders "
                     "WHERE shop_id = %(shop)s AND created_at > %(start)s GROUP BY 1, 2", p)
    (submitted, attempted, completed, unaided, went_attention, retried, spooler_twice, printed_twice, unexplained,
     resolved_by_hand, said_printed, said_not_printed, said_retry, late_reports) = db.one(_SUMMARY, p)
    timing_rows = {r[0]: r for r in db.rows(_TIMINGS, p)}
    hours_busy = db.rows("SELECT EXTRACT(HOUR FROM created_at AT TIME ZONE %(tz)s)::int, count(*) FROM ap.jobs "
                         "WHERE shop_id = %(shop)s AND created_at > %(start)s GROUP BY 1 ORDER BY 2 DESC, 1", p)
    days = db.rows("SELECT (created_at AT TIME ZONE %(tz)s)::date, count(*), count(*) FILTER (WHERE status = 'completed'), "
                   "count(*) FILTER (WHERE status IN ('needs_attention', 'failed')) FROM ap.jobs "
                   "WHERE shop_id = %(shop)s AND created_at > %(start)s GROUP BY 1 ORDER BY 1", p)
    recent = db.rows("SELECT o.short_code, j.status::text, j.attempt_count, j.created_at, "
                     "EXTRACT(EPOCH FROM (j.updated_at - j.created_at))::int "
                     "FROM ap.jobs j JOIN ap.orders o ON o.id = j.order_id "
                     "WHERE j.shop_id = %(shop)s AND j.created_at > %(start)s ORDER BY j.created_at DESC LIMIT 50", p)

    tracked_since = offline_tracking(db)
    devices = db.rows(
        "SELECT d.id, d.display_name, d.status::text, d.last_seen_at, d.agent_version, d.created_at, "
        "       (d.status = 'active' AND d.last_seen_at > now() - make_interval(secs => %(online)s)), "
        "       g.gaps, g.seconds, g.longest "
        "  FROM ap.devices d LEFT JOIN LATERAL ("
        "       SELECT count(*) AS gaps, "
        "              sum(least((e.data->>'offline_seconds')::numeric, EXTRACT(EPOCH FROM e.at - %(start)s))) AS seconds, "
        "              max(least((e.data->>'offline_seconds')::numeric, EXTRACT(EPOCH FROM e.at - %(start)s))) AS longest "
        "         FROM ap.events e WHERE e.shop_id = d.shop_id AND e.at > %(start)s AND e.type = 'device.back_online' AND e.actor_id = d.id"
        "       ) g ON true "
        " WHERE d.shop_id = %(shop)s ORDER BY d.created_at DESC LIMIT 20", p)

    def device_row(d: tuple) -> dict:
        _, dname, status, seen, version, paired, online, gaps, seconds, longest = d
        row = {"name": dname, "status": status, "last_seen_at": seen, "agent_version": version, "paired_at": paired,
               "online": bool(online)}
        if tracked_since is None:
            row["offline"] = None                      # never recorded: only last_seen_at exists
            return row
        away_now = None
        if status == "active" and seen is not None and (now - seen).total_seconds() > OFFLINE_GAP_SECONDS:
            away_now = int((now - max(seen, start)).total_seconds())      # a gap that is still open has no event yet
        row["offline"] = {"recorded_from": max(start, tracked_since, paired), "gaps_ended": int(gaps or 0),
                          "seconds_in_ended_gaps": int(seconds or 0), "longest_ended_gap_seconds": int(longest or 0),
                          "away_now_seconds": away_now}
        return row

    started = sum(r[2] for r in orders)
    never_sent = sum(r[2] for r in orders if not r[1])
    return {
        "shop": {"code": code, "name": name, "is_active": is_active},
        "window_hours": hours, "window_start": start, "generated_at": now, "timezone": tz, "first_job_at": first_job_at,
        # jobs created in the window, by the state they are in now
        "counts": counts,
        "attention": counts.get("needs_attention", 0) + counts.get("failed", 0),
        "orders": {"started": started, "sent_to_shop": started - never_sent, "never_sent": never_sent,
                   "by_status": {s: sum(r[2] for r in orders if r[0] == s) for s in sorted({r[0] for r in orders})}},
        "outcomes": {
            "jobs_sent_to_shop": submitted, "jobs_that_reached_the_printer_step": attempted,
            "sent_to_printer": completed, "sent_to_printer_first_try_no_help": unaided,
            "went_to_needs_attention": went_attention,
            "rejected": counts.get("rejected", 0), "cancelled": counts.get("cancelled", 0), "expired": counts.get("expired", 0),
            "failed_now": counts.get("failed", 0), "needs_attention_now": counts.get("needs_attention", 0),
            "still_open": sum(counts.get(s, 0) for s in ("awaiting_approval", "approved", "printing")),
            # denominators are jobs that reached the printer step (were claimed at least once)
            "success_rate": _rate(completed, attempted), "first_try_no_help_rate": _rate(unaided, attempted),
            "needs_attention_rate": _rate(went_attention, attempted),
        },
        "human_actions": {"jobs_resolved_by_hand": resolved_by_hand, "said_it_printed": said_printed,
                          "said_it_did_not_print": said_not_printed, "print_again": said_retry},
        "duplicates": {
            "jobs_with_more_than_one_attempt": retried,
            "jobs_handed_to_windows_printing_more_than_once": spooler_twice,
            "jobs_where_two_attempts_ended_as_printed": printed_twice,
            "attempts_without_a_human_print_again": unexplained,      # must be 0: a second attempt is never automatic
            "late_conflicting_reports": late_reports,
        },
        "timings": [{"step": key, "label": label, "jobs": timing_rows[key][1], "median_seconds": _round(timing_rows[key][2]),
                     "p90_seconds": _round(timing_rows[key][3]), "longest_seconds": _round(timing_rows[key][4])}
                    for key, label in STEPS if key in timing_rows],
        "busiest_hours": [{"hour": h, "jobs": n} for h, n in hours_busy],
        "days": [{"date": str(d), "jobs": n, "sent_to_printer": c, "failed_or_needs_attention": a} for d, n, c, a in days],
        "jobs": [{"order": r[0], "status": r[1], "attempts": r[2], "created_at": r[3], "seconds_to_final_state": r[4]} for r in recent],
        "devices": [device_row(d) for d in devices],
        "offline_tracking": {
            "available": tracked_since is not None, "since": tracked_since,
            "note": ("Time away is recorded from the date shown, when a computer comes back after more than "
                     f"{OFFLINE_GAP_SECONDS} seconds of silence. Before that date only the last check-in was kept.")
                    if tracked_since is not None else
                    "Not recorded: the database only keeps each computer's last check-in time (migration 0011 adds this).",
        },
        "cannot_show": CANNOT_SHOW,
    }


def shops_overview(db: Database, tz: str, online_seconds: int) -> list[dict]:
    """Every shop in one row each. One statement; the per-shop counts use the (shop_id, ...) indexes."""
    rows = db.rows(
        "SELECT s.code, s.name, s.is_active, s.created_at, "
        "       (SELECT count(*) FROM ap.devices d WHERE d.shop_id = s.id AND d.status = 'active'), "
        "       (SELECT max(d.last_seen_at) FROM ap.devices d WHERE d.shop_id = s.id AND d.status = 'active'), "
        "       (SELECT r.version FROM ap.rate_cards r WHERE r.shop_id = s.id AND r.retired_at IS NULL), "
        "       (SELECT count(*) FROM ap.jobs j WHERE j.shop_id = s.id "
        "           AND j.created_at >= date_trunc('day', now() AT TIME ZONE %(tz)s) AT TIME ZONE %(tz)s), "
        "       (SELECT count(*) FROM ap.jobs j WHERE j.shop_id = s.id AND j.status = 'needs_attention'), "
        "       (SELECT count(*) FROM ap.jobs j WHERE j.shop_id = s.id AND j.status = 'failed' AND j.updated_at > now() - interval '24 hours'), "
        "       (SELECT count(*) FROM ap.jobs j WHERE j.shop_id = s.id AND j.status = 'awaiting_approval'), "
        "       now() "
        "  FROM ap.shops s ORDER BY s.code", {"tz": tz})
    out = []
    for code, name, active, created, computers, seen, rate_version, today, attention, failed, waiting, now in rows:
        out.append({"code": code, "name": name, "is_active": active, "created_at": created, "computers": computers,
                    "last_seen_at": seen, "online": bool(seen and (now - seen).total_seconds() < online_seconds),
                    "rate_card_version": rate_version, "jobs_today": today, "needs_attention": attention,
                    "failed_last_24h": failed, "waiting_for_approval": waiting})
    return out
