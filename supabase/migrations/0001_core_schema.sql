-- AutoPrint V4 — 0001 core schema
--
-- Conventions
--   * Everything lives in schema "ap". This schema must NOT be added to Supabase's
--     "exposed schemas" list: the browser and the desktop app never talk to the database.
--   * Money is integer paise. No floats.
--   * Order, payment, job and print attempt are separate records with separate status.
--   * Enumerations are defined here once. The API's enum list is checked against these.
--   * Plain PostgreSQL only (no Supabase-specific objects), so the same files run on a
--     local test database and on Supabase.

CREATE SCHEMA IF NOT EXISTS ap;

-- ---------------------------------------------------------------- enumerations
CREATE TYPE ap.order_status   AS ENUM ('draft', 'submitted', 'closed', 'cancelled', 'expired');
CREATE TYPE ap.document_status AS ENUM ('pending_upload', 'validated', 'rejected', 'deleted');
CREATE TYPE ap.payment_mode   AS ENUM ('pay_at_counter', 'finflow');
CREATE TYPE ap.payment_status AS ENUM ('not_required', 'pending', 'paid', 'failed', 'refunded');
CREATE TYPE ap.job_status     AS ENUM (
  'awaiting_approval', 'approved', 'printing', 'completed', 'failed',
  'needs_attention', 'rejected', 'cancelled', 'expired'
);
CREATE TYPE ap.attempt_status AS ENUM ('claimed', 'sent_to_spooler', 'completed', 'failed', 'uncertain');
CREATE TYPE ap.actor_type     AS ENUM ('customer', 'device', 'system', 'founder');
CREATE TYPE ap.device_status  AS ENUM ('active', 'revoked');

-- ---------------------------------------------------------------- shops and devices
CREATE TABLE ap.shops (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code        text NOT NULL UNIQUE CHECK (code ~ '^[A-Z]{3}[0-9]{3}$'),
  name        text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  is_active   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Rates are versioned and immutable once used. Rules JSON shape is validated by the API
-- (see docs/CONTRACTS.md, "Pricing"); the database only requires a JSON object.
CREATE TABLE ap.rate_cards (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shop_id     uuid NOT NULL REFERENCES ap.shops(id),
  version     integer NOT NULL CHECK (version >= 1),
  rules       jsonb NOT NULL CHECK (jsonb_typeof(rules) = 'object'),
  created_at  timestamptz NOT NULL DEFAULT now(),
  retired_at  timestamptz,
  UNIQUE (shop_id, version)
);
CREATE UNIQUE INDEX one_active_rate_card_per_shop ON ap.rate_cards (shop_id) WHERE retired_at IS NULL;

CREATE TABLE ap.devices (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shop_id          uuid NOT NULL REFERENCES ap.shops(id),
  display_name     text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 80),
  credential_hash  text NOT NULL,                 -- SHA-256 of the device secret; secret itself is never stored
  status           ap.device_status NOT NULL DEFAULT 'active',
  agent_version    text,
  last_seen_at     timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  revoked_at       timestamptz
);
CREATE INDEX devices_shop_idx ON ap.devices (shop_id) WHERE status = 'active';

CREATE TABLE ap.enrollment_codes (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shop_id      uuid NOT NULL REFERENCES ap.shops(id),
  code_hash    text NOT NULL UNIQUE,
  expires_at   timestamptz NOT NULL,
  consumed_at  timestamptz,
  device_id    uuid REFERENCES ap.devices(id),
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK ((consumed_at IS NULL) = (device_id IS NULL))
);

-- ---------------------------------------------------------------- orders and documents
-- expires_at: while the order is draft it is the abandonment deadline; once submitted it is the
-- 1-hour approval window (decision O-10). It is cleared when every job has been approved or the
-- order reaches a final state. access_until is the hard cap (48 h from creation, decision O-5):
-- the order secret stops working after it, and documents are gone by then.
CREATE TABLE ap.orders (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shop_id       uuid NOT NULL REFERENCES ap.shops(id),
  short_code    text NOT NULL CHECK (short_code ~ '^[A-Z0-9]{4}$'),
  secret_hash   text NOT NULL UNIQUE,             -- SHA-256 of the order secret; the secret is the customer's only credential
  status        ap.order_status NOT NULL DEFAULT 'draft',
  expires_at    timestamptz,
  access_until  timestamptz NOT NULL,
  submitted_at  timestamptz,
  closed_at     timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (access_until > created_at)
);
CREATE INDEX orders_shop_status_idx ON ap.orders (shop_id, status);
CREATE INDEX orders_expiry_idx ON ap.orders (expires_at) WHERE expires_at IS NOT NULL;

