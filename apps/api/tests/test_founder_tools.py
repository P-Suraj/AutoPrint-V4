"""Founder tools: the pilot metrics report, the all-shops list, switching a shop on and off, renaming, showing prices.
Everything runs through the real API and a real database, the way scripts/ap_remote.py and scripts/ap_report.py use it."""
import dataclasses
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import pdfs
from app.main import create_app
from app.pricing import validate_rules
from conftest import Flow
from test_agent_api import GOOD, Agent

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ap_remote  # noqa: E402
import ap_report  # noqa: E402

TOKEN = {"X-Maintenance-Token": "m" * 40}


@pytest.fixture
def admin(settings):
    # its own signing key, so these tests do not use up the per-address order limit the other test files share
    with TestClient(create_app(dataclasses.replace(settings, maintenance_token="m" * 40, signing_key="f" * 40))) as c:
        yield c


@pytest.fixture
def scripts(admin, monkeypatch):
    """Point both founder scripts at the test application instead of the live site."""
    for mod in (ap_remote, ap_report):
        monkeypatch.setattr(mod, "HTTP", admin)
        monkeypatch.setattr(mod, "BASE", "")
        monkeypatch.setattr(mod, "token", lambda: "m" * 40)
    return admin


def send(client, shop, name="my-passport-scan.pdf"):
    """One customer order with one document, submitted. Returns (flow, job_id)."""
    f = Flow(client, shop)
    f.create_order()
    doc = f.upload(pdfs.blank(2), name=name)
    assert f.finalize(doc).status_code == 200
    q = f.quote([{"document_id": doc, "options": {}}]).json()
    return f, f.submit(q["quote_id"]).json()["job_ids"][0]


def print_it(agent, job, outcome="completed"):
    """approve (if still waiting) -> claim -> sent -> outcome. Returns the claim."""
    agent.post(f"/jobs/{job}/approve")
    c = agent.post("/claim").json()
    assert c["status"] == "claimed" and c["job_id"] == job, c
    assert agent.post(f"/attempts/{c['attempt_id']}/sent", json={"attempt_token": c["attempt_token"]}).status_code == 200
    r = agent.post(f"/attempts/{c['attempt_id']}/outcome",
                   json={"attempt_token": c["attempt_token"], "outcome": outcome, "evidence": GOOD if outcome == "completed" else {}})
    assert r.status_code == 200, r.text
    return c


def report(admin, shop, **params):
    r = admin.get(f"/v1/internal/report/{shop.code}", headers=TOKEN, params=params)
    assert r.status_code == 200, r.text
    return r


