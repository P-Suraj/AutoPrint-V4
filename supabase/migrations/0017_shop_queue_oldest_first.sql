-- AutoPrint V4 — 0017 the shop's queue lists open jobs oldest first and never hides them behind newer ones
--
-- Why: ap.agent_poll returned the 60 newest jobs of the shop, open and finished together. A few orders with many
-- files each (20 files per order is allowed) were enough to push older jobs that were still waiting off the
-- shopkeeper's screen: they could not be approved and expired unseen. Anyone can send an order, so anyone could do it.
--
-- Now the list is built from two separate groups:
--   open      awaiting approval, approved, printing, needs attention: OLDEST first (the one waiting longest is on
--             top), up to 300. Finished jobs can no longer take any of these places. 300 is a guard on the size of
--             the answer, not a working limit: 0018 keeps a shop's waiting jobs at 150 or fewer.
--   finished  everything else that changed in the last 24 hours: most recently finished first, at most 40.
-- The answer has the same fields as before; only which jobs are in it and their order changed.
--
-- Speed: still ONE round trip. The open group is read through jobs_shop_open_idx and the finished group through
-- jobs_shop_updated_idx (both from 0012); the details are then joined by primary key for the rows that are returned.
-- Everything before the job list is the text of 0011.
-- Safe on a database with existing rows: it replaces a function and touches no data.

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

  SELECT COALESCE(jsonb_agg(to_jsonb(r) - 'sort_group' - 'ord' ORDER BY r.sort_group, r.ord), '[]'::jsonb) INTO jobs FROM (
    SELECT j.id AS job_id, o.short_code AS order_short_code, doc.original_name AS document_name, doc.page_count,
           qi.copies, qi.color, qi.duplex, qi.page_range, qi.amount_paise, j.status, j.created_at,
           CASE WHEN j.status = 'awaiting_approval' THEN o.expires_at END AS approval_expires_at,
           j.attempt_count, pick.sort_group, pick.ord
      FROM (
            (SELECT x.id, 0 AS sort_group, row_number() OVER (ORDER BY x.created_at, x.id) AS ord
               FROM ap.jobs x
              WHERE x.shop_id = d.shop_id AND x.status IN ('awaiting_approval', 'approved', 'printing', 'needs_attention')
              ORDER BY x.created_at, x.id LIMIT 300)
            UNION ALL
            (SELECT x.id, 1 AS sort_group, row_number() OVER (ORDER BY x.updated_at DESC, x.id) AS ord
               FROM ap.jobs x
              WHERE x.shop_id = d.shop_id AND x.updated_at > now() - interval '24 hours'
                AND x.status NOT IN ('awaiting_approval', 'approved', 'printing', 'needs_attention')
              ORDER BY x.updated_at DESC, x.id LIMIT 40)
           ) pick
      JOIN ap.jobs j ON j.id = pick.id
      JOIN ap.orders o ON o.id = j.order_id
      JOIN ap.documents doc ON doc.id = j.document_id
      JOIN ap.quote_items qi ON qi.id = j.quote_item_id) r;

  RETURN jsonb_build_object('result', 'ok', 'device_id', d.id, 'shop_code', sh.code, 'shop_name', sh.name,
                            'jobs', jobs, 'swept', swept);
END $$;
