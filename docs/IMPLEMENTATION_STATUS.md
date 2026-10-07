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

## Pilot-readiness pass (6 October 2026, evening)

Three parallel work streams, stopped early to save usage budget. Read the "not verified" list before trusting any of it at a shop.

**Windows app, now 4.0.1.** Screens rebuilt (large order code and amount to collect, waiting and expiry times, Printing now, Needs attention with each choice explained, a Finished tab with search by order code, numbered pairing steps, printer and offline banners, Settings with sound toggle, version and log-folder button). Cards update in place; work is off the UI thread. Core fixes: the agent loop no longer dies on a timeout; the heartbeat continues during a long print; downloads time out after 4 minutes; a corrupt journal is set aside; SumatraPDF is never started for a missing printer; stale work files are swept. The uninstaller now stops only its own copy of AutoPrint.exe (before, it would also have stopped V3's). New support switch `AutoPrint.exe --selftest-ui <folder> [live]` renders every screen with fake data (renders in `dist\ui-selftest`). Reject stays one click: the customer never sees a reason.

**Website.** A "Your order" card on the home and shop pages brings a customer back to an order after closing the tab. Password-protected, empty and broken PDFs get their own messages. Status polling pauses when the tab is hidden, resumes on unlock or when the network returns, and survives a rate-limit answer. Requests time out (40 s; stalled upload 60 s). A refresh at the Settings step keeps the upload. Flat single-accent look, motion on transform and opacity only, reduced-motion respected. Main bundle 83.7 to 73.1 KB gzipped; dashboard, poster and QR code load on demand. Rupee amounts are grouped the Indian way.

**API and founder tools.** The connection pool closed every connection after each statement (50 statements: 3209 ms before, 7 ms after, measured locally). Database, storage and pool errors answer 503 `try_again` instead of 500. One undeletable file no longer blocks cleanup. A damaged PDF that made the reader give up is refused cleanly. Migrations 0011 (records when a shop computer comes back after 2 minutes of silence), 0012 (indexes: shop poll 43 ms to 3 ms at 200,000 jobs, local), 0013 (lock order in `report_outcome`, removes a possible deadlock). Founder report rewritten (`ap_report.py CODE`, `--all`, `--days`): success and needs-attention rates, duplicate signs, medians and 90th percentiles per step, busiest hours. New `ap_remote.py` commands: `shops`, `prices`, `shop-on`, `shop-off`, `rename`. Finding: no order, job or event row is ever deleted, so pilot numbers do not vanish; the document's original file name also stays in its row after the file is deleted (not fixed).

**Checked:** 225 Python tests; 90 desktop tests (4 real-printer ones skipped); 71 web unit tests, type check, build; 6 browser tests; the whole chain on this PC with `e2e/run_local_chain.py` (new: local API, scratch database, real app core, real SumatraPDF, virtual printer): PASS, customer saw "completed" 5.6 s after submit, 2 pages out for 2 sent. Before these changes, the customer flow was also run on the live site in Edge (Pixel 7 profile) and WebKit (iPhone 13 profile): upload to Supabase Storage worked under the Content-Security-Policy with no console errors.

**Not verified:** the new Windows screens on a real display with a real paired session (only renders and an in-process run; that run was not repeated after its last fix); animations, sound, taskbar flash, tray messages, sleep and wake; the website's visual changes (the after screenshots were not reviewed), the order card and draft restore in a real browser, screens at 320 px wide past the file step, the changed code in WebKit; the new connection pool on Vercel against the Supabase pooler; the 503 mapping, claim-failure path, cleanup isolation and deadlock fix have no dedicated tests; the report queries at scale. The first browser-suite run after a dependency change can fail once because the Vite dev server reloads the page; a second run passes.

**Not done:** `docs/RUNBOOK.md` and `docs/TEST_THE_WINDOWS_APP.md` do not describe the new tools and screens yet; new browser tests for the web changes; a soak measurement. Known and left: NUL bytes in text inputs still give 500; `claim_next_job` can deadlock with a customer cancel in a rare branch; no statement timeout.

Founder statement (6 Oct): physical printing was tried on a real printer and worked. No results are recorded in the repository; the completion rule stays marked provisional until it is known whether that test went through this app.

## Security and privacy review (6 October 2026, read-only)

A read-only review of the whole system (API, SQL functions, website, Windows app, scripts, workflow; 5 unauthenticated header checks on the live site). No critical or high-severity issue. Fixes for items 1, 3, 4, 5, 7, 9 and the upload limit were handed to the backend and Windows app work on the same day; see the next status section for which landed.

Confirmed (code path traced):
1. MEDIUM. **Queue flood hides real jobs.** The shop poll returned the 60 newest jobs (`0004_agent_and_views.sql:68-69`), submit had no cap and an order can hold 20 files, so three orders from one phone could push older waiting jobs off the shopkeeper's screen.
2. MEDIUM. **Storage can be filled.** The signed upload URL carries no size or type limit; size is only checked at finalize (`apps/api/app/storage.py:120-124`). **Founder action:** in Supabase, set the `print-documents` bucket to a 25 MB limit and `application/pdf` only.
3. MEDIUM (privacy). **Deleted does not remove the file name.** `mark_document_deleted` (`0002_functions.sql:517-519`) kept `original_name` and the SHA-256 forever; order, job and event rows are never removed.
4. MEDIUM-LOW. **Retention depends on someone calling.** Files are deleted only when a shop app polls or the scheduled workflow runs, and `job_document` checked `deleted_at`, not `delete_after`. **Founder action:** add the GitHub secret `AUTOPRINT_MAINTENANCE_TOKEN`.
5. LOW-MEDIUM. **Page-range pricing bypass.** The parser accepted non-ASCII digits and newlines (`apps/api/app/pricing.py:21`); the desktop filter passed them to SumatraPDF (`SumatraEngine.cs:36`), which may then print every page.
6. LOW. **Email sign-in** (not switched on): the 3-per-hour limit per email is not tied to the caller, so a known address can be locked out; registered addresses answer more slowly. Not fixed.
7. LOW. **Rate-limit address hashes may be unsalted in production:** the salt is `signing_key`, which the deploy script never sets (`main.py:230`, `scripts/set_vercel_env.py:67-76`).
8. LOW. **Shop link keys never expire and Sign out is local only** (`0007_shop_logins.sql:48-57`, `ShopDashboard.tsx`). Not fixed.
9. LOW. **Purge matched every order of a shop with that 4-character code** in 30 days (`main.py`, `/v1/internal/purge`).

Suspicions (cannot be proved from the repository):
- Email sign-in takeover if Supabase Auth allows unconfirmed, password or OAuth sign-up (`email_auth.py:44-45`). **Before switching it on:** Confirm email ON, password and other providers OFF.
- A malicious PDF is parsed unsandboxed by the Windows preview and SumatraPDF 3.6.1 on the shop PC. Very unlikely; keep both current.
- Pairing-code phishing: someone who gets a shopkeeper to type a code from the attacker's PC gains a device for that shop. Codes are 40 bits, 15 minutes, and need a shop key.
- The limiter trusts the first `X-Forwarded-For` value; believed overwritten by Vercel, not confirmed.

Found sound: customer isolation (256-bit order secret, hashed, header only); shop isolation in every device and dashboard function; revoked devices and logins refused; maintenance token (192-bit, constant-time, required on every internal route); SumatraPDF started with an argument list and no shell, hash-checked; downloads size- and hash-checked, work files swept, DPAPI for secrets; no HTML injection sinks, no open redirect; live headers (CSP, frame denial, nosniff, no-referrer, HSTS, no-store on `/v1`); no secret in the working tree or in 41 commits.

Could not assess: Supabase dashboard settings (bucket privacy and limits, Auth), Vercel environment values and logs, SumatraPDF's handling of an odd range, dependency advisories (no audit run; NuGet versions float), Windows spool files.

## Review notes from the pilot-kit work (6 October 2026)

- **Duplicate-print path (handed to the Windows app work):** after paper-out or printer-off the watcher gives up (`Evidence.cs:95`) and the job becomes "Needs attention" while the original can still sit in the Windows queue; "Print again" then prints twice when the printer recovers.
- The report's "page opened to ..." timings start when the customer presses Continue after choosing a file (`apps/api/app/report.py:104,108`; the order is created at `ShopPage.tsx:150`), so scanning, page load and file picking are not measured. There is no measure of shopkeeper attention, only waiting time.
- The customer page calls a shop offline after 45 s (`apps/api/app/settings.py:30`); the shop dashboard uses 60 s (`ShopDashboard.tsx:10`).
- "Print a test page" tested only the black-and-white printer (`SettingsWindow.xaml.cs:69`).
- **Cause of the founder's failed job BLS3 (6 Oct, 17:57):** the app's chosen printer was "Microsoft Print to PDF", which opens a Save As window and waits; the job ended `engine_failed_nothing_in_spooler` after 87 s. Every job through the installed app on the founder PC so far went to that virtual printer, so the completion rule is still unconfirmed on a physical printer through this app.
- The permission system of the Claude Code session refused three actions on 6 Oct: applying migrations through `/v1/internal/migrate`, running `e2e/run_live_e2e.py`, and starting a payments agent on a separate branch. The founder runs the first two himself.

## Payments design (6 October 2026, design only, nothing built)

`docs/PAYMENTS_DESIGN.md` was written from a read of FinFlow's source (`F:\Projects\finflow`, read, not run). Headline findings:
- **FinFlow cannot take a customer payment today.** Creating a payment intent only writes a row; it creates no provider order and returns no checkout link.
- **FinFlow is built for the opposite of decision P-1:** one platform Razorpay account, a 10% fee, a ledger split and later payouts to shops. There is no per-shop provider account or onboarding.
- **AutoPrint has the payment record (`ap.payments`) but no eligibility check:** `approve_job` and `claim_next_job` never read the payment, although BUILD_PHASES says the check exists.
- FinFlow's outbound signed event differs from its own document and gives up after 5 tries in about 7.5 minutes; intents never expire. Not deployed, not sandbox-verified. No host was found that is free, needs no card and is always on; the nearest is a UPI-paid server at a reported Rs 360 to 400 a month (unverified).
- The AutoPrint side (13 steps, default OFF per shop) can be built and tested now against a fake FinFlow. The real integration is blocked on FinFlow changes and on 14 founder questions listed in the design, each with a recommendation.

## Verification of the wip branch (7 October 2026)

The branch `wip/2026-10-06-unverified` was re-tested area by area on the founder PC with no other agent running. **Everything below is local only: nothing was merged to `main`, deployed, or applied to the live database.**

| Area | Command | Result |
|---|---|---|
| Python (API and database) | `apps\api\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | First run 268 passed, 1 failed; after the test fix below, `test_resilience.py` 13 passed (the full suite is re-run before the merge, see the next section) |
| Cancel-versus-claim race and lock order (0013, 0014) | `pytest supabase/tests/test_state_machine.py::test_cancel_racing_claim_has_exactly_one_winner supabase/tests/test_lock_order.py`, 5 times | 12 passed each time |
| Web type check, unit tests, build | `npx tsc --noEmit`, `npx vitest run`, `npm run build` in `apps/web` | clean; 72 passed; built, main bundle 73.21 KB gzipped |
| Web browser tests | `E2E_CHANNEL=msedge apps/api/.venv/Scripts/python.exe e2e/run_web_e2e.py` | 17 passed (Edge, Pixel 7 profile) |
| Windows app build and tests | `dotnet build apps/desktop -c Release`; `dotnet test apps/desktop/tests/AutoPrint.Core.Tests --filter "FullyQualifiedName!~LiveE2ETests"` | 0 warnings; 161 passed, 5 skipped |
| Windows app tests with the real spooler | the same with `AP_REAL_PRINTER=AutoPrint-Spike-PDF` and `AP_SUMATRA=...\tools\SumatraPDF.exe` | 166 passed, 0 skipped |
| Windows app in-process run | `AutoPrint.exe --selftest-ui <folder> live` (Release build) | exit 0, 61 PASS, 0 FAIL |
| Whole chain on this PC | `apps/api/.venv/Scripts/python.exe e2e/run_local_chain.py` | PASS: customer saw "printing" 1.0 s and "completed" 5.1 s after submit; 2 pages out for 2 sent |

Findings:
- **The failing cancel-versus-claim race of 6 Oct was connection exhaustion, not migration 0014.** With the database to itself the test passed in the full run and in 5 repeats together with the lock-order tests. 0014 is no longer suspected.
- **The other failure was a bug in the test, now fixed** (`apps/api/tests/test_resilience.py`: the document ids are cast with `%s::uuid[]`). No application code changed.
- Migrations 0014 to 0018 were read in full: each is a complete file, and each replaces one function. Only 0015 changes data (the irreversible blanking of names and checksums of already-deleted documents).
- The desktop core works against the reordered queue of 0017 (the local chain and the in-process run both use it).
- The three small desktop edits made after the agent's last real-spooler run are now covered: the 166 real-spooler tests and the 61-step run were repeated on the final code.

Still not verified on this branch: anything on the live site or live database; a physical printer; WebKit; real phones; the "Test the colour printer" button on a real printer; the items the agents listed as "changed, no dedicated test" (see the handover) unless a later section says otherwise.

## Website: WebKit, small phones and load numbers (7 October 2026, local only)

- **WebKit:** `E2E_ENGINE=webkit apps/api/.venv/Scripts/python.exe e2e/run_web_e2e.py`: 17 of 17 passed (Playwright WebKit, iPhone 13 profile; not a real iPhone).
- **Small phones:** `E2E_TOOL=walk E2E_OUT=<folder>` through the same runner: "no layout findings" at 320, 360 and 412 px over screens 01 to 34, 40 and 45. Six of the combined pictures were looked at (shop page, 300 pages x 100 copies, price and send, waiting, completed, needs attention): nothing cut off, the long file name is shortened with an ellipsis, Rs 3,00,000 fits. Not looked at: the other pictures; the shop dashboard screens 35 to 44 were not captured (they need `E2E_SHOP_KEY`).
- **Finding, fixed: the production build served by `vite preview` showed a blank page.** A `compressedPreview` plugin added on 6 Oct in `apps/web/vite.config.ts` compressed the scripts a second time (the preview server already compresses), so the browser could not read them. It only affected local preview, never the live site (Vercel does not use it). The plugin was removed. Before the fix the perf tool timed out on all 3 measurements.
- `e2e/run_web_e2e.py` now builds and serves the production build when `E2E_TOOL=perf`.
- **Load numbers** (`E2E_TOOL=perf E2E_CHANNEL=msedge ...run_web_e2e.py`, production build with the host's headers, local API; "slow phone" = 400 ms delay, 400 kbit/s, processor 4 times slower). One run; other work was starting on the PC near its end, so treat as approximate:

| | Fast connection | Slow phone |
|---|---|---|
| Home, first view | 80.8 KB downloaded; first paint 456 ms | first paint 1.2 s, first content 2.9 s, usable 3.2 s, longest task 162 ms |
| Shop page, first view | 81.7 KB; first paint 76 ms | first paint 1.2 s, first content 2.8 s, usable 3.4 s, longest task 102 ms |
| File chosen to preview drawn | 235 ms (downloads pdf.js, 121 KB) | **11.9 s** |
| Continue: upload and check (3-page file) | 420 ms | 2.8 s |
| Send to status shown | 110 ms | 1.6 s |
| Layout shift | 0 | 0.0005 (the spinner) |

- **Open:** on the slow profile the preview takes 11.9 s after a file is chosen (pdf.js and its 1.4 MB worker are downloaded then). Whether the customer can press Continue before the preview is drawn was not checked here; handed to the website work of the same day.
- **Changed, see the next section for test results:** the status page asks every 2 s while a job is approved or printing (was 4 s), so the result shows up to 2 s sooner at the counter; a handful of extra calls per order.

## Backend: tests for the review fixes, fewer database round trips (7 October 2026, local only)

Done by a backend sub-agent; its report is folded in here. The lead read the whole diff of `apps/api/app/main.py` and migration 0019 afterwards; the lead's own full-suite run is recorded in the closing section of this day. **Nothing is deployed and 0019 is applied nowhere but test databases.**

**Tests for changes that had none** (`apps/api/tests/test_review_fixes.py`, 22 tests, written by the lead, passed on their first run with no application change): page range refuses non-ASCII digits, tabs and line breaks and is stored in one normal form (`1,1,1` is priced and stored as `1`); purge takes one order among several with the same code (most recent, or `--which N`), and bad `which` values are refused; the limiter is salted from the Supabase secret key or the maintenance token when no signing key is set, and the stored bucket differs per secret; 120 file registrations per address per hour, the 121st answers 429, other addresses unaffected; `GET /v1/internal/status` (401 without the token, lists applied and pending, applies nothing) and the `status` and `migrate` commands of `ap_remote.py` against a scratch database. No application bug was found.

**Round trips on the customer path** (each one is a trip to the database pooler on the live site):

| Route | Before | After |
|---|---|---|
| new order | 3 | 1 |
| register a file (upload intent) | 3 | 1 |
| quote | 5 | 2 (pricing runs in Python between the read and the write) |
| submit | 3 | 1 with migration 0019, 2 without |

- How: the limiter, the secret check and the work are one SQL statement (a `CASE`, evaluated in order), in `main.py` (`in_one_trip`, `limit_bucket`). Each route keeps the old step-by-step path and uses it when the combined statement is refused as a whole (for example a broken limiter), so "a broken limiter never stops a customer" still holds.
- **Migration 0019** (`0019_submit_answers_with_payment.sql`): `ap.submit_order` is the 0018 text plus the payment's mode, status and amount in its "ok" answers. Touches no data. The API works with or without it (a test puts the 0018 function back and submit still answers correctly in 2 trips), so the order "site first, then database" holds.
- Counted by wrapping the database connection in `apps/api/tests/test_round_trips.py` (10 tests, pins the counts so they cannot grow back; also checks the order of refusals, that a wrong secret still gets 404 before any other answer, that a refused limit creates nothing, idempotent submit, 8 customers at once without deadlock).
- Sub-agent's result: `pytest -q -p no:cacheprovider` 301 passed. `contracts/openapi.json` unchanged after `scripts/export_openapi.py`; the TypeScript client needs no regeneration.

**Behaviour differences to know before deploying (not defects, but new):**
1. A lost connection, deadlock or statement timeout inside a combined statement answers 503 "try again". Before, a failure in the limiter step alone was skipped.
2. The limiter's counter row stays locked for the whole statement (a few milliseconds), so requests sharing a counter (one shop's new orders, one address's uploads) queue behind each other. Lock order is the same everywhere; the concurrency test passes; **not load-tested** (`e2e/load_test.py` was not re-run).
3. The quote reads the price list and the page counts at one instant instead of in two statements; `create_quote` re-checks both.
4. The quote statement uses `WITH ... AS MATERIALIZED` (PostgreSQL 12 or newer). **The live PostgreSQL version was not checked**; on an older server quote would fall back to the old path and log "combined statement failed".
5. The limit tests can fail if a limiter window boundary (10 minutes or 1 hour) falls inside a test, as the older limiter test already could.

**Not measured:** latency. Only statement counts; the gain on the live pooler is inferred.

**Finalize (not changed), sub-agent's findings:** the server must download every byte of an upload to compute the SHA-256 the shop app later checks and to validate the PDF, so the download cannot be avoided; the read is already bounded by the declared size. Proposals not done: (a) `SupabaseStorage.read` briefly holds about three copies of the file (about 75 MB for 25 MiB), could be one, untestable without the live store; (b) finalize makes 3 database trips and could make 2 the same way, no migration needed.

## Website: verified after the day's edits; preview no longer holds the customer up (7 October 2026, local only)

Done by a website sub-agent; its report is folded in here. The lead did not repeat its runs. **Not deployed.**

**Verified by the sub-agent on the final code, once each:** `npx tsc --noEmit` clean; `npx vitest run` 73 passed; `npm run build` passed; browser suite 17 of 17 in Edge (Pixel 7 profile) and 17 of 17 in WebKit (iPhone 13 profile); the walk at 320, 360 and 412 px: "no layout findings" over 42 screens, now including the shop dashboard (the runner makes a throwaway dashboard key in the scratch database for the walk). All 41 pictures of the first walk were looked at; after the fixes, the 8 affected ones.

**Changes:**
- **The preview no longer delays Continue.** Before: Continue was never disabled, but pressing it ran a file check that waited for the same pdf.js download as the preview, so "Checking your file" could sit for about 12 s on a slow phone. Now Continue waits at most 3 s for that check and then uploads (the server checks every file anyway); if the preview already opened the file its result is reused.
- **pdf.js and its worker are fetched in the background on the shop page**, when the browser is idle after the first screen is usable (with data-saver on: only when the file button is touched). First-view bytes are unchanged (about 82 KB). **Cost to know about: every visitor to a shop page now downloads about 530 KB more (gzip) in the background even if they never choose a file.** The home page fetches nothing extra.
- The status page asks every 2 s while a job is approved or printing (lead's edit, unit-tested).
- The shop dashboard calls a computer offline after 45 s, the same as the customer page (was 60 s).
- Visual fixes: an error message below the fold at 320 x 568, or behind the pinned price bar, is now scrolled into view; the settings no longer jump about 40 px while a page range is being typed; "needs attention" is amber throughout and "failed" red throughout (each had a red headline with an amber icon); line spacing of the "Print at" row on the home page.
- Tools: the perf tool reports first-view bytes separately from the background fetch and has cases for "file chosen after 6 s / 15 s" and "Continue pressed at once"; the walk has a "send failed" screen.

**Load numbers after the changes** (production build under `vite preview`, Edge, 360 px, single runs; slow = 400 ms delay, 400 kbit/s, processor 4 times slower):

| | Fast | Slow |
|---|---|---|
| First view downloaded | home 81.1 KB, shop 81.9 KB | |
| Usable | | home 3.0 to 3.1 s; shop 3.7 to 4.1 s (3.4 to 3.9 s before; the sub-agent reads the spread as noise, not proven) |
| Preview drawn, file chosen at once | about 250 ms | 11.0 to 11.4 s (11.9 s before) |
| Preview drawn, file chosen 6 s after the screen | | 5.1 to 5.6 s |
| Preview drawn, file chosen 15 s after the screen | | 1.0 s |
| Upload and check after Continue | about 300 ms | 2.3 s; 5.6 s when Continue is pressed without waiting for the preview |
| Status shown after Send | 135 ms | 1.5 s |
| Layout shift | 0 | 0.0003 to 0.0005 (spinner moves a pixel as the percentage text changes width) |

Correction to the earlier table of this day: choosing a file always cost about 530 KB (pdf.js 121 KB plus its worker 409 KB, gzip), not 121 KB; the tool could not see the worker's own download.

**Left open:**
- A slow link cannot move 530 KB in under about 11 s, so a customer who picks a file within a second or two of opening the page still waits for the preview (but can continue). Shrinking the worker (modern pdf.js build, or a lighter page counter) was not attempted.
- pdf.js starting in the background is one task of 160 to 270 ms on the slow profile; a tap in that window is answered that much later.
- At 320 px with a price like Rs 3,00,000 the word "About" wraps above the amount (readable).
- The dashboard's 45 s is a copy of a server setting, and it compares the server's last-seen time with the browser's clock, so a wrong clock gives a wrong answer. The proper fix is an `online` field per computer from `/v1/shop/devices` (needs the API and the contract). Not done.

**Not verified:** real phones; the live site; whether Vercel sends the `.mjs` worker compressed and with cache headers that let the background fetch be reused (check with `curl -sI -H "Accept-Encoding: br, gzip" https://autoprint-v4.vercel.app/assets/pdf.worker.min-<hash>.mjs` after deploying); the case where a locked or broken PDF is uploaded because the 3 s cap ran out and the server then refuses it (no test exercises it); the data-saver branch; the background fetch and the 3 s cap in WebKit beyond the 17 functional tests; dashboard screens at 320 px; the 45 s threshold against a real shop computer.

## Windows app 4.0.3: screens looked at, soak measured, a never-ending reminder fixed (7 October 2026, local only)

Done by a Windows app sub-agent; its report is folded in here. The lead did not repeat its runs; the lead bumped the version and built the installer. Only the virtual printer AutoPrint-Spike-PDF was used. **Not installed anywhere; nothing tried on a real printer or by a person on a real screen.**

**Verified by the sub-agent after its last source edit:** `dotnet build apps/desktop -c Release` 0 warnings; `dotnet test ... --filter "FullyQualifiedName!~LiveE2ETests"` 171 passed, 6 skipped; the same with `AP_REAL_PRINTER=AutoPrint-Spike-PDF` and `AP_SUMATRA` set: 177 passed, 0 skipped; `AutoPrint.exe --selftest-ui <folder> live` exit 0, 72 PASS, 0 FAIL; `e2e/run_local_chain.py` PASS (job visible 2.19 s, completed 5.6 s, 2 pages out), run with the backend changes of this day already in the working tree, so the lead did not run it again.

**Installer:** `dist\AutoPrintSetup-4.0.3.exe`, 59.0 MB, SHA-256 `3943fc0f623fa91ffc90f6f63fb72373467bf995710da59c112799625a966d68`, built by the lead with `apps\desktop\installeruild.ps1 -Version 4.0.3` after changing the version from 4.0.2 in six files. **The tests were not re-run after the version change** (a version string only; the publish compiled). Not signed, not installed, not scanned.

**Defect found and fixed: the reminder sound could repeat forever.** When the PC lost its connection the app kept showing the last queue it had, and chimed every 2 minutes for as long as the PC stayed on (for example all night with the router off), about requests that had long expired. Now: no sound while offline; requests past their approval time (server clock) are not counted; one reminder when the connection is back and something still waits. Test: 8 hours offline give no reminder; one unanswered request gives 29 reminders, all inside its hour.

**Other changes:**
- Opening the window from the tray, or bringing it to the front, asks the server at once if the last answer is older than 3 s (it did not before). It replaces the next regular poll, so the steady rate of one call per 10 s is unchanged; 20 calls make one poll (tested).
- The moving progress line of a printing job rests when nobody can see it (window in the tray, minimised, or the Finished tab in front).
- "Test the colour printer": the logic moved to `TestPrint` (in `TestPage.cs`) with tests: it can only go to the printer chosen in the colour box, a double click sends one page (two extra guards), the file is always deleted, every failure has plain words.
- A banner's icon sat about 7 px above its text; fixed.

**Soak** (`--selftest-ui <folder> soak:300`, 8 logical processors, per cent of one core):

| State, 300 s each | CPU | Private memory |
|---|---|---|
| Quiet queue | 0.2 to 0.8% (0.8% includes start-up) | 89 to 81 MB, falling |
| One job printing, window in view | 8 to 11% (other work was running on the PC) | steady |
| One job printing, window minimised | 0.18% | steady |

Idle cost is close to zero and memory does not grow. The one real cost is the moving line while a job prints. Not measured on a slow shop PC. Not done: capping that animation at 30 frames a second (about half the cost), because nobody could judge on a real screen whether it still looks smooth.

**Screens:** all 74 pictures of the build before these changes were looked at (26 scenes at 100%, 150% and the smallest window). The 26 scenes were **not** rendered again on the final build; the banner fix was seen only in the live run's own pictures. Left open: the Settings window (807 px tall) will always scroll on a 1366 x 768 laptop, and with the no-paper warning the last line of the disconnect text is cut until scrolled; at 640 x 480 two long banners overflow the banner area; "Colour" is not highlighted in the preview header as it is on the card; the colour test page has only black text, so it shows that the colour printer answers, not that colour works.

**Read but not run for real:** the taskbar flash (logic reads correct; while Preview or Settings is the active window, a new request flashes the taskbar button until that window is closed); the wake-up on the real "window activated" path; the sound.

**Open decisions for the founder (nothing changed):**
1. The reminder chimes every 2 minutes for up to the hour a request can wait (up to 29 times per request). Too many?
2. The 10 s poll. The remaining wait is 0 to 10 s for a request to appear when the shopkeeper is not touching the app. A shop open 12 hours makes about 4,300 calls a day at 10 s; 5 s doubles that and would bring the measured 90th percentile from about 9 s to about 5 s. A middle way: every 4 to 5 s for a few minutes after something happened, 10 s or slower when the shop is quiet (a small change in `AgentService.NextDelay`).

A V3 `F:\AutoPrint\AutoPrint.exe` was running on the PC throughout and was left alone.

## Deployed; Windows app 4.0.4 (7 October 2026, afternoon)

- **Deployed (founder decision G-1):** `wip/2026-10-06-unverified` was merged to `main` (merge commit `0603216`) and pushed. Evidence that the new code is live: `GET https://autoprint-v4.vercel.app/v1/internal/status` without a token answered 404 before the push and stopped answering 404 a few minutes after it (the waiting loop ended, which it does only on 401; that route exists only in the new code). **Nothing else was checked on the live site.**
- **NOT done, and not possible from the Claude session:** `scripts/ap_remote.py status` was refused by the session's permission system (it reads the live system with the maintenance token), so `migrate` and `e2e/run_live_e2e.py` were not attempted. **Migrations up to 0019 are therefore not known to be applied live, and the live site has not been tried end to end with the new code.** The new API is written to work with the older database (tested locally for 0019 only; 0014 to 0018 replace functions the API calls the same way). The founder runs the three commands in the handover.
- **Windows app 4.0.4** (decision G-3 and the colour test): the reminder comes three times 2 minutes apart, then every 10 minutes (test: minutes 2, 4, 6, 16, 26, 36, 46, 56 for one unanswered request); the colour test page has a red, a green and a blue square and its result line asks to check them. Verified once each on the final code: `dotnet build apps/desktop -c Release` 0 warnings; `dotnet test ... --filter "FullyQualifiedName!~LiveE2ETests"` with the virtual printer variables set: 177 passed, 0 skipped; `AutoPrint.exe --selftest-ui <folder> live`: exit 0, 72 PASS, 0 FAIL. Installer `dist\AutoPrintSetup-4.0.4.exe`, 59.0 MB, SHA-256 `f621c70acbb61c69d8b7f2ed6fa77f0b93e07b4a47764233610f2ea50ae1e649`. Not installed, not signed, not scanned; the coloured squares were not looked at on paper or on a screen (the page's content is checked by a test, and a colour test page went through the real print program to the virtual printer in the test run).
- `dist\AutoPrintSetup-4.0.3.exe` is superseded; do not hand it out.
- Decisions taken by the model under the founder's G-2 are G-3 to G-8 in `docs/DECISIONS.md`, each with its reason. Payments were deliberately not started (G-7).

## Live database updated (7 October 2026, run by the founder)

Output pasted by the founder into the session, not run by the model:
- `ap_remote.py status` before: site "live (HTTP 200)", database "ready (HTTP 200)", 9 applied (0001 to 0009), 10 pending (0010 to 0019).
- `ap_remote.py migrate`: "Applied now: 10", 0010 to 0019 in order, "The database now has 19 updates (latest: 0019_submit_answers_with_payment)".
- `ap_remote.py status` after: 19 applied, 0010 to 0019 all stamped 2026-10-07 04:05 (UTC), "Nothing pending: the database matches the code that is live."

This is also the first live run of the `status` and `migrate` commands, and it shows the new API ran against the 0009 database for a while without the site or its database check going down. **Still not checked live:** an order from start to finish on the new code and database (`e2e/run_live_e2e.py` and one PDF from a real phone), and the backfill of 0015 (that already-deleted documents now read "deleted file").

## Whole chain on the live site after the deploy: PASS (7 October 2026, run by the founder)

`e2e/run_live_e2e.py`, output pasted by the founder: verdict PASS on the new code with all 19 migrations. Order UVW3 on TST001, 2 pages sent, 2 pages in the virtual printer's file, outcome `rule_v2_satisfied`, device disconnected afterwards.
- Customer side: new order to submitted 2.1 s; "approved" 1.9 s, "printing" 2.5 s and "completed" 11.2 s after submit.
- Shop side: paired 0.67 s; job visible 5.18 s; approved 5.29 s; claimed 5.90 s; downloading 6.06 s; printing 6.65 s to 12.74 s; reporting 14.27 s; finished 14.69 s.
- "shop computer connected after 15.3 s" at the start (includes building and starting the test program; possibly a cold start of the host; not separated).

**Slower than the run of 5 October** (completed 5.9 s after submit then, 11.2 s now). The difference is in the printing stage, about 6 s here against about 2 s in the local run of the same day. Cause not investigated: one run, on the founder's network, with the virtual printer. Compare again on the real printer before reading anything into it.

Still not checked: a real phone on the live site, the installed 4.0.4 app, any physical printer.

## Founder feedback build: shop settings, several files per order, search, installer link (7 October 2026, evening, local only)

Branch `wip/2026-10-07-shop-settings-multi-file`. **Nothing here is deployed, migration 0020 is not applied live, and Windows app 4.0.5 is not installed anywhere.** Decisions: H-1 to H-6 and G-9 to G-11 in `docs/DECISIONS.md`. Built by the main session (database, API) and three sub-agents working at the same time (customer page, dashboard, Windows app); their reports are folded in below.

### What was built
- **Migration `0020_shop_settings.sql`:** `ap.shops.color_enabled` (default true); `ap.shop_settings` and `ap.shop_settings_update` (shop key; a changed price list is a new version, the old one is retired); `ap.agent_poll` gives each job `order_files` and `order_total_paise`. Safe to run twice (`IF NOT EXISTS`, `CREATE OR REPLACE`).
- **API:** `GET` and `POST /v1/shop/settings` (30 saves per 10 minutes per address); `ShopPublic.color_available`; a colour item in a quote is refused with `color_not_available` (409) when the shop has colour off. The API also runs on a database without 0020: colour reads as available, jobs default to one file, and only the dashboard's settings panel fails to load.
- **Customer page:** several PDFs in one order (at most 20), one card per file with its own colour, sides, copies and pages, "Use these settings for all files", "Add another file", one quote and one total. A shop with colour off shows "This shop prints in black & white only." The draft kept across a refresh now holds a list of files and still reads the old one-file shape.
- **Dashboard:** panel "Prices and shop details" (name, colour on or off, one price per printed side for each of four kinds plus optional bulk prices) and "Download AutoPrint for Windows" in "Connect a computer", with the SmartScreen hint. New files `apps/web/src/rates.ts`, `shop-settings.css`.
- **Windows app 4.0.5:** one search box in the tab row for both tabs (on Requests it filters the cards; Ctrl+F focuses it); a card of an order with several files says "One of N files in this order" and "Order total"; `build.ps1` also writes `dist\AutoPrintSetup.exe`. Installer `dist\AutoPrintSetup-4.0.5.exe`, 61,895,761 bytes, SHA-256 `52a9bc6ac062414c42490b7092b2f5305146a0c2d01f87f26db36cf5d71285dc` (reported by the sub-agent that built it; `dist\AutoPrintSetup.exe` is the same bytes).

### What was checked, and how
- **Python, whole suite once:** `apps\api\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`: 302 passed, 3 failed. The 3 were expectations about the old shape (shop lookup without `color_available`, the job field list, and a test that applies the newest migrations twice, which is why 0020 was made re-runnable). After the fixes those files and the new `test_shop_settings.py` were run again: 34 passed, 1 failed (two jobs made in one transaction have no fixed order in the list; the test now sorts), then the 4 settings tests alone: 4 passed. The whole suite was not run a second time.
- **Web:** `npx tsc --noEmit` clean, `npx vitest run` 83 passed in 7 files, `npm run build` built (sub-agent reports).
- **Browser tests** (`e2e/run_web_e2e.py`, dev server): 17 passed, 1 failed on the second run, including the new "two files with different settings are sent as one order with one total". The failing one is the first test of the run ("a student sends a PDF…": "3 pages" not visible within 5 s, the page still says "Uploading…"). **It fails the same way on unchanged `main`** (checked by stashing this work and running the rig: 16 passed, 1 failed, same test), so it is a cold-start timing fault of the rig that was there before, not caused by this work. Not fixed. On the first run, made while the installer was being built, "an order that is gone says so on its own page" also failed once and passed afterwards.
- **Screens looked at** (`E2E_TOOL=walk`, "no layout findings"): the dashboard with the new panel and the download button at 1280 and 360 px, and the one-file Settings step at 360 px.
- **Windows app:** `dotnet test apps/desktop/tests/AutoPrint.Core.Tests`: 172 passed, 7 skipped (contract test included). `AutoPrint.exe --selftest-ui`: exit 0; the sub-agent looked at the pictures of a search on Requests with a three-file order, a search with no match, and the Finished search at 640 x 480.

### Not verified
- Anything on the live site or the live database. The settings panel was never saved against a running server by a person; only the API tests did it.
- The several-files Settings step was not looked at as a picture (two cards, the accordion, the row with "Use these settings for all files" and "Remove" on a 320 px phone, the "Add another file" control next to the price bar). A real phone's file picker with several files.
- The `color_not_available` answer on a page that was open before the shop switched colour off: built, no test.
- Windows app 4.0.5 on a real screen, with a real several-file order, against a database with 0020, installed over 4.0.4; no Defender scan of the new installer; `live` and `soak` self-test modes not re-run.
- The download button: no GitHub release exists yet, so the link answers "not found" until the founder publishes one (`docs/RUNBOOK.md` section 9).

### Known and left open
- A file the customer removes still counts towards the 20 files of an order (there is no delete-document route), and stays stored until the normal one-hour cleanup of unsent files.
- The files of one order appear on the shop computer in no fixed order (same creation time; ordered by id).
- A search left typed in the Windows app hides new requests that do not match; the tab count and the sound still announce them.
- Dashboard: unsaved price edits are lost without a warning when the page is left; a failed load says "Could not load your prices" whatever the cause.
- The first browser test of a rig run fails on a cold start (see above).
- Colour on or off is not offered in the Windows app's printer choice (G-9).

## Deployed: the founder feedback build (7 October 2026, night)

On the founder word "deploy": `wip/2026-10-07-shop-settings-multi-file` merged into `main` (merge commit `15f13f5`) and pushed. **Seen live:** `GET https://autoprint-v4.vercel.app/v1/shops/TST001` answered with the new `color_available: true` about a minute after the push, so the new API is serving, and it runs on the database without migration 0020 as designed. **Not checked live: anything else** (the customer page with several files, the dashboard panel, which cannot load until 0020 is applied, and the download button, which has no release behind it yet). Migration 0020 is NOT applied: only the founder can run `ap_remote.py migrate`.
