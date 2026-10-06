# Implementation Status

> Resuming? Start with `docs/HANDOVER.md` (current state, what is unverified, next steps, how to work on it).

**Last updated:** 5 October 2026
**Current phase:** 5 (Windows desktop app) built and launching; the customer site and shop API are live on Vercel and Supabase. Nothing has printed on a physical printer.

## Phase gates

| Phase | Gate | State |
|---|---|---|
| 0 Approvals and repository | all decisions recorded, pushed, founder confirms | Mostly done. O-items answered, D-5/D-12/D-15/D-18 approved; the other D-items are still PROPOSED. Founder written confirmation not given as a single statement |
| 1 Print spike | physical printer, 30 normal prints, completion rule, engine chosen | **NOT PASSED.** Virtual printer only (founder-allowed). 30/30 normal prints, completion rule v1 written, engine provisional. Physical-printer run, duplex/colour and real failure drills outstanding. See `docs/PRINT_SPIKE_REPORT.md` |
| 2 Contracts | see checklist below | Done except the C# client |
| 3 Backend slice | Customer and shop APIs built, tested on a real PostgreSQL, deployed to Vercel (Mumbai) with Supabase; migrations 0001-0007 applied live | Done on free tier; cold-start latency not measured |
| 4 Customer web | Built. 24 unit tests (estimator matches Python on 21 shared vectors) and 6 end-to-end browser tests pass against the real API, real PostgreSQL and real file storage on this PC | **Gate NOT passed**: not tested on a real Android or iPhone, not tested against the deployed API, 60-second timing not measured. Emulation only (Edge, Pixel 7 profile) |
| 5 Windows desktop app | Core (journal, agent loop, pairing, real engine, spooler observer) with 58 tests; WPF app launches and shows a pairing code | **In progress.** Done: job preview, start at sign-in, installer, live end-to-end run on the virtual printer. Not yet done: physical printer, other PCs, signing |
| 6-10 | not started | |

## Phase 2 checklist

- [x] Migrations apply cleanly to an empty PostgreSQL, from scratch, twice (`test_migrations_apply_to_empty_database_twice`).
- [x] Every allowed transition has a test, and each state has a refusal test (`test_transition_matrix.py`; the table and the scenarios are compared).
- [x] Concurrency: two and six simultaneous claims give one winner; 15 cancel-versus-claim races give exactly one winner each.
- [x] `contracts/openapi.json` generated from the declared routes; stale-file test.
- [x] TypeScript client generated with no manual edits; stale-file test.
- [ ] **C# client**: .NET 8 SDK is now installed; generation is not set up (Phase 5).
- [x] `docs/CONTRACTS.md` and `docs/ARCHITECTURE.md` written. **Founder review pending.**
- [x] Error catalog covers every SQL result code (test).
- [x] Pricing with worked examples (test), including 3 pages at 2 rupees = 6 rupees.

## Verified results (5 Oct 2026)

`apps/api/.venv/Scripts/python.exe -m pytest` runs all suites against a throwaway PostgreSQL 17 on port 55432.

- Database tests (state machine, completion rule, transition matrix): pass
- API tests (pricing, contract checks): pass
- Full count is recorded in the commit message of the latest commit.

## Phase 3 progress (5 Oct 2026)

- Customer routes implemented; PDF validation by structure (rejects a multipart envelope; accepts valid files that contain the bytes /JS).
- `SupabaseStorage` verified against the live V4 project (5 tests: private bucket, raw PUT, signed download, PDF-only, signed URL scoped to one object).
- Founder admin script `scripts/ap_admin.py` (create shop, set rates, issue enrollment code, list jobs, revoke device) tested.
- `supabase/_combined.sql` (generated, git-ignored) is verified to apply once to an empty database and to refuse a second run.
- NOT done: apply the schema to Supabase, deploy to Vercel, measure latency, GitHub Actions maintenance cron.
- Blocked: this network cannot reach Supabase's SQL ports. The schema must be pasted into the SQL Editor by the founder.

## Phase 4 progress (5 Oct 2026)

