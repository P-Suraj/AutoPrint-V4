-- AutoPrint V4 demo, step 2: act as the shopkeeper and APPROVE the newest waiting job of the test shop.
-- Run after you have sent a file from the website. The customer's status page changes to "Approved".
-- Returns {"result": "ok"} on success. {"result": "job_not_found"} means no job is waiting.

select ap.approve_job(
  (select j.id from ap.jobs j join ap.shops s on s.id = j.shop_id
    where s.code = 'TST001' and j.status = 'awaiting_approval' order by j.created_at desc limit 1),
  (select id from ap.devices where display_name = 'Test device' limit 1)
) as result;
