# Decisions

Append-only. Status is one of FROZEN, PROPOSED, OPEN, APPROVED, REJECTED.
Full reasoning for each ID is in `docs/BUILD_PHASES.md` section 4.

## Frozen by the founder (5 October 2026)

F-1 isolated project and repo · F-2 first success target · F-3 web-only customer surface · F-4 anonymous customers · F-5 PDF only · F-6 manual approval · F-7 one Windows desktop app · F-8 spooler-evidence completion, ambiguous means human · F-9 order/payment/attempt/pickup separate · F-10 FinFlow owns money · F-11 Supabase plus one small always-on backend, ₹500–2,000/month · F-12 Windows 10/11, founder-managed onboarding · F-13 private storage, short retention, never used for AI · F-14 never log secrets, signed URLs or documents.

## Decisions log (D = design proposals, O = open questions)

| ID | Subject | Status |
|---|---|---|
| D-1 | Monorepo layout | PROPOSED |
| D-2 | API: Python + FastAPI, always-on host, pooled direct PostgreSQL | PROPOSED |
| D-3 | New Supabase project in Mumbai, database and storage only | PROPOSED |
| D-4 | Web: React + Vite + TypeScript on new Vercel project | PROPOSED |
| D-5 | Desktop: C# .NET WPF | APPROVED 2026-10-05 (via O-3) |
| D-6 | Print engine decided by Phase 1 spike | PROVISIONAL 2026-10-05: SumatraPDF 3.6.1 portable. Measured on a virtual printer only; the PDFium/Windows-API alternative was not compared. Re-validate on the physical printer. |
| D-7 | Business rules in SQL transactions | PROPOSED |
| D-8 | Upload once, validate once | PROPOSED |
| D-9 | Previews rendered client-side | PROPOSED |
| D-10 | WebSocket signal plus HTTPS calls plus slow safety poll | PROPOSED |
| D-11 | No cookies; order secret in header | PROPOSED |
| D-12 | One-time enrolment code, DPAPI secret, no shopkeeper PIN for first shop | APPROVED 2026-10-05 (via O-6) |
| D-13 | OpenAPI is the single contract, generated clients | PROPOSED |
| D-14 | Cross-component end-to-end test | PROPOSED |
| D-15 | Schema supports many documents per order; MVP screen allows one PDF | APPROVED 2026-10-05 (via O-9) |
| D-16 | A4 only, B&W and colour printer slots | PROPOSED |
| D-17 | Founder operations as scripts | PROPOSED |
| D-18 | Deploy a skeleton in Phase 3 | APPROVED 2026-10-05 |
| C-1 | Completion rule version 1 (`docs/PRINT_SPIKE_REPORT.md`, migration 0003) | PROVISIONAL 2026-10-05: derived from a virtual printer; must be re-validated on a physical printer before Phase 8 |
| C-2 | Founder allowed a virtual printer for Phase 1 testing (2026-10-05) | RECORDED. The Phase 1 gate still requires a physical printer and is NOT passed |
| O-1 | Submit from anywhere | ANSWERED: yes, shop link works off-site |
| O-2 | Payments timing | ANSWERED: no online payment before physical certification; pay-at-counter for the pilot; FinFlow after printing is proven (Phase 9) |
| O-3 | C# codebase | ANSWERED: yes, C# / .NET / WPF |
| O-4 | Always-on host | OPEN by choice: decide in Phase 3 from current pricing and latency to the V4 Supabase database |
| O-5 | Retention | ANSWERED: unconfirmed/abandoned uploads 1 hour; files 24 hours after final state; hard maximum 48 hours from upload |
| O-6 | Shopkeeper PIN/login | ANSWERED: none for first shop; revisit before the second shop |
| O-7 | Pilot shop, PC, printers | PENDING: founder will supply shop, Windows PC/version, printer models, connection type, access details before Phase 1. Blocks Phase 1. |
| O-8 | Success wording | ANSWERED: "Sent to printer". Do not say "Printed" until the Phase 1 spike proves the completion evidence. |
| O-9 | Multiple PDFs | ANSWERED: no multi-PDF UI for certification; schema supports many documents from day one |
| O-10 | Unapproved job expiry | ANSWERED: customer can cancel before approval; unapproved jobs expire after a fixed 1-hour window, stored as `expires_at` on the order. No shop closing-time configuration in the MVP. |

## Still awaiting approval

D-1, D-2, D-3, D-4, D-6, D-7, D-8, D-9, D-10, D-11, D-13, D-14, D-16, D-17 remain PROPOSED. Most are technical choices that Phases 1-3 will test.
