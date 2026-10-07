-- AutoPrint V4 — 0015 a deleted document no longer keeps its file name or its checksum
--
-- Why: when a stored file was deleted (retention deadline, or a purge the customer asked for) its row in ap.documents
-- kept original_name and sha256 for good, and every print attempt of it kept a copy of the checksum
-- (print_attempts.artifact_sha256). A file name is personal data ("Ravi-passport-scan.pdf"), and a checksum lets
-- anyone who holds a copy of a file prove that this exact file was sent to this shop. The promise to the customer is
-- that the document is gone. From now on the name and the checksum go when the file goes.
--
--   documents.original_name          becomes the fixed text 'deleted file' (the column is NOT NULL with a length
--                                    check of 1 to 255, and the customer page and the shop app expect some text)
--   documents.sha256                 becomes NULL (allowed for every status except 'validated'; the status is 'deleted')
--   print_attempts.artifact_sha256   becomes '' for the attempts of that document's jobs (the column is NOT NULL)
-- Nothing else changes: status, page count, byte size and the times stay, so the founder report (which reads none of
-- the three) and the job history are unaffected.
--
-- Who still sees a name, and when it goes:
--   * a job that can still print (awaiting approval, approved, printing) keeps its file and its name for the 48 hours
--     a submitted order lives: retention does not delete it sooner, and a purge is refused while such a job exists
--   * a finished job shows its real name until the file is deleted (24 hours after the order ended), then 'deleted file'
--   * a job still open past the 48 hour limit (left approved or in "needs attention") loses its file, as before, and
--     now its name too; the shopkeeper still has the order code, pages, copies and amount
-- The checksum is only ever sent to the shop computer together with a download link, which a deleted file never gets.
--
-- Locks: the function updates the document row and then its attempts. No other function locks a document and then
-- waits for an order, job or attempt held by someone who wants that document, so this adds no deadlock.
--
-- On a database with existing rows: the two UPDATEs at the end rewrite every document that is already deleted and
-- the attempts of its jobs. Ordinary row locks on those rows only, one statement each; at pilot size that is
-- milliseconds. It cannot be undone: the old names and checksums are gone, which is the point.

CREATE OR REPLACE FUNCTION ap.mark_document_deleted(p_document_id uuid) RETURNS void LANGUAGE sql AS $$
  WITH gone AS (
    UPDATE ap.documents SET status = 'deleted', deleted_at = now(), original_name = 'deleted file', sha256 = NULL
     WHERE id = p_document_id AND deleted_at IS NULL
    RETURNING id)
  UPDATE ap.print_attempts a SET artifact_sha256 = ''
    FROM ap.jobs j JOIN gone ON gone.id = j.document_id
   WHERE a.job_id = j.id
$$;

UPDATE ap.print_attempts a SET artifact_sha256 = ''
  FROM ap.jobs j JOIN ap.documents d ON d.id = j.document_id
 WHERE a.job_id = j.id AND d.deleted_at IS NOT NULL AND a.artifact_sha256 <> '';

UPDATE ap.documents SET original_name = 'deleted file', sha256 = NULL
 WHERE deleted_at IS NOT NULL AND (original_name <> 'deleted file' OR sha256 IS NOT NULL);
