-- AutoPrint V4 — 0006 completion rule, version 2
--
-- Why: version 1 also required "max_pages_printed >= 1". Measured on 5 Oct 2026 with the .NET Windows printing API
-- (System.Printing) against the virtual printer: a job that DID print (the output file exists, 1 page) was reported
-- with 0 pages printed for its whole life in the queue. Printer drivers often report no page count until the very
-- end, so the requirement would have forced a person to resolve jobs that printed correctly, defeating automatic
-- completion (decision F-8). The pages-printed number is still recorded, as information only.
--
-- Version 2 requires ALL of:
--   spooler_job_seen   the job was found in the Windows spooler under the unique name we gave it
--   printing_seen      the spooler reported it as PRINTING at some point
--   left_queue         the job was seen leaving the queue
--   no bad flag        none of ERROR, DELETING, DELETED, OFFLINE, PAPEROUT, BLOCKED_DEVQ, USER_INTERVENTION, RESTART
--
-- "Left the queue" alone is still never enough: a job cancelled at the printer also leaves it, and is caught by the
-- DELETING flag. Anything else is reported uncertain or failed and resolved by a person. Never retried automatically.
-- Still provisional: must be re-validated on the physical printer before the pilot.

CREATE OR REPLACE FUNCTION ap.evidence_supports_completion(p_evidence jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  flags jsonb;
  bad constant text[] := ARRAY['ERROR','DELETING','DELETED','OFFLINE','PAPEROUT','BLOCKED_DEVQ','USER_INTERVENTION','RESTART'];
  f text;
BEGIN
  IF p_evidence IS NULL OR jsonb_typeof(p_evidence) <> 'object' THEN RETURN false; END IF;
  IF (p_evidence->>'rule_version') IS DISTINCT FROM '2' THEN RETURN false; END IF;
  IF (p_evidence->'spooler_job_seen') IS DISTINCT FROM 'true'::jsonb THEN RETURN false; END IF;
  IF (p_evidence->'printing_seen')    IS DISTINCT FROM 'true'::jsonb THEN RETURN false; END IF;
  IF (p_evidence->'left_queue')       IS DISTINCT FROM 'true'::jsonb THEN RETURN false; END IF;
  flags := p_evidence->'flags_seen';
  IF flags IS NULL OR jsonb_typeof(flags) <> 'array' THEN RETURN false; END IF;
  FOR f IN SELECT jsonb_array_elements_text(flags) LOOP
    IF f = ANY (bad) THEN RETURN false; END IF;
  END LOOP;
  RETURN true;
END $$;