# ------------------------------------------------------------------ pilot metrics
def test_pilot_metrics_come_from_the_job_tables_and_the_events_table(admin, shop, raw_db):
    agent = Agent(admin, shop, raw_db)
    _, clean = send(admin, shop)
    print_it(agent, clean)                                                   # printed first try, nobody stepped in
    _, shaky = send(admin, shop)
    first = print_it(agent, shaky, outcome="uncertain")                      # the app could not confirm it
    assert agent.post(f"/jobs/{shaky}/resolve", json={"resolution": "retry"}).status_code == 200   # shopkeeper: Print again
    print_it(agent, shaky)
    _, refused = send(admin, shop)
    assert agent.post(f"/jobs/{refused}/reject", json={}).status_code == 200
    gone, _ = send(admin, shop)
    assert gone.cancel().status_code == 200
    Flow(admin, shop).create_order()                                         # a customer who opened the page and left

    assert admin.get(f"/v1/internal/report/{shop.code}").status_code == 401
    r = report(admin, shop)
    d = r.json()
    assert d["counts"] == {"completed": 2, "rejected": 1, "cancelled": 1} and d["attention"] == 0
    assert d["orders"]["started"] == 5 and d["orders"]["never_sent"] == 1 and d["orders"]["sent_to_shop"] == 4
    o = d["outcomes"]
    assert (o["jobs_sent_to_shop"], o["jobs_that_reached_the_printer_step"], o["sent_to_printer"]) == (4, 2, 2)
    assert (o["sent_to_printer_first_try_no_help"], o["went_to_needs_attention"]) == (1, 1)
    assert (o["rejected"], o["cancelled"], o["expired"], o["still_open"]) == (1, 1, 0, 0)
    assert (o["success_rate"], o["first_try_no_help_rate"], o["needs_attention_rate"]) == (1.0, 0.5, 0.5)
    assert d["human_actions"] == {"jobs_resolved_by_hand": 1, "said_it_printed": 0, "said_it_did_not_print": 0, "print_again": 1}
    assert d["duplicates"] == {"jobs_with_more_than_one_attempt": 1, "jobs_handed_to_windows_printing_more_than_once": 1,
                               "jobs_where_two_attempts_ended_as_printed": 0, "attempts_without_a_human_print_again": 0,
                               "late_conflicting_reports": 0}

    steps = {t["step"]: t for t in d["timings"]}
    assert steps["order_created_to_submitted"]["jobs"] == 4 and steps["file_upload_and_check"]["jobs"] == 4
    assert steps["shopkeeper_response"]["jobs"] == 3 and steps["submitted_to_approved"]["jobs"] == 2     # 2 approved + 1 rejected
    assert steps["claimed_to_sent_to_spooler"]["jobs"] == 3 and steps["sent_to_spooler_to_outcome"]["jobs"] == 3   # per attempt
    assert steps["customer_wait_to_sent_to_printer"]["jobs"] == 2 and steps["customer_wait_to_any_final_state"]["jobs"] == 4
    for t in d["timings"]:
        assert 0 <= t["median_seconds"] <= t["p90_seconds"] <= t["longest_seconds"] < 120, t
    assert sum(h["jobs"] for h in d["busiest_hours"]) == 4 and sum(day["jobs"] for day in d["days"]) == 4
    assert len(d["jobs"]) == 4 and d["devices"][0]["online"] is True

    # nothing that names a document or a file leaves the server
    for forbidden in ("my-passport-scan", "file_name", "object_key", "orders/", "document_name"):
        assert forbidden not in r.text, forbidden

    # the duplicate signs react to what a duplicate would look like in the data
    late = agent.post(f"/attempts/{first['attempt_id']}/outcome",
                      json={"attempt_token": first["attempt_token"], "outcome": "completed", "evidence": GOOD})
    assert late.status_code == 409                                           # refused, but recorded as a late report
    raw_db.run("UPDATE ap.jobs SET attempt_count = 2 WHERE id = %s", (clean,))    # an attempt with no 'Print again' behind it
    dup = report(admin, shop).json()["duplicates"]
    assert dup["jobs_where_two_attempts_ended_as_printed"] == 1 and dup["late_conflicting_reports"] == 1
    assert dup["attempts_without_a_human_print_again"] == 1

    # the window: nothing in the last hour once the rows are a day old; days=2 sees them again
    raw_db.run("UPDATE ap.jobs SET created_at = created_at - interval '26 hours' WHERE shop_id = %s", (shop.id,))
    raw_db.run("UPDATE ap.orders SET created_at = created_at - interval '26 hours' WHERE shop_id = %s", (shop.id,))
    assert report(admin, shop).json()["outcomes"]["jobs_sent_to_shop"] == 0
    assert report(admin, shop, days=2).json()["outcomes"]["jobs_sent_to_shop"] == 4
    empty = report(admin, shop, hours=1).json()
    assert empty["outcomes"]["success_rate"] is None and empty["counts"] == {}
    assert report(admin, shop, days=100000).json()["window_hours"] == 90 * 24          # capped at 90 days
    assert admin.get(f"/v1/internal/report/{shop.code}", headers=TOKEN, params={"tz": "Not/AZone"}).status_code == 422
    assert admin.get(f"/v1/internal/report/{shop.code}", headers=TOKEN, params={"tz": "x'; DROP"}).status_code == 422
    assert admin.get("/v1/internal/report/NOP000", headers=TOKEN).status_code == 404


