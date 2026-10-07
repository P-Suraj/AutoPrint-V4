-- AutoPrint V4 — 0020 the shopkeeper sets the shop's name, prices and whether it prints in colour
--
-- Why (founder, 7 October 2026): until now only the founder could rename a shop or publish its prices, with the
-- maintenance token. A shopkeeper must be able to do both from the dashboard. Some shops have no colour printer:
-- they must be able to say so, and their customers must be told before they choose colour.
--
-- What is added:
--   ap.shops.color_enabled        true (every existing shop keeps printing colour) or false
--   ap.shop_settings(key hash)    what the dashboard shows: name, colour on or off, the price list in use
--   ap.shop_settings_update(...)  changes any of the three; a changed price list is a NEW version (the old one is
--                                 retired, never edited, so a quote already made keeps the prices it was made with)
--   ap.agent_poll                 each job now also says how many files its order has and the order's total, so
--                                 the shop computer can show what to collect for an order with several files
--
-- Order of deployment: the API works with or without this file. Without it the customer page says colour is
-- available (as it was), the shop computer shows each file's own amount (as it did), and the dashboard's new
-- "Prices and shop details" panel says it cannot load. Nothing else depends on it.
--
-- Safe on a database with existing rows: one new column with a default, two new functions, and ap.agent_poll
-- replaced with the text of 0017 plus two values per job.

ALTER TABLE ap.shops ADD COLUMN IF NOT EXISTS color_enabled boolean NOT NULL DEFAULT true;

CREATE OR REPLACE FUNCTION ap.shop_settings(p_credential_hash text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE who jsonb; s ap.shops%ROWTYPE; rc ap.rate_cards%ROWTYPE;
BEGIN
  who := ap.shop_login_resolve(p_credential_hash);
  IF who->>'result' <> 'ok' THEN RETURN who; END IF;
  SELECT * INTO s FROM ap.shops WHERE code = who->>'shop_code';
  SELECT * INTO rc FROM ap.rate_cards WHERE shop_id = s.id AND retired_at IS NULL;
  RETURN jsonb_build_object('result', 'ok', 'shop_code', s.code, 'shop_name', s.name, 'color_enabled', s.color_enabled,
                            'rate_card_version', rc.version, 'rules', rc.rules);
END $$;

-- NULL for a value means "leave it as it is". The API checks the shape of p_rules before calling (app/pricing.py),
-- as it does for the founder's route.
CREATE OR REPLACE FUNCTION ap.shop_settings_update(p_credential_hash text, p_name text, p_color_enabled boolean, p_rules jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE who jsonb; s ap.shops%ROWTYPE; rc ap.rate_cards%ROWTYPE; new_name text; new_color boolean; new_version integer;
BEGIN
  who := ap.shop_login_resolve(p_credential_hash);
  IF who->>'result' <> 'ok' THEN RETURN who; END IF;
  SELECT * INTO s FROM ap.shops WHERE code = who->>'shop_code' FOR UPDATE;
  new_name := COALESCE(NULLIF(btrim(p_name), ''), s.name);
  new_color := COALESCE(p_color_enabled, s.color_enabled);
  IF length(new_name) > 80 THEN RETURN jsonb_build_object('result', 'invalid_items'); END IF;
  IF new_name <> s.name OR new_color <> s.color_enabled THEN
    UPDATE ap.shops SET name = new_name, color_enabled = new_color WHERE id = s.id;
  END IF;
  IF p_rules IS NOT NULL THEN
    SELECT * INTO rc FROM ap.rate_cards WHERE shop_id = s.id AND retired_at IS NULL;
    IF NOT FOUND OR rc.rules <> p_rules THEN
      SELECT COALESCE(max(version), 0) + 1 INTO new_version FROM ap.rate_cards WHERE shop_id = s.id;
      UPDATE ap.rate_cards SET retired_at = now() WHERE shop_id = s.id AND retired_at IS NULL;
      INSERT INTO ap.rate_cards (shop_id, version, rules) VALUES (s.id, new_version, p_rules);
    END IF;
  END IF;
  IF new_name <> s.name OR new_color <> s.color_enabled OR new_version IS NOT NULL THEN
    PERFORM ap.log_event('shop.settings_changed', 'shop', (who->>'login_id')::uuid, s.id, NULL, NULL, NULL,
                         jsonb_build_object('renamed', new_name <> s.name, 'color_enabled', new_color, 'rate_card_version', new_version));
  END IF;
  RETURN ap.shop_settings(p_credential_hash);
END $$;

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
           j.attempt_count,
           (SELECT count(*) FROM ap.jobs oj WHERE oj.order_id = j.order_id) AS order_files,
           (SELECT q.total_paise FROM ap.quotes q WHERE q.id = qi.quote_id) AS order_total_paise,
           pick.sort_group, pick.ord
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