CREATE TABLE ap.documents (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id       uuid NOT NULL REFERENCES ap.orders(id),
  position       integer NOT NULL DEFAULT 1 CHECK (position >= 1),
  original_name  text NOT NULL CHECK (length(original_name) BETWEEN 1 AND 255),
  declared_bytes bigint NOT NULL CHECK (declared_bytes BETWEEN 1 AND 26214400),   -- 25 MiB
  object_key     text NOT NULL UNIQUE,
  status         ap.document_status NOT NULL DEFAULT 'pending_upload',
  sha256         text CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  verified_bytes bigint CHECK (verified_bytes > 0),
  page_count     integer CHECK (page_count BETWEEN 1 AND 2000),
  reject_reason  text,
  delete_after   timestamptz NOT NULL,            -- retention deadline; see ap.refresh_retention()
  deleted_at     timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (order_id, position),
  CHECK (status <> 'validated' OR (sha256 IS NOT NULL AND page_count IS NOT NULL AND verified_bytes IS NOT NULL))
);
CREATE INDEX documents_delete_idx ON ap.documents (delete_after) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------- quotes (immutable)
CREATE TABLE ap.quotes (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id           uuid NOT NULL REFERENCES ap.orders(id),
  rate_card_id       uuid NOT NULL REFERENCES ap.rate_cards(id),
  total_paise        integer NOT NULL CHECK (total_paise >= 0),
  currency           text NOT NULL DEFAULT 'INR' CHECK (currency = 'INR'),
  created_at         timestamptz NOT NULL DEFAULT now(),
  accepted_at        timestamptz
);
CREATE UNIQUE INDEX one_accepted_quote_per_order ON ap.quotes (order_id) WHERE accepted_at IS NOT NULL;

CREATE TABLE ap.quote_items (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quote_id        uuid NOT NULL REFERENCES ap.quotes(id),
  document_id     uuid NOT NULL REFERENCES ap.documents(id),
  copies          integer NOT NULL CHECK (copies BETWEEN 1 AND 100),
  color           boolean NOT NULL,
  duplex          boolean NOT NULL,
  page_range      text,                              -- NULL = all pages; validated by the API
  selected_pages  integer NOT NULL CHECK (selected_pages >= 1),
  printed_sides   integer NOT NULL CHECK (printed_sides >= 1),
  amount_paise    integer NOT NULL CHECK (amount_paise >= 0),
  UNIQUE (quote_id, document_id)
);

-- ---------------------------------------------------------------- payment (state only; FinFlow owns money)
CREATE TABLE ap.payments (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id      uuid NOT NULL UNIQUE REFERENCES ap.orders(id),
  mode          ap.payment_mode NOT NULL DEFAULT 'pay_at_counter',
  status        ap.payment_status NOT NULL DEFAULT 'not_required',
  amount_paise  integer NOT NULL CHECK (amount_paise >= 0),
  external_ref  text,                                -- FinFlow payment reference (Phase 9)
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (mode = 'finflow' OR status = 'not_required')
);

