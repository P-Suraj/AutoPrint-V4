# AutoPrint V4

Cloud-to-local print automation for campus and local print shops.
A student uploads a PDF from a phone browser; the shopkeeper approves it in a Windows app; the shop's existing printer prints it.

**Status:** the whole software chain is built and passes end to end on a virtual printer. Physical printing is not certified yet.
See `docs/HANDOVER.md` first, then `docs/IMPLEMENTATION_STATUS.md` for evidence and what is unverified.

This is a standalone project. It shares no code, database, storage, credentials or deployment with AutoPrint V3.

## Parts

| Folder | What it is |
|---|---|
| `apps/web` | Customer pages and the shopkeeper web dashboard (React, Vite, TypeScript) |
| `apps/api` | The API (Python, FastAPI, on Vercel) |
| `apps/desktop` | The shop's Windows app (C# .NET 8, WPF) and its installer |
| `supabase/migrations` | The database: every business rule is a PostgreSQL function |
| `contracts` | Generated API contract and shared test vectors |
| `scripts` | Founder tools: add a shop, prices, shop links, reports |
| `e2e` | Whole-chain tests |

## Documents

| File | Purpose |
|---|---|
| `docs/HANDOVER.md` | Where things stand and how to work on the project. Read first. |
| `docs/RUNBOOK.md` | Running a shop: add a shop, install, daily check, what to do when something goes wrong |
| `docs/TEST_THE_WINDOWS_APP.md` | Trying the Windows app yourself |
| `docs/IMPLEMENTATION_STATUS.md` | Verified results. The only status file. |
| `docs/DECISIONS.md` | Every decision, with status |
| `docs/PRODUCT.md` | Scope boundary: what is in and out of the MVP |
| `docs/BUILD_PHASES.md` | The phased build plan and rules for AI coding agents |

## Running the tests

`PY` means `apps\api\.venv\Scripts\python.exe`. The Python and browser suites need the local test PostgreSQL (see `docs/HANDOVER.md`, section 6).

| What | Command |
|---|---|
| API and database | `PY -m pytest -q -p no:cacheprovider` |
| Windows app | `dotnet test apps/desktop/tests/AutoPrint.Core.Tests` |
| Web unit tests | `npx vitest run` in `apps/web` |
| Web in a real browser | `PY e2e/run_web_e2e.py` |
| Whole chain on this PC (virtual printer, no internet) | `PY e2e/run_local_chain.py` |
| Whole chain on the live site (virtual printer) | `PY e2e/run_live_e2e.py` |
