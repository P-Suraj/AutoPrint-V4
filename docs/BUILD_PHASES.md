# AutoPrint V4 — Build Phases

**Date:** 5 October 2026
**Audience:** the founder, and any AI coding agent (for example Claude Sonnet) that builds V4.
**Status:** DRAFT. Decisions marked PROPOSED or OPEN need founder approval before Phase 1 starts.
**Location note:** this file was written into the V3 folder only because the V4 folder does not exist yet. In Phase 0 it moves to `docs/BUILD_PHASES.md` in the V4 repository and this copy is left as is.

---

## 0. How an AI agent must use this document

Read this section at the start of every session.

1. **Work on one phase at a time.** Do not start a phase until the previous phase's exit gate is recorded as passed in `docs/IMPLEMENTATION_STATUS.md`.
2. **Source of truth, in order:** V4 code → V4 migrations → V4 tests → founder decisions in `docs/DECISIONS.md` → other V4 docs → V3 material → your assumptions. Your assumptions are never facts.
3. **If something is not decided, stop and ask.** Say "I don't have enough information to determine this." Section 4 lists the known open decisions. Do not resolve them yourself.
4. **Never claim something works without showing the command and its output.** "The code looks correct" is not evidence. A phase gate needs pasted test output, a log excerpt, or a photo/record of paper.
5. **Never say "printed" about anything that used a virtual printer** (Microsoft Print to PDF, XPS Writer). Only a physical printer counts.
6. **Check library and API behaviour against the installed version**, not memory. Before using a package API you have not used in this repo, read its docs or source for the pinned version.
7. **Do not invent values.** No made-up URLs, keys, project references, prices, printer names, or percentages. Environment values come from the founder.
8. **A change is finished only when both sides of a contract and the test that crosses them are updated in the same commit.** This is the single most important rule; its absence caused most V3 defects.
9. **V3 is read-only.** Never edit, move, delete, deploy, or connect to anything under `F:\Projects\Printer automation`, the V3 Supabase project, or the V3 Vercel projects. Never copy a V3 `.env` value.
10. **No demo data, no silent fallbacks.** If the backend fails, the UI shows the failure.
11. **Scope is closed.** Section 3 lists what is out. If a task seems to need an out-of-scope feature, stop and ask.
12. **Update `docs/IMPLEMENTATION_STATUS.md` at the end of every session** with what was done, what was verified and how, and what is not done.

---

## 1. What V4 is

AutoPrint lets a student send a document from their phone to a print shop's existing Windows computer and existing printer, with the shopkeeper in control.

The core loop, and the only thing V4 must prove first:

> real customer → real job → real shop → real Windows machine → real printer → real paper

**Honest starting position.** V3 proved the web flow up to shop approval on a deployed system. It did not certify physical printing; the agent logs in the V3 repository show only "Microsoft Print to PDF". Some of the project history describes real-printer testing at a shop, but there is no recorded job data from it. V4 therefore treats physical printing as **unproven** and builds its first milestones around proving it.

---

## 2. Evidence

### 2.1 Student survey

Source: `Student Printing Experience — Quick Survey.csv`. **81 responses** collected 20–22 September 2026; 79 are students.

Limits: this is a small convenience sample gathered over two days, probably from one or two campuses. It measures what students say, not what they do. Treat the numbers as direction, not proof.

| Question | Result (count of 81) |
|---|---|
| Prints weekly or more | 63 (78%) — 38 several times a week, 25 about weekly |
| Prints at a campus shop | 64 (79%); nearby shop 48 (59%) |
| Sends files by email | **68 (84%)** |
| Sends files by WhatsApp | 52 (64%) |
| Sends by USB / takes file directly | 1 / 2 |
| Usual wait 5–20 minutes | 52 (64%); over 20 minutes 11 (14%); under 5 minutes 6 (7%) |
| Problem: long queues | **69 (85%)** |
| Problem: shop/printer busy | 54 (67%) |
| Problem: having to stay at the shop | 38 (47%) |
| Problem: explaining print requirements | 29 (36%) |
| Problem: sending files via WhatsApp/email | 20 (25%) |
| Problem: not knowing the price | 17 (21%) |
| Problem: mistakes in print settings | 13 (16%) |
| **Biggest** inconvenience: waiting in queue | **49 (60%)** |
| Biggest: having to stay at the shop | 14 (17%) |
| Biggest: print errors/miscommunication | 5 (6%) |
| Biggest: sending/handling files | 3 (4%) |
| Biggest: unclear pricing | 2 (2%) |
| Would use "upload, set, see price, send **before you arrive**": definitely / probably | 58 (72%) / 15 (19%) |
| Motivator: avoiding the queue | **68 (84%)** |
| Motivator: collect without waiting | 51 (63%) |
| Motivator: notified when ready | 48 (59%) |
| Motivator: choosing settings myself | 38 (47%) |
| Motivator: paying online | 29 (36%) |
| Motivator: uploading from phone | 28 (35%) |
| Motivator: knowing the price beforehand | 24 (30%) |

