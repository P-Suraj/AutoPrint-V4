-- AutoPrint V4 — 0008 request rate limits
--
-- A small fixed-window counter in the database (no extra service, nothing to pay for). The API hashes the caller's
-- address with a server-side secret, so the table never holds an address. Used for the entry points that create work:
-- new orders (per address and per shop) and new pairing codes.

CREATE TABLE ap.rate_limits (
  bucket        text        NOT NULL,
  window_start  timestamptz NOT NULL,
  hits          integer     NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket, window_start)
);
ALTER TABLE ap.rate_limits ENABLE ROW LEVEL SECURITY;

-- Counts one hit and returns true when the caller is still within the limit.
CREATE FUNCTION ap.rate_hit(p_bucket text, p_window_seconds integer, p_max integer) RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE w timestamptz; n integer;
BEGIN
  IF p_window_seconds < 1 OR p_max < 1 THEN RAISE EXCEPTION 'bad rate limit'; END IF;
  w := to_timestamp(floor(extract(epoch FROM now()) / p_window_seconds) * p_window_seconds);
  INSERT INTO ap.rate_limits (bucket, window_start, hits) VALUES (p_bucket, w, 1)
  ON CONFLICT (bucket, window_start) DO UPDATE SET hits = ap.rate_limits.hits + 1
  RETURNING hits INTO n;
  IF random() < 0.01 THEN                                  -- housekeeping: old windows are of no use
    DELETE FROM ap.rate_limits WHERE window_start < now() - interval '1 day';
  END IF;
  RETURN n <= p_max;
END $$;
