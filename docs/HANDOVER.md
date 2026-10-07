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

- **`main` (pushed, live) is unchanged since 6 October:** Windows app 4.0.1, website and API of commit `f04edf8`. Live database: migrations 0001 to 0009 applied; whether 0010 to 0013 were applied by the founder is **not known in this repository** (check with `PY scripts/ap_remote.py status` once the new code is live, or `scripts/ap_report.py`).
- **Branch `wip/2026-10-06-unverified` is now tested and green locally, and holds everything below. It is NOT merged, NOT deployed, and its migrations are NOT applied live.** The branch name is historical; the work on it is no longer "unverified" in the local sense.
  - Backend: security-review fixes with tests; migrations 0014 to 0019 (0015 irreversibly blanks names and checksums of already-deleted documents; the others replace one function each); customer routes down to 1 or 2 database round trips; `ap_remote.py status` and `migrate`. Last full run: 301 passed.
  - Website: 73 unit tests, 17 of 17 browser tests in Edge and in WebKit; preview never delays Continue; pdf.js fetched in the background on the shop page; 2 s status poll between approval and result; small-phone fixes.
  - Windows app 4.0.3: `dist\AutoPrintSetup-4.0.3.exe` (SHA-256 in the file next to it and in the status file). 177 tests with the real print queue on the virtual printer, 72-step self-test, whole local chain PASS.
- The failing cancel-versus-claim race of 6 October was the shared test database running out of connections, not migration 0014.

### Next steps, in order
1. **Founder decides: merge the branch to `main` and push.** Pushing `main` deploys the site and API. Commands: `git checkout main`, `git merge --no-ff wip/2026-10-06-unverified`, `git push origin main`. The new API works with the old database, so deploy first.
2. **Founder runs** (the Claude session is not permitted to call the live maintenance endpoints): `apps\api\.venv\Scripts\python.exe scripts\ap_remote.py status`, then `... scripts\ap_remote.py migrate`, then `status` again (must say "Nothing pending"). See RUNBOOK section 8.
3. **Founder runs** `apps\api\.venv\Scripts\python.exe e2e\run_live_e2e.py`, and sends one PDF from a real phone at `/s/TST001`. After deploying also check the worker file is served compressed (command in the status file, website section of 7 October).
4. **Founder installs `dist\AutoPrintSetup-4.0.3.exe`** over the installed copy, opens Settings and **chooses the real printer** (the installed app was set to Microsoft Print to PDF, which is why order BLS3 failed), then follows `docs/TEST_THE_WINDOWS_APP.md`, including the six things listed there to try on a real screen and printer.
5. Founder actions still open from before: add the GitHub secret `AUTOPRINT_MAINTENANCE_TOKEN`; in Supabase set the `print-documents` bucket to 25 MB and `application/pdf` only.
6. Physical certification at the shop (30 to 50 real prints, duplex, colour, failure drills); then the Phase 7 leftovers (clean-PC install, reboot, 24-hour soak).
7. Payments: parked by the founder until the rest is done. Design and 14 questions in `docs/PAYMENTS_DESIGN.md`.

### Decisions waiting for the founder (nothing was changed for these)
- Reminder sound: every 2 minutes for up to an hour per unanswered request (up to 29 chimes). Keep, or fewer?
- Shop poll interval: keep 10 s, halve it (doubles the calls to the host), or "fast for a few minutes after something happens, slow when quiet".
- The shop page now downloads about 530 KB in the background for every visitor so the preview is quick. Keep, or fetch only when the file button is touched (slower preview, less mobile data)?
- Requests already waiting when the app starts make no sound at first (a reminder follows after 2 minutes). Keep?

### Known and left open (details in the status file)
Not load-tested after the round-trip change (`e2e/load_test.py` not re-run); latency on the live pooler not measured; the live PostgreSQL version not checked (the quote statement needs 12 or newer, else it falls back); Settings window scrolls on a 1366 x 768 laptop; the colour test page is black only; the dashboard's offline threshold is a copy of a server setting and trusts the browser clock; a locked PDF uploaded after the 3 s check limit is refused only by the server and that path has no test; finalize could save one database round trip; the docstring of `supabase/tests/test_queue_and_retention.py` still says "0014 to 0018".

### Working notes from this session
- Sub-agents sharing the local PostgreSQL can exhaust its connections ("too many clients already"): re-run that test alone before believing a failure.
- `test_migrate_endpoint.py` asserts the newest migration (now `0019_submit_answers_with_payment`); update it when adding one.
- `vite preview` compresses by itself; do not add a compression plugin (it made the production build blank locally on 6 October).
- Browser tools: `E2E_TOOL=walk E2E_OUT=<folder>` (screenshots at 320, 360, 412 px, dashboard included) and `E2E_TOOL=perf` (production build, slow-phone profile) through `e2e/run_web_e2e.py`.
- The founder asked on 7 October not to spend tokens on unnecessary testing: test what a change touches, once.
- A V3 `F:\AutoPrint\AutoPrint.exe` was running on this PC during the session. Leave it alone.
