# Decisions

Append-only. Status is one of FROZEN, PROPOSED, OPEN, APPROVED, REJECTED.
Full reasoning for each ID is in `docs/BUILD_PHASES.md` section 4.

## Frozen by the founder (5 October 2026)

F-1 isolated project and repo · F-2 first success target · F-3 web-only customer surface · F-4 anonymous customers · F-5 PDF only · F-6 manual approval · F-7 one Windows desktop app · F-8 spooler-evidence completion, ambiguous means human · F-9 order/payment/attempt/pickup separate · F-10 FinFlow owns money · F-11 Supabase plus one small always-on backend, ₹500–2,000/month · F-12 Windows 10/11, founder-managed onboarding · F-13 private storage, short retention, never used for AI · F-14 never log secrets, signed URLs or documents.

## Decisions log (D = design proposals, O = open questions)

| ID | Subject | Status |
|---|---|---|
| D-1 | Monorepo layout | PROPOSED |
| D-2 | API: Python + FastAPI on Vercel serverless (project autoprint-v4, region bom1), Supabase pooler for SQL | REVISED 2026-10-05 (see O-4). Not yet deployed or measured |
| D-3 | New Supabase project in Mumbai, database and storage only | PROPOSED |
| D-4 | Web: React + Vite + TypeScript on new Vercel project | PROPOSED |
| D-5 | Desktop: C# .NET WPF | APPROVED 2026-10-05 (via O-3) |
| D-6 | Print engine decided by Phase 1 spike | PROVISIONAL 2026-10-05: SumatraPDF 3.6.1 portable. Measured on a virtual printer only; the PDFium/Windows-API alternative was not compared. Re-validate on the physical printer. |
| D-7 | Business rules in SQL transactions | PROPOSED |
| D-8 | Upload once, validate once | PROPOSED |
| D-9 | Previews rendered client-side | PROPOSED |
| D-10 | Desktop app reaches the API by HTTPS polling about every 10 s (heartbeat and job list in one call); no WebSocket | REVISED 2026-10-05: serverless cannot hold a socket. Supabase Realtime is a later option, unverified |
| D-11 | No cookies; order secret in header | PROPOSED |
| D-12 | One-time enrolment code, DPAPI secret, no shopkeeper PIN for first shop | APPROVED 2026-10-05 (via O-6) |
| D-13 | OpenAPI is the single contract, generated clients | PROPOSED |
| D-14 | Cross-component end-to-end test | PROPOSED |
| D-15 | Schema supports many documents per order; MVP screen allows one PDF | APPROVED 2026-10-05 (via O-9) |
| D-16 | A4 only, B&W and colour printer slots | PROPOSED |
| D-17 | Founder operations as scripts | PROPOSED |
| D-18 | Deploy a skeleton in Phase 3 | APPROVED 2026-10-05 |
| C-1 | Completion rule version 2 (`docs/PRINT_SPIKE_REPORT.md` addendum, migration 0006). Version 1 also required pages printed >= 1; dropped because Windows reported 0 for a job that printed | PROVISIONAL 2026-10-05: derived from a virtual printer; must be re-validated on a physical printer before Phase 8 |
| C-3 | Desktop app: hand-written typed wire models plus a contract test against `contracts/openapi.json`, instead of a generated C# client (D-13 adjusted). NSwag turned every nullable field into an empty class and would have silently lost values | DECIDED 2026-10-05 |
| C-4 | Desktop app reads the spooler through the native winspool API, not System.Printing (thread affinity crashed async code) | DECIDED 2026-10-05 |
| C-5 | Device pairing is initiated by the shop PC (migration 0005): the app makes its own secret and shows a short code; the founder approves it. The one-time enrollment code remains as a fallback | DECIDED 2026-10-05 |
| C-2 | Founder allowed a virtual printer for Phase 1 testing (2026-10-05) | RECORDED. The Phase 1 gate still requires a physical printer and is NOT passed |
| O-1 | Submit from anywhere | ANSWERED: yes, shop link works off-site |
| O-2 | Payments timing | ANSWERED: no online payment before physical certification; pay-at-counter for the pilot; FinFlow after printing is proven (Phase 9) |
| O-3 | C# codebase | ANSWERED: yes, C# / .NET / WPF |
| O-4 | Always-on host | ANSWERED 2026-10-05: founder has no card, so no always-on host. Use free resources: Vercel (bom1) for the API and web, Supabase for database and storage, GitHub Actions cron for scheduled maintenance. Risks listed in docs/ARCHITECTURE.md |
| O-5 | Retention | ANSWERED: unconfirmed/abandoned uploads 1 hour; files 24 hours after final state; hard maximum 48 hours from upload |
| O-6 | Shopkeeper PIN/login | ANSWERED: none for first shop; revisit before the second shop |
| O-7 | Pilot shop, PC, printers | PENDING: founder will supply shop, Windows PC/version, printer models, connection type, access details before Phase 1. Blocks Phase 1. |
| O-8 | Success wording | ANSWERED: "Sent to printer". Do not say "Printed" until the Phase 1 spike proves the completion evidence. |
| O-9 | Multiple PDFs | ANSWERED: no multi-PDF UI for certification; schema supports many documents from day one |
| O-10 | Unapproved job expiry | ANSWERED: customer can cancel before approval; unapproved jobs expire after a fixed 1-hour window, stored as `expires_at` on the order. No shop closing-time configuration in the MVP. |

