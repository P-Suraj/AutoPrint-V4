# AutoPrint V4 — Product Boundary

Source: founder brief of 5 October 2026 and `docs/BUILD_PHASES.md` sections 1–3.

## Goal

Prove this loop on real hardware before anything else:

> real customer → real job → real shop → real Windows machine → real printer → real paper

## In the MVP

- Customer (mobile web, no account, no app): scan shop QR, select a PDF, preview, choose colour/B&W, copies, single/double-sided and page range, see the server-calculated price, confirm, watch status.
- Shopkeeper (one Windows desktop app): see new jobs, preview, approve or reject; approved jobs print on the selected printer; failures that need attention are listed and resolved by a human.
- System: authoritative server-side price; exactly one print attempt per approval; conservative status wording; private storage with automatic deletion; a timestamped event for every step.

## Out of the MVP (closed until the Phase 8 gate passes)

Shop discovery, maps, marketplace. Pickup codes and policies. Queue-time estimates. Ledger, customers module, CRM, analytics dashboards. Subscription billing. Self-service shop signup. Customer accounts, history, customer reprint. SMS/WhatsApp/push notifications. Mobile app. Aadhaar/ID layouts, photo grids, N-up. Word and image files. Paper sizes other than A4. Auto-print without approval. Multiple devices per shop. Auto-update. Code signing. Shop-owner web console. AI features.

## Ownership boundary

- AutoPrint owns: document, print settings, quote, job, shop approval, printer, print attempt, physical outcome, customer print status.
- FinFlow owns: payment provider, ledger, refunds, settlement, reconciliation. AutoPrint stores only a payment reference, amount, status and timestamps.

## Success target (first stage)

One real shop, one Windows PC, one or two real printers, about 50–100 real customer jobs, high success, no dangerous duplicates, no privacy incident, shopkeeper operating alone.

## Adoption bar (founder, 5 Oct 2026)

Printing today runs on WhatsApp and email. People will switch only if AutoPrint takes **at least 50% less effort than that, for the student and for the shopkeeper**. A feature that does not move one of those two numbers is not worth building yet. Features that add steps for either person are a cost, however clever.

What we know and do not know:

- The survey (81 students) says the queue is the biggest pain (49 of 81) and that 84% send files by email, 64% by WhatsApp. It does **not** measure how long the current process takes, and it asked nothing about the shopkeeper.
- There is **no baseline yet**. Before the pilot, time 20 real WhatsApp/email jobs at the shop: seconds from "student arrives or sends" to "paper in hand" for the student, and seconds of shopkeeper attention per job. "50% better" means nothing until those two numbers exist.
- The system already records a timestamped event for every step, so the V4 side of the comparison comes from the database, not from guesses.

Working targets until the baseline replaces them (from `docs/BUILD_PHASES.md`): student scan-to-submitted under 60 seconds; shopkeeper approve in under 10 seconds; every screen update within a few seconds without a manual refresh. Measured on the live deployment on 5 Oct 2026, warm: shop poll 94 ms, status/shop lookups about 115 ms, static page 50 ms. Cold-start times are not measured.

## Business questions to keep in mind (not decided, not for MVP)

The founder wants these kept in view while building. They are open, and nothing in the product depends on an answer yet.

1. **Who pays?** Students are very price-sensitive; shopkeepers have thin margins. Options on the table: a fee to the shop, a fee to the student, advertising, or free at first. The August business notes proposed a shop subscription (about 299 and 699 rupees a month) as a hypothesis only. The survey gave no evidence about willingness to pay.
2. **Ads.** Ads on a page used for a 60-second task earn little and add weight and clutter, which cuts against the speed goal. Not evaluated.
3. **Why are competitors not everywhere?** Competitors exist (the August notes name two). We do not know why they have not spread. This needs field research, not a guess.
4. **Distribution.** Not decided. The August notes suggest founder-led onboarding in dense campus clusters first.
5. **Design implication that is already safe:** keep the shopkeeper's cost near zero (free install, no hardware, no training) and make every step faster than WhatsApp, because adoption by shops comes before any pricing question.