**What the survey did not ask.** It has no question on document types, file formats, privacy, payment method, which print settings are used, or QR codes. It gives no evidence for or against PDF-only, and none on privacy concerns. Do not cite it for those.

Free-text answers worth noting (17 non-empty, most are "no"/"nil"): one student avoids the queue by using an off-campus shop and WhatsApping the owner ahead; others mention self-service, a vending machine, delivery, and shop opening times.

### 2.2 Where the evidence disagrees with the plan

| Assumption in the founder brief | What the evidence says | Consequence for V4 |
|---|---|---|
| The pain is WhatsApp file transfer and explaining settings | The pain is the **queue** (60% biggest) and being stuck at the shop (17%). File handling is the biggest issue for 4%, pricing for 2%. | A counter-only flow improves the things students rank lowest. See decision O-1. |
| MVP is counter QR; remote orders are out | The survey question that got 91% "yes" described sending **before arriving**. The top three motivators all need the job to be ready on arrival. | The cheapest way to honour this is to not restrict where the link is opened. No pickup codes or discovery are needed. See O-1. |
| WhatsApp is the main channel | Email is selected more often (84% vs 64%). | Messaging to "replace WhatsApp" misses most students. Product copy should say "no email, no WhatsApp". |
| Notifications can wait | 59% chose "notified when ready". | Status page only is acceptable for the first certification, but notification is the first feature to add after it. |
| Online payment is core | 36% chose it as a motivator. Not asked: whether anyone objects to it. | Payment matters mainly as protection against no-shows on pre-arrival jobs, not as a student-facing draw. See O-2. |

### 2.3 FinFlow readiness (checked 5 October 2026 in `F:\Projects\finflow`)

FinFlow has code for Razorpay webhooks, refunds and payouts, with 111 local tests passing. Its own handover says it is **not** sandbox-verified, not deployed, and that the merchant-of-record and settlement model is undecided. It needs a JVM service plus PostgreSQL, Redis and RabbitMQ, which does not fit inside the ₹500–2,000 monthly budget alongside AutoPrint.

Consequence: "payments in MVP" makes the first physical pilot depend on a second, undeployed system and an unmade legal decision.

### 2.4 V3 lessons that V4 must not repeat

Use this as a regression checklist during design review.

| V3 problem | V4 rule |
|---|---|
| Agent and API hand-wrote the same contract and drifted; print results were rejected with 422 | One machine-readable contract; generated clients; a cross-component test (D-13, D-14) |
| "When is a job done?" had three different answers | One completion rule, written before agent code (Phase 1 output, Phase 2 contract) |
| API in a different region from the database | API and database in the same region; latency measured at deployment (Phase 3 gate) |
| 3–8 database round trips per request over HTTP | API uses a pooled direct PostgreSQL connection; one transaction per operation |
| Agent polled a serverless endpoint every second | Push channel with a slow safety poll (D-10) |
| Cross-site cookies, CSRF recovery, sessions dying after 2 hours | No cookies anywhere in MVP (D-11) |
| Customer order link expired after 1 hour | Order access lasts until the order is purged (D-11) |
| PDF check rejected valid files at random (raw byte scan for `/JS`) | Parse the PDF structure; never scan raw bytes; test with a corpus of real files |
| File moved three times; "artifact" was a byte-for-byte copy | Upload once; the stored object is immutable and identified by its SHA-256 |
| Multipart form data sent to a raw signed upload URL | Raw bytes PUT; covered by an automated test |
| Database errors surfaced as HTTP 500 | Typed error model; every expected failure has a code (Phase 2) |
| Spooler matching was "any new job on this printer" | Each print attempt carries a unique job name that is matched in the spooler (Phase 1 must prove this) |
| Agent died permanently if offline at boot | Agent never exits on network failure; it retries forever with backoff |
| Shop showed "offline" during long prints | Heartbeat runs independently of printing |
| Demo jobs and fallbacks hid backend failures | No demo data in any deployed environment |
| Weeks of work uncommitted; core agent never in git | Commit at the end of every working session; nothing deployed that is not in git |
| Features built before one printer was certified | Section 3 scope is closed until the Phase 8 gate passes |
| 14,700 lines of handoff documents, several stale | Small fixed doc set (section 6); status lives in one file |

