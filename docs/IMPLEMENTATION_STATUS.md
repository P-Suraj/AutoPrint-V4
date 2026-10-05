# Implementation Status

**Last updated:** 5 October 2026
**Current phase:** 2 (contracts) substantially done; 1 (print spike) done on a virtual printer only; 3 not started.

## Phase gates

| Phase | Gate | State |
|---|---|---|
| 0 Approvals and repository | all decisions recorded, pushed, founder confirms | Mostly done. O-items answered, D-5/D-12/D-15/D-18 approved; the other D-items are still PROPOSED. Founder written confirmation not given as a single statement |
| 1 Print spike | physical printer, 30 normal prints, completion rule, engine chosen | **NOT PASSED.** Virtual printer only (founder-allowed). 30/30 normal prints, completion rule v1 written, engine provisional. Physical-printer run, duplex/colour and real failure drills outstanding. See `docs/PRINT_SPIKE_REPORT.md` |
| 2 Contracts | see checklist below | Done except the C# client |
| 3 Backend slice | customer API built and tested locally (45 integration tests) against a real PostgreSQL; Supabase storage backend verified live; **database not yet created on Supabase and nothing deployed** | In progress |
| 4 Customer web | Built. 24 unit tests (estimator matches Python on 21 shared vectors) and 6 end-to-end browser tests pass against the real API, real PostgreSQL and real file storage on this PC | **Gate NOT passed**: not tested on a real Android or iPhone, not tested against the deployed API, 60-second timing not measured. Emulation only (Edge, Pixel 7 profile) |
| 5-10 | not started | |

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

## Findings so far

- V3's bundled `SumatraPDF.exe` is the installer, not the portable program (identical hash). V3 could never have reliably printed through it.
- "Job left the spooler queue" is not evidence of printing: a cancelled job also leaves. Fixed in the rule.
- A killed print process can leave an orphan job stuck in the spooler.
- A nonexistent printer name makes Sumatra hang rather than fail.
- A bug the tests caught: the completion rule failed open when evidence lacked `max_pages_printed`. Fixed.

## Not verified

Physical printing in any form. Duplex and colour. Anything on Supabase or a deployed host: no V4 cloud resource exists yet (Phase 3 needs founder-created accounts).

## Blocked on founder

- Physical printer access for the real Phase 1 drills (the Kyocera on this PC is offline).
- Creating the V4 Supabase project and an API host account (Phase 3). The agent must not use any V3 resource.
- Review of `docs/CONTRACTS.md` and `docs/ARCHITECTURE.md`.

## Machine changes made on this PC (clean up when finished)

- A local printer named **AutoPrint-Spike-PDF** and a printer port at `F:\Projects\AutoPrint-V4\spikes\_out\spike_out.pdf`. One orphan spooler job is stuck on it. Remove with `Remove-Printer` and `Remove-PrinterPort`.
- A throwaway PostgreSQL 17 data directory at `.localdb/` (ignored by git), started on port 55432.
- .NET 8 SDK installed with winget.
