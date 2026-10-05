"""The shop-side API against a real database: enrollment, one-call poll, approve, claim, print outcome."""
import uuid

import pytest

import pdfs
from dbtools import sha

GOOD = {"rule_version": 2, "spooler_job_seen": True, "printing_seen": True, "left_queue": True,
        "flags_seen": ["SPOOLING", "PRINTING"], "max_pages_printed": 3, "expected_pages": 3}


def err(r):
    return r.json()["error"]["code"]


class Agent:
    def __init__(self, client, shop, raw_db):
        self.c, self.shop, self.db = client, shop, raw_db
        code = uuid.uuid4().hex[:12].upper()
        assert raw_db.call("issue_enrollment_code", shop.code, sha(code), 30)["result"] == "ok"
        r = client.post("/v1/agent/enroll", json={"enrollment_code": code.lower() + " ", "display_name": "Counter PC"})
        assert r.status_code == 201, r.text
        b = r.json()
        self.id, self.secret, self.enroll_body = b["device_id"], b["device_secret"], b
        self.code = code

    @property
    def h(self):
        return {"X-Device-Id": self.id, "X-Device-Secret": self.secret}

    def poll(self, **kw):
        return self.c.get("/v1/agent/jobs", headers={**self.h, **kw})

    def post(self, path, **kw):
        return self.c.post(f"/v1/agent{path}", headers=self.h, **kw)


@pytest.fixture
def agent(client, shop, raw_db):
    return Agent(client, shop, raw_db)


def submitted(flow, pages=3, **opts):
    flow.full(pdfs.blank(pages), **opts)
    return flow.view().json()


# ------------------------------------------------------------------ enrollment
def test_enrollment_returns_a_secret_once_and_the_code_cannot_be_reused(agent, client):
    assert agent.enroll_body["shop_code"] == agent.shop.code and len(agent.secret) == 64
    again = client.post("/v1/agent/enroll", json={"enrollment_code": agent.code, "display_name": "Other PC"})
    assert again.status_code == 400 and err(again) == "invalid_enrollment_code"
    assert client.post("/v1/agent/enroll", json={"enrollment_code": "WRONGCODE123", "display_name": "x"}).status_code == 400


def test_device_secret_is_stored_only_as_a_hash(agent):
    stored = agent.db.one("SELECT credential_hash FROM ap.devices WHERE id=%s", (agent.id,))
    assert stored == sha(agent.secret) and agent.secret not in stored


# ------------------------------------------------------------------ authentication on every route
def test_every_shop_route_refuses_bad_credentials(agent, client, flow):
    v = submitted(flow)
    job = v["jobs"][0]["job_id"]
    bad = {"X-Device-Id": agent.id, "X-Device-Secret": "0" * 64}
    for method, path, body in [("get", "/v1/agent/jobs", None), ("get", f"/v1/agent/jobs/{job}/document", None),
                               ("post", f"/v1/agent/jobs/{job}/approve", None), ("post", f"/v1/agent/jobs/{job}/reject", {}),
                               ("post", f"/v1/agent/jobs/{job}/resolve", {"resolution": "failed"}),
                               ("post", "/v1/agent/claim", None)]:
        r = getattr(client, method)(path, headers=bad, **({"json": body} if body is not None else {}))
        assert r.status_code == 401 and err(r) == "unauthorized", (method, path, r.text)
    assert client.get("/v1/agent/jobs").status_code == 422                 # headers missing entirely


def test_revoked_device_is_locked_out(agent, raw_db):
    assert agent.poll().status_code == 200
    raw_db.run("UPDATE ap.devices SET status='revoked', revoked_at=now() WHERE id=%s", (agent.id,))
    assert agent.poll().status_code == 401 and agent.post("/claim").status_code == 401


