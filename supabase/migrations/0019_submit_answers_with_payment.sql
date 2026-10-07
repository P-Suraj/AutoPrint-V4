-- AutoPrint V4 — 0019 sending an order answers with its payment, so the API does not ask a second time
--
-- Why: when a customer presses "send", the API called ap.submit_order and then read the order's payment row with a
-- second statement, only to put three values in its answer (how it is paid, the payment state, the amount). On the
-- live site every statement travels to the database pooler and back, and the customer waits for each one.
--
-- ap.submit_order now puts those three values in its own answer: payment_mode, payment_status, amount_paise. They
-- are read from the payment row itself after it is written, so they are exactly what the second statement returned,
-- also when the same accepted quote is sent again (the row as it is at that moment).
--
-- Order of deployment: the API works with either version of this function. When the answer has no payment_mode
-- (this file not applied yet) it reads the payment row itself, as before. So the API can go out first and this file
-- can be applied at any time afterwards; rolling this file back needs no API change either.
--
-- Nothing else changes: every check, every refusal, the cap of 150 waiting jobs (0018) and the order in which rows
-- are locked are the text of 0018. Only the two successful answers gained three keys. Safe on a database with
-- existing rows: it replaces a function and touches no data.

CREATE OR REPLACE FUNCTION ap.submit_order(p_order_id uuid, p_quote_id uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE o ap.orders%ROWTYPE; q ap.quotes%ROWTYPE; job_ids jsonb; waiting integer; adding integer; pay ap.payments%ROWTYPE;
        max_waiting constant integer := 150;
BEGIN
  SELECT * INTO o FROM ap.orders WHERE id = p_order_id FOR UPDATE;
  IF NOT FOUND OR o.access_until <= now() THEN RETURN jsonb_build_object('result', 'order_not_found'); END IF;
  SELECT * INTO q FROM ap.quotes WHERE id = p_quote_id AND order_id = o.id FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('result', 'quote_not_found'); END IF;
  IF o.status = 'submitted' AND q.accepted_at IS NOT NULL THEN
    SELECT jsonb_agg(id ORDER BY created_at, id) INTO job_ids FROM ap.jobs WHERE order_id = o.id;
    SELECT * INTO pay FROM ap.payments WHERE order_id = o.id;
    RETURN jsonb_build_object('result', 'ok', 'idempotent', true, 'job_ids', job_ids, 'expires_at', o.expires_at,
                              'payment_mode', pay.mode, 'payment_status', pay.status, 'amount_paise', pay.amount_paise);
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
  INSERT INTO ap.payments (order_id, amount_paise) VALUES (o.id, q.total_paise) RETURNING * INTO pay;
  UPDATE ap.orders SET status = 'submitted', submitted_at = now(), expires_at = now() + interval '1 hour', updated_at = now()
  WHERE id = o.id RETURNING * INTO o;
  PERFORM ap.refresh_retention(o.id);
  SELECT jsonb_agg(id ORDER BY created_at, id) INTO job_ids FROM ap.jobs WHERE order_id = o.id;
  PERFORM ap.log_event('order.submitted', 'customer', NULL, o.shop_id, o.id, NULL, NULL,
                       jsonb_build_object('quote_id', q.id, 'jobs', jsonb_array_length(job_ids), 'total_paise', q.total_paise));
  RETURN jsonb_build_object('result', 'ok', 'job_ids', job_ids, 'expires_at', o.expires_at,
                            'payment_mode', pay.mode, 'payment_status', pay.status, 'amount_paise', pay.amount_paise);
END $$;
