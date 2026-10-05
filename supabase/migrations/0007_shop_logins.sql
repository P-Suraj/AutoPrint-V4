-- AutoPrint V4 — 0007 shop owner logins
--
-- How a shopkeeper proves "I run this shop" to the web dashboard. One table, one column that names the METHOD,
-- so new ways in (phone OTP, email link) are added later as new rows with another method and the same dashboard
-- and the same functions keep working. Only a hash of the credential is stored.
--
--   method 'link'   a long secret in a private link or QR that the founder hands over (pilot)
--   method 'phone'  reserved: one-time code by SMS (later)
--   method 'email'  reserved: sign-in link by email (later)
--
-- A shop can have several logins (owner, helper) and each can be revoked on its own.

ALTER TYPE ap.actor_type ADD VALUE IF NOT EXISTS 'shop';

CREATE TABLE ap.shop_logins (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shop_id         uuid NOT NULL REFERENCES ap.shops(id),
  method          text NOT NULL CHECK (method IN ('link', 'phone', 'email')),
  credential_hash text NOT NULL UNIQUE,
  label           text NOT NULL DEFAULT '' CHECK (length(label) <= 80),
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_used_at    timestamptz,
  revoked_at      timestamptz
);
CREATE INDEX shop_logins_shop_idx ON ap.shop_logins (shop_id);
ALTER TABLE ap.shop_logins ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION ap.shop_login_create(p_shop_code text, p_method text, p_credential_hash text, p_label text) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE s ap.shops%ROWTYPE; l_id uuid;
BEGIN
  SELECT * INTO s FROM ap.shops WHERE code = upper(p_shop_code) AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'shop_not_found'); END IF;
  INSERT INTO ap.shop_logins (shop_id, method, credential_hash, label) VALUES (s.id, p_method, p_credential_hash, left(coalesce(p_label, ''), 80))
  RETURNING id INTO l_id;
  PERFORM ap.log_event('shop_login.created', 'founder', NULL, s.id, NULL, NULL, NULL, jsonb_build_object('login_id', l_id, 'method', p_method));
  RETURN jsonb_build_object('result', 'ok', 'login_id', l_id);
END $$;

CREATE FUNCTION ap.shop_login_revoke(p_login_id uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  UPDATE ap.shop_logins SET revoked_at = now() WHERE id = p_login_id AND revoked_at IS NULL;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'login_not_found'); END IF;
  RETURN jsonb_build_object('result', 'ok');
END $$;

-- who is this? (also the "who am I" call of the dashboard)
CREATE FUNCTION ap.shop_login_resolve(p_credential_hash text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE l ap.shop_logins%ROWTYPE; s ap.shops%ROWTYPE;
BEGIN
  SELECT * INTO l FROM ap.shop_logins WHERE credential_hash = p_credential_hash AND revoked_at IS NULL;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  SELECT * INTO s FROM ap.shops WHERE id = l.shop_id AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  UPDATE ap.shop_logins SET last_used_at = now() WHERE id = l.id AND (last_used_at IS NULL OR last_used_at < now() - interval '1 minute');
  RETURN jsonb_build_object('result', 'ok', 'shop_code', s.code, 'shop_name', s.name, 'login_id', l.id);
END $$;

-- pairing screens for the dashboard
CREATE FUNCTION ap.shop_pair_lookup(p_credential_hash text, p_code text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE who jsonb; r jsonb;
BEGIN
  who := ap.shop_login_resolve(p_credential_hash);
  IF who->>'result' <> 'ok' THEN RETURN who; END IF;
  r := ap.pair_lookup(p_code);
  IF r->>'result' <> 'ok' THEN RETURN r; END IF;
  RETURN r || jsonb_build_object('shop_name', who->>'shop_name');
END $$;

CREATE FUNCTION ap.shop_pair_approve(p_credential_hash text, p_code text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE who jsonb; r jsonb;
BEGIN
  who := ap.shop_login_resolve(p_credential_hash);
  IF who->>'result' <> 'ok' THEN RETURN who; END IF;
  r := ap.pair_approve(p_code, who->>'shop_code');
  IF r->>'result' = 'ok' THEN
    PERFORM ap.log_event('device.paired_by_shop', 'shop', NULL, (SELECT shop_id FROM ap.devices WHERE id = (r->>'device_id')::uuid), NULL, NULL, NULL,
                         jsonb_build_object('login_id', who->>'login_id'));
  END IF;
  RETURN r;
END $$;

-- the shop's computers, so the shopkeeper can see what is connected and disconnect one
CREATE FUNCTION ap.shop_devices(p_credential_hash text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE who jsonb;
BEGIN
  who := ap.shop_login_resolve(p_credential_hash);
  IF who->>'result' <> 'ok' THEN RETURN who; END IF;
  RETURN jsonb_build_object('result', 'ok', 'devices', coalesce((
    SELECT jsonb_agg(jsonb_build_object('device_id', d.id, 'name', d.display_name, 'last_seen_at', d.last_seen_at, 'revoked', d.status <> 'active') ORDER BY d.created_at DESC)
    FROM ap.devices d JOIN ap.shops s ON s.id = d.shop_id WHERE s.code = who->>'shop_code'), '[]'::jsonb));
END $$;

CREATE FUNCTION ap.shop_device_revoke(p_credential_hash text, p_device_id uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE who jsonb;
BEGIN
  who := ap.shop_login_resolve(p_credential_hash);
  IF who->>'result' <> 'ok' THEN RETURN who; END IF;
  UPDATE ap.devices d SET status = 'revoked', revoked_at = now() FROM ap.shops s
   WHERE d.id = p_device_id AND d.shop_id = s.id AND s.code = who->>'shop_code' AND d.status = 'active';
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'device_not_found'); END IF;
  RETURN jsonb_build_object('result', 'ok');
END $$;
