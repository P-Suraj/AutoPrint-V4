-- AutoPrint V4 — 0011 record when a shop computer comes back after being away
--
-- Why: the pilot must report "agent offline periods" (BUILD_PHASES 3.3), but the only thing stored was
-- devices.last_seen_at, which is overwritten by every poll. How long a computer was away could not be known afterwards.
--
-- Now, when a device checks in and its previous check-in is more than 120 seconds old, one event is written:
--   type  device.back_online     actor device, actor_id = the device
--   data  {"offline_seconds": n, "last_seen_at": "<the previous check-in>"}
-- The app checks in about every 10 to 20 seconds, so 120 seconds means several missed in a row, not one slow request.
-- One event per gap: the previous check-in is read under the row lock, so two simultaneous requests cannot both log it.
-- A gap that is still open (the computer is away right now) has no event yet; the founder report adds it from last_seen_at.
-- An event says the app was not reaching the server. It cannot say why (PC off, asleep, no internet, shop closed).
--
-- The shop poll stays ONE round trip and one row update, as before.
-- Safe on a database with existing rows: no existing row is rewritten except the single ap.system_state row.

ALTER TABLE ap.system_state ADD COLUMN offline_tracked_since timestamptz NOT NULL DEFAULT now();

CREATE FUNCTION ap.touch_device(p_device_id uuid, p_agent_version text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE prev timestamptz; shop uuid;
BEGIN
  UPDATE ap.devices x SET last_seen_at = now(), agent_version = COALESCE(left(p_agent_version, 40), x.agent_version)
    FROM (SELECT id, last_seen_at FROM ap.devices WHERE id = p_device_id FOR UPDATE) old
   WHERE x.id = old.id
  RETURNING old.last_seen_at, x.shop_id INTO prev, shop;
  IF prev IS NOT NULL AND prev < now() - interval '120 seconds' THEN
    PERFORM ap.log_event('device.back_online', 'device', p_device_id, shop, NULL, NULL, NULL,
                         jsonb_build_object('offline_seconds', floor(extract(epoch FROM now() - prev))::int, 'last_seen_at', prev));
  END IF;
END $$;

-- unchanged from 0002 except that the check-in goes through ap.touch_device
CREATE OR REPLACE FUNCTION ap.authenticate_device(p_device_id uuid, p_credential_hash text, p_agent_version text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE d ap.devices%ROWTYPE;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND OR d.credential_hash <> p_credential_hash THEN
    RETURN jsonb_build_object('result', 'unauthorized');
  END IF;
  PERFORM ap.touch_device(d.id, p_agent_version);
  RETURN jsonb_build_object('result', 'ok', 'device_id', d.id, 'shop_id', d.shop_id);
END $$;

-- unchanged from 0004 except that the check-in goes through ap.touch_device
CREATE OR REPLACE FUNCTION ap.agent_poll(p_device_id uuid, p_credential_hash text, p_agent_version text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE d ap.devices%ROWTYPE; sh ap.shops%ROWTYPE; jobs jsonb; swept boolean := false;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND OR d.credential_hash <> p_credential_hash THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  PERFORM ap.touch_device(d.id, p_agent_version);
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