def test_job_and_event_rows_outlive_the_file_cleanup_so_metrics_do_not_vanish(admin, shop, raw_db, settings, api_db_url):
    """Retention deletes the stored files and marks the document rows; it never deletes order, job or event rows."""
    from app.db import Database
    from app.main import make_storage, run_maintenance_once
    agent = Agent(admin, shop, raw_db)
    _, job = send(admin, shop)
    print_it(agent, job)
    before = raw_db.one("SELECT count(*) FROM ap.events WHERE shop_id = %s", (shop.id,))
    raw_db.run("UPDATE ap.documents SET delete_after = now() - interval '1 second' WHERE order_id IN (SELECT id FROM ap.orders WHERE shop_id = %s)", (shop.id,))
    db = Database(api_db_url)
    try:
        assert run_maintenance_once(db, make_storage(settings))["documents_deleted"] >= 1
    finally:
        db.close()
    assert raw_db.one("SELECT count(*) FROM ap.documents d JOIN ap.orders o ON o.id = d.order_id WHERE o.shop_id = %s AND d.deleted_at IS NULL", (shop.id,)) == 0
    assert raw_db.one("SELECT count(*) FROM ap.events WHERE shop_id = %s", (shop.id,)) == before
    d = report(admin, shop).json()
    assert d["outcomes"]["sent_to_printer"] == 1 and d["outcomes"]["success_rate"] == 1.0
    assert {t["step"] for t in d["timings"]} >= {"submitted_to_approved", "sent_to_spooler_to_outcome"}


def test_time_a_shop_computer_was_away_is_reported_from_recorded_gaps_only(admin, shop, raw_db):
    agent = Agent(admin, shop, raw_db)
    assert agent.poll().status_code == 200
    d = report(admin, shop).json()
    assert d["offline_tracking"]["available"] is True
    assert d["devices"][0]["offline"]["gaps_ended"] == 0 and d["devices"][0]["offline"]["away_now_seconds"] is None

    raw_db.run("UPDATE ap.devices SET last_seen_at = now() - interval '10 minutes' WHERE id = %s", (agent.id,))
    away = report(admin, shop).json()["devices"][0]
    assert away["online"] is False and 595 <= away["offline"]["away_now_seconds"] <= 610      # the gap is still open
    assert agent.poll().status_code == 200                                                    # the computer comes back
    assert agent.poll().status_code == 200
    back = report(admin, shop).json()["devices"][0]
    assert back["online"] is True and back["offline"]["gaps_ended"] == 1 and back["offline"]["away_now_seconds"] is None
    assert 595 <= back["offline"]["seconds_in_ended_gaps"] <= 610 and back["offline"]["longest_ended_gap_seconds"] >= 595

    # a gap that began before the window only counts from the start of the window
    raw_db.run("UPDATE ap.devices SET last_seen_at = now() - interval '3 hours' WHERE id = %s", (agent.id,))
    assert agent.poll().status_code == 200
    one_hour = report(admin, shop, hours=1).json()["devices"][0]["offline"]
    assert one_hour["gaps_ended"] == 2 and 3595 + 595 <= one_hour["seconds_in_ended_gaps"] <= 3600 + 610


