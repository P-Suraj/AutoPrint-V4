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
