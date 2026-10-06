-- AutoPrint V4 — 0010 email sign-ins expire and follow their registered address
--
-- Why: an 'email' login key from 0009 lived until somebody signed in again more than 30 days later, and removing a
-- registered address (a helper who left) did not touch the keys that address had already been given.
--
--   * every email login remembers which registered address created it (email_id)
--   * removing an address, or moving it to another shop, revokes its logins at once
--   * an email login stops working 30 days after it was created, whether or not anyone signs in again
--   * 'link' logins are unchanged: they last until the founder revokes them

ALTER TABLE ap.shop_logins ADD COLUMN email_id uuid REFERENCES ap.shop_emails(id);
CREATE INDEX shop_logins_email_idx ON ap.shop_logins (email_id) WHERE email_id IS NOT NULL;

-- email logins made before this migration cannot be tied to an address: sign in again
UPDATE ap.shop_logins SET revoked_at = now() WHERE method = 'email' AND email_id IS NULL AND revoked_at IS NULL;

CREATE OR REPLACE FUNCTION ap.shop_login_resolve(p_credential_hash text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE l ap.shop_logins%ROWTYPE; s ap.shops%ROWTYPE;
BEGIN
  SELECT * INTO l FROM ap.shop_logins WHERE credential_hash = p_credential_hash AND revoked_at IS NULL;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  IF l.method = 'email' AND l.created_at <= now() - interval '30 days' THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  SELECT * INTO s FROM ap.shops WHERE id = l.shop_id AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  UPDATE ap.shop_logins SET last_used_at = now() WHERE id = l.id AND (last_used_at IS NULL OR last_used_at < now() - interval '1 minute');
  RETURN jsonb_build_object('result', 'ok', 'shop_code', s.code, 'shop_name', s.name, 'login_id', l.id);
END $$;

CREATE OR REPLACE FUNCTION ap.shop_email_add(p_shop_code text, p_email_hash text, p_label text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE s ap.shops%ROWTYPE;
BEGIN
  SELECT * INTO s FROM ap.shops WHERE code = upper(p_shop_code) AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'shop_not_found'); END IF;
  -- the address is being moved from another shop: its keys for the old shop stop working
  UPDATE ap.shop_logins l SET revoked_at = now() FROM ap.shop_emails e
   WHERE e.email_hash = p_email_hash AND e.shop_id <> s.id AND l.email_id = e.id AND l.revoked_at IS NULL;
  INSERT INTO ap.shop_emails (shop_id, email_hash, label) VALUES (s.id, p_email_hash, left(coalesce(p_label, ''), 80))
  ON CONFLICT (email_hash) DO UPDATE SET shop_id = s.id, removed_at = NULL, label = EXCLUDED.label;
  PERFORM ap.log_event('shop_email.registered', 'founder', NULL, s.id, NULL, NULL, NULL, '{}'::jsonb);
  RETURN jsonb_build_object('result', 'ok');
END $$;

CREATE OR REPLACE FUNCTION ap.shop_email_remove(p_email_hash text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE e_id uuid;
BEGIN
  UPDATE ap.shop_emails SET removed_at = now() WHERE email_hash = p_email_hash AND removed_at IS NULL RETURNING id INTO e_id;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'login_not_found'); END IF;
  UPDATE ap.shop_logins SET revoked_at = now() WHERE email_id = e_id AND revoked_at IS NULL;
  RETURN jsonb_build_object('result', 'ok');
END $$;

CREATE OR REPLACE FUNCTION ap.shop_email_login(p_email_hash text, p_key_hash text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE e ap.shop_emails%ROWTYPE; s ap.shops%ROWTYPE; l_id uuid;
BEGIN
  SELECT * INTO e FROM ap.shop_emails WHERE email_hash = p_email_hash AND removed_at IS NULL;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  SELECT * INTO s FROM ap.shops WHERE id = e.shop_id AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  -- keep the table tidy: expired email sign-ins for this shop are marked revoked (they already stopped working)
  UPDATE ap.shop_logins SET revoked_at = now() WHERE shop_id = s.id AND method = 'email' AND revoked_at IS NULL AND created_at < now() - interval '30 days';
  INSERT INTO ap.shop_logins (shop_id, method, credential_hash, label, email_id) VALUES (s.id, 'email', p_key_hash, left(coalesce(e.label, 'email'), 80), e.id)
  RETURNING id INTO l_id;
  PERFORM ap.log_event('shop_login.created', 'shop', NULL, s.id, NULL, NULL, NULL, jsonb_build_object('login_id', l_id, 'method', 'email'));
  RETURN jsonb_build_object('result', 'ok', 'shop_code', s.code, 'shop_name', s.name, 'login_id', l_id);
END $$;