---

## 3. Product boundary

### 3.1 In the MVP

Customer (mobile web, no account, no app):
scan shop QR → select PDF → preview → choose colour/B&W, copies, single/double-sided, page range → see server-calculated price → confirm → status page.

Shopkeeper (one Windows desktop application):
see new jobs → preview → approve or reject → job prints on the selected printer → see failures that need attention → resolve them.

System:
authoritative server-side price; exactly one print attempt per approval; conservative status wording; private storage with automatic deletion; a timestamped event for every step so the metrics in section 3.3 come from SQL.

### 3.2 Out of the MVP (closed)

Shop discovery, maps, marketplace. Pickup codes and pickup policies. Queue-time estimates. Ledger, customers module, CRM, analytics dashboards. Shop subscription billing. Self-service shop signup. Customer accounts, history, customer-initiated reprint. SMS/WhatsApp/push notifications. Mobile app. Aadhaar/ID layouts, photo grids, N-up. Word and image files. Paper sizes other than A4. Auto-print without approval. Multiple devices per shop. Auto-update. Code signing. Web console for shop owners. Any AI feature.

Recorded for later, in this order of likely value given the survey: ready notification, pre-arrival flow polish, multiple files per order, images and DOCX, N-up, ID layouts, auto-print.

### 3.3 What gets measured from day one

Per job: time from upload → quote → confirm → approval → claim → sent to spooler → outcome. Per shop: jobs attempted, completed, failed, needs-attention, duplicates, rejections, cancellations, support interventions, agent offline periods.

---

## 4. Decisions

### 4.1 Frozen by the founder (do not reopen)

| ID | Decision |
|---|---|
| F-1 | V4 is a separate project: own folder, repo (`P-Suraj/AutoPrint-V4`), Vercel project, Supabase project, storage, secrets. V3 untouched. |
| F-2 | First success target: one real shop, one Windows PC, one or two real printers, about 50–100 real customer jobs, high success, no dangerous duplicates, no privacy incident, shopkeeper operates it alone. |
| F-3 | Customer surface is web only. Flutter app is parked and must not influence design. |
| F-4 | Customers are anonymous. No account, email, password or OTP. Access is by a scoped per-order secret. |
| F-5 | PDF only. |
| F-6 | Manual shop approval for every job. |
| F-7 | Shopkeeper works in one Windows desktop application that also does the printing. |
| F-8 | Completion uses spooler evidence. Ambiguous outcomes become "needs attention" for a human. An uncertain job is never reprinted automatically. |
| F-9 | Order, payment, print attempt and pickup are separate concepts with separate state. The point of no return is the agent's claim. |
| F-10 | FinFlow owns all money. AutoPrint stores only a payment reference, amount, status and timestamps. A browser "success" screen is never trusted. |
| F-11 | Supabase for PostgreSQL and storage, plus one small always-on backend. No Kubernetes, no microservices. Budget ₹500–2,000 per month. |
| F-12 | Windows 10 and 11. Founder installs and enrols the first shop by hand. |
| F-13 | Files live in private storage, are reached only by short-lived signed access, and are deleted automatically after a short window. Never used for AI. |
| F-14 | Never log secrets, signed URLs, device secrets, document contents, or unnecessary personal data. |

### 4.2 Proposed (need founder approval; reasons given)

