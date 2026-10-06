# Implementation Status

> Resuming? Start with `docs/HANDOVER.md` (current state, what is unverified, next steps, how to work on it).

**Last updated:** 6 October 2026
**Current phase:** 5 (Windows desktop app) built, installer made, whole chain passed on the live site with a virtual printer; Phase 7 pieces partly built. Nothing has printed on a physical printer.

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
- `POST /v1/internal/purge` and `ap_remote.py purge`: delete one finished order's files on request. Local tests pass; run live on a finished test order (1 file deleted, a repeat deleted none). The "refused while live" case was only checked locally.
- 212 Python tests.

## Rate limits (6 Oct 2026)

Migration 0008 and `limit()` in the API: 60 new orders per 10 minutes per address, 300 per shop, 12 pairing codes per address; a fixed-window counter in the database, addresses hashed with a server secret and never stored. If the limiter itself fails the request is allowed, so a broken counter cannot stop a shop. Local tests pass (flood stopped at the 61st order, other addresses unaffected, pairing limited, no address stored). Applied live; normal order and pairing calls still succeed. **Not flood-tested live** (it would lock the founder own address for 10 minutes), and it is **not verified that Vercel passes the real client address in `X-Forwarded-For`** (if it did not, everyone would share one bucket and the 60 per 10 minutes cap would apply to all customers together; check by looking at the table after a real test). Other routes (uploads, quotes) are not limited yet. 215 Python tests.

## Items 3 and 4 work (6 Oct 2026)

- **Wording:** completed now reads "Sent to printer. Collect it at the counter." (still never "Printed"; the founder says a physical printer works, but the certification drills have not been run, so the rule stands).
- **Rate limits** extended to uploads (150 per 10 min per address) and quotes (300). New founder check `GET /v1/internal/whoami` shows which address headers the host passes, to confirm the limiter sees real customer addresses. Run once live: the host passes `x-forwarded-for`, `x-real-ip` and `x-vercel-forwarded-for` (values not compared with the real address, so per-address behaviour under real traffic is still unproven).
- **Email sign-in for shopkeepers** (migration 0009, `app/email_auth.py`, `/v1/shop/email/start` and `/finish`, dashboard sign-in screen, `ap_remote.py add-email`). Built and tested with a fake provider (registered address gets a key, unknown or unregistered gets nothing, an email can never be used as a key, limits, provider failure). **Not verified against real Supabase Auth, and not usable yet.** To switch it on the founder must: (1) in Supabase, Authentication, URL Configuration, set Site URL to `https://autoprint-v4.vercel.app` and add `https://autoprint-v4.vercel.app/shop` to the redirect URLs; (1b) in Supabase, Authentication, Sign In / Providers, Email: keep **Confirm email ON**, and unless something else needs it turn password sign-in off. The API trusts the provider's "this address is confirmed" flag; with confirmation off, anyone could create a confirmed account for a shopkeeper's address with a password and receive that shop's key; (2) add the project publishable key to Vercel as `AUTOPRINT_V4_SUPABASE_PUBLISHABLE_KEY` and redeploy; (3) register an address with `ap_remote.py add-email`; (4) try it. The default Supabase mail sender is rate limited to a few emails per hour; fine for a pilot, replace with a real mail service later. Phone sign-in is not built (SMS costs money).
- **npm audit** now works with `--registry=https://registry.npmjs.org`. Production dependencies: **0 vulnerabilities** after upgrading `react-router-dom` to 7.18.4 (type check, 39 unit tests, build and the 6 browser end-to-end tests all pass). Dev tools still have known issues (vite, vitest, esbuild, tinypool; 2 critical, 1 high, only reachable while running the dev server or tests on the founder PC). Fix later by upgrading vite 8 and vitest 5, which are breaking changes.
- 218 Python tests pass.
- **Not done:** cold-start latency measurement, cleaning the test printer and data, an operator web page, payments (blocked by decision O-2), phone sign-in, second-stage validation.

## Review fixes (6 Oct 2026)

A code review of everything so far found the items below. All are fixed and tested locally. **None is deployed:** not pushed, migration 0010 not applied live, no new installer built, the live end-to-end run not repeated.

Desktop app:
- **The spooler watch now starts together with the print process**, not after it. Before, the lease (300 s) was not renewed while SumatraPDF was running, so a job that took longer would have been refused as stale and shown as "needs attention" although it printed; and a short job could have left the queue before the watch began. Test: a slow engine whose job leaves the queue first still ends "completed", with renewals before the engine returns. How long SumatraPDF really runs on a large job is still unmeasured; check a 150+ side job at physical certification.
- **A failed queue read is no longer taken as an empty queue** (`WinSpoolObserver.ListJobs` checks the result of `EnumJobs`). An empty queue is what the watcher reads as "the job left". Checked against the real spooler on the virtual printer (both real-spooler tests pass); the failure path itself cannot be provoked on this PC.
- **Undelivered outcomes are settled as soon as the server answers again**, not only at the next app start, and an outcome decided in the same run is sent as it was, with its evidence (before: always "uncertain"). After a restart the journal rule is unchanged: uncertain or failed, never a reprint.

