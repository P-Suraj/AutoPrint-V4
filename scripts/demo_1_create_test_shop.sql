-- AutoPrint V4 demo, step 1 of 3: create a TEST shop with prices and a test "shopkeeper" device.
-- Paste into Supabase > SQL Editor and Run, ONCE. Then open https://autoprint-v4.vercel.app/s/TST001
-- Prices: black & white 2 rupees a side (1.20 double-sided), colour 10 rupees (8 double-sided).
-- The test device cannot log in anywhere; it only lets step 2 and 3 act as the shopkeeper.

insert into ap.shops (code, name) values ('TST001', 'AutoPrint Test Shop');

insert into ap.rate_cards (shop_id, version, rules)
select id, 1,
  '{"bw":{"simplex":[{"from_sides":1,"to_sides":null,"paise_per_side":200}],"duplex":[{"from_sides":1,"to_sides":null,"paise_per_side":120}]},
    "color":{"simplex":[{"from_sides":1,"to_sides":null,"paise_per_side":1000}],"duplex":[{"from_sides":1,"to_sides":null,"paise_per_side":800}]}}'::jsonb
from ap.shops where code = 'TST001';

insert into ap.devices (shop_id, display_name, credential_hash, last_seen_at)
select id, 'Test device', repeat('0', 64), now() from ap.shops where code = 'TST001';