| ID | Proposal | Why |
|---|---|---|
| D-1 | **Monorepo** with `apps/api`, `apps/web`, `apps/desktop`, `contracts/`, `supabase/migrations/`, `docs/`, `spikes/`. | One commit can change both sides of a contract. |
| D-2 | **API: Python + FastAPI on an always-on host in the same region as the database**, connecting to PostgreSQL directly through a connection pool. | Founder knows Python; PDF tooling is mature; a long-lived process can hold agent connections and process files without serverless limits. |
| D-3 | **New Supabase project in Mumbai.** Used for PostgreSQL and Storage only. The browser and the desktop app never talk to the database. | Smallest attack surface; one place enforces rules. |
| D-4 | **Customer web: React + Vite + TypeScript, static hosting on the new Vercel project.** | Proven in V3; no server logic in the frontend. |
| D-5 | **Desktop app: C# on .NET, WPF.** | Native access to the Windows print spooler and job status, built-in DPAPI, a single self-contained installer, and fewer antivirus false positives than PyInstaller. Depends on O-3. |
| D-6 | **PDF print engine chosen by the Phase 1 spike**, between (a) SumatraPDF command line and (b) PDFium rendering through the Windows print API. | The choice decides how reliably a job can be identified and observed in the spooler. This must be measured on the real printer, not assumed. |
| D-7 | **Business rules live in SQL functions inside transactions** (claim, approve, report outcome, cancel), carrying forward the V3 ideas of atomic claim, attempt token, and an allowed-transitions table. | This was the sound part of V3. Reuse the concepts, rewrite the code. |
| D-8 | **Upload once.** Browser PUTs raw bytes to a signed URL; the API downloads the object once, validates it in a worker thread with size and time limits, records page count and SHA-256. No second copy. | Removes the V3 triple transfer and the timeouts. |
| D-9 | **Customer preview is rendered in the browser from the local file; shop preview is rendered in the desktop app from the downloaded file.** No server-side rendering in MVP. | Nothing to host; the shop sees the exact bytes that will print. |
| D-10 | **Desktop ↔ API: one outbound WebSocket for "something changed" signals and heartbeat; every state change is an ordinary HTTPS call; a slow poll (about every 30 s) runs as a safety net.** | Fast in the normal case, still correct if the socket drops. The API runs as a single instance in MVP, which must be written down as a constraint. |
| D-11 | **No cookies.** Customer requests carry the order secret in a header; desktop requests carry device credentials. The order secret stays valid until the order is purged. | Removes cross-site cookie, CSRF and session-expiry failures entirely. |
| D-12 | **Device enrolment by one-time code generated by a founder script**, device secret stored with DPAPI. No shopkeeper password in MVP. Depends on O-6. | Founder-managed pilot on a PC that sits in the shop. |
| D-13 | **The API's OpenAPI document is the only contract.** TypeScript and C# clients are generated from it; CI fails if generated code is stale. Enumerations are defined once. | Makes contract drift a build failure. |
| D-14 | **One end-to-end test** runs the real API against a real local PostgreSQL with a fake print engine: order → approve → claim → outcome, plus the failure paths. | V3 had 186 passing tests and a broken print path because no test crossed components. |
| D-15 | **An order holds a list of documents from day one, but the MVP user interface allows one PDF per order.** Depends on O-9. | Multiple files was real shop feedback; the schema should not need rework to add it. |
| D-16 | **A4 only, automatic orientation.** Two printer slots per shop: B&W and colour (may be the same printer). | Matches what a campus shop prints most; anything else is a later decision. |
| D-17 | **Founder operations are scripts, not screens**: create shop, set rate card, issue enrolment code, list jobs, purge. | No admin UI to build or secure. |
| D-18 | **Deploy a skeleton early** (Phase 3) rather than only at the end. | V3 showed that production exposes problems local testing hides. Features still ship only after their phase gate. This differs from the founder's original phase order and needs approval. |

### 4.3 Open (the founder must decide; the agent must not)

| ID | Question | Recommendation |
|---|---|---|
| O-1 | May a customer submit from anywhere, or only at the counter? | **Allow anywhere, add nothing else.** The shop link works off-site; the status page shows a short order code; the shopkeeper approves when they choose. This serves the survey's top need without pickup codes, discovery or estimates. |
| O-2 | Is online payment required before the first physical certification? | **No. Certify printing with pay-at-counter first, then add FinFlow as Phase 9.** Reasons: FinFlow is not deployed or sandbox-verified; the merchant model is undecided; certification is when prints fail most, and every failure would need a working refund; the founder's own priority list puts payment after printing. The payment record and eligibility check are in the schema from Phase 2, so adding FinFlow does not change the job model. |
| O-3 | Is the founder willing to own a C# codebase for the desktop app? | If yes, D-5 stands. If not, Python with a native UI toolkit is the fallback, accepting weaker spooler access and installer friction. |
| O-4 | Which always-on host? | Any provider with a Mumbai or nearby region that fits the budget. Pick in Phase 3 after checking current prices and measuring latency to the database. |
| O-5 | Exact retention times. | Suggested: abandoned unconfirmed uploads deleted after 1 hour; all other files deleted 24 hours after the job reaches a final state, with a hard limit of 48 hours from upload. |
| O-6 | Does the desktop app need a shopkeeper PIN or login? | Not for the first shop. Revisit before the second. |
| O-7 | Which shop, which PC, which printer models, and when is the printer available for the Phase 1 spike? | Needed before Phase 1 can start. |
| O-8 | Customer wording for a successful job. | Decide after Phase 1 shows what the printer actually reports. Until then use "Sent to printer". |
| O-9 | One PDF per order in the MVP screen? | Yes for certification; enable multiple right after. |
| O-10 | What happens to a job the shop never approves? | Suggested: customer can cancel any time before approval; unapproved jobs expire at shop closing or after a fixed number of hours. |

