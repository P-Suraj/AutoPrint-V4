-- AutoPrint V4 — 0002 transactional functions
--
-- Rules
--   * Every state change happens inside one of these functions, in one transaction.
--   * Expected failures (not found, stale, too late, wrong state) are RETURNED as
--     {"result": "<code>"}; they never raise. The API maps result codes to HTTP status via
--     docs/CONTRACTS.md. Only genuine bugs raise, and the API turns those into one generic 500.
--   * Row locks are always taken in the order: order -> job -> attempt.
--   * Time comes from now(); tests move time by editing deadline columns.

-- ---------------------------------------------------------------- helpers
CREATE FUNCTION ap.new_secret() RETURNS text LANGUAGE sql VOLATILE AS $$
  SELECT replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '')
$$;

CREATE FUNCTION ap.sha256_hex(p text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(sha256(convert_to(p, 'UTF8')), 'hex')
$$;

CREATE FUNCTION ap.log_event(
  p_type text, p_actor ap.actor_type, p_actor_id uuid,
  p_shop uuid, p_order uuid, p_job uuid, p_attempt uuid, p_data jsonb DEFAULT '{}'::jsonb
) RETURNS void LANGUAGE sql AS $$
  INSERT INTO ap.events (type, actor, actor_id, shop_id, order_id, job_id, attempt_id, data)
  VALUES (p_type, p_actor, p_actor_id, p_shop, p_order, p_job, p_attempt, COALESCE(p_data, '{}'::jsonb))
$$;

CREATE FUNCTION ap.transition_allowed(p_entity text, p_from text, p_to text, p_actor ap.actor_type)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (SELECT 1 FROM ap.allowed_transitions
                 WHERE entity = p_entity AND from_status = p_from AND to_status = p_to AND actor = p_actor)
$$;

-- The completion rule lives in exactly one place. A job may only be marked completed when the
-- agent's evidence satisfies this function. Replaced in 0003 once the Phase 1 spike defines it.
CREATE FUNCTION ap.evidence_supports_completion(p_evidence jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT false
$$;

-- Retention (decision O-5). Recomputes delete_after for every live document of an order.
--   draft order          : 1 hour after the document was registered, never later than access_until
--   submitted order      : access_until (48 h hard cap) while jobs are still live
--   final order          : 24 hours after it became final, never later than access_until
--   never submitted      : (cancelled or expired draft) 1 hour after the upload, like a draft
CREATE FUNCTION ap.refresh_retention(p_order_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE o ap.orders%ROWTYPE;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE id = p_order_id;
  IF NOT FOUND THEN RETURN; END IF;
  UPDATE ap.documents d SET delete_after = CASE
      WHEN o.status = 'draft'     THEN least(d.created_at + interval '1 hour', o.access_until)
      WHEN o.status = 'submitted' THEN o.access_until
      -- cancelled or expired without ever being submitted: an abandoned upload, 1 hour from upload
      WHEN o.submitted_at IS NULL THEN least(d.created_at + interval '1 hour', o.access_until)
      ELSE least(COALESCE(o.closed_at, now()) + interval '24 hours', o.access_until)
    END
  WHERE d.order_id = p_order_id AND d.deleted_at IS NULL;
END $$;

-- Closes an order when every one of its jobs is in a final state.
CREATE FUNCTION ap.close_order_if_done(p_order_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE o ap.orders%ROWTYPE; live integer; any_job integer;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE id = p_order_id FOR UPDATE;
  IF NOT FOUND OR o.status <> 'submitted' THEN RETURN; END IF;
  SELECT count(*) FILTER (WHERE status IN ('awaiting_approval','approved','printing','needs_attention')),
         count(*) INTO live, any_job FROM ap.jobs WHERE order_id = p_order_id;
  IF any_job > 0 AND live = 0 THEN
    UPDATE ap.orders SET status = 'closed', closed_at = now(), expires_at = NULL, updated_at = now() WHERE id = p_order_id;
    PERFORM ap.refresh_retention(p_order_id);
    PERFORM ap.log_event('order.closed', 'system', NULL, o.shop_id, o.id, NULL, NULL);
  END IF;
END $$;

-- ---------------------------------------------------------------- devices
-- Returns the device's shop when the credentials are valid and the device is active.
CREATE FUNCTION ap.authenticate_device(p_device_id uuid, p_credential_hash text, p_agent_version text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE d ap.devices%ROWTYPE;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND OR d.credential_hash <> p_credential_hash THEN
    RETURN jsonb_build_object('result', 'unauthorized');
  END IF;
  UPDATE ap.devices SET last_seen_at = now(), agent_version = COALESCE(p_agent_version, agent_version) WHERE id = d.id;
  RETURN jsonb_build_object('result', 'ok', 'device_id', d.id, 'shop_id', d.shop_id);
END $$;

CREATE FUNCTION ap.issue_enrollment_code(p_shop_code text, p_code_hash text, p_ttl_minutes integer DEFAULT 30)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE s ap.shops%ROWTYPE;
BEGIN
  SELECT * INTO s FROM ap.shops WHERE code = upper(p_shop_code) AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'shop_not_found'); END IF;
  INSERT INTO ap.enrollment_codes (shop_id, code_hash, expires_at)
  VALUES (s.id, p_code_hash, now() + make_interval(mins => p_ttl_minutes));
  RETURN jsonb_build_object('result', 'ok', 'shop_id', s.id);
END $$;

CREATE FUNCTION ap.consume_enrollment(p_code_hash text, p_display_name text, p_credential_hash text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE c ap.enrollment_codes%ROWTYPE; d_id uuid; sh ap.shops%ROWTYPE;
BEGIN
  SELECT * INTO c FROM ap.enrollment_codes WHERE code_hash = p_code_hash FOR UPDATE;
  IF NOT FOUND OR c.consumed_at IS NOT NULL OR c.expires_at <= now() THEN
    RETURN jsonb_build_object('result', 'invalid_code');
  END IF;
  INSERT INTO ap.devices (shop_id, display_name, credential_hash)
  VALUES (c.shop_id, left(btrim(p_display_name), 80), p_credential_hash) RETURNING id INTO d_id;
  UPDATE ap.enrollment_codes SET consumed_at = now(), device_id = d_id WHERE id = c.id;
  SELECT * INTO sh FROM ap.shops WHERE id = c.shop_id;
  PERFORM ap.log_event('device.enrolled', 'device', d_id, c.shop_id, NULL, NULL, NULL);
  RETURN jsonb_build_object('result', 'ok', 'device_id', d_id, 'shop_id', c.shop_id, 'shop_code', sh.code, 'shop_name', sh.name);
END $$;

-- ---------------------------------------------------------------- customer side
CREATE FUNCTION ap.create_order(p_shop_code text, p_secret_hash text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE s ap.shops%ROWTYPE; o ap.orders%ROWTYPE; new_code text; tries integer := 0;
        alphabet constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
BEGIN
  SELECT * INTO s FROM ap.shops WHERE code = upper(p_shop_code) AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'shop_not_found'); END IF;
  LOOP
    new_code := '';
    FOR i IN 1..4 LOOP
      new_code := new_code || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
    END LOOP;
    EXIT WHEN NOT EXISTS (SELECT 1 FROM ap.orders WHERE shop_id = s.id AND short_code = new_code AND status IN ('draft', 'submitted'));
    tries := tries + 1;
    IF tries > 20 THEN RETURN jsonb_build_object('result', 'busy'); END IF;
  END LOOP;
  INSERT INTO ap.orders (shop_id, short_code, secret_hash, expires_at, access_until)
  VALUES (s.id, new_code, p_secret_hash, now() + interval '1 hour', now() + interval '48 hours')
  RETURNING * INTO o;
  PERFORM ap.log_event('order.created', 'customer', NULL, s.id, o.id, NULL, NULL);
  RETURN jsonb_build_object('result', 'ok', 'order_id', o.id, 'short_code', o.short_code,
                            'expires_at', o.expires_at, 'access_until', o.access_until);
END $$;

-- Maps an order secret to its order, only while the secret is still valid.
CREATE FUNCTION ap.order_for_secret(p_secret_hash text) RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT id FROM ap.orders WHERE secret_hash = p_secret_hash AND access_until > now()
$$;

CREATE FUNCTION ap.register_document(p_order_id uuid, p_original_name text, p_declared_bytes bigint, p_object_key text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE o ap.orders%ROWTYPE; pos integer; d ap.documents%ROWTYPE;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE id = p_order_id FOR UPDATE;
  IF NOT FOUND OR o.access_until <= now() THEN RETURN jsonb_build_object('result', 'order_not_found'); END IF;
  IF o.status <> 'draft' THEN RETURN jsonb_build_object('result', 'order_not_draft', 'status', o.status); END IF;
  IF o.expires_at <= now() THEN RETURN jsonb_build_object('result', 'order_expired'); END IF;
  SELECT COALESCE(max(position), 0) + 1 INTO pos FROM ap.documents WHERE order_id = o.id;
  IF pos > 20 THEN RETURN jsonb_build_object('result', 'too_many_documents'); END IF;
  INSERT INTO ap.documents (order_id, position, original_name, declared_bytes, object_key, delete_after)
  VALUES (o.id, pos, left(p_original_name, 255), p_declared_bytes, p_object_key,
          least(now() + interval '1 hour', o.access_until))
  RETURNING * INTO d;
  PERFORM ap.log_event('document.registered', 'customer', NULL, o.shop_id, o.id, NULL, NULL,
                       jsonb_build_object('document_id', d.id, 'bytes', p_declared_bytes));
  RETURN jsonb_build_object('result', 'ok', 'document_id', d.id, 'position', pos);
END $$;

CREATE FUNCTION ap.finalize_document(p_document_id uuid, p_sha256 text, p_verified_bytes bigint, p_page_count integer)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE d ap.documents%ROWTYPE; o ap.orders%ROWTYPE;
BEGIN
  SELECT * INTO d FROM ap.documents WHERE id = p_document_id FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'document_not_found'); END IF;
  SELECT * INTO o FROM ap.orders WHERE id = d.order_id;
  IF d.status = 'validated' THEN
    RETURN jsonb_build_object('result', 'ok', 'idempotent', true, 'page_count', d.page_count, 'sha256', d.sha256);
  END IF;
  IF d.status <> 'pending_upload' THEN RETURN jsonb_build_object('result', 'document_not_pending', 'status', d.status); END IF;
  IF o.status <> 'draft' THEN RETURN jsonb_build_object('result', 'order_not_draft'); END IF;
  UPDATE ap.documents SET status = 'validated', sha256 = p_sha256, verified_bytes = p_verified_bytes, page_count = p_page_count
  WHERE id = d.id;
  PERFORM ap.log_event('document.validated', 'system', NULL, o.shop_id, o.id, NULL, NULL,
                       jsonb_build_object('document_id', d.id, 'pages', p_page_count));
  RETURN jsonb_build_object('result', 'ok', 'page_count', p_page_count, 'sha256', p_sha256);
END $$;

CREATE FUNCTION ap.reject_document(p_document_id uuid, p_reason text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE d ap.documents%ROWTYPE; o ap.orders%ROWTYPE;
BEGIN
  SELECT * INTO d FROM ap.documents WHERE id = p_document_id FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'document_not_found'); END IF;
  IF d.status NOT IN ('pending_upload', 'rejected') THEN RETURN jsonb_build_object('result', 'document_not_pending'); END IF;
  SELECT * INTO o FROM ap.orders WHERE id = d.order_id;
  UPDATE ap.documents SET status = 'rejected', reject_reason = left(p_reason, 200) WHERE id = d.id;
  PERFORM ap.log_event('document.rejected', 'system', NULL, o.shop_id, o.id, NULL, NULL,
                       jsonb_build_object('document_id', d.id, 'reason', left(p_reason, 200)));
  RETURN jsonb_build_object('result', 'ok');
END $$;

-- p_items: [{"document_id": uuid, "copies": int, "color": bool, "duplex": bool,
--            "page_range": text|null, "selected_pages": int, "printed_sides": int, "amount_paise": int}]
-- The API prices the items. This function re-checks ownership, page bounds and the total.
CREATE FUNCTION ap.create_quote(p_order_id uuid, p_items jsonb, p_total_paise integer) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE o ap.orders%ROWTYPE; rc ap.rate_cards%ROWTYPE; q_id uuid; it jsonb; d ap.documents%ROWTYPE; sum_paise integer := 0;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE id = p_order_id FOR UPDATE;
  IF NOT FOUND OR o.access_until <= now() THEN RETURN jsonb_build_object('result', 'order_not_found'); END IF;
  IF o.status <> 'draft' THEN RETURN jsonb_build_object('result', 'order_not_draft'); END IF;
  IF o.expires_at <= now() THEN RETURN jsonb_build_object('result', 'order_expired'); END IF;
  IF jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 20 THEN
    RETURN jsonb_build_object('result', 'invalid_items');
  END IF;
  SELECT * INTO rc FROM ap.rate_cards WHERE shop_id = o.shop_id AND retired_at IS NULL;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'no_rate_card'); END IF;

  -- validate every item before inserting anything
  FOR it IN SELECT * FROM jsonb_array_elements(p_items) LOOP
    SELECT * INTO d FROM ap.documents WHERE id = (it->>'document_id')::uuid AND order_id = o.id;
    IF NOT FOUND OR d.status <> 'validated' THEN RETURN jsonb_build_object('result', 'document_not_ready'); END IF;
    IF (it->>'selected_pages')::int > d.page_count THEN RETURN jsonb_build_object('result', 'invalid_items'); END IF;
    sum_paise := sum_paise + (it->>'amount_paise')::int;
  END LOOP;
  IF (SELECT count(DISTINCT it2->>'document_id') FROM jsonb_array_elements(p_items) it2) <> jsonb_array_length(p_items) THEN
    RETURN jsonb_build_object('result', 'invalid_items');
  END IF;
  IF sum_paise <> p_total_paise THEN RETURN jsonb_build_object('result', 'total_mismatch'); END IF;

  INSERT INTO ap.quotes (order_id, rate_card_id, total_paise) VALUES (o.id, rc.id, p_total_paise) RETURNING id INTO q_id;
  INSERT INTO ap.quote_items (quote_id, document_id, copies, color, duplex, page_range, selected_pages, printed_sides, amount_paise)
  SELECT q_id, (e->>'document_id')::uuid, (e->>'copies')::int, (e->>'color')::boolean, (e->>'duplex')::boolean,
         NULLIF(e->>'page_range', ''), (e->>'selected_pages')::int, (e->>'printed_sides')::int, (e->>'amount_paise')::int
  FROM jsonb_array_elements(p_items) e;
  PERFORM ap.log_event('quote.created', 'customer', NULL, o.shop_id, o.id, NULL, NULL,
                       jsonb_build_object('quote_id', q_id, 'total_paise', p_total_paise, 'rate_card_version', rc.version));
  RETURN jsonb_build_object('result', 'ok', 'quote_id', q_id, 'total_paise', p_total_paise, 'rate_card_version', rc.version);
END $$;

-- Accepts a quote and creates one job per quote item. Idempotent for the same quote.
CREATE FUNCTION ap.submit_order(p_order_id uuid, p_quote_id uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE o ap.orders%ROWTYPE; q ap.quotes%ROWTYPE; job_ids jsonb;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE id = p_order_id FOR UPDATE;
  IF NOT FOUND OR o.access_until <= now() THEN RETURN jsonb_build_object('result', 'order_not_found'); END IF;
  SELECT * INTO q FROM ap.quotes WHERE id = p_quote_id AND order_id = o.id FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'quote_not_found'); END IF;
  IF o.status = 'submitted' AND q.accepted_at IS NOT NULL THEN
    SELECT jsonb_agg(id ORDER BY created_at, id) INTO job_ids FROM ap.jobs WHERE order_id = o.id;
    RETURN jsonb_build_object('result', 'ok', 'idempotent', true, 'job_ids', job_ids, 'expires_at', o.expires_at);
  END IF;
  IF o.status <> 'draft' THEN RETURN jsonb_build_object('result', 'order_not_draft', 'status', o.status); END IF;
  IF o.expires_at <= now() THEN RETURN jsonb_build_object('result', 'order_expired'); END IF;

  UPDATE ap.quotes SET accepted_at = now() WHERE id = q.id;
  INSERT INTO ap.jobs (order_id, shop_id, document_id, quote_item_id)
  SELECT o.id, o.shop_id, qi.document_id, qi.id FROM ap.quote_items qi WHERE qi.quote_id = q.id;
  INSERT INTO ap.payments (order_id, amount_paise) VALUES (o.id, q.total_paise);
  UPDATE ap.orders SET status = 'submitted', submitted_at = now(), expires_at = now() + interval '1 hour', updated_at = now()
  WHERE id = o.id RETURNING * INTO o;
  PERFORM ap.refresh_retention(o.id);
  SELECT jsonb_agg(id ORDER BY created_at, id) INTO job_ids FROM ap.jobs WHERE order_id = o.id;
  PERFORM ap.log_event('order.submitted', 'customer', NULL, o.shop_id, o.id, NULL, NULL,
                       jsonb_build_object('quote_id', q.id, 'jobs', jsonb_array_length(job_ids), 'total_paise', q.total_paise));
  RETURN jsonb_build_object('result', 'ok', 'job_ids', job_ids, 'expires_at', o.expires_at);
END $$;

-- Cancels an order while nothing has been claimed. After a claim cancellation is no longer
-- guaranteed (decision F-9): the answer is "too_late" and printing continues.
CREATE FUNCTION ap.cancel_order(p_order_id uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE o ap.orders%ROWTYPE; started integer;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE id = p_order_id FOR UPDATE;
  IF NOT FOUND OR o.access_until <= now() THEN RETURN jsonb_build_object('result', 'order_not_found'); END IF;
  IF o.status = 'cancelled' THEN RETURN jsonb_build_object('result', 'ok', 'idempotent', true); END IF;
  IF o.status NOT IN ('draft', 'submitted') THEN RETURN jsonb_build_object('result', 'order_not_cancellable', 'status', o.status); END IF;
  PERFORM 1 FROM ap.jobs WHERE order_id = o.id FOR UPDATE;
  SELECT count(*) INTO started FROM ap.jobs
   WHERE order_id = o.id AND status NOT IN ('awaiting_approval', 'approved', 'rejected', 'cancelled', 'expired');
  IF started > 0 OR EXISTS (SELECT 1 FROM ap.jobs WHERE order_id = o.id AND current_attempt_id IS NOT NULL) THEN
    RETURN jsonb_build_object('result', 'too_late');
  END IF;
  UPDATE ap.jobs SET status = 'cancelled', updated_at = now()
   WHERE order_id = o.id AND status IN ('awaiting_approval', 'approved');
  UPDATE ap.orders SET status = 'cancelled', closed_at = now(), expires_at = NULL, updated_at = now() WHERE id = o.id;
  PERFORM ap.refresh_retention(o.id);
  PERFORM ap.log_event('order.cancelled', 'customer', NULL, o.shop_id, o.id, NULL, NULL);
  RETURN jsonb_build_object('result', 'ok');
END $$;

-- ---------------------------------------------------------------- shop side (called with an authenticated device)
CREATE FUNCTION ap.approve_job(p_job_id uuid, p_device_id uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE d ap.devices%ROWTYPE; j ap.jobs%ROWTYPE; o ap.orders%ROWTYPE;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  SELECT * INTO o FROM ap.orders WHERE id = (SELECT order_id FROM ap.jobs WHERE id = p_job_id) FOR UPDATE;
  SELECT * INTO j FROM ap.jobs WHERE id = p_job_id FOR UPDATE;
  IF NOT FOUND OR j.shop_id <> d.shop_id THEN RETURN jsonb_build_object('result', 'job_not_found'); END IF;
  IF j.status = 'approved' THEN RETURN jsonb_build_object('result', 'ok', 'idempotent', true); END IF;
  IF j.status <> 'awaiting_approval' THEN RETURN jsonb_build_object('result', 'not_actionable', 'status', j.status); END IF;
  IF o.expires_at IS NOT NULL AND o.expires_at <= now() THEN RETURN jsonb_build_object('result', 'order_expired'); END IF;
  UPDATE ap.jobs SET status = 'approved', approved_at = now(), updated_at = now() WHERE id = j.id;
  IF NOT EXISTS (SELECT 1 FROM ap.jobs WHERE order_id = o.id AND status = 'awaiting_approval') THEN
    UPDATE ap.orders SET expires_at = NULL, updated_at = now() WHERE id = o.id;
  END IF;
  PERFORM ap.log_event('job.approved', 'device', d.id, j.shop_id, j.order_id, j.id, NULL);
  RETURN jsonb_build_object('result', 'ok');
END $$;

CREATE FUNCTION ap.reject_job(p_job_id uuid, p_device_id uuid, p_reason text DEFAULT NULL) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE d ap.devices%ROWTYPE; j ap.jobs%ROWTYPE;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  PERFORM 1 FROM ap.orders WHERE id = (SELECT order_id FROM ap.jobs WHERE id = p_job_id) FOR UPDATE;
  SELECT * INTO j FROM ap.jobs WHERE id = p_job_id FOR UPDATE;
  IF NOT FOUND OR j.shop_id <> d.shop_id THEN RETURN jsonb_build_object('result', 'job_not_found'); END IF;
  IF j.status = 'rejected' THEN RETURN jsonb_build_object('result', 'ok', 'idempotent', true); END IF;
  IF j.status <> 'awaiting_approval' THEN RETURN jsonb_build_object('result', 'not_actionable', 'status', j.status); END IF;
  UPDATE ap.jobs SET status = 'rejected', updated_at = now() WHERE id = j.id;
  PERFORM ap.log_event('job.rejected', 'device', d.id, j.shop_id, j.order_id, j.id, NULL,
                       jsonb_build_object('reason', left(COALESCE(p_reason, ''), 200)));
  PERFORM ap.close_order_if_done(j.order_id);
  RETURN jsonb_build_object('result', 'ok');
END $$;

-- ---------------------------------------------------------------- agent side
-- At most one live attempt per device. Returns the instruction set for the claimed job.
CREATE FUNCTION ap.claim_next_job(p_device_id uuid, p_lease_seconds integer DEFAULT 300) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE d ap.devices%ROWTYPE; j ap.jobs%ROWTYPE; doc ap.documents%ROWTYPE; qi ap.quote_items%ROWTYPE;
        a_id uuid; raw text; job_name text; lease timestamptz;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  IF p_lease_seconds NOT BETWEEN 30 AND 900 THEN RETURN jsonb_build_object('result', 'invalid_lease'); END IF;
  -- one print at a time per device keeps spooler correlation unambiguous
  IF EXISTS (SELECT 1 FROM ap.print_attempts WHERE device_id = d.id AND status IN ('claimed', 'sent_to_spooler') AND lease_expires_at > now()) THEN
    RETURN jsonb_build_object('result', 'busy');
  END IF;
  SELECT * INTO j FROM ap.jobs
   WHERE shop_id = d.shop_id AND status = 'approved'
   ORDER BY approved_at, id LIMIT 1 FOR UPDATE SKIP LOCKED;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'no_job'); END IF;
  SELECT * INTO doc FROM ap.documents WHERE id = j.document_id;
  IF doc.deleted_at IS NOT NULL OR doc.status <> 'validated' THEN
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

-- Shared guard for attempt calls: returns the locked attempt if the caller owns it, else NULL.
CREATE FUNCTION ap.lock_owned_attempt(p_attempt_id uuid, p_token text, p_device_id uuid) RETURNS ap.print_attempts
LANGUAGE plpgsql AS $$
DECLARE a ap.print_attempts%ROWTYPE;
BEGIN
  SELECT * INTO a FROM ap.print_attempts
   WHERE id = p_attempt_id AND device_id = p_device_id AND attempt_token_hash = ap.sha256_hex(p_token) FOR UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  RETURN a;
END $$;

CREATE FUNCTION ap.renew_lease(p_attempt_id uuid, p_token text, p_device_id uuid, p_lease_seconds integer DEFAULT 300)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE a ap.print_attempts%ROWTYPE;
BEGIN
  a := ap.lock_owned_attempt(p_attempt_id, p_token, p_device_id);
  IF a.id IS NULL THEN RETURN jsonb_build_object('result', 'stale_attempt'); END IF;
  IF a.status NOT IN ('claimed', 'sent_to_spooler') OR a.lease_expires_at <= now() THEN
    RETURN jsonb_build_object('result', 'stale_attempt');
  END IF;
  IF p_lease_seconds NOT BETWEEN 30 AND 900 THEN RETURN jsonb_build_object('result', 'invalid_lease'); END IF;
  UPDATE ap.print_attempts SET lease_expires_at = now() + make_interval(secs => p_lease_seconds), updated_at = now() WHERE id = a.id
  RETURNING lease_expires_at INTO a.lease_expires_at;
  RETURN jsonb_build_object('result', 'ok', 'lease_expires_at', a.lease_expires_at);
END $$;

-- The agent calls this once the print process has handed the job to the spooler.
CREATE FUNCTION ap.mark_sent(p_attempt_id uuid, p_token text, p_device_id uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE a ap.print_attempts%ROWTYPE; j ap.jobs%ROWTYPE;
BEGIN
  a := ap.lock_owned_attempt(p_attempt_id, p_token, p_device_id);
  IF a.id IS NULL THEN RETURN jsonb_build_object('result', 'stale_attempt'); END IF;
  IF a.status = 'sent_to_spooler' THEN RETURN jsonb_build_object('result', 'ok', 'idempotent', true); END IF;
  IF a.status <> 'claimed' OR a.lease_expires_at <= now() THEN RETURN jsonb_build_object('result', 'stale_attempt'); END IF;
  SELECT * INTO j FROM ap.jobs WHERE id = a.job_id;
  UPDATE ap.print_attempts SET status = 'sent_to_spooler', sent_at = now(), updated_at = now() WHERE id = a.id;
  PERFORM ap.log_event('attempt.sent_to_spooler', 'device', p_device_id, j.shop_id, j.order_id, j.id, a.id);
  RETURN jsonb_build_object('result', 'ok');
END $$;

-- p_outcome: 'completed' | 'failed' | 'uncertain'. 'completed' needs evidence that satisfies the
-- completion rule; otherwise the answer is "evidence_insufficient" and nothing changes.
CREATE FUNCTION ap.report_outcome(p_attempt_id uuid, p_token text, p_device_id uuid, p_outcome text, p_evidence jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE a ap.print_attempts%ROWTYPE; j ap.jobs%ROWTYPE; new_attempt ap.attempt_status; new_job ap.job_status; ev jsonb; same_status text;
BEGIN
  same_status := p_outcome;
  IF p_outcome NOT IN ('completed', 'failed', 'uncertain') THEN RETURN jsonb_build_object('result', 'invalid_outcome'); END IF;
  ev := COALESCE(p_evidence, '{}'::jsonb);
  IF jsonb_typeof(ev) <> 'object' OR length(ev::text) > 4000 THEN RETURN jsonb_build_object('result', 'invalid_evidence'); END IF;
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

-- Shopkeeper action on a job that needs a human. 'retry' is the only way a second attempt is
-- ever created, and it is always an explicit human choice.
CREATE FUNCTION ap.resolve_job(p_job_id uuid, p_device_id uuid, p_resolution text, p_note text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE d ap.devices%ROWTYPE; j ap.jobs%ROWTYPE; target ap.job_status;
BEGIN
  IF p_resolution NOT IN ('completed', 'failed', 'retry') THEN RETURN jsonb_build_object('result', 'invalid_resolution'); END IF;
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  PERFORM 1 FROM ap.orders WHERE id = (SELECT order_id FROM ap.jobs WHERE id = p_job_id) FOR UPDATE;
  SELECT * INTO j FROM ap.jobs WHERE id = p_job_id FOR UPDATE;
  IF NOT FOUND OR j.shop_id <> d.shop_id THEN RETURN jsonb_build_object('result', 'job_not_found'); END IF;
  target := CASE p_resolution WHEN 'completed' THEN 'completed' WHEN 'failed' THEN 'failed' ELSE 'approved' END;
  IF NOT ap.transition_allowed('job', j.status::text, target::text, 'device') OR j.status = 'printing' THEN
    RETURN jsonb_build_object('result', 'not_actionable', 'status', j.status);
  END IF;
  UPDATE ap.jobs SET status = target, current_attempt_id = CASE WHEN target = 'approved' THEN NULL ELSE current_attempt_id END,
         approved_at = CASE WHEN target = 'approved' THEN now() ELSE approved_at END, updated_at = now() WHERE id = j.id;
  PERFORM ap.log_event('job.resolved', 'device', d.id, j.shop_id, j.order_id, j.id, j.current_attempt_id,
                       jsonb_build_object('resolution', p_resolution, 'from', j.status, 'note', left(COALESCE(p_note, ''), 200)));
  PERFORM ap.close_order_if_done(j.order_id);
  RETURN jsonb_build_object('result', 'ok', 'job_status', target);
END $$;

-- ---------------------------------------------------------------- system sweeps
-- Run every minute by the API process. Idempotent.
CREATE FUNCTION ap.sweep() RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE r record; stale_attempts integer := 0; expired_jobs integer := 0; expired_orders integer := 0;
BEGIN
  -- attempts whose lease ran out: the outcome is unknown, so a human decides. Never auto-retry.
  FOR r IN SELECT a.id AS attempt_id, a.job_id, j.order_id, j.shop_id
             FROM ap.print_attempts a JOIN ap.jobs j ON j.id = a.job_id
            WHERE a.status IN ('claimed', 'sent_to_spooler') AND a.lease_expires_at <= now() AND j.status = 'printing'
            ORDER BY a.id FOR UPDATE OF a, j SKIP LOCKED LOOP
    UPDATE ap.print_attempts SET status = 'uncertain', finished_at = now(), updated_at = now(),
           evidence = evidence || '{"reason":"lease_expired"}'::jsonb WHERE id = r.attempt_id;
    UPDATE ap.jobs SET status = 'needs_attention', updated_at = now() WHERE id = r.job_id;
    PERFORM ap.log_event('attempt.lease_expired', 'system', NULL, r.shop_id, r.order_id, r.job_id, r.attempt_id);
    stale_attempts := stale_attempts + 1;
  END LOOP;

  -- unapproved jobs and orders past their 1 hour window
  FOR r IN SELECT o.id AS order_id, o.shop_id, o.status FROM ap.orders o
            WHERE o.status IN ('draft', 'submitted') AND o.expires_at IS NOT NULL AND o.expires_at <= now()
            ORDER BY o.id FOR UPDATE SKIP LOCKED LOOP
    UPDATE ap.jobs SET status = 'expired', updated_at = now() WHERE order_id = r.order_id AND status = 'awaiting_approval';
    GET DIAGNOSTICS expired_jobs = ROW_COUNT;
    IF r.status = 'draft' THEN
      UPDATE ap.orders SET status = 'expired', closed_at = now(), expires_at = NULL, updated_at = now() WHERE id = r.order_id;
      PERFORM ap.refresh_retention(r.order_id);
      PERFORM ap.log_event('order.expired', 'system', NULL, r.shop_id, r.order_id, NULL, NULL);
      expired_orders := expired_orders + 1;
    ELSE
      UPDATE ap.orders SET expires_at = NULL, updated_at = now() WHERE id = r.order_id;
      PERFORM ap.log_event('order.approval_window_elapsed', 'system', NULL, r.shop_id, r.order_id, NULL, NULL);
      PERFORM ap.close_order_if_done(r.order_id);
      expired_orders := expired_orders + 1;
    END IF;
  END LOOP;
  RETURN jsonb_build_object('stale_attempts', stale_attempts, 'orders_expired', expired_orders);
END $$;

-- ---------------------------------------------------------------- retention
CREATE FUNCTION ap.documents_due_for_deletion(p_limit integer DEFAULT 100) RETURNS TABLE (document_id uuid, object_key text)
LANGUAGE sql STABLE AS $$
  SELECT id, object_key FROM ap.documents WHERE deleted_at IS NULL AND delete_after <= now() ORDER BY delete_after LIMIT p_limit
$$;

CREATE FUNCTION ap.mark_document_deleted(p_document_id uuid) RETURNS void LANGUAGE sql AS $$
  UPDATE ap.documents SET status = 'deleted', deleted_at = now() WHERE id = p_document_id AND deleted_at IS NULL
$$;