-- ---------------------------------------------------------------- jobs and attempts
CREATE TABLE ap.jobs (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id           uuid NOT NULL REFERENCES ap.orders(id),
  shop_id            uuid NOT NULL REFERENCES ap.shops(id),
  document_id        uuid NOT NULL REFERENCES ap.documents(id),
  quote_item_id      uuid NOT NULL UNIQUE REFERENCES ap.quote_items(id),
  status             ap.job_status NOT NULL DEFAULT 'awaiting_approval',
  approved_at        timestamptz,
  current_attempt_id uuid,                           -- FK added below
  attempt_count      integer NOT NULL DEFAULT 0,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_claimable_idx ON ap.jobs (shop_id, approved_at) WHERE status = 'approved';
CREATE INDEX jobs_order_idx ON ap.jobs (order_id);

CREATE TABLE ap.print_attempts (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id           uuid NOT NULL REFERENCES ap.jobs(id),
  device_id        uuid NOT NULL REFERENCES ap.devices(id),
  attempt_token_hash text NOT NULL UNIQUE,         -- SHA-256 of the fencing token; proves the caller owns this attempt
  spooler_job_name text NOT NULL UNIQUE,             -- unique document name the agent must give the spooler
  artifact_sha256  text NOT NULL,
  status           ap.attempt_status NOT NULL DEFAULT 'claimed',
  lease_expires_at timestamptz NOT NULL,
  sent_at          timestamptz,
  finished_at      timestamptz,
  evidence         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX attempts_job_idx ON ap.print_attempts (job_id);
CREATE INDEX attempts_lease_idx ON ap.print_attempts (lease_expires_at) WHERE status IN ('claimed', 'sent_to_spooler');

ALTER TABLE ap.jobs
  ADD CONSTRAINT jobs_current_attempt_fk FOREIGN KEY (current_attempt_id) REFERENCES ap.print_attempts(id);

-- ---------------------------------------------------------------- events (append-only audit and metrics)
CREATE TABLE ap.events (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at          timestamptz NOT NULL DEFAULT now(),
  shop_id     uuid REFERENCES ap.shops(id),
  order_id    uuid REFERENCES ap.orders(id),
  job_id      uuid REFERENCES ap.jobs(id),
  attempt_id  uuid REFERENCES ap.print_attempts(id),
  type        text NOT NULL,
  actor       ap.actor_type NOT NULL,
  actor_id    uuid,
  data        jsonb NOT NULL DEFAULT '{}'::jsonb      -- never store secrets, URLs, file names or document content
);
CREATE INDEX events_job_idx ON ap.events (job_id, id);
CREATE INDEX events_order_idx ON ap.events (order_id, id);
CREATE INDEX events_shop_time_idx ON ap.events (shop_id, at);

CREATE FUNCTION ap.events_are_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'ap.events is append-only';
END $$;
CREATE TRIGGER events_no_update BEFORE UPDATE OR DELETE ON ap.events
  FOR EACH ROW EXECUTE FUNCTION ap.events_are_append_only();

-- ---------------------------------------------------------------- allowed state transitions
-- One row per legal (entity, from, to, actor). Functions check this table; tests assert
-- every legal row works and that illegal moves are refused.
CREATE TABLE ap.allowed_transitions (
  entity      text NOT NULL CHECK (entity IN ('order', 'job', 'attempt')),
  from_status text NOT NULL,
  to_status   text NOT NULL,
  actor       ap.actor_type NOT NULL,
  PRIMARY KEY (entity, from_status, to_status, actor)
);

INSERT INTO ap.allowed_transitions (entity, from_status, to_status, actor) VALUES
  -- order
  ('order', 'draft',     'submitted', 'customer'),
  ('order', 'draft',     'expired',   'system'),
  ('order', 'draft',     'cancelled', 'customer'),
  ('order', 'submitted', 'cancelled', 'customer'),
  ('order', 'submitted', 'closed',    'system'),
  -- job
  ('job', 'awaiting_approval', 'approved',  'device'),
  ('job', 'awaiting_approval', 'rejected',  'device'),
  ('job', 'awaiting_approval', 'cancelled', 'customer'),
  ('job', 'awaiting_approval', 'expired',   'system'),
  ('job', 'approved',          'printing',  'device'),
  ('job', 'approved',          'cancelled', 'customer'),
  ('job', 'printing',          'completed', 'device'),
  ('job', 'printing',          'failed',    'device'),
  ('job', 'printing',          'needs_attention', 'device'),
  ('job', 'printing',          'needs_attention', 'system'),
  ('job', 'needs_attention',   'completed', 'device'),   -- shopkeeper resolves in the desktop app
  ('job', 'needs_attention',   'failed',    'device'),
  ('job', 'needs_attention',   'approved',  'device'),   -- explicit human retry; never automatic
  ('job', 'failed',            'approved',  'device'),   -- explicit human retry; never automatic
  -- attempt
  ('attempt', 'claimed',         'sent_to_spooler', 'device'),
  ('attempt', 'claimed',         'failed',          'device'),
  ('attempt', 'claimed',         'uncertain',       'system'),
  ('attempt', 'claimed',         'uncertain',       'device'),
  ('attempt', 'sent_to_spooler', 'completed',       'device'),
  ('attempt', 'sent_to_spooler', 'failed',          'device'),
  ('attempt', 'sent_to_spooler', 'uncertain',       'device'),
  ('attempt', 'sent_to_spooler', 'uncertain',       'system');

-- ---------------------------------------------------------------- defence in depth
-- The database is not exposed to browsers. If Supabase's API roles exist, remove their access anyway
-- and enable row-level security with no policies, so an accidental exposure returns nothing.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON SCHEMA ap FROM %I', r);
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA ap FROM %I', r);
    END IF;
  END LOOP;
END $$;

DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'ap' LOOP
    EXECUTE format('ALTER TABLE ap.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;
