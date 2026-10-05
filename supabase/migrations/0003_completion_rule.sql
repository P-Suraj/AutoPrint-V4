-- AutoPrint V4 — 0003 completion rule (version 1)
--
-- Source: docs/PRINT_SPIKE_REPORT.md. Measured on a VIRTUAL printer only (Microsoft Print to PDF);
-- it MUST be re-validated on the pilot's physical printer before Phase 8 (decision F-8, O-8).
--
-- A job may be recorded "completed" only when the agent's evidence shows ALL of:
--   spooler_job_seen   the job was found in the Windows spooler under the unique name we gave it
--   printing_seen      the spooler reported it as PRINTING at some point
--   left_queue         the job was seen leaving the queue
--   no bad flag        none of ERROR, DELETING, DELETED, OFFLINE, PAPEROUT, BLOCKED_DEVQ,
--                      USER_INTERVENTION, RESTART appeared in flags_seen at any sample
--   max_pages_printed  at least 1 page was reported printed
--
-- Deliberately NOT required: pages printed equal to the page total. In the spike the last
-- increment was missed in 4 of 37 jobs because the job leaves the queue between samples.
--
-- Deliberately NOT sufficient: "the job left the queue". A job cancelled at the printer also
-- leaves the queue; it is told apart by the DELETING flag.
--
-- Anything that does not satisfy this rule is reported as 'uncertain' or 'failed' by the agent
-- and ends in needs_attention or failed, for a human. It is never retried automatically.

CREATE OR REPLACE FUNCTION ap.evidence_supports_completion(p_evidence jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  flags jsonb;
  bad constant text[] := ARRAY['ERROR','DELETING','DELETED','OFFLINE','PAPEROUT','BLOCKED_DEVQ','USER_INTERVENTION','RESTART'];
  f text;
BEGIN
  IF p_evidence IS NULL OR jsonb_typeof(p_evidence) <> 'object' THEN RETURN false; END IF;
  IF (p_evidence->>'rule_version') IS DISTINCT FROM '1' THEN RETURN false; END IF;
  IF (p_evidence->'spooler_job_seen') IS DISTINCT FROM 'true'::jsonb THEN RETURN false; END IF;
  IF (p_evidence->'printing_seen')    IS DISTINCT FROM 'true'::jsonb THEN RETURN false; END IF;
  IF (p_evidence->'left_queue')       IS DISTINCT FROM 'true'::jsonb THEN RETURN false; END IF;
  flags := p_evidence->'flags_seen';
  IF flags IS NULL OR jsonb_typeof(flags) <> 'array' THEN RETURN false; END IF;
  FOR f IN SELECT jsonb_array_elements_text(flags) LOOP
    IF f = ANY (bad) THEN RETURN false; END IF;
  END LOOP;
  -- NULL-safe: a missing field must fail closed, never fall through to true
  IF jsonb_typeof(p_evidence->'max_pages_printed') IS DISTINCT FROM 'number' THEN RETURN false; END IF;
  IF (p_evidence->>'max_pages_printed')::numeric < 1 THEN RETURN false; END IF;
  RETURN true;
END $$;
