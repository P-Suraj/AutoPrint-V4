# Decisions

Append-only. Status is one of FROZEN, PROPOSED, OPEN, APPROVED, REJECTED.
Full reasoning for each ID is in `docs/BUILD_PHASES.md` section 4.

## Frozen by the founder (5 October 2026)

F-1 isolated project and repo · F-2 first success target · F-3 web-only customer surface · F-4 anonymous customers · F-5 PDF only · F-6 manual approval · F-7 one Windows desktop app · F-8 spooler-evidence completion, ambiguous means human · F-9 order/payment/attempt/pickup separate · F-10 FinFlow owns money · F-11 Supabase plus one small always-on backend, ₹500–2,000/month · F-12 Windows 10/11, founder-managed onboarding · F-13 private storage, short retention, never used for AI · F-14 never log secrets, signed URLs or documents.

## Awaiting founder answer

| ID | Subject | Status |
|---|---|---|
| D-1 | Monorepo layout | PROPOSED |
| D-2 | API: Python + FastAPI, always-on host, pooled direct PostgreSQL | PROPOSED |
| D-3 | New Supabase project in Mumbai, database and storage only | PROPOSED |
| D-4 | Web: React + Vite + TypeScript on new Vercel project | PROPOSED |
| D-5 | Desktop: C# .NET WPF | PROPOSED (depends on O-3) |
| D-6 | Print engine decided by Phase 1 spike | PROPOSED |
| D-7 | Business rules in SQL transactions | PROPOSED |
| D-8 | Upload once, validate once | PROPOSED |
| D-9 | Previews rendered client-side | PROPOSED |
| D-10 | WebSocket signal plus HTTPS calls plus slow safety poll | PROPOSED |
| D-11 | No cookies; order secret in header | PROPOSED |
| D-12 | One-time enrolment code, DPAPI secret | PROPOSED (depends on O-6) |
| D-13 | OpenAPI is the single contract, generated clients | PROPOSED |
| D-14 | Cross-component end-to-end test | PROPOSED |
| D-15 | Schema supports many documents per order | PROPOSED (depends on O-9) |
| D-16 | A4 only, B&W and colour printer slots | PROPOSED |
| D-17 | Founder operations as scripts | PROPOSED |
| D-18 | Deploy a skeleton in Phase 3 | PROPOSED |
| O-1 | Submit from anywhere or counter only | OPEN (recommend: anywhere) |
| O-2 | Payments before or after physical certification | OPEN (recommend: after) |
| O-3 | Founder owns a C# codebase | OPEN |
| O-4 | Always-on host | OPEN (decide in Phase 3) |
| O-5 | Retention times | OPEN (suggest 1 h unconfirmed, 24 h after final state, 48 h hard cap) |
| O-6 | Shopkeeper PIN/login | OPEN (suggest: not for first shop) |
| O-7 | Pilot shop, PC, printer models, spike date | OPEN, blocks Phase 1 |
| O-8 | Customer wording for success | OPEN (decide after Phase 1) |
| O-9 | One PDF per order in MVP screen | OPEN |
| O-10 | Unapproved job expiry | OPEN |

## Decided

None yet beyond the frozen items.
