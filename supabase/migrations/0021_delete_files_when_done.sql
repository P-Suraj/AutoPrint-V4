-- AutoPrint V4 — 0021 a customer's file is deleted as soon as it is no longer needed
--
-- Why (founder, 7 October 2026): "the PDFs should be deleted once they are printed". Until now a file was kept for
-- 24 hours after its whole ORDER had ended (decision O-5), whatever happened to it, and a file that was uploaded
-- but left out of the order stayed for as long as the order was open (up to 48 hours).
--
-- Now each file follows its OWN job:
--   sent to the printer (completed), rejected, cancelled, not approved in time   delete now
--   uploaded but not part of the order that was sent                              delete now
--   did not go through (failed)                                                   keep 24 hours: the shopkeeper
--                                                                                  can still press "Print again"
--   waiting, approved, printing, needs attention                                  keep (hard cap 48 hours, as before)
--   order never sent (draft, abandoned)                                           1 hour from upload, as before
-- Nothing in the software can use a file after its job is completed, rejected, cancelled or expired (there is no
-- way to print those again), so nothing is lost by deleting it at once.
--
-- "Delete now" sets the deadline; the file itself is removed from storage by the next cleanup (the shop computer's
-- poll does one about once a minute, the scheduled workflow every 15 minutes), so in practice within a minute or
-- two while a shop computer is on.
--
-- A trigger keeps the deadline right whenever a job reaches one of those states, also while other files of the
-- same order are still waiting. The last statement applies the new rule to the files already stored.
-- Safe to run twice. Order of deployment: no API change is needed.

CREATE OR REPLACE FUNCTION ap.refresh_retention(p_order_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE o ap.orders%ROWTYPE;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE id = p_order_id;
  IF NOT FOUND THEN RETURN; END IF;
  UPDATE ap.documents d SET delete_after = CASE
      WHEN o.status = 'draft'     THEN least(d.created_at + interval '1 hour', o.access_until)
      -- cancelled or expired without ever being submitted: an abandoned upload, 1 hour from upload
      WHEN o.submitted_at IS NULL THEN least(d.created_at + interval '1 hour', o.access_until)
      -- the order was sent: the file's own job decides (j.status is NULL for a file that was left out of the order)
      WHEN j.status IS NULL OR j.status IN ('completed', 'rejected', 'cancelled', 'expired') THEN least(d.delete_after, now())
      WHEN j.status = 'failed'    THEN least(j.updated_at + interval '24 hours', o.access_until)
      ELSE o.access_until
    END
  FROM ap.documents d2 LEFT JOIN ap.jobs j ON j.document_id = d2.id
  WHERE d2.id = d.id AND d.order_id = p_order_id AND d.deleted_at IS NULL;
END $$;

CREATE OR REPLACE FUNCTION ap.jobs_refresh_retention() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM ap.refresh_retention(NEW.order_id);
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS jobs_refresh_retention ON ap.jobs;
CREATE TRIGGER jobs_refresh_retention AFTER UPDATE OF status ON ap.jobs FOR EACH ROW
  WHEN (OLD.status IS DISTINCT FROM NEW.status
        AND (NEW.status IN ('completed', 'failed', 'rejected', 'cancelled', 'expired') OR OLD.status = 'failed'))
  EXECUTE FUNCTION ap.jobs_refresh_retention();

-- the files already stored
SELECT ap.refresh_retention(o.id) FROM ap.orders o
 WHERE EXISTS (SELECT 1 FROM ap.documents d WHERE d.order_id = o.id AND d.deleted_at IS NULL);
