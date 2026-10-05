-- AutoPrint V4 — 0005 device-initiated pairing
--
-- The shop PC shows a short code on its own screen. The founder, on the phone with the shopkeeper, checks the
-- PC name and approves that code for a shop. The device generates its own secret and sends it once at the start;
-- the server stores only its hash, so no secret ever has to come back to the PC.
--
--   pair_start    device     registers (poll token hash, secret hash, PC name) and receives a code
--   pair_lookup   founder    shows which PC owns a code before approving
--   pair_approve  founder    ties the code to a shop; this creates the active device
--   pair_poll     device     asks whether it was approved (no secret in the answer)

CREATE TABLE ap.pairings (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code             text NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9]{8}$'),
  poll_hash        text NOT NULL UNIQUE,
  credential_hash  text NOT NULL,
  display_name     text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 80),
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  shop_id          uuid REFERENCES ap.shops(id),
  device_id        uuid REFERENCES ap.devices(id),
  approved_at      timestamptz,
  CHECK ((device_id IS NULL) = (approved_at IS NULL))
);
CREATE INDEX pairings_created_idx ON ap.pairings (created_at);
ALTER TABLE ap.pairings ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION ap.pair_start(p_poll_hash text, p_credential_hash text, p_display_name text) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE alphabet constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; c text; tries integer := 0; exp timestamptz;
BEGIN
  -- global brake on abuse: at most 60 new pairings a minute, across everyone
  IF (SELECT count(*) FROM ap.pairings WHERE created_at > now() - interval '1 minute') >= 60 THEN
    RETURN jsonb_build_object('result', 'try_again');
  END IF;
  LOOP
    c := '';
    FOR i IN 1..8 LOOP c := c || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1); END LOOP;
    EXIT WHEN NOT EXISTS (SELECT 1 FROM ap.pairings WHERE code = c);
    tries := tries + 1;
    IF tries > 10 THEN RETURN jsonb_build_object('result', 'try_again'); END IF;
  END LOOP;
  exp := now() + interval '15 minutes';
  INSERT INTO ap.pairings (code, poll_hash, credential_hash, display_name, expires_at)
  VALUES (c, p_poll_hash, p_credential_hash, left(btrim(p_display_name), 80), exp);
  RETURN jsonb_build_object('result', 'ok', 'code', c, 'expires_at', exp);
EXCEPTION WHEN unique_violation THEN
  RETURN jsonb_build_object('result', 'try_again');
END $$;

CREATE FUNCTION ap.pair_lookup(p_code text) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE p ap.pairings%ROWTYPE;
BEGIN
  SELECT * INTO p FROM ap.pairings WHERE code = upper(replace(btrim(p_code), '-', ''));
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'pairing_not_found'); END IF;
  RETURN jsonb_build_object('result', 'ok', 'display_name', p.display_name, 'created_at', p.created_at,
                            'expired', p.expires_at <= now(), 'approved', p.approved_at IS NOT NULL);
END $$;

CREATE FUNCTION ap.pair_approve(p_code text, p_shop_code text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE p ap.pairings%ROWTYPE; s ap.shops%ROWTYPE; d_id uuid;
BEGIN
  SELECT * INTO p FROM ap.pairings WHERE code = upper(replace(btrim(p_code), '-', '')) FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'pairing_not_found'); END IF;
  IF p.expires_at <= now() THEN RETURN jsonb_build_object('result', 'pairing_expired'); END IF;
  IF p.approved_at IS NOT NULL THEN RETURN jsonb_build_object('result', 'pairing_already_approved'); END IF;
  SELECT * INTO s FROM ap.shops WHERE code = upper(p_shop_code) AND is_active;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'shop_not_found'); END IF;
  INSERT INTO ap.devices (shop_id, display_name, credential_hash) VALUES (s.id, p.display_name, p.credential_hash) RETURNING id INTO d_id;
  UPDATE ap.pairings SET shop_id = s.id, device_id = d_id, approved_at = now() WHERE id = p.id;
  PERFORM ap.log_event('device.paired', 'founder', NULL, s.id, NULL, NULL, NULL, jsonb_build_object('device_id', d_id));
  RETURN jsonb_build_object('result', 'ok', 'device_id', d_id, 'shop_code', s.code, 'display_name', p.display_name);
END $$;

CREATE FUNCTION ap.pair_poll(p_poll_hash text) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE p ap.pairings%ROWTYPE; s ap.shops%ROWTYPE;
BEGIN
  SELECT * INTO p FROM ap.pairings WHERE poll_hash = p_poll_hash;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'pairing_not_found'); END IF;
  IF p.approved_at IS NOT NULL THEN
    SELECT * INTO s FROM ap.shops WHERE id = p.shop_id;
    RETURN jsonb_build_object('result', 'ok', 'status', 'approved', 'device_id', p.device_id, 'shop_code', s.code, 'shop_name', s.name);
  END IF;
  IF p.expires_at <= now() THEN RETURN jsonb_build_object('result', 'ok', 'status', 'expired'); END IF;
  RETURN jsonb_build_object('result', 'ok', 'status', 'pending');
END $$;