---

## 5. Target shape (subject to section 4 approvals)

```
Phone browser ──HTTPS──► API (always-on, same region as DB) ──► PostgreSQL (Supabase)
      │                         ▲   │
      │ raw PDF PUT             │   └──► Storage (private, signed access)
      └────────► Storage        │
                                │ HTTPS calls + one WebSocket
                        Windows desktop app (queue UI + print engine + local journal)
                                │
                        Windows spooler ──► physical printer
```

State is kept in four separate records, never one combined status:

- **Order**: draft → submitted → cancelled / expired / closed
- **Payment**: not_required / pending / paid / failed / refunded (MVP uses `not_required` until Phase 9)
- **Job**: awaiting_approval → approved → printing → completed / failed / needs_attention; or rejected
- **Print attempt**: one row per claim, with a unique token, the document hash, and the evidence collected

Exact names and transitions are fixed in Phase 2, not here.

---

## 6. Documentation set

Only these files. Each has one job. Anything else needs a reason.

| File | Contains | Written in |
|---|---|---|
| `README.md` | What the project is, how to run each app locally | Phase 0, kept current |
| `docs/BUILD_PHASES.md` | This document | Phase 0 |
| `docs/PRODUCT.md` | Sections 1–3 of this document, expanded only where needed | Phase 0 |
| `docs/DECISIONS.md` | Every decision with ID, date, status, reason. Append-only. | Phase 0 onward |
| `docs/IMPLEMENTATION_STATUS.md` | Current phase, gate results with evidence, known gaps. The only status file. | Every session |
| `docs/PRINT_SPIKE_REPORT.md` | Phase 1 measurements and the completion rule | Phase 1 |
| `docs/CONTRACTS.md` | State machines, error codes, agent protocol, retention rules. Links to the OpenAPI file and migrations rather than repeating them. | Phase 2 |
| `docs/ARCHITECTURE.md` | The diagram, component responsibilities, constraints (for example "API is single-instance") | Phase 2 |
| `docs/RUNBOOK.md` | Provision a shop, install the app, enrol, recover from each failure, purge | Phase 7 |

No handoff documents. A new session reads `IMPLEMENTATION_STATUS.md`, `DECISIONS.md`, and the phase it is working on.

---

## 7. Repository layout (D-1)

```
AutoPrint-V4/
├── README.md
├── docs/
├── contracts/            # openapi.json (generated from the API), shared enum list
├── supabase/migrations/  # numbered SQL, applied in order, never edited after merge
├── apps/
│   ├── api/              # FastAPI service + tests
│   ├── web/              # customer web app + tests
│   └── desktop/          # Windows app: UI, print engine, journal + tests
├── scripts/              # founder operations (create shop, rate card, enrolment code, purge)
├── e2e/                  # cross-component test with fake print engine
└── spikes/               # throwaway experiments; never imported by apps
```

Git rules: commit at the end of every session; one logical change per commit; conventional prefixes (`feat:`, `fix:`, `test:`, `docs:`, `chore:`); never commit `.env`, installers, build output or generated IDE files; nothing is deployed that is not on `main`.

---

## 8. Phases

Each phase lists its goal, what must exist before it starts, the work, what it must not include, and the exit gate. A gate is passed only with recorded evidence.

### Phase 0 — Approvals and repository

**Goal:** decisions are signed off and an empty, correctly isolated repository exists.

