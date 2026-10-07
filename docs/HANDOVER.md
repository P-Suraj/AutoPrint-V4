# Handover: where AutoPrint V4 stands (6 October 2026)

Written so work can resume in a new session with no memory of this one. Read this first, then `docs/IMPLEMENTATION_STATUS.md` (detail and evidence), `docs/DECISIONS.md` (what is frozen), `docs/RUNBOOK.md` (operating a shop).

## 1. What AutoPrint V4 is
A customer sends a PDF from a phone (no account); the shopkeeper approves it in a Windows app; the app prints it on the shop's own printer. V4 is a fully separate project from V3 (`F:\Projects\Printer automation`), which must never be modified, deployed over, or connected.

| Thing | Where |
|---|---|
| Code | `F:\Projects\AutoPrint-V4`, GitHub `P-Suraj/AutoPrint-V4`, branch `main` (see `git log` for the latest commit) |
| Live site | https://autoprint-v4.vercel.app (Vercel project `autoprint-v4`, region Mumbai; pushes to `main` deploy automatically) |
| Database and file storage | Supabase project `qgiutwhmqidnkcwbeuls` (Mumbai), schema `ap` |
| Test shop | `TST001` ("AutoPrint Test Shop"): customer page `/s/TST001`; shopkeeper link is in `dist\SHOP_LINK.txt` (git-ignored) |
| Windows app | `apps/desktop`; installer `dist\AutoPrintSetup-4.0.0.exe` (git-ignored; rebuild with `apps\desktop\installer\build.ps1`) |

