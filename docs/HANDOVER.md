# Handover: where AutoPrint V4 stands (5 October 2026)

Written so work can resume in a new session with no memory of this one. Read this first, then `docs/IMPLEMENTATION_STATUS.md` (detail and evidence), `docs/DECISIONS.md` (what is frozen), `docs/RUNBOOK.md` (operating a shop).

## 1. What AutoPrint V4 is
A customer sends a PDF from a phone (no account); the shopkeeper approves it in a Windows app; the app prints it on the shop's own printer. V4 is a fully separate project from V3 (`F:\Projects\Printer automation`), which must never be modified, deployed over, or connected.

| Thing | Where |
|---|---|
| Code | `F:\Projects\AutoPrint-V4`, GitHub `P-Suraj/AutoPrint-V4`, branch `main` (last commit `735c6ac` at writing) |
| Live site | https://autoprint-v4.vercel.app (Vercel project `autoprint-v4`, region Mumbai; pushes to `main` deploy automatically) |
| Database and file storage | Supabase project `qgiutwhmqidnkcwbeuls` (Mumbai), schema `ap` |
| Test shop | `TST001` ("AutoPrint Test Shop"): customer page `/s/TST001`; shopkeeper link is in `dist\SHOP_LINK.txt` (git-ignored) |
| Windows app | `apps/desktop`; installer `dist\AutoPrintSetup-4.0.0.exe` (git-ignored; rebuild with `apps\desktop\installer\build.ps1`) |

## 2. What is built and working (evidence in IMPLEMENTATION_STATUS.md)
- **Database** (`supabase/migrations/0001..0007`, all applied live): orders, jobs, print attempts, devices, pairings, shop logins; every business rule is a PostgreSQL function returning `{"result": code}`. Separate state machines for order, payment, job and print attempt. A job is never printed twice automatically; anything uncertain goes to a human (`needs_attention`).
- **API** (`apps/api`, FastAPI on Vercel): customer routes (order secret header), shop-app routes (device id and secret headers), shopkeeper dashboard routes (`X-Shop-Key`), founder routes (`X-Maintenance-Token`: migrate, maintenance, shop-login, shop provisioning, report).
- **Customer web** (`apps/web`, React, Vite): scan or open `/s/CODE`, or type the 3-letters-3-digits code on the home page (typo-tolerant; remembers last 5 shops); upload, options, price estimate, submit, live status. Wording says "Sent to printer", never "Printed" (decision O-8).
- **Shopkeeper dashboard** (`/shop#key=...`): private-link login; type the code shown by the Windows app to connect a computer; list and disconnect computers. The `shop_logins.method` column reserves `phone` and `email` for later sign-in methods.
- **Windows app** (`apps/desktop`, C# .NET 8, WPF): pairing screen with code, queue cards, Preview (built-in Windows PDF viewer), Approve/Reject, needs-attention actions, printer picker with test page, tray icon, single instance, start at sign-in option, offline/online dot. Core: SQLite journal written before printing, never reprints, recovery reports uncertain, SumatraPDF portable (hash-checked) as engine, native winspool queue observer.
- **Installer**: Inno Setup, per-user, no administrator, self-contained, 59 MB, publisher "Suraj Pandavula", not signed.
- **Founder tools** (through the live API because this PC cannot reach the database ports): `scripts/ap_remote.py`, `scripts/ap_report.py`.
- **CI**: `.github/workflows/maintenance.yml` (every 15 minutes).

## 3. Test status at the last run
- Python: 211 passed (`apps\api\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`; needs the local test PostgreSQL, see section 6).
- Desktop: 56 passed, 3 skipped (`dotnet test apps/desktop/tests/AutoPrint.Core.Tests`; the skipped ones need `AP_REAL_PRINTER` and `AP_SUMATRA`).
- Web: 39 unit tests pass (`npx vitest run`); typecheck and build pass. The Playwright end-to-end suite was not re-run after the shop-code box was added.
- Whole chain on the live site, virtual printer: PASS (`e2e/run_live_e2e.py`): customer sees "printing" about 2.4 s and "completed" about 5.9 s after submit.

## 4. What is NOT verified (be honest about this)
- **Physical printing, in any form.** The Kyocera TASKalfa 3212i is installed but was offline and untouched. The completion rule (v2, migration 0006) was derived on a virtual printer and is **provisional**. Open risk: if a real driver never reports PRINTING, no job would ever auto-complete and decision F-8 needs the founder.
- Duplex and colour output on paper; failure signals (jam, paper out, offline, cable pulled, power off).
- Real phones (only browser emulation was used); the WPF windows driven with a real queued job (the founder started testing this); upgrade over an older install; a clean PC without .NET; the "start at sign-in" option; a reboot; a 24-hour soak.
- Defender: the installer scan showed no detection; the file is unsigned so SmartScreen will warn. Not tested on other antivirus products.
- Cold-start latency of the Vercel function; 7 npm advisories (the audit endpoint was unavailable); Vercel Hobby terms for commercial use; retention proven live past a real window.
- No per-address rate limit on customer requests (nothing prints without shopkeeper approval, and unapproved jobs expire in 1 hour).

## 5. Next steps, in suggested order
1. **Founder action:** add GitHub repository secret `AUTOPRINT_MAINTENANCE_TOKEN` (value of `AUTOPRINT_V4_MAINTENANCE_TOKEN` in `.env`) so the cleanup workflow works.
2. **Founder test** following `docs/TEST_THE_WINDOWS_APP.md`; collect wording, speed and warning-text feedback.
3. **Physical certification (Phases 1, 6, 8)** when at the shop: 30 to 50 real prints, duplex and colour, every failure drill, record which flags the real driver raises, re-validate or change the completion rule. This gates any "Printed" wording and any payments.
4. Phase 7 leftovers: timed clean-PC install, reboot test, 24-hour soak, retention proven live, purge-on-request script, counter poster generator.
5. Customer side: rate limit, add-to-home-screen, optional wording "Sent to printer. Collect it at the counter."
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