**Work**
1. Founder reviews section 4 and answers every O-item and every D-item (approve, change, or reject).
2. Create the V4 folder outside the V3 directory. `git init`, add the remote `P-Suraj/AutoPrint-V4`.
3. Add `.gitignore` covering env files, build output, virtual environments, `node_modules`, installers, IDE files.
4. Write `README.md`, `docs/BUILD_PHASES.md`, `docs/PRODUCT.md`, `docs/DECISIONS.md`, `docs/IMPLEMENTATION_STATUS.md`.
5. First commit and push.

**Not in this phase:** any application code, any cloud resource.

**Exit gate**
- Every decision in section 4 has a recorded answer in `DECISIONS.md`.
- `git remote -v` shows only the V4 repository.
- A search of the V4 folder finds no V3 URL, key, or project reference.
- Founder confirms in writing.

---

### Phase 1 — Print spike on a real printer

**Goal:** learn, by measurement, how to send a PDF to the pilot printer and what the system can truthfully know about the result. This phase decides D-6, O-8 and the completion rule. It is the highest-risk part of the product and comes before everything else.

**Before starting:** O-7 answered; access to a physical printer (the pilot shop's model if possible; otherwise any physical printer first, then repeat on the shop's).

**Work** (throwaway code in `spikes/`, no cloud, no UI)
1. For each candidate engine in D-6, print a fixed set of test PDFs: 1 page, 10 pages, 50 pages, mixed portrait/landscape, a scanned image PDF, a large file near the size limit.
2. For each print, vary: copies, colour/B&W, single/double-sided, page range. Record whether the paper matched the request.
3. Give each print a unique job name and record whether that name can be found in the spooler and followed until the job leaves the queue.
4. Record every status signal available during a normal print (queued, spooling, printing, pages printed, removed).
5. Run failure drills and record exactly what the system reports for each: printer powered off, cable or network unplugged mid-job, paper tray empty, paper jam if it can be produced safely, queue paused, job cancelled at the printer, PC restarted mid-job, application killed mid-job.
6. Measure time from "send" to "left the queue" for each test size.
7. Record printer model, driver name and version, connection type, Windows version.

**Not in this phase:** API, database, production code, anything reusable. Spike code is deleted or left in `spikes/` and never imported.

**Exit gate**
- `docs/PRINT_SPIKE_REPORT.md` contains the results table for every test and drill, with what was observed, not what was expected.
- At least 30 consecutive normal prints with correct paper output on a physical printer, logged.
- A written **completion rule**: the exact observations that allow "completed", the ones that mean "failed", and everything else is "needs attention".
- A written answer on whether duplex, colour, copies and page range can be controlled reliably by the chosen engine, and what to do for any that cannot.
- Engine chosen and recorded in `DECISIONS.md`.
- If the spike shows the printer reports too little to tell success from failure, **stop and discuss with the founder** before Phase 2. F-8 may need adjusting.

---

### Phase 2 — Contracts

**Goal:** everything that two components must agree on is written down once, before feature code.

**Work**
1. Database schema as migration files: shops, rate cards, devices, enrolment codes, orders, documents, quotes, payments, jobs, print attempts, events, allowed transitions. Amounts stored as integer paise.
2. State machines for order, payment, job and print attempt: every state, every allowed transition, who may make it.
3. SQL functions for the transactional operations: submit order, approve, reject, cancel, claim, report outcome, resolve needs-attention, expire, purge-mark.
4. API surface as an OpenAPI document generated from typed API stubs (routes declared, handlers returning "not implemented").
5. Error model: a fixed list of error codes with HTTP status and meaning. No expected failure may produce a 500.
6. Agent protocol: enrolment, authentication, the WebSocket messages, heartbeat, claim, lease/timeout behaviour, outcome report, what happens on restart, what the local journal stores.
7. Pricing rule: inputs, rate-card structure, rounding, worked examples that become tests.
8. Retention rule from O-5 as concrete timers.
9. Client generation set up for TypeScript and C#, with a CI check that generated code is current.

**Not in this phase:** handler logic, UI, deployment.

**Exit gate**
- Migrations apply cleanly to an empty local PostgreSQL, twice from scratch.
- SQL tests cover every allowed transition and reject at least one disallowed transition per state.
- A concurrency test shows two simultaneous claims produce exactly one winner.
- `contracts/openapi.json` exists and both clients generate from it without manual edits.
- `docs/CONTRACTS.md` and `docs/ARCHITECTURE.md` reviewed and approved by the founder.

---

### Phase 3 — Backend slice and early deployment