## 2. What is built and working (evidence in IMPLEMENTATION_STATUS.md)
- **Database** (`supabase/migrations/0001..0013` and later; 0001 to 0009 applied live, **0010 and later not yet applied live as of 6 Oct evening**; check with `scripts/ap_report.py`, which says when 0011 is missing): orders, jobs, print attempts, devices, pairings, shop logins, rate limits, shop emails; every business rule is a PostgreSQL function returning `{"result": code}`. Separate state machines for order, payment, job and print attempt. A job is never printed twice automatically; anything uncertain goes to a human (`needs_attention`).
- **API** (`apps/api`, FastAPI on Vercel): customer routes (order secret header), shop-app routes (device id and secret headers), shopkeeper dashboard routes (`X-Shop-Key`), founder routes (`X-Maintenance-Token`: migrate, maintenance, shop-login, shop provisioning, report).
- **Customer web** (`apps/web`, React, Vite): scan or open `/s/CODE`, or type the 3-letters-3-digits code on the home page (typo-tolerant; remembers last 5 shops); upload, options, price estimate, submit, live status. Wording says "Sent to printer", never "Printed" (decision O-8).
- **Shopkeeper dashboard** (`/shop#key=...`): private-link login; type the code shown by the Windows app to connect a computer; list and disconnect computers. The `shop_logins.method` column reserves `phone` and `email` for later sign-in methods.
- **Windows app** (`apps/desktop`, C# .NET 8, WPF): pairing screen with code, queue cards, Preview (built-in Windows PDF viewer), Approve/Reject, needs-attention actions, printer picker with test page, tray icon, single instance, start at sign-in option, offline/online dot. Core: SQLite journal written before printing, never reprints, recovery reports uncertain, SumatraPDF portable (hash-checked) as engine, native winspool queue observer.
- **Installer**: Inno Setup, per-user, no administrator, self-contained, 59 MB, publisher "Suraj Pandavula", not signed.
- **Founder tools** (through the live API because this PC cannot reach the database ports): `scripts/ap_remote.py`, `scripts/ap_report.py`.
- **CI**: `.github/workflows/maintenance.yml` (every 15 minutes).

## 3. Test status at the last run
- Python: 219 passed (`apps\api\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`; needs the local test PostgreSQL, see section 6).
- Desktop: 58 passed, 3 skipped (`dotnet test apps/desktop/tests/AutoPrint.Core.Tests`; the skipped ones need `AP_REAL_PRINTER` and `AP_SUMATRA`). With those two set to the virtual printer, the 2 real-spooler tests also pass (60 of 60, the live end-to-end test excluded).
- Web: 39 unit tests pass (`npx vitest run`); typecheck and build pass. The 6 Playwright tests pass against the production build served with the `vercel.json` headers.
- Whole chain on the live site, virtual printer: PASS on 6 Oct (`e2e/run_live_e2e.py`): customer sees "printing" about 2.4 s and "completed" about 5.9 s after submit. **Not re-run after the review fixes of 6 Oct** (see IMPLEMENTATION_STATUS.md, "Review fixes").

## 4. What is NOT verified (be honest about this)
- **Physical printing, in any form.** The Kyocera TASKalfa 3212i is installed but was offline and untouched. The completion rule (v2, migration 0006) was derived on a virtual printer and is **provisional**. Open risk: if a real driver never reports PRINTING, no job would ever auto-complete and decision F-8 needs the founder.
- Duplex and colour output on paper; failure signals (jam, paper out, offline, cable pulled, power off).
- Real phones (only browser emulation was used); the WPF windows driven with a real queued job (the founder started testing this); upgrade over an older install; a clean PC without .NET; the "start at sign-in" option; a reboot; a 24-hour soak.
- Defender: the installer scan showed no detection; the file is unsigned so SmartScreen will warn. Not tested on other antivirus products.
- Cold-start latency of the Vercel function; 7 npm advisories (the audit endpoint was unavailable); Vercel Hobby terms for commercial use; retention proven live past a real window.
- Per-address rate limits exist (migration 0008) but were not flood-tested live, and the address values the host passes were not compared with a real customer address.
- The review fixes of 6 Oct are tested locally only: not deployed, migration 0010 not applied live, no new installer built, the new Content-Security-Policy header not seen on the live site (the upload to Supabase Storage under it is untested).

## 5. Next steps, in suggested order
0. **Ship the review fixes:** commit and push (deploys the site), apply migration 0010 through `/v1/internal/migrate`, then on the live site send one PDF from `/s/TST001` (proves uploads work under the new Content-Security-Policy) and re-run `e2e/run_live_e2e.py`. Build a new installer (bump the version) so shops get the desktop fixes.
1. **Founder action:** add GitHub repository secret `AUTOPRINT_MAINTENANCE_TOKEN` (value of `AUTOPRINT_V4_MAINTENANCE_TOKEN` in `.env`) so the cleanup workflow works.
2. **Founder test** following `docs/TEST_THE_WINDOWS_APP.md`; collect wording, speed and warning-text feedback.
3. **Physical certification (Phases 1, 6, 8)** when at the shop: 30 to 50 real prints, duplex and colour, every failure drill, record which flags the real driver raises, re-validate or change the completion rule. This gates any "Printed" wording and any payments.
4. Phase 7 leftovers: timed clean-PC install, reboot test, 24-hour soak, retention proven live, purge-on-request script, counter poster generator.
5. Customer side: done (rate limits, installable site, wording "Sent to printer. Collect it at the counter."). Still to check: run `GET /v1/internal/whoami` to confirm real addresses reach the limiter.
5b. Switch on email sign-in for shopkeepers (steps in IMPLEMENTATION_STATUS.md, section "Items 3 and 4 work"); it is built but needs the Supabase dashboard settings and the publishable key.
6. Code signing route decision (`docs/DESKTOP_DISTRIBUTION.md`): unsigned for the first pilot shops; report each build to Microsoft; buy a certificate when shops install without the founder.
7. Phase 9 payments via FinFlow (not started; blocked on physical certification and the founder's O-2 decision: no payments before certification). Phase 10 validation.
8. Business questions kept in the background (not yet answered): adoption baseline (time about 20 real WhatsApp or email jobs at the pilot shop), ads versus fees, why competitors are not everywhere, distribution.

## 6. How to work on it
- Shell is Git Bash plus PowerShell on Windows 11. `dotnet` is at `C:\Program Files\dotnet` (add to PATH in Git Bash). Node at `C:\Program Files\nodejs`. Python venv at `apps\api\.venv`.
- Local test database: PostgreSQL 17 at `F:\Projects\AutoPrint-V4\.localdb\data`, port 55432. It was stopped once by the system for low memory. Start: `"C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" -D .localdb\data -o "-p 55432 -c listen_addresses=127.0.0.1" -l .localdb\pg.log start` (it can look hung with `-w`; the server is usually already up). Tests create and drop their own databases.
- Secrets live only in the git-ignored `.env` and the Vercel project environment. **Never print or commit them.** Vercel applies environment changes only to new deployments: redeploy after any change. The Supabase database ports are not reachable from this PC, so use the founder API tools, not `psycopg2`, for live data.
- Tooling gotchas seen this session: the Bash tool failed on heredocs containing apostrophes (write files with the Write tool); the Edit tool needs a prior Read for files outside the working directory.
- Contract files are generated: after changing the API run `scripts/export_openapi.py` and `npm run gen:client` in `apps/web`; stale-file tests enforce this.
- Releases: bump the version in `AutoPrint.Desktop.csproj`, run `installer\build.ps1 -Version x.y.z`, publish the SHA-256 with it.

## 7. Machine changes on the founder PC (clean up when finished)
- Virtual printer **AutoPrint-Spike-PDF** and its port file `spikes\_out\spike_out.pdf`; one orphan spooler job may remain. Remove with `Remove-Printer` and `Remove-PrinterPort`.
- The local PostgreSQL data directory `.localdb` (git-ignored).
- .NET 8 SDK (winget). Inno Setup 6 was already present.
- The founder may have the **AutoPrint app installed on this PC** (computer name `P-SURAJ`, paired to TST001, data in `%LOCALAPPDATA%\AutoPrintV4`). Uninstall from Settings, Apps. The test installs made by Claude were removed.
- Test data on the live database for shop `TST001` (completed, cancelled and expired orders; revoked `E2E-TEST-PC` devices; shop logins labelled `e2e-run`, `probe` (revoked) and `founder-test`).
- V3's `%LOCALAPPDATA%\AutoPrint` folder was touched once by a log line that was deleted; V3 data is intact.

## 8. Rules the founder set (do not break)
- Never modify, deploy over, or connect to V3. Never print or expose secrets. Do not ask the founder for a Vercel token (the machine is logged in).
- Free resources only: no credit card, no paid always-on host.
- Keep it fast and smooth; efficient in both speed and cost. Report honestly: no claim without evidence, mark anything unverified.
- Adoption bar: AutoPrint must be at least 50% more efficient than WhatsApp or email for both student and shopkeeper.
- Claude Code runs on the founder laptop; if it sleeps, work pauses. Cloud sessions cannot reach the printer or local files.

Migration 0009 is applied live (6 Oct 2026); email sign-in stays inactive until the Supabase settings and the publishable key are added. Migration 0010 (email sign-ins expire after 30 days and are revoked with their address) is written and tested locally, not applied live.

## CURRENT STATE on 7 October 2026: read this before anything else

(Sections 2 to 5 above describe 6 October and are partly out of date: test counts, installer version and "next steps" are superseded by this section. Evidence for everything here is in `docs/IMPLEMENTATION_STATUS.md`, the sections dated 7 October.)

- **`main` is deployed (7 October, merge commit `0603216` and later):** security-review fixes, customer routes in 1 or 2 database round trips, the website changes, and the source of Windows app 4.0.4. Seen live: only that the new `/v1/internal/status` route exists. **Not checked live: anything else.**
- **Live database: all 19 migrations applied** (0010 to 0019 by the founder on 7 October 2026 at 04:05 UTC with `ap_remote.py migrate`; `status` afterwards: "Nothing pending"). The Claude session is refused every call that uses the maintenance token, so only the founder can run `status` and `migrate`.
- **Windows app 4.0.4:** `dist\AutoPrintSetup-4.0.4.exe` (SHA-256 next to it and in the status file). Not yet installed anywhere. The founder's installed copy is older and was set to Microsoft Print to PDF.
- The founder gave the model freedom to decide features (G-2), with "do not over-engineer". Decisions taken under it are G-3 to G-8 in `docs/DECISIONS.md`. **Payments are deliberately not started (G-7).**
- The non-payment software build is complete as far as it can be without a real printer, a real phone and the founder's live checks. What remains is checking, not building.

### Next steps, in order (all for the founder; `PY` = `apps\api\.venv\Scripts\python.exe`)
1. DONE 7 October: `PY scripts\ap_remote.py status`.
2. DONE 7 October: `PY scripts\ap_remote.py migrate` (10 applied, then "Nothing pending").
3. DONE 7 October: `PY e2e\run_live_e2e.py` PASS on the new code and database (completed 11.2 s after submit). Still to do: send one PDF from a real phone at `https://autoprint-v4.vercel.app/s/TST001`.
4. Install `dist\AutoPrintSetup-4.0.4.exe` over the installed copy, open Settings, **choose the real printer**, press "Print a test page" (and "Test the colour printer" if there is one), then follow `docs/TEST_THE_WINDOWS_APP.md`.
5. Add the GitHub secret `AUTOPRINT_MAINTENANCE_TOKEN` (the cleanup workflow fails until then); in Supabase set the `print-documents` bucket to 25 MB and `application/pdf` only.
6. Physical certification at the shop with `docs/pilot/` (30 to 50 real prints, duplex, colour, failure drills, record what the real driver reports). Until then the page says "Sent to printer", never "Printed".
7. Phase 7 leftovers when a spare PC is at hand: clean-PC install timed, reboot, 24-hour soak.
8. If anything fails in steps 1 to 4, paste the exact output into a new session; the model can fix code but cannot see the live system.

### Known and left open (details in the status file)
Not load-tested after the round-trip change (`e2e/load_test.py` not re-run); latency on the live pooler not measured; the live PostgreSQL version not checked (the quote statement needs 12 or newer, else it falls back); Settings window scrolls on a 1366 x 768 laptop; the colour test page is black only; the dashboard's offline threshold is a copy of a server setting and trusts the browser clock; a locked PDF uploaded after the 3 s check limit is refused only by the server and that path has no test; finalize could save one database round trip; the docstring of `supabase/tests/test_queue_and_retention.py` still says "0014 to 0018".

### Working notes from this session
- Sub-agents sharing the local PostgreSQL can exhaust its connections ("too many clients already"): re-run that test alone before believing a failure.
- `test_migrate_endpoint.py` asserts the newest migration (now `0019_submit_answers_with_payment`); update it when adding one.
- `vite preview` compresses by itself; do not add a compression plugin (it made the production build blank locally on 6 October).
- Browser tools: `E2E_TOOL=walk E2E_OUT=<folder>` (screenshots at 320, 360, 412 px, dashboard included) and `E2E_TOOL=perf` (production build, slow-phone profile) through `e2e/run_web_e2e.py`.
- The founder asked on 7 October not to spend tokens on unnecessary testing: test what a change touches, once.
- A V3 `F:\AutoPrint\AutoPrint.exe` was running on this PC during the session. Leave it alone.

## AFTER THE WALKTHROUGH, 7 October 2026 evening: read this too

The founder asked for six things (H-1 to H-6 in `docs/DECISIONS.md`). Five are built on branch **`wip/2026-10-07-shop-settings-multi-file`**, tested locally only (evidence: the last section of `docs/IMPLEMENTATION_STATUS.md`). `main` and the live site are unchanged. H-6 (email sign-in) was left alone on his word.

Built: the shopkeeper sets name, prices and colour on or off on the dashboard (migration 0020); several files per order with their own settings; search on the Requests tab and order totals in Windows app 4.0.5 (`dist\AutoPrintSetup-4.0.5.exe`); a download button for the installer on the dashboard.

### Next steps, in order (for the founder; `PY` = `apps\api\.venv\Scripts\python.exe`)
1. Say "deploy" to a model session (it merges the branch into `main` and pushes; the site deploys by itself), or do it yourself: `git checkout main`, `git merge wip/2026-10-07-shop-settings-multi-file`, `git push`.
2. `PY scripts\ap_remote.py migrate` (applies 0020), then `PY scripts\ap_remote.py status` should say nothing is pending. Until this is run the site works as before, but the dashboard's price panel cannot load.
3. Publish the installer so the dashboard button works: GitHub, the repository, Releases, "Draft a new release", tag `v4.0.5`, attach `dist\AutoPrintSetup.exe` (exactly this name), Publish. Details in `docs/RUNBOOK.md` section 9.
4. Open the dashboard link: change a price and save, switch colour off and on, press the download button. On a phone open `/s/TST001` and send two PDFs with different settings.
5. Install `dist\AutoPrintSetup-4.0.5.exe` over the installed copy and follow `docs/TEST_THE_WINDOWS_APP.md` ("What is new in 4.0.5"): type an order code in the search box, approve a two-file order.
6. Then the earlier list above still stands (real printer, GitHub secret, bucket limits, physical certification).

### Working notes
- The first browser test of `e2e/run_web_e2e.py` fails on a cold start on `main` as well; the rest pass. Do not chase it as a regression.
- `test_migrate_endpoint.py` now names `0020_shop_settings`; `test_review_fixes.py` applies the two newest migrations twice, so a new migration must be safe to run twice.
- Three forked sub-agents with separate files worked without clashes. `store.ts`, `api.ts` and `styles.css` are shared by the customer page and the dashboard: give each file to one owner.

**Update, 7 October night:** step 1 above is DONE (`main` at merge commit `15f13f5` is deployed; the live shop lookup shows `color_available`). Steps 2 to 5 are still to do, starting with `PY scripts\ap_remote.py migrate`.

**Update:** step 2 is DONE too (founder ran `migrate` and `status` on 7 October, 08:57 UTC: 20 applied, nothing pending). Next: step 3 (publish the GitHub release with `dist\AutoPrintSetup.exe`), then steps 4 and 5.

**Update, 7 October night (2):** Windows app is now **4.0.6** (`dist\AutoPrintSetup-4.0.6.exe`; one card per order with "View files", decision H-7). Wherever the steps above say 4.0.5, use 4.0.6: release tag `v4.0.6`, attach `dist\AutoPrintSetup.exe`. The app runs on Windows 10 (1903+) and 11, 64-bit, not on Windows 7 (H-8).

**Update, 7 October night (3):** the 4.0.6 source is merged into `main` and pushed (founder said "deploy"). It changes only the Windows app; the website code is the same. Still to do by the founder: publish release `v4.0.6` with `dist\AutoPrintSetup.exe`, then steps 4 and 5 above.
