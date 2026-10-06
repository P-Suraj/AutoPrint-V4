-- AutoPrint V4 — 0014 claim_next_job takes the order lock first
--
-- Why: the rule in 0002 is "row locks are always taken in the order: order -> job -> attempt". ap.claim_next_job
-- locked the job and, only when the job's file turned out to be gone (deleted or never validated), went on to lock
-- the order inside ap.close_order_if_done. A customer pressing Cancel at that moment holds the order and waits for the
-- job, while the claim holds the job and waits for the order. PostgreSQL aborts one of the two after a second
-- (deadlock detected) and that request fails. Nothing was ever printed because of this: the branch only runs for a
-- job that has no file to print.
--
-- What changes: the claim now looks at the oldest approved job WITHOUT locking it, locks that job's order, and only
-- then locks the job and checks that it is still approved. Everything from the document check onwards is the text of
-- 0002. The answer, the one-print-at-a-time rule and the "never a second attempt without a person" rule are unchanged.
--
--   * If the job was taken or cancelled while the claim waited for the order, the claim looks again (at most three
--     times). For the second and third look the order lock is taken only if it is free: a claim never WAITS for an
--     order while it already holds another one, so two claims cannot block each other either. If it is not free the
--     answer is "no_job" and the shop computer asks again a moment later, as it always does.
--   * Cost on the normal path: one more row read and one more row lock, inside the same single call. No extra round trip.
--
-- One more change, in the document check: a file whose retention deadline (delete_after) has passed is treated as
-- gone even when the cleanup has not removed it yet, so a late cleanup can never let a file be printed after the
-- time the customer was promised it would be deleted. The job fails with reason "document_unavailable", exactly as
-- it does once the cleanup has run. See 0016 for the same rule on the download link.
--
-- Safe on a database with existing rows: it replaces a function and touches no data.

CREATE OR REPLACE FUNCTION ap.claim_next_job(p_device_id uuid, p_lease_seconds integer DEFAULT 300) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE d ap.devices%ROWTYPE; j ap.jobs%ROWTYPE; doc ap.documents%ROWTYPE; qi ap.quote_items%ROWTYPE;
        a_id uuid; raw text; job_name text; lease timestamptz; cand_id uuid; cand_order uuid; looks integer := 0;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  IF p_lease_seconds NOT BETWEEN 30 AND 900 THEN RETURN jsonb_build_object('result', 'invalid_lease'); END IF;
  -- one print at a time per device keeps spooler correlation unambiguous
  IF EXISTS (SELECT 1 FROM ap.print_attempts WHERE device_id = d.id AND status IN ('claimed', 'sent_to_spooler') AND lease_expires_at > now()) THEN
    RETURN jsonb_build_object('result', 'busy');
  END IF;

  -- lock order: order -> job (the order first, like every other function)
  LOOP
    SELECT id, order_id INTO cand_id, cand_order FROM ap.jobs
     WHERE shop_id = d.shop_id AND status = 'approved'
     ORDER BY approved_at, id LIMIT 1;
    IF NOT FOUND THEN RETURN jsonb_build_object('result', 'no_job'); END IF;
    looks := looks + 1;
    IF looks = 1 THEN
      PERFORM 1 FROM ap.orders WHERE id = cand_order FOR UPDATE;
    ELSE
      PERFORM 1 FROM ap.orders WHERE id = cand_order FOR UPDATE SKIP LOCKED;
      IF NOT FOUND THEN RETURN jsonb_build_object('result', 'no_job'); END IF;
    END IF;
    SELECT * INTO j FROM ap.jobs WHERE id = cand_id AND status = 'approved' FOR UPDATE SKIP LOCKED;
    EXIT WHEN FOUND;
    IF looks >= 3 THEN RETURN jsonb_build_object('result', 'no_job'); END IF;
  END LOOP;

  SELECT * INTO doc FROM ap.documents WHERE id = j.document_id;
  IF doc.deleted_at IS NOT NULL OR doc.status <> 'validated' OR doc.delete_after <= now() THEN
    UPDATE ap.jobs SET status = 'failed', updated_at = now() WHERE id = j.id;
    PERFORM ap.log_event('job.failed', 'system', NULL, j.shop_id, j.order_id, j.id, NULL, jsonb_build_object('reason', 'document_unavailable'));
    PERFORM ap.close_order_if_done(j.order_id);
    RETURN jsonb_build_object('result', 'no_job');
  END IF;
  SELECT * INTO qi FROM ap.quote_items WHERE id = j.quote_item_id;
  raw := ap.new_secret();
  job_name := 'apjob_' || replace(gen_random_uuid()::text, '-', '');
  lease := now() + make_interval(secs => p_lease_seconds);
  INSERT INTO ap.print_attempts (job_id, device_id, attempt_token_hash, spooler_job_name, artifact_sha256, lease_expires_at)
  VALUES (j.id, d.id, ap.sha256_hex(raw), job_name, doc.sha256, lease) RETURNING id INTO a_id;
  UPDATE ap.jobs SET status = 'printing', current_attempt_id = a_id, attempt_count = attempt_count + 1, updated_at = now() WHERE id = j.id;
  PERFORM ap.log_event('job.claimed', 'device', d.id, j.shop_id, j.order_id, j.id, a_id);
  RETURN jsonb_build_object(
    'result', 'claimed', 'job_id', j.id, 'attempt_id', a_id, 'attempt_token', raw,
    'spooler_job_name', job_name, 'lease_expires_at', lease,
    'document', jsonb_build_object('object_key', doc.object_key, 'sha256', doc.sha256, 'bytes', doc.verified_bytes, 'pages', doc.page_count),
    'options', jsonb_build_object('copies', qi.copies, 'color', qi.color, 'duplex', qi.duplex, 'page_range', qi.page_range));
END $$;
