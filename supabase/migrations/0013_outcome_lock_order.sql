-- AutoPrint V4 — 0013 report_outcome takes the order lock first
--
-- Why: 0002 states the rule "row locks are always taken in the order: order -> job -> attempt", and every function
-- follows it except ap.report_outcome, which locked the attempt and the job and only then the order (inside
-- ap.close_order_if_done). A customer pressing Cancel, or a shopkeeper pressing Reject or resolving, on the same job at
-- the moment its print outcome arrives holds the order and waits for the job, while report_outcome holds the job and
-- waits for the order. PostgreSQL then aborts one of the two after a second (deadlock detected) and that request fails.
-- If the aborted one is the outcome report, a print that succeeded is left for the lease to expire and a person to
-- resolve. Nothing was ever printed twice because of this; it only cost a failed request in a rare overlap.
--
-- The only change is the one PERFORM that locks the order before anything else. Everything after it is the text of
-- 0002. Safe on a database with existing rows: it replaces a function and touches no data.

CREATE OR REPLACE FUNCTION ap.report_outcome(p_attempt_id uuid, p_token text, p_device_id uuid, p_outcome text, p_evidence jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE a ap.print_attempts%ROWTYPE; j ap.jobs%ROWTYPE; new_attempt ap.attempt_status; new_job ap.job_status; ev jsonb; same_status text;
BEGIN
  same_status := p_outcome;
  IF p_outcome NOT IN ('completed', 'failed', 'uncertain') THEN RETURN jsonb_build_object('result', 'invalid_outcome'); END IF;
  ev := COALESCE(p_evidence, '{}'::jsonb);
  IF jsonb_typeof(ev) <> 'object' OR length(ev::text) > 4000 THEN RETURN jsonb_build_object('result', 'invalid_evidence'); END IF;
  -- lock order: order -> attempt -> job (the order first, like every other function)
  PERFORM 1 FROM ap.orders WHERE id = (SELECT jj.order_id FROM ap.print_attempts aa JOIN ap.jobs jj ON jj.id = aa.job_id
                                        WHERE aa.id = p_attempt_id AND aa.device_id = p_device_id) FOR UPDATE;
  a := ap.lock_owned_attempt(p_attempt_id, p_token, p_device_id);
  IF a.id IS NULL THEN RETURN jsonb_build_object('result', 'stale_attempt'); END IF;
  SELECT * INTO j FROM ap.jobs WHERE id = a.job_id FOR UPDATE;

  IF a.status IN ('completed', 'failed', 'uncertain') THEN
    -- a repeated identical report is idempotent; a conflicting one is recorded and refused
    IF a.status::text = same_status THEN
      RETURN jsonb_build_object('result', 'ok', 'idempotent', true);
    END IF;
    PERFORM ap.log_event('attempt.late_report', 'device', p_device_id, j.shop_id, j.order_id, j.id, a.id,
                         jsonb_build_object('reported', p_outcome, 'recorded', a.status, 'evidence', ev));
    RETURN jsonb_build_object('result', 'stale_attempt', 'recorded_status', a.status);
  END IF;

  new_attempt := CASE p_outcome WHEN 'completed' THEN 'completed' WHEN 'failed' THEN 'failed' ELSE 'uncertain' END;
  new_job     := CASE p_outcome WHEN 'completed' THEN 'completed' WHEN 'failed' THEN 'failed' ELSE 'needs_attention' END;

  IF p_outcome = 'completed' THEN
    IF a.status <> 'sent_to_spooler' OR a.lease_expires_at <= now() THEN RETURN jsonb_build_object('result', 'stale_attempt'); END IF;
    IF NOT ap.evidence_supports_completion(ev) THEN RETURN jsonb_build_object('result', 'evidence_insufficient'); END IF;
  END IF;
  IF NOT ap.transition_allowed('attempt', a.status::text, new_attempt::text, 'device')
     OR NOT ap.transition_allowed('job', j.status::text, new_job::text, 'device') THEN
    RETURN jsonb_build_object('result', 'stale_attempt');
  END IF;

  UPDATE ap.print_attempts SET status = new_attempt, evidence = ev, finished_at = now(), updated_at = now() WHERE id = a.id;
  UPDATE ap.jobs SET status = new_job, updated_at = now() WHERE id = j.id;
  PERFORM ap.log_event('attempt.' || p_outcome, 'device', p_device_id, j.shop_id, j.order_id, j.id, a.id, jsonb_build_object('evidence', ev));
  PERFORM ap.close_order_if_done(j.order_id);
  RETURN jsonb_build_object('result', 'ok', 'job_status', new_job);
END $$;