**Goal:** an order can be created, a PDF uploaded and validated, a price quoted, and the order submitted, through the real API against a real database, both locally and on V4 infrastructure.

**Before starting:** founder creates the new Supabase project and the API host account, and supplies V4-only credentials. The agent verifies each value belongs to V4 before use and stops if unsure.

**Work**
1. API service with pooled database access, structured logging with a redaction list (F-14), health endpoints.
2. Founder scripts: create shop, set rate card, issue enrolment code.
3. Endpoints: shop lookup by code, create order, upload intent, finalise upload, quote, submit, order status, cancel.
4. PDF validation in a worker thread with size and time limits; structural parsing only; encrypted files rejected with a clear message.
5. Events written for every step.
6. Deploy the service to the chosen host; apply migrations to the V4 database.

**Not in this phase:** web UI, desktop app, payments, any shop-side endpoint beyond what tests need.

**Exit gate**
- API tests run against real local PostgreSQL (not mocks) and pass; output recorded.
- A corpus of at least 20 real-world PDFs (scanner output, phone exports, large files) validates with the correct page count; any rejection is explained.
- An automated test proves the upload path uses a raw-bytes PUT.
- Deployed health endpoint reachable; measured API-to-database round trip recorded; measured end-to-end time for upload → quote on a 3-page PDF recorded.
- Isolation check recorded: the deployed service's database host and storage bucket are the V4 ones.

---

### Phase 4 — Customer web slice

**Goal:** a student on a phone can go from the shop link to a submitted order and watch its status.

**Work**
1. Shop landing from QR link, file selection, in-browser preview, settings, server price, confirm, status page.
2. All calls through the generated TypeScript client.
3. Clear error states for every error code from Phase 2. No fallback data.
4. Status page updates without manual refresh and shows the short order code.
5. Deploy to the new Vercel project.

**Not in this phase:** accounts, saved shops, notifications, multiple files (unless O-9 says otherwise), payment screens.

**Exit gate**
- Tested on at least one Android Chrome and one iPhone Safari against the deployed API, including a private/incognito session; results recorded.
- A fresh user completes link → submitted order in under 60 seconds on mobile data; time recorded.
- Killing the API mid-flow shows an error, not a spinner or fake success.
- The order appears in the database with the correct price and events.

---

### Phase 5 — Desktop app with a fake printer

**Goal:** the shopkeeper's application works end to end except for the physical print, which is replaced by a fake engine that can be told to succeed, fail, hang, or crash.

**Work**
1. Enrolment with a one-time code; device secret stored with DPAPI.
2. Connection management: WebSocket, heartbeat, safety poll, reconnect with backoff, never exit on network failure.
3. Queue screen: new jobs, preview, settings, price, approve, reject. Needs-attention list with resolve actions.
4. Printer settings: choose B&W and colour printers from installed printers; test page button.
5. Claim → download → verify SHA-256 → hand to engine → report outcome, with a local journal written before each irreversible step.
6. Restart recovery: on start, any attempt the journal shows as possibly sent is reported as needs-attention, never reprinted.
7. Runs at Windows sign-in; closing the window keeps it running in the tray; single instance.
8. The end-to-end test from D-14 in `e2e/`.

**Not in this phase:** the real print engine, installer polish, auto-update, signing.

**Exit gate**
- End-to-end test passes for: success, engine failure, engine hang past timeout, app killed mid-print, network lost mid-print, duplicate approve click, cancel racing with claim. Output recorded.
- In every failure case the job ends in the state the contract specifies, and no case produces a second print attempt without a human action.
- Approval → fake print start measured and recorded.
- A non-technical person can approve a job from the queue screen without instructions (founder observes one person).

---

### Phase 6 — Real print engine and fault drills

**Goal:** replace the fake engine with the engine chosen in Phase 1 and prove the completion rule on paper.

**Work**
1. Implement the engine behind the same interface the fake used.
2. Implement spooler observation exactly as the Phase 1 completion rule specifies.
3. Repeat every Phase 1 failure drill through the full system.
4. Local temporary files deleted after every outcome.

**Not in this phase:** new features, new settings.

**Exit gate**
- 50 consecutive jobs submitted from a phone through the deployed system to a physical printer, each checked against the paper; results table recorded.
- Every failure drill recorded with the resulting job state and customer-visible wording.
- Zero duplicate prints. Zero jobs marked completed without paper.
- No document remains on the PC after its job ends (checked).

