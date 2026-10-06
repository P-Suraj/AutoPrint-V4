-- AutoPrint V4 — 0009 shopkeeper sign-in by email
--
-- The founder registers a shopkeeper's email for a shop. The shopkeeper asks for a sign-in link; the email provider
-- (Supabase Auth) proves they own that address; the API then asks this function for a normal shop login key. The key is
-- an ordinary 'email' row in ap.shop_logins, so every dashboard call keeps working unchanged and each sign-in can be
-- revoked on its own. Only a hash of the (lower-case) email is stored. An email string can never be used as a key:
-- the registered hashes live in their own table and are never looked up as credentials.

CREATE TABLE ap.shop_emails (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shop_id     uuid NOT NULL REFERENCES ap.shops(id),
  email_hash  text NOT NULL UNIQUE,
  label       text NOT NULL DEFAULT '' CHECK (length(label) <= 80),
  created_at  timestamptz NOT NULL DEFAULT now(),
  removed_at  timestamptz
);
ALTER TABLE ap.shop_emails ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION ap.shop_email_add(p_shop_code text, p_email_hash text, p_label text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE s ap.shops%ROWTYPE;
BEGIN
  SELECT * INTO s FROM ap.shops WHERE code = upper(p_shop_code) AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'shop_not_found'); END IF;
  INSERT INTO ap.shop_emails (shop_id, email_hash, label) VALUES (s.id, p_email_hash, left(coalesce(p_label, ''), 80))
  ON CONFLICT (email_hash) DO UPDATE SET shop_id = s.id, removed_at = NULL, label = EXCLUDED.label;
  PERFORM ap.log_event('shop_email.registered', 'founder', NULL, s.id, NULL, NULL, NULL, '{}'::jsonb);
  RETURN jsonb_build_object('result', 'ok');
END $$;

CREATE FUNCTION ap.shop_email_remove(p_email_hash text) RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
  UPDATE ap.shop_emails SET removed_at = now() WHERE email_hash = p_email_hash AND removed_at IS NULL;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'login_not_found'); END IF;
  RETURN jsonb_build_object('result', 'ok');
END $$;

-- is this email registered? (used before sending a sign-in email, so unknown addresses never receive one)
CREATE FUNCTION ap.shop_email_known(p_email_hash text) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (SELECT 1 FROM ap.shop_emails e JOIN ap.shops s ON s.id = e.shop_id
                  WHERE e.email_hash = p_email_hash AND e.removed_at IS NULL AND s.is_active)
$$;

-- the provider has proven ownership of this email: create a login key for its shop
CREATE FUNCTION ap.shop_email_login(p_email_hash text, p_key_hash text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE e ap.shop_emails%ROWTYPE; s ap.shops%ROWTYPE; l_id uuid;
BEGIN
  SELECT * INTO e FROM ap.shop_emails WHERE email_hash = p_email_hash AND removed_at IS NULL;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  SELECT * INTO s FROM ap.shops WHERE id = e.shop_id AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  -- keep the table tidy: old email sign-ins for this shop past 30 days are revoked
  UPDATE ap.shop_logins SET revoked_at = now() WHERE shop_id = s.id AND method = 'email' AND revoked_at IS NULL AND created_at < now() - interval '30 days';
  INSERT INTO ap.shop_logins (shop_id, method, credential_hash, label) VALUES (s.id, 'email', p_key_hash, left(coalesce(e.label, 'email'), 80))
  RETURNING id INTO l_id;
  PERFORM ap.log_event('shop_login.created', 'shop', NULL, s.id, NULL, NULL, NULL, jsonb_build_object('login_id', l_id, 'method', 'email'));
  RETURN jsonb_build_object('result', 'ok', 'shop_code', s.code, 'shop_name', s.name, 'login_id', l_id);
END $$;