## Payments and print mode (founder, 6 October 2026)

Decided by the founder for Phase 9. **Nothing here is built yet**; payment work starts only after the non-payment software is complete.

| ID | Subject | Status |
|---|---|---|
| P-1 | Each shop receives its customers' payments directly, through its own payment-provider and KYC account. AutoPrint never collects or settles merchant funds | DECIDED 2026-10-06 |
| P-2 | FinFlow owns the payment infrastructure and money movement and runs as a separate always-on service. No payment logic moves into AutoPrint (F-10 stands) | DECIDED 2026-10-06 |
| P-3 | Manual approval is no longer the only mode (changes F-6). Each shop has two settings: **Online payments** ON/OFF and **Print mode** MANUAL/AUTO. Payments OFF: submit, then the normal shopkeeper approval. ON + MANUAL: the customer pays, the job is paid and ready, the shopkeeper approves, then it prints. ON + AUTO: once payment is confirmed server-side the job is authorised to print with no shopkeeper approval; the shopkeeper's job is to have the print ready before the customer arrives | DECIDED 2026-10-06 |
| P-4 | The customer-facing payment success page is never proof of payment. Only FinFlow's server-side confirmation (webhook) is | DECIDED 2026-10-06 |
| P-5 | Where FinFlow is hosted. It needs a JVM service, PostgreSQL, Redis and RabbitMQ; O-4 says free resources only | OPEN: founder to decide |
| P-6 | Whether O-2 (no online payment before physical certification) still holds | ANSWERED 2026-10-06: the founder states that physical printing passed on a real printer ("I tried it out on a printer and it worked") and that nothing should be held back for it. Recorded on the founder's word: no results table, printer model, job count or failure drills are in the repository. Payment work is no longer blocked by certification; it still starts only after the non-payment build is complete |

## Resources (no secrets here)

| Resource | Value | Verified |
|---|---|---|
| Supabase project ref | qgiutwhmqidnkcwbeuls (V4 only; V3 uses a different ref); region Mumbai per founder, 5 Oct 2026 | HTTPS API reachable and key accepted, 5 Oct 2026 |
| Supabase storage bucket | print-documents, private, 25 MiB limit, PDF only | Created and tested live 5 Oct 2026 |
| Supabase SQL port (5432/6543) | Not reachable from the founder's current network (timeouts) | Migrations are applied by pasting supabase/_combined.sql into the SQL Editor |
| Vercel project | autoprint-v4, connected to P-Suraj/AutoPrint-V4, region bom1 | Not yet deployed; no access from this machine |

## Still awaiting approval

D-1, D-2, D-3, D-4, D-6, D-7, D-8, D-9, D-10, D-11, D-13, D-14, D-16, D-17 remain PROPOSED. Most are technical choices that Phases 1-3 will test.

## Deploy and delegated feature decisions (founder, 7 October 2026)

| ID | Subject | Status |
|---|---|---|
| G-1 | Deploy the tested branch `wip/2026-10-06-unverified` (merge to `main`, push). Founder's word: "deploy" | DECIDED 2026-10-07 |
| G-2 | The founder gives the AI model working on the project freedom to decide which features to add and to take product decisions, because he is a third-year BTech student and does not yet know everything the software needs. Limits he set in the same message: do not over-engineer; complete the remaining build. Earlier rules still stand (never touch V3, no secrets, never print twice without a person, free resources only, honest reporting, the design bar) | DECIDED 2026-10-07 |

Decisions taken under G-2 are listed below as they are made, each marked "taken by the model under G-2" so the founder can overrule any of them.

| ID | Subject | Status |
|---|---|---|
| G-3 | Reminder sound for an unanswered request: three times 2 minutes apart, then every 10 minutes (8 in the hour a request can wait; it was 29). Reason: a shopkeeper who has not answered after three reminders is busy or away, and a chime every 2 minutes for an hour makes people switch the sound off | Taken by the model under G-2, 2026-10-07. Built in 4.0.4 |
| G-4 | The shop app keeps asking the server every 10 s (D-10 unchanged). Reason: it already asks at once after every action and when the window is opened; what is left is on average 5 s before a new request appears, which is small next to the time a person takes to approve; a faster or adaptive pace costs host calls and code for a gain nobody would notice | Taken by the model under G-2, 2026-10-07. No change |
| G-5 | The shop page keeps fetching the PDF reader (about 530 KB) in the background once the page is usable. Reason: almost everyone who opens a shop page is there to choose a file, the preview then appears in about 1 s instead of 11 s on a slow phone, and with data-saver on it waits for a touch | Taken by the model under G-2, 2026-10-07. No change |
| G-6 | Requests already waiting when the app starts stay silent at first; the reminder follows 2 minutes later. Reason: the shopkeeper has just opened the app and is looking at them | Taken by the model under G-2, 2026-10-07. No change |
| G-7 | Online payments (Phase 9) are not built now, not even the AutoPrint side against a pretend FinFlow. Reason: FinFlow cannot take a payment today, has no free always-on host (P-5 open, O-4 says free only), and each shop would need its own provider account (P-1); code written against a pretend service that cannot go live would be guesswork to maintain. The pilot runs on pay-at-counter, which is built. Revisit when a pilot shop asks for it. This follows the founder's own order (payments after the rest) and his "do not over-engineer" | Taken by the model under G-2, 2026-10-07 |
| G-8 | Left as they are, on purpose: the Settings window scrolls on a 1366 x 768 screen (Save stays in view); the shop dashboard's "online" uses a 45 s rule copied from the server; finalize makes 3 database trips. Each works; each fix is more code than the problem is worth before a pilot shows it matters | Taken by the model under G-2, 2026-10-07 |