# ------------------------------------------------------------------ the founder scripts, end to end
def test_shop_can_be_switched_off_and_on_renamed_and_listed(scripts, shop, raw_db, capsys):
    agent = Agent(scripts, shop, raw_db)
    _, waiting = send(scripts, shop)
    key = scripts.post("/v1/internal/shop-login", headers=TOKEN, json={"shop_code": shop.code}).json()["key"]

    assert ap_remote.main(["shop-off", shop.code.lower()]) == 0
    assert "switched off." in capsys.readouterr().out
    assert scripts.get(f"/v1/shops/{shop.code}").json()["accepting_orders"] is False
    assert scripts.post(f"/v1/shops/{shop.code}/orders").status_code == 404           # no new order can be started
    assert scripts.get("/v1/shop/me", headers={"X-Shop-Key": key}).status_code == 401  # the dashboard link is paused
    assert agent.post(f"/jobs/{waiting}/approve").status_code == 200                   # what was already sent still prints
    assert agent.post("/claim").json()["status"] == "claimed"
    assert ap_remote.main(["shop-off", shop.code]) == 0 and "(it already was)" in capsys.readouterr().out

    assert ap_remote.main(["shops"]) == 0
    line = next(l for l in capsys.readouterr().out.splitlines() if l.startswith(shop.code))
    assert " OFF " in line and "online" in line

    assert ap_remote.main(["shop-on", shop.code]) == 0 and "is taking orders." in capsys.readouterr().out
    assert scripts.get(f"/v1/shops/{shop.code}").json()["accepting_orders"] is True
    assert scripts.get("/v1/shop/me", headers={"X-Shop-Key": key}).status_code == 200

    assert ap_remote.main(["rename", shop.code, "  Sri Lakshmi Xerox  "]) == 0
    assert "Sri Lakshmi Xerox" in capsys.readouterr().out
    assert scripts.get(f"/v1/shops/{shop.code}").json()["name"] == "Sri Lakshmi Xerox"

    # every change is in the events table, without the name
    events = raw_db.rows("SELECT data FROM ap.events WHERE shop_id = %s AND type = 'shop.updated' ORDER BY id", (shop.id,))
    assert [e[0]["is_active"] for e in events] == [False, True, True] and events[2][0]["renamed"] is True
    assert "Lakshmi" not in json.dumps([e[0] for e in events])

    # refusals
    for body, status in [({"code": "NOP000", "is_active": False}, 404), ({"code": shop.code}, 422),
                         ({"code": shop.code, "is_active": "no"}, 422), ({"code": shop.code, "name": "   "}, 422),
                         ({"code": shop.code, "name": "x" * 81}, 422)]:
        assert scripts.post("/v1/internal/shop-update", headers=TOKEN, json=body).status_code == status, body
    assert scripts.post("/v1/internal/shop-update", json={"code": shop.code, "is_active": False}).status_code == 401
    assert scripts.get("/v1/internal/shops").status_code == 401
    assert scripts.get(f"/v1/internal/shop/{shop.code}/rates").status_code == 401
    with pytest.raises(SystemExit):
        ap_remote.main(["shop-off", "NOP000"])


def test_prices_are_shown_in_rupees_and_the_example_file_cannot_be_published(scripts, shop, raw_db, capsys):
    assert ap_remote.main(["prices", shop.code]) == 0
    out = capsys.readouterr().out
    assert "Price list version 1" in out and "Rs 2 per side" in out and "Rs 1.20 per side" in out and "Colour" in out

    example = SCRIPTS / "rates.example.json"
    validate_rules(json.loads(example.read_text(encoding="utf-8")))            # the shape the API accepts
    with pytest.raises(SystemExit) as refused:
        ap_remote.main(["set-rates", shop.code, "--rates", str(example)])
    assert "placeholder" in str(refused.value)
    assert raw_db.one("SELECT count(*) FROM ap.rate_cards WHERE shop_id = %s", (shop.id,)) == 1       # nothing was published

    raw_db.run("UPDATE ap.rate_cards SET retired_at = now() WHERE shop_id = %s", (shop.id,))
    assert scripts.get(f"/v1/internal/shop/{shop.code}/rates", headers=TOKEN).status_code == 409      # no prices set
    assert scripts.get("/v1/internal/shop/NOP000/rates", headers=TOKEN).status_code == 404


def test_daily_report_and_all_shops_list_read_well_and_name_no_document(scripts, shop, raw_db, capsys):
    agent = Agent(scripts, shop, raw_db)
    _, job = send(scripts, shop)
    print_it(agent, job, outcome="uncertain")
    assert ap_report.main([shop.code]) == 0
    out = capsys.readouterr().out
    assert "NEEDS A LOOK NOW: 1 job needs the shopkeeper to say what happened. Phone the shop." in out
    assert "needs-attention rate" in out and "100%  (1 of 1)" in out and "ONLINE" in out
    assert "HOW LONG THINGS TOOK" in out and "WHAT THIS REPORT CANNOT SHOW" in out
    assert "my-passport-scan" not in out and "m" * 40 not in out

    assert ap_report.main(["--all"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("CODE")
    mine = next(l for l in lines if l.startswith(shop.code))
    assert " on " in mine and "online" in mine and "1 need attention" in mine

    row = next(s for s in scripts.get("/v1/internal/shops", headers=TOKEN).json()["shops"] if s["code"] == shop.code)
    assert (row["jobs_today"], row["needs_attention"], row["computers"], row["rate_card_version"]) == (1, 1, 1, 1)
