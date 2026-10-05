-- AutoPrint V4 — 0004 one-round-trip reads for the hot paths, and the shop-side document lookup
--
-- Speed rule: the two requests made most often must cost ONE database round trip each.
--   * ap.order_view   customer status page, polled every few seconds
--   * ap.agent_poll   the shop app, polled every ~10 seconds; also its heartbeat
-- A serverless request plus several sequential round trips is what made V3 feel slow.

-- A single row that lets any caller run the housekeeping sweep at most once a minute, so expiry
-- and lease handling keep working even before a scheduler is set up.
CREATE TABLE ap.system_state (
  singleton     boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  last_sweep_at timestamptz NOT NULL DEFAULT '-infinity'
);
INSERT INTO ap.system_state DEFAULT VALUES;
ALTER TABLE ap.system_state ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION ap.order_view(p_secret_hash text) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE o ap.orders%ROWTYPE; shop_name text; pay ap.payments%ROWTYPE; jobs jsonb; can_cancel boolean;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE secret_hash = p_secret_hash AND access_until > now();
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'order_not_found'); END IF;
  SELECT name INTO shop_name FROM ap.shops WHERE id = o.shop_id;
  SELECT * INTO pay FROM ap.payments WHERE order_id = o.id;
  SELECT COALESCE(jsonb_agg(jsonb_build_object('job_id', j.id, 'document_name', d.original_name, 'status', j.status)
                            ORDER BY j.created_at, j.id), '[]'::jsonb)
    INTO jobs FROM ap.jobs j JOIN ap.documents d ON d.id = j.document_id WHERE j.order_id = o.id;
  can_cancel := o.status IN ('draft', 'submitted') AND NOT EXISTS (
    SELECT 1 FROM ap.jobs j WHERE j.order_id = o.id
       AND (j.status NOT IN ('awaiting_approval', 'approved') OR j.current_attempt_id IS NOT NULL));
  RETURN jsonb_build_object(
    'result', 'ok', 'order_id', o.id, 'short_code', o.short_code, 'shop_name', shop_name, 'status', o.status,
    'approval_expires_at', CASE WHEN o.status = 'submitted' THEN o.expires_at END,
    'payment_mode', pay.mode, 'payment_status', pay.status, 'amount_paise', pay.amount_paise,
    'can_cancel', can_cancel, 'jobs', jobs);
END $$;

-- Authenticates the device, records that it is alive, runs the housekeeping sweep when due, and
-- returns the shop's current queue. Active jobs first, then the last 24 hours of finished ones.
CREATE FUNCTION ap.agent_poll(p_device_id uuid, p_credential_hash text, p_agent_version text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE d ap.devices%ROWTYPE; sh ap.shops%ROWTYPE; jobs jsonb; swept boolean := false;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND OR d.credential_hash <> p_credential_hash THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  UPDATE ap.devices SET last_seen_at = now(), agent_version = COALESCE(left(p_agent_version, 40), agent_version) WHERE id = d.id;
  SELECT * INTO sh FROM ap.shops WHERE id = d.shop_id;

  IF pg_try_advisory_xact_lock(7001) THEN
    IF now() - (SELECT last_sweep_at FROM ap.system_state) > interval '60 seconds' THEN
      PERFORM ap.sweep();
      UPDATE ap.system_state SET last_sweep_at = now();
      swept := true;
    END IF;
  END IF;

  SELECT COALESCE(jsonb_agg(to_jsonb(r) - 'sort_group' ORDER BY r.sort_group, r.created_at DESC), '[]'::jsonb) INTO jobs FROM (
    SELECT j.id AS job_id, o.short_code AS order_short_code, doc.original_name AS document_name, doc.page_count,
           qi.copies, qi.color, qi.duplex, qi.page_range, qi.amount_paise, j.status, j.created_at,
           CASE WHEN j.status = 'awaiting_approval' THEN o.expires_at END AS approval_expires_at,
           j.attempt_count,
           CASE WHEN j.status IN ('awaiting_approval', 'approved', 'printing', 'needs_attention') THEN 0 ELSE 1 END AS sort_group
      FROM ap.jobs j
      JOIN ap.orders o ON o.id = j.order_id
      JOIN ap.documents doc ON doc.id = j.document_id
      JOIN ap.quote_items qi ON qi.id = j.quote_item_id
     WHERE j.shop_id = d.shop_id
       AND (j.status IN ('awaiting_approval', 'approved', 'printing', 'needs_attention') OR j.updated_at > now() - interval '24 hours')
     ORDER BY sort_group, j.created_at DESC
     LIMIT 60) r;

  RETURN jsonb_build_object('result', 'ok', 'device_id', d.id, 'shop_code', sh.code, 'shop_name', sh.name,
                            'jobs', jobs, 'swept', swept);
END $$;

-- What the shop app may download for a job of its own shop. Never returns another shop's file.
CREATE FUNCTION ap.job_document(p_job_id uuid, p_device_id uuid) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE d ap.devices%ROWTYPE; doc ap.documents%ROWTYPE;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  SELECT doc2.* INTO doc FROM ap.jobs j JOIN ap.documents doc2 ON doc2.id = j.document_id
   WHERE j.id = p_job_id AND j.shop_id = d.shop_id;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'job_not_found'); END IF;
  IF doc.deleted_at IS NOT NULL OR doc.status <> 'validated' THEN RETURN jsonb_build_object('result', 'document_not_found'); END IF;
  RETURN jsonb_build_object('result', 'ok', 'object_key', doc.object_key, 'sha256', doc.sha256, 'bytes', doc.verified_bytes);
END $$;