API and database:
- **Migration 0010:** an email sign-in key stops working 30 days after it was made (before: only when someone signed in again later); removing a registered address, or moving it to another shop, revokes the keys it was given. Private-link keys are unchanged. Email keys made before 0010 are revoked by it (none exist live; the feature is not switched on).
- **`/v1/shop/email/start` gives the same answer when the mail provider fails** (before: an error only for registered addresses, which revealed them). The failure is logged. Not changed: anyone can use up the 3-per-hour cap of a known address and so delay that shopkeeper's email sign-in; the cap protects the provider's small mail quota, and the private link still works.
- **Revoking shop logins is per shop:** `ap_remote.py revoke-link ABC123 --label owner` (the API refuses a revoke without a shop code). Before, the label alone was matched across all shops.
- **Purge deletes only the files of the order asked for** (before, it ran the general cleanup, so its count could include other orders).

Web:
- **Content-Security-Policy header** in `vercel.json` (scripts, workers and styles from the site only; connections to the site and `https://*.supabase.co` for uploads). Checked: the production build served locally with the same headers passes the 6 browser tests plus a run over the shop, order, poster and dashboard pages with zero policy violations. **Not checked:** the live site, where the upload goes to Supabase Storage rather than the local test storage. Send one PDF on the live site after deploying.
- **Trying an upload again reuses the same draft order** instead of creating a new one each time (each new order counted against the 60-per-address limit).

Counts after these changes: 219 Python tests, 58 desktop tests plus 2 real-spooler tests on the virtual printer, 39 web unit tests, 6 browser tests.

## Interface redesign (6 Oct 2026)

The customer pages and the shopkeeper web dashboard were redesigned (`apps/web/src/styles.css`, `ui.tsx`, the pages). No API change; wording that comes from the server is unchanged and the pages still never say "Printed".

- **Home:** the shop code is checked while it is typed and the shop's name appears before the customer goes on; shops used before are one tap.
- **Send a file:** three visible steps (File, Settings, Send); a large file target (drag and drop works on a computer); a real upload progress bar; touch-sized choices that each show what the whole job would cost; the price pinned to the bottom of the screen.
- **Order status:** the order code large ("Say this code at the counter"), a four-step track, an animated state for waiting and for the printer, a green finish; the tab title changes and the phone buzzes once when everything is ready to collect.
- **Shop dashboard:** one line that says whether the shop can receive prints (from when its computer was last seen), refreshed every 10 seconds; the pairing code is looked up by itself at the eighth character; copy, share and print for the customer link; a clear "sign in again" screen when a key has expired. A private link opened in a tab that already shows the page now signs in (before, only a fresh load did).

Checked: type check, build, 39 unit tests, the 6 browser tests, and a scripted walk through every screen above on the production build under the Content-Security-Policy with screenshots reviewed (phone size, and the dashboard at desktop width). **Not checked:** a real phone, Safari, the live site, the email sign-in screens beyond the first one, a screen reader. The upload now uses XMLHttpRequest (needed for the progress bar); against Supabase Storage on the live site this is untested, so the one-PDF check after deploying matters more.

## Customer connection (built)

A customer reaches a shop by scanning the counter QR, opening `/s/<SHOP CODE>`, or typing the short code on the home page (typo-tolerant, remembers the last shops); no account. The site can be added to the home screen and each shop has a printable counter poster. Per-address rate limits exist; see "Rate limits" for what is unverified.

## Findings so far

- V3's bundled `SumatraPDF.exe` is the installer, not the portable program (identical hash). V3 could never have reliably printed through it.
- "Job left the spooler queue" is not evidence of printing: a cancelled job also leaves. Fixed in the rule.
- A killed print process can leave an orphan job stuck in the spooler.
- A nonexistent printer name makes Sumatra hang rather than fail.
- A bug the tests caught: the completion rule failed open when evidence lacked `max_pages_printed`. Fixed (rule v1); v2 now ignores the field.

## Not verified

Physical printing in any form. Duplex and colour. Real-phone behaviour. Cold-start latency. SmartScreen and other antivirus behaviour of the app (a Defender scan of the installer found nothing). The whole chain on a physical printer (it passed on the virtual one). Vercel Hobby terms for commercial use. The scheduled maintenance job: the workflow exists but does nothing until the repository secret is added. Email sign-in against real Supabase Auth. The review fixes of 6 Oct on the live site.

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
