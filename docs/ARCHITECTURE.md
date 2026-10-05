# Architecture

Status: Phase 2 draft. Decisions D-2, D-3, D-4, D-10 are still PROPOSED; this file records the working assumption and the constraints it creates.

```
Phone browser ──HTTPS──► API (always-on, same region as the DB) ──► PostgreSQL (Supabase, schema "ap")
     │                         ▲   │
     │ raw PDF PUT             │   └──► Storage (private bucket, signed URLs)
     └────────► Storage        │
                               │ HTTPS calls + one WebSocket (wake-ups only)
                       Windows desktop app (queue UI + print engine + local journal)
                               │
                       Windows spooler ──► physical printer
```

## Components and what each owns

| Component | Owns | Does not |
|---|---|---|
| **Customer web** (React, static) | The upload and settings screens, in-browser preview, a price *estimate* | Trust its own price; talk to the database or storage except the signed upload |
| **API** (FastAPI) | Validation, pricing, auth checks, calling SQL functions, signed URLs, sweeps | Hold business state in memory |
| **PostgreSQL** | All state and all rules (functions in `ap`) | Get exposed to browsers; schema `ap` must never be added to Supabase's exposed schemas |
| **Storage** | PDFs, private, signed access only | Hold anything past the retention rule |
| **Desktop app** (C# WPF) | Shopkeeper UI, enrollment, claiming, printing, spooler observation, the local journal | Decide business outcomes alone: it reports evidence, the database applies the rule |
| **FinFlow** (later) | Money | AutoPrint stores only a reference and a status |

## Constraints this design creates (write them down so nobody forgets)

1. **The API runs as one instance in the MVP.** The WebSocket wake-up registry is in memory. Two instances would need a shared channel. Correctness does not depend on the WebSocket (30 s safety poll), only latency does.
2. **The API and the database must be in the same region** (Mumbai). V3 was slow partly because they were not. Phase 3 measures the round trip and records it.
3. **One database transaction per operation**, through a direct pooled PostgreSQL connection, not the REST client. This is why every rule is a SQL function.
4. **No cookies.** Credentials travel in headers; see `docs/CONTRACTS.md`.
5. **The desktop app may be offline** at any time. It never exits on a network failure; it retries with backoff.
6. **A printer is shared.** The device prints one job at a time so a spooler job can be matched by name.
7. **Only the database function can mark a job completed**, and only for evidence that satisfies `ap.evidence_supports_completion`.

## What is deliberately absent

No queue broker, no cache, no worker fleet, no search engine, no service mesh, no second database. PDF validation runs inside the API process in a bounded worker thread. If a limit is reached, the answer is a measured change, not a guess.