## Founder feedback after the walkthrough (7 October 2026, evening)

The founder was walked through the software part by part and asked for the following. Each is his decision; how it was built is the model's choice under G-2 and can be overruled.

| ID | Subject | Status |
|---|---|---|
| H-1 | The shopkeeper sets the shop's prices and edits the shop's name from the dashboard (before, only the founder could, with the maintenance token) | DECIDED by the founder 2026-10-07. Built: migration 0020, `GET/POST /v1/shop/settings`, dashboard panel |
| H-2 | A customer can send several documents in one order, each with its own print settings. This replaces O-9 and D-15's "the screen allows one PDF" (the database allowed many from the start) | DECIDED by the founder 2026-10-07. Built in the customer page; at most 20 files per order (the existing server limit) |
| H-3 | The Windows app can search the waiting requests by the order code the customer says at the counter | DECIDED by the founder 2026-10-07. Built in 4.0.5: one search box for both tabs |
| H-4 | A shop without a colour printer can say so; its customers are told and cannot choose colour | DECIDED by the founder 2026-10-07. Built: `ap.shops.color_enabled`, set on the dashboard; the customer page shows "black & white only" and the server refuses a colour quote |
| H-5 | The shopkeeper downloads the Windows installer from the dashboard | DECIDED by the founder 2026-10-07. Built as a link to the newest GitHub release of this repository (free; the installer is 59 MB, over Supabase's free 50 MB per-file limit). The founder must publish the release |
| H-6 | "Email me a sign-in link" does not work yet. Leave it; the founder hands out private links for now | DECIDED by the founder 2026-10-07. Nothing changed |
| G-9 | Colour on or off (H-4) is set in ONE place, the dashboard, next to the prices, and not also in the Windows app's printer choice as the founder suggested as an alternative. Reason: two switches for one fact can disagree, and the dashboard is where the colour prices are | Taken by the model under G-2, 2026-10-07 |
| G-10 | The price editor shows one price per printed side for each of the four kinds, plus optional bulk prices ("from N sides"). It writes the same slab format the server always had | Taken by the model under G-2, 2026-10-07 |
| G-11 | With several files in one order the shop computer still shows one card per file (each is approved and printed by itself), and each card says how many files the order has and the order's total to collect | Taken by the model under G-2, 2026-10-07 |
| G-12 | Deploy the branch `wip/2026-10-07-shop-settings-multi-file` (merge to `main`, push). Founder word: "deploy" | DECIDED by the founder 2026-10-07. Done: merge commit `15f13f5` |
| H-7 | In the Windows app the files of one order are one request: approve or reject all at once, or press "View files" and answer each file by itself. This replaces G-11 (one card per file) | DECIDED by the founder 2026-10-07. Built in 4.0.6 |
| H-8 | The founder hoped the installer also runs on Windows 7. It does not and cannot without rebuilding the app on old technology: the app is built on .NET 8, which Microsoft supports on Windows 10 (version 1607) and later only, and the installer refuses anything older than Windows 10 version 1903 (`MinVersion=10.0.18362` in `AutoPrint.iss`), 64-bit only. F-12 (frozen 5 October) already says Windows 10/11. Told to the founder; no change made | RECORDED 2026-10-07. Open to the founder if a pilot shop turns out to run Windows 7 |
| G-13 | Deploy the branch `wip/2026-10-07-order-card` (merge to `main`, push). Founder word: "deploy" | DECIDED by the founder 2026-10-07. Done |
| H-9 | A customer's PDF is deleted once it is printed, not kept for 24 hours after the order ends. This replaces the "files 24 hours after final state" part of O-5. Founder's words: "they should be deleted once they are printed" | DECIDED by the founder 2026-10-07. Built: migration 0021 |
| G-14 | How H-9 was built: each file follows its own job. Sent to the printer, rejected, cancelled or not approved in time: due for deletion at once. Did not go through (failed): kept 24 hours, because the shopkeeper can still press "Print again" and that needs the file. A file uploaded but left out of the order: at once. The 1 hour for unsent files and the 48 hour hard cap stay | Taken by the model under G-2, 2026-10-07. The founder can ask for failed files to go at once too; "Print again" would then tell the customer to send the file again |
