-- AutoPrint V4 — 0012 indexes for the shop poll and the founder report
--
-- Why: job rows are never deleted, and ap.jobs had no index that starts with shop_id except the one for claimable
-- jobs. The shop poll (ap.agent_poll, every 10 to 20 seconds per shop computer) therefore read the whole table to find
-- one shop's open jobs and its last 24 hours. Measured on a local PostgreSQL 17 with 200,000 jobs across 20 shops:
-- ap.agent_poll took about 43 ms (median of 20 calls) before these indexes and about 3 ms after. At pilot size (hundreds of jobs) the difference is not
-- noticeable; this keeps it that way as the table grows.
--
--   jobs_shop_open_idx      one shop's jobs that still need someone (the first half of the poll's filter)
--   jobs_shop_updated_idx   one shop's recently changed jobs (the second half)
--   jobs_shop_created_idx   one shop's jobs in a time window (the founder report and the all-shops list)
--
-- Safe on a database with existing rows: plain CREATE INDEX holds a write lock on ap.jobs only while it builds, which
-- is milliseconds at the current size. No data changes.

CREATE INDEX jobs_shop_open_idx ON ap.jobs (shop_id)
  WHERE status IN ('awaiting_approval', 'approved', 'printing', 'needs_attention');
CREATE INDEX jobs_shop_updated_idx ON ap.jobs (shop_id, updated_at);
CREATE INDEX jobs_shop_created_idx ON ap.jobs (shop_id, created_at);
