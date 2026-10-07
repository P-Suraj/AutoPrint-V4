-- AutoPrint V4 — 0018 a shop can have at most 150 jobs waiting for approval
--
-- Why: nothing limited how many jobs could be waiting on one shopkeeper's screen. Orders need no account, so a
-- script could fill a shop's queue with thousands of jobs and bury the real ones (0017 keeps the oldest on top, this
-- keeps the list a size a person can work through). A real counter does not have 150 unanswered jobs: each one
-- expires an hour after it was sent if nobody approves it.
--
-- ap.submit_order now counts the shop's jobs in "awaiting approval" and refuses the order when it would take the
-- total past 150, with the result "shop_not_accepting" (the customer reads "This shop is not taking orders right
-- now"; an existing answer, HTTP 409). Nothing is changed by a refused call: the order stays a draft and can be sent
-- again once the queue has moved. Sending the same accepted quote again is still answered "ok" as before.
--
-- The count uses jobs_shop_open_idx (0012) and happens inside the same single call. Two orders sent at the same
-- instant can each see room and together land a little over 150; the cap is a brake, not an exact number.
-- The limit per caller address is in the API (file registrations per address per hour): the database never sees
-- an address.
--
-- Everything else is the text of 0002. Safe on a database with existing rows: it replaces a function and touches
-- no data. Jobs already waiting are not affected, even if there are more than 150 of them.

CREATE OR REPLACE FUNCTION ap.submit_order(p_order_id uuid, p_quote_id uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE o ap.orders%ROWTYPE; q ap.quotes%ROWTYPE; job_ids jsonb; waiting integer; adding integer;
        max_waiting constant integer := 150;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE id = p_order_id FOR UPDATE;
  IF NOT FOUND OR o.access_until <= now() THEN RETURN jsonb_build_object('result', 'order_not_found'); END IF;
  SELECT * INTO q FROM ap.quotes WHERE id = p_quote_id AND order_id = o.id FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'quote_not_found'); END IF;
  IF o.status = 'submitted' AND q.accepted_at IS NOT NULL THEN
    SELECT jsonb_agg(id ORDER BY created_at, id) INTO job_ids FROM ap.jobs WHERE order_id = o.id;
    RETURN jsonb_build_object('result', 'ok', 'idempotent', true, 'job_ids', job_ids, 'expires_at', o.expires_at);
  END IF;
  IF o.status <> 'draft' THEN RETURN jsonb_build_object('result', 'order_not_draft', 'status', o.status); END IF;
  IF o.expires_at <= now() THEN RETURN jsonb_build_object('result', 'order_expired'); END IF;

  SELECT count(*) INTO adding FROM ap.quote_items WHERE quote_id = q.id;
  SELECT count(*) INTO waiting FROM ap.jobs WHERE shop_id = o.shop_id AND status = 'awaiting_approval';
  IF waiting + adding > max_waiting THEN
    RETURN jsonb_build_object('result', 'shop_not_accepting', 'reason', 'queue_full');
  END IF;

  UPDATE ap.quotes SET accepted_at = now() WHERE id = q.id;
  INSERT INTO ap.jobs (order_id, shop_id, document_id, quote_item_id)
  SELECT o.id, o.shop_id, qi.document_id, qi.id FROM ap.quote_items qi WHERE qi.quote_id = q.id;
  INSERT INTO ap.payments (order_id, amount_paise) VALUES (o.id, q.total_paise);
  UPDATE ap.orders SET status = 'submitted', submitted_at = now(), expires_at = now() + interval '1 hour', updated_at = now()
  WHERE id = o.id RETURNING * INTO o;
  PERFORM ap.refresh_retention(o.id);
  SELECT jsonb_agg(id ORDER BY created_at, id) INTO job_ids FROM ap.jobs WHERE order_id = o.id;
  PERFORM ap.log_event('order.submitted', 'customer', NULL, o.shop_id, o.id, NULL, NULL,
                       jsonb_build_object('quote_id', q.id, 'jobs', jsonb_array_length(job_ids), 'total_paise', q.total_paise));
  RETURN jsonb_build_object('result', 'ok', 'job_ids', job_ids, 'expires_at', o.expires_at);
END $$;