- `apps/web`: React + TypeScript, built from the generated API types; production build passes; main bundle 60 KB gzipped, pdf.js loaded only when a file is chosen.
- Run the browser suite: `E2E_CHANNEL=msedge apps/api/.venv/Scripts/python.exe e2e/run_web_e2e.py` (uses Edge; or install Playwright's Chromium and drop the variable).
- Verified in the browser: 3 pages at 2 rupees shows an estimate of 6 rupees and an exact server price of 6 rupees; the order secret is never in the URL or page text; the status page moves from waiting, to approved, to "Sent to printer."; the word "printed" never appears; cancel works before approval; an order link opened in a different browser reveals nothing; an unreachable API shows an error instead of a fake result.
- NOT verified: real phones, Safari, slow mobile networks, the deployed API.

## Deployment (5 Oct 2026)

- Site and API: https://autoprint-v4.vercel.app (V4 Vercel project autoprint-v4, region bom1). API entry `api/index.py`, config `vercel.json`.
- Verified live: `/health` 200; `/health/ready` reports database ok; `/v1/shops/<unknown>` returns the shop_not_found error after a real query of `ap.shops` in the V4 Supabase project; a browser-origin PUT to Supabase Storage is allowed (CORS `*`).
- The Supabase pooler cluster for this project is `aws-0-ap-south-1` (transaction mode, port 6543). `aws-1` answers "tenant not found".
- An earlier incident: until the first `vercel.json`, the production alias served the raw repository files publicly (docs, SQL). No secret was in the repository, and it was fixed the same day by serving only `apps/web/dist` plus the API. The alias now returns the app page for those paths.
- Not verified: latency numbers, the 60-second customer timing on a real phone, the scheduled maintenance call (no GitHub Actions workflow yet; retention and expiry sweeps do not run on the deployed site until one exists), the Vercel Hobby terms for a paid shop, and the 7 npm advisories printed by the build (audit is unreachable from this network).

## Shop-side API and speed (5 Oct 2026)

- Shop-side routes implemented and tested against a real database: enroll, poll (also the heartbeat), approve, reject, resolve, claim, renew, sent, outcome, job document. The shop poll and the customer status call each cost one database round trip (migration 0004).
- Migration 0004 applied to the live V4 database through the token-protected `/v1/internal/migrate` endpoint (repo files only, one transaction per file, rolled back on failure). `ap.schema_migrations` lists 0001 to 0004.
- Live timings from the founder's network, warm: /health 70 ms, shop lookup 115 ms, shop poll 94 ms, static page 50 ms. Cold starts and a full successful poll under load are NOT measured.
- Still no desktop app: nothing prints. The demo SQL files stand in for the shopkeeper.

## Privacy finding: deleted files stayed readable (5 Oct 2026)

Supabase's CDN caches authenticated object reads. After `delete`, an authenticated read of the same URL still returned the file (HTTP 200, cache HIT) for at least 20 seconds. Measured on the live V4 project.

- NOT a leak to outsiders: unauthenticated and wrong-key requests got 400 and never received the cached file, and signed-URL reads are never cached.
- It did break "purged means gone" for the server's own reads. Fixed: every server-side read adds a unique query string, which misses the cache (400 immediately after delete). The live regression test (read, delete, read) now passes 3 of 3 runs.
- Not measured: how long the CDN keeps the orphaned cached bytes. They can only be fetched with the exact URL plus a valid key, and no code path asks for that URL again.

## Credential rotation (5 Oct 2026)

Supabase credentials were rotated by the founder. Old key rejected (HTTP 400). New values live in the git-ignored `.env` and the V4 Vercel project. Vercel only applies environment changes to NEW deployments, so a redeploy is required after every change (I forgot once; the live site reported `database: failed` until redeployed). After redeploy: `/health/ready` OK, and a full live customer flow (create, upload, finalize, quote, submit, status, cancel) succeeded.

## Windows desktop app and print engine (5 Oct 2026)

- `apps/desktop`: `AutoPrint.Core` (journal, agent loop with backoff, pairing client, Sumatra engine, native spooler observer) and `AutoPrint.Desktop` (WPF: pairing screen with code, queue cards with approve/reject, needs-attention actions, printer picker with test page, tray icon, single instance, closing the window keeps printing). 58 tests pass, including 5 that use the real spooler and the real engine on the virtual printer (they skip unless `AP_REAL_PRINTER` and `AP_SUMATRA` are set).
- **Completion rule v2** (migration 0006). Windows reported 0 pages printed for a job that did print, so "pages printed >= 1" is no longer required (the count is stored for information). Other safeguards unchanged. Still provisional: needs a physical printer.
- **Native spooler API** instead of `System.Printing`, which is bound to its creating thread and crashed in async code.
- **Sumatra hash check** before every print (V3 shipped the installer under that name). The expected hash is from the portable 3.6.1 download and was not checked against a publisher checksum. `tools/SumatraPDF.exe` is git-ignored and must be placed there for builds.
- App data lives in `%LOCALAPPDATA%\AutoPrintV4`, separate from V3's `AutoPrint` folder. A first launch wrote one log line into V3's folder before I moved it; that line was deleted.
- Antivirus and SmartScreen: see `docs/DESKTOP_DISTRIBUTION.md`. Not yet tested against Defender.

## Connecting a shop computer (5 Oct 2026)

- **Device pairing** (migration 0005): the PC makes its own secret, shows a code like `ABCD-EFGH` (15 minutes, single use), the code is approved, the app connects. Servers store only hashes; no secret travels back.
- **Shop dashboard** (migration 0007, page `/shop`): the founder runs `ap_admin.py issue-shop-link --shop CODE` and hands over a private link (`/shop#key=...`). The shopkeeper types the app's code on that page to connect a computer, sees their computers and can disconnect one. The `shop_logins` table has a `method` column (`link` now; `phone` and `email` reserved) so other sign-in methods can be added later without changing the dashboard. Only hashes are stored; each login can be revoked.
- Bug caught by tests: disconnecting must set the device `status`, not only `revoked_at`; fixed before release.
- Founder-run approval (`ap_admin.py approve-pairing`) still works as a fallback.
- Live check done: wrong key gives 401, `/shop` loads. Not done: issuing a real link and connecting the real app through the dashboard.

## Whole-chain run on the live site (5 Oct 2026)

`e2e/run_live_e2e.py` plays the customer against https://autoprint-v4.vercel.app (new order, upload, quote, submit) while the C# test `LiveE2ETests` plays the shop with the real agent, real SumatraPDF and the real Windows spooler on the virtual printer. It pairs through the shopkeeper dashboard API, approves the job, and disconnects its device afterwards. Last result: **PASS**. Customer saw "awaiting approval", then "printing" 2.4 s after submit, then "completed" 5.9 s after submit; the virtual printer produced a 2-page file for the 2-page upload. Approve click to done was about 4 s (about 1 s of that waiting for the next poll).

What this proves: the whole software chain on real infrastructure. What it does not prove: physical printing, a real phone, the WPF screens (the run uses the same core code, not the window), or behaviour when the shop network drops.

Found by this run, fixed: `ShopApi` set `BaseAddress` on an HttpClient already used for pairing, which throws, so the real app would have crashed right after pairing. It now builds absolute URLs. Also added `POST /v1/internal/shop-login` (maintenance token) because the Supabase database ports are not reachable from the founder's PC; it creates or revokes shop logins through the deployed API.

Each run leaves one completed order on the test shop TST001 (retained until the normal cleanup).

## Job preview and installer (5 Oct 2026)

- **Preview:** each waiting job has a Preview button. It downloads the file (hash-checked), shows the pages with the PDF viewer built into Windows, and offers Approve and Reject inside the window. The temp file is deleted when it closes. Checked: a 3-page PDF renders correctly through the same code (`AutoPrint.exe --selftest-preview file.pdf`). Not checked: the window itself with a real queued job (that is for the founder test).
- **Start at sign-in** is a setting (and an installer option), per user, no administrator rights.
- **Installer:** `apps/desktop/installer/build.ps1` builds `dist/AutoPrintSetup-4.0.0.exe` (59 MB, Inno Setup 6, self-contained .NET so the shop PC needs nothing else; not packed, not trimmed). Per-user install, no administrator prompt, publisher "Suraj Pandavula", Sumatra hash verified at build time, GPL notice included. Checked: silent install, installed app runs, silent uninstall leaves no program files, V3 data untouched. Defender scan of the installer: no detection. **Not signed** (Authenticode status NotSigned), so SmartScreen will warn. Not checked: the "start at sign-in" option, upgrade over an older version, a clean PC without .NET, other Windows versions.
- Founder test guide: `docs/TEST_THE_WINDOWS_APP.md`.
- Machine change: Inno Setup 6 was already installed on this PC.

## Phase 7 pieces built (5 Oct 2026)

- `docs/RUNBOOK.md`: provision a shop, install, daily check, failure table, retention, secrets. Items it marks not verified are not verified.
- Founder tools through the deployed API (the database port is unreachable from the founder PC): `scripts/ap_remote.py` (create shop with prices in one transaction, publish new prices, issue and revoke shop links) and `scripts/ap_report.py` (per-shop counts, outcomes, computers online; no document names). Live check: the report for TST001 listed 8 jobs and the founder installed app as ONLINE. These endpoints use the maintenance token, which can now also read reports and mint shop logins, so it is a high-value secret.
- `.github/workflows/maintenance.yml` (every 15 minutes). **Does nothing until the founder adds the repository secret `AUTOPRINT_MAINTENANCE_TOKEN`.**
- Still open in Phase 7: clean-PC install timed against the runbook, retention proven live past a real window, reboot test, 24-hour soak, purge-on-request script, counter poster generator.
- 211 Python tests pass.

## Poster, installable site, purge (6 Oct 2026)

- `/poster/CODE`: printable A4 counter sign (QR to `/s/CODE`, shop code, three steps), linked from the shopkeeper dashboard. Live and screenshotted. The QR is produced by a standard library; **not yet scanned with a real phone**.
- The site has a web app manifest and icons, so a phone can add it to the home screen. **Not yet tried on a phone**; there is no offline mode or service worker.
- `POST /v1/internal/purge` and `ap_remote.py purge`: delete one finished order's files on request. Local tests pass (refused while live, works once final, files gone, 404 for an unknown order). Not run on a real live order.
- 212 Python tests.

## Customer connection (discussed, not built)

Today a customer reaches a shop by scanning the counter QR or opening `/s/<SHOP CODE>`; no account. Decided on 5 Oct 2026, to build later: a home-page box where the customer types the short shop code (keep `ABC123`), typo correction by position (letter where digit belongs), case and dash insensitive, show shop name before upload, remember the last shop, optional add-to-home-screen, a printable counter poster. Open risk: no verified per-address rate limit on customer requests.

## Findings so far

- V3's bundled `SumatraPDF.exe` is the installer, not the portable program (identical hash). V3 could never have reliably printed through it.
- "Job left the spooler queue" is not evidence of printing: a cancelled job also leaves. Fixed in the rule.
- A killed print process can leave an orphan job stuck in the spooler.
- A nonexistent printer name makes Sumatra hang rather than fail.
- A bug the tests caught: the completion rule failed open when evidence lacked `max_pages_printed`. Fixed (rule v1); v2 now ignores the field.

## Not verified

Physical printing in any form. Duplex and colour. Real-phone behaviour. Cold-start latency. Defender and SmartScreen behaviour of the app. The whole chain (customer upload to Windows app to printer) in one run. 7 npm advisories were not checked (audit endpoint unavailable). Vercel Hobby terms for commercial use. The scheduled maintenance job (GitHub Actions) is not set up.

## Blocked on founder

- Physical printer access for the real Phase 1 drills (the Kyocera on this PC is offline).
- Issue a shop link and run the real app through the dashboard (needs the founder at the PC).
- Decision on the code-signing route (see `docs/DESKTOP_DISTRIBUTION.md`).
- Review of `docs/CONTRACTS.md` and `docs/ARCHITECTURE.md`.

## Machine changes made on this PC (clean up when finished)

- A local printer named **AutoPrint-Spike-PDF** and a printer port at `F:\Projects\AutoPrint-V4\spikes\_out\spike_out.pdf`. One orphan spooler job is stuck on it. Remove with `Remove-Printer` and `Remove-PrinterPort`.
- A throwaway PostgreSQL 17 data directory at `.localdb/` (ignored by git), started on port 55432.
- .NET 8 SDK installed with winget.
- A built copy of the app in `apps/desktop/src/AutoPrint.Desktop/bin` (git-ignored). The test launch was stopped and its `AutoPrintV4` data folder deleted.