---

### Phase 7 — Installer, retention, runbook

**Goal:** the system can be installed at the shop and operated without the developer present.

**Work**
1. Installer for the desktop app (unsigned is acceptable for the private pilot; the SmartScreen warning is documented in the runbook).
2. Retention job: delete storage objects and mark records per O-5; verify deletion really removes the object.
3. `docs/RUNBOOK.md`: provision shop, install, enrol, test print, daily check, each failure and its fix, how to purge on request.
4. Minimal operator visibility: a founder script that lists today's jobs, failures and agent uptime for a shop.

**Exit gate**
- Clean install on a Windows PC that has never had the app, following only the runbook; time to first physical test print recorded (target under 15 minutes).
- Retention verified: a file past its window is gone from storage and cannot be fetched with an old signed URL.
- Reboot test: PC restarts, app comes back, reconnects, and processes a new job with no manual step.
- 24-hour soak with the app idle and connected; no crash, memory stable, heartbeats continuous.

---

### Phase 8 — Physical certification at the pilot shop

**Goal:** meet F-2.

**Work**
1. Install at the pilot shop. Counter QR sign that names the shop.
2. Run with real customers. Founder observes the first day, then stays away.
3. Fix only defects. Log every support intervention.

**Not in this phase:** feature requests. Record them in a backlog; do not build them.

**Exit gate**
- 50–100 real customer jobs recorded.
- Success rate, needs-attention rate, duplicate count, and timing medians reported from the events table.
- No privacy incident.
- At least three consecutive working days where the shopkeeper operated without help.
- Founder decides: proceed, fix and repeat, or change direction. Until this gate passes, section 3.2 stays closed.

---

### Phase 9 — Payments through FinFlow

**Before starting:** FinFlow is deployed, provider-sandbox verified, and the merchant-of-record and settlement model is decided in writing. If any of these is missing, this phase does not start.

**Goal:** a job becomes eligible for approval only after FinFlow confirms payment server-to-server.

**Work**
1. AutoPrint requests a payment intent from FinFlow for a quote; stores only the reference, amount and status.
2. A signed, idempotent webhook from FinFlow updates the payment record; only then is the job eligible.
3. Refund request to FinFlow when a paid job is rejected, cancelled before claim, or resolved as failed.
4. Customer screens for pay, pending, failed, refunded.

**Exit gate**
- Sandbox tests: success, failure, timeout, duplicate webhook, webhook before redirect, redirect without webhook, refund on each trigger. Results recorded.
- A forged or replayed webhook is rejected.
- No financial amounts or ledger logic exist in AutoPrint beyond the payment record.
- Live rollout only after a founder sign-off separate from the sandbox gate.

---

### Phase 10 — Second-stage validation

**Goal:** three shops printing daily for two weeks with about 99% of jobs completed or correctly resolved and a near-zero duplicate rate.

Before the second shop: decide O-6 (shopkeeper PIN), buy a code-signing certificate, and add the "ready" notification, which the survey ranks as the most wanted feature not in the MVP.

Everything else in section 3.2 is prioritised only after this phase, using measured data from the shops.

---

## 9. V3 reference map (read-only)

Read these for ideas. Do not copy code without checking it against the V4 contract, and never copy configuration.

| Concept | Where in `F:\Projects\Printer automation` |
|---|---|
| Atomic claim, attempt token, transitions table | `services/api/migrations/0001`, `0005`, `0006`, `0024` |
| Order secret (capability token) pattern | `services/api/app/capabilities.py`, `routes/orders.py` |
| Rate-card pricing and page-range parsing | `services/api/app/pricing.py` |
| Device enrolment and DPAPI storage | `services/api/app/device_auth.py`, `windows-agent/v3_device_credentials.py` |
| Local attempt journal | `windows-agent/attempt_journal.py` |
| Spooler reading (what not to do: match "any new job") | `windows-agent/v3_agent_runner.py` |
| Launcher, mutex, tray, graceful shutdown | `windows-agent/launcher.py`, `agent.py`, `tray_app.py` |
| Full list of V3 defects and causes | `claude_analysis_2026-10-05.md` |
| Product and business thinking | `docs/AI_PRODUCT_BUSINESS_CONTEXT.md` |
| Payment boundary | `docs/FINFLOW_ANTIGRAVITY_BUILD_BRIEF.md`, `F:\Projects\finflow\HANDOVER.md` |
