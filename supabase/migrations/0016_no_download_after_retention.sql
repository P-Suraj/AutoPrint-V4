-- AutoPrint V4 — 0016 no download link for a file whose retention deadline has passed
--
-- Why: ap.job_document (the shop app's Preview) refused a document only once the cleanup had marked it deleted. The
-- cleanup runs every minute while a shop is online and every 15 minutes otherwise, and it can fail (file store
-- unreachable). In that gap a file past its deadline (documents.delete_after) could still be downloaded. The deadline
-- is the promise made to the customer, so it is now enforced here as well: past it the answer is "document_not_found",
-- the same as after the cleanup. ap.claim_next_job has the same rule since 0014.
--
-- The only change is "OR doc.delete_after <= now()". Everything else is the text of 0004.
-- Safe on a database with existing rows: it replaces a function and touches no data.

CREATE OR REPLACE FUNCTION ap.job_document(p_job_id uuid, p_device_id uuid) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE d ap.devices%ROWTYPE; doc ap.documents%ROWTYPE;
BEGIN
  SELECT * INTO d FROM ap.devices WHERE id = p_device_id AND status = 'active';
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'unauthorized'); END IF;
  SELECT doc2.* INTO doc FROM ap.jobs j JOIN ap.documents doc2 ON doc2.id = j.document_id
   WHERE j.id = p_job_id AND j.shop_id = d.shop_id;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'job_not_found'); END IF;
  IF doc.deleted_at IS NOT NULL OR doc.status <> 'validated' OR doc.delete_after <= now() THEN
    RETURN jsonb_build_object('result', 'document_not_found');
  END IF;
  RETURN jsonb_build_object('result', 'ok', 'object_key', doc.object_key, 'sha256', doc.sha256, 'bytes', doc.verified_bytes);
END $$;