# ------------------------------------------------------------------ the poll is the heartbeat, in one call
def test_poll_lists_the_queue_and_marks_the_shop_online(agent, client, flow):
    assert client.get(f"/v1/shops/{agent.shop.code}").json()["agent_online"] is False
    empty = agent.poll(**{"X-Agent-Version": "4.0.0-test"})
    assert empty.status_code == 200 and empty.json()["jobs"] == [] and empty.json()["shop_code"] == agent.shop.code
    assert client.get(f"/v1/shops/{agent.shop.code}").json()["agent_online"] is True
    assert agent.db.one("SELECT agent_version FROM ap.devices WHERE id=%s", (agent.id,)) == "4.0.0-test"

    v = submitted(flow, pages=3, copies=2, color=True)
    jobs = agent.poll().json()["jobs"]
    assert len(jobs) == 1
    j = jobs[0]
    assert j["order_short_code"] == v["short_code"] and j["status"] == "awaiting_approval"
    assert (j["page_count"], j["copies"], j["color"], j["duplex"], j["amount_paise"]) == (3, 2, True, False, 6000)
    assert j["approval_expires_at"] is not None


def test_a_shop_only_sees_its_own_jobs(agent, client, flow, make_shop_agent):
    submitted(flow)
    other = make_shop_agent()
    assert other.poll().json()["jobs"] == []
    assert len(agent.poll().json()["jobs"]) == 1


@pytest.fixture
def make_shop_agent(client, raw_db):
    from dbtools import Shop
    from sample_data import RULES
    import json

    def make():
        s = Shop(raw_db)
        raw_db.run("UPDATE ap.rate_cards SET rules=%s::jsonb WHERE shop_id=%s", (json.dumps(RULES), s.id))
        return Agent(client, s, raw_db)
    return make


# ------------------------------------------------------------------ approve, claim, print, report
def test_full_shop_flow_to_sent_to_printer(agent, flow, client):
    v = submitted(flow)
    job = v["jobs"][0]["job_id"]
    assert agent.post(f"/jobs/{job}/approve").json() == {"job_id": job, "status": "approved"}
    assert flow.view().json()["jobs"][0]["customer_message"] == "Approved. Waiting for the printer."

    doc = agent.c.get(f"/v1/agent/jobs/{job}/document", headers=agent.h)
    assert doc.status_code == 200 and doc.json()["byte_size"] > 0 and len(doc.json()["sha256"]) == 64

    c = agent.post("/claim").json()
    assert c["status"] == "claimed" and c["spooler_job_name"].startswith("apjob_") and c["options"]["copies"] == 1
    assert c["document"]["download_url"].startswith("http") and len(c["attempt_token"]) == 64
    busy = agent.post("/claim")                                   # one print at a time per device
    assert busy.status_code == 409 and err(busy) == "device_busy"

    aid, tok = c["attempt_id"], c["attempt_token"]
    assert agent.post(f"/attempts/{aid}/renew", json={"attempt_token": tok, "lease_seconds": 600}).status_code == 200
    assert agent.post(f"/attempts/{aid}/sent", json={"attempt_token": tok}).json() == {"status": "ok"}
    assert flow.view().json()["jobs"][0]["customer_message"] == "Sending to the printer."

    r = agent.post(f"/attempts/{aid}/outcome", json={"attempt_token": tok, "outcome": "completed", "evidence": GOOD})
    assert r.status_code == 200 and r.json() == {"job_status": "completed"}
    v2 = flow.view().json()
    assert v2["status"] == "closed" and v2["jobs"][0]["customer_message"] == "Sent to printer."


def test_completed_without_evidence_is_refused(agent, flow):
    job = submitted(flow)["jobs"][0]["job_id"]
    agent.post(f"/jobs/{job}/approve")
    c = agent.post("/claim").json()
    agent.post(f"/attempts/{c['attempt_id']}/sent", json={"attempt_token": c["attempt_token"]})
    r = agent.post(f"/attempts/{c['attempt_id']}/outcome", json={"attempt_token": c["attempt_token"], "outcome": "completed", "evidence": {}})
    assert r.status_code == 409 and err(r) == "evidence_insufficient"
    cancelled = agent.post(f"/attempts/{c['attempt_id']}/outcome",
                           json={"attempt_token": c["attempt_token"], "outcome": "completed",
                                 "evidence": dict(GOOD, flags_seen=["PRINTING", "DELETING"])})
    assert err(cancelled) == "evidence_insufficient"


