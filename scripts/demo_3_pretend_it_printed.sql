-- AutoPrint V4 demo, step 3: pretend the shop's printer handled the approved job.
-- NO PAPER IS PRINTED: there is no desktop app yet. This only records the spooler evidence that the real
-- app will send, so you can see the customer page change to "Sent to printer."
-- Run after step 2. Returns {"result": "ok", "job_status": "completed"}.

do $$
declare d uuid; c jsonb;
begin
  select id into d from ap.devices where display_name = 'Test device' limit 1;
  c := ap.claim_next_job(d, 300);
  if c->>'result' <> 'claimed' then raise exception 'nothing to print: %', c->>'result'; end if;
  perform ap.mark_sent((c->>'attempt_id')::uuid, c->>'attempt_token', d);
  perform ap.report_outcome((c->>'attempt_id')::uuid, c->>'attempt_token', d, 'completed',
    '{"rule_version":1,"spooler_job_seen":true,"printing_seen":true,"left_queue":true,"flags_seen":["SPOOLING","PRINTING"],"max_pages_printed":1}'::jsonb);
end $$;

select j.status as job_status from ap.jobs j join ap.shops s on s.id = j.shop_id
 where s.code = 'TST001' order by j.updated_at desc limit 1;