def test_wrong_attempt_token_is_a_409_not_a_500(agent, flow):
    job = submitted(flow)["jobs"][0]["job_id"]
    agent.post(f"/jobs/{job}/approve")
    c = agent.post("/claim").json()
    for path, body in [("/sent", {"attempt_token": "f" * 64}), ("/renew", {"attempt_token": "f" * 64}),
                       ("/outcome", {"attempt_token": "f" * 64, "outcome": "failed", "evidence": {}})]:
        r = agent.post(f"/attempts/{c['attempt_id']}{path}", json=body)
        assert r.status_code == 409 and err(r) == "stale_attempt", (path, r.text)


def test_reject_and_resolve_and_customer_wording(agent, flow):
    job = submitted(flow)["jobs"][0]["job_id"]
    assert agent.post(f"/jobs/{job}/reject", json={"reason": "blurry scan"}).json()["status"] == "rejected"
    assert flow.view().json()["jobs"][0]["customer_message"] == "The shop declined this print."
    assert agent.post(f"/jobs/{job}/reject", json={}).status_code in (200,)          # idempotent
    assert err(agent.post(f"/jobs/{job}/approve")) == "not_actionable"

    other = submitted(type(flow)(flow.c, flow.shop))["jobs"][0]["job_id"]
    agent.post(f"/jobs/{other}/approve"); c = agent.post("/claim").json()
    agent.post(f"/attempts/{c['attempt_id']}/outcome", json={"attempt_token": c["attempt_token"], "outcome": "uncertain", "evidence": {}})
    assert err(agent.post(f"/jobs/{other}/resolve", json={"resolution": "bogus"})) == "invalid_request"
    r = agent.post(f"/jobs/{other}/resolve", json={"resolution": "retry", "note": "jam cleared"})
    assert r.json()["status"] == "approved"
    assert agent.post("/claim").json()["status"] == "claimed"


def test_other_shop_cannot_act_on_or_download_our_job(agent, flow, make_shop_agent):
    job = submitted(flow)["jobs"][0]["job_id"]
    other = make_shop_agent()
    assert other.post(f"/jobs/{job}/approve").status_code == 404
    assert other.c.get(f"/v1/agent/jobs/{job}/document", headers=other.h).status_code == 404
    assert other.post("/claim").json()["status"] == "no_job"


def test_cancel_after_claim_is_too_late_and_poll_shows_printing(agent, flow):
    job = submitted(flow)["jobs"][0]["job_id"]
    agent.post(f"/jobs/{job}/approve"); agent.post("/claim")
    assert agent.poll().json()["jobs"][0]["status"] == "printing"
    r = flow.cancel()
    assert r.status_code == 409 and err(r) == "too_late"


# ------------------------------------------------------------------ housekeeping through the poll
def test_poll_runs_the_sweep_and_retention_at_most_once_a_minute(agent, flow, raw_db, settings, tmp_path):
    from pathlib import Path
    flow.create_order()
    doc = flow.upload(pdfs.blank(1))
    key = raw_db.one("SELECT object_key FROM ap.documents WHERE id=%s", (doc,))
    path = Path(settings.local_storage_dir) / key
    raw_db.run("UPDATE ap.orders SET created_at=now()-interval '2 hours', expires_at=now()-interval '1 second' WHERE id=%s", (flow.order_id,))
    raw_db.run("UPDATE ap.documents SET created_at=now()-interval '2 hours' WHERE id=%s", (doc,))
    raw_db.run("UPDATE ap.system_state SET last_sweep_at = '-infinity'")
    assert path.exists()
    assert agent.poll().status_code == 200
    assert raw_db.one("SELECT status FROM ap.orders WHERE id=%s", (flow.order_id,)) == "expired"
    assert not path.exists()
    last = raw_db.one("SELECT last_sweep_at FROM ap.system_state")
    agent.poll()
    assert raw_db.one("SELECT last_sweep_at FROM ap.system_state") == last          # no second sweep within a minute


def test_poll_with_a_stale_lease_marks_needs_attention(agent, flow, raw_db):
    job = submitted(flow)["jobs"][0]["job_id"]
    agent.post(f"/jobs/{job}/approve"); c = agent.post("/claim").json()
    raw_db.run("UPDATE ap.print_attempts SET lease_expires_at = now() - interval '1 second' WHERE id=%s", (c["attempt_id"],))
    raw_db.run("UPDATE ap.system_state SET last_sweep_at = '-infinity'")
    assert agent.poll().json()["jobs"][0]["status"] == "needs_attention"
