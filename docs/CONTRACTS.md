# Contracts

What the database, the API, the web app and the desktop app must agree on. This file explains; the code enforces.

| Thing | Where it is defined | How drift is caught |
|---|---|---|
| Tables, enums, transitions, functions | `supabase/migrations/*.sql` | `supabase/tests/` run on a real PostgreSQL |
| HTTP routes and bodies | `apps/api/app/schemas.py`, `apps/api/app/main.py` → `contracts/openapi.json` | `test_openapi_file_is_current` |
| TypeScript types for the web app | `contracts/clients/ts/schema.d.ts`, generated | `test_typescript_client_is_current` |
| C# client for the desktop app | generated from `contracts/openapi.json` (Phase 5) | not set up yet |
| Enumerations | SQL is the source | `test_enums_match_the_database` |
| Error codes | `apps/api/app/errors.py` | `test_every_sql_result_code_is_in_the_error_catalog` |
| Customer wording | `apps/api/app/wording.py` | `test_customer_wording_never_claims_printed` |
| Pricing | `apps/api/app/pricing.py` | worked examples in `apps/api/tests/test_pricing.py` |

Rule: a change is finished only when both sides of a contract and the test that crosses them change in the same commit.

## State machines

Four separate records. No combined status. Legal moves are rows in `ap.allowed_transitions`; every SQL function checks them.

```
ORDER    draft ──submit──► submitted ──all jobs final──► closed
           │ │                │ └──► cancelled (customer, before any claim)
           │ └► cancelled     └─────► expired (system)
           └──► expired (1 h abandoned)

JOB      awaiting_approval ──approve──► approved ──claim──► printing ──► completed
              │ │ └ reject ► rejected         │                │ ├─────► failed
              │ └ customer ► cancelled        └ customer ► cancelled   └─────► needs_attention
              └ system ► expired                                              │
                                              (human) completed / failed / retry→approved
                                              failed ──(human retry)──► approved

ATTEMPT  claimed ──► sent_to_spooler ──► completed | failed | uncertain
            └──────► failed | uncertain

PAYMENT  not_required (MVP)  ... pending → paid | failed → refunded (Phase 9, FinFlow owns the money)
```

Point of no return: the **claim**. Before it, the customer may cancel. After it, `cancel_order` answers `too_late` and printing continues.

Never automatic: a second attempt. Only `resolve_job(..., 'retry')` by a person creates one.

## Time rules (decisions O-5, O-10)

| What | Rule |
|---|---|
| Unapproved job | Expires 1 hour after the order is submitted (`orders.expires_at`). Approved jobs are not affected |
| Abandoned draft | Order expires 1 hour after creation; documents deleted at the same time |
| Documents of a live order | Kept until the 48-hour hard cap (`orders.access_until`) |
| Documents after the order is final | Deleted 24 hours later, never beyond the hard cap |
| Order secret | Stops working at the hard cap |
| Lease | An attempt that is silent past `lease_expires_at` becomes `needs_attention` (never retried) |

`ap.sweep()` and the retention functions are called by the API process every minute. They are idempotent.

## Result codes

Every SQL function returns `{"result": "<code>", ...}`. Expected failures never raise. The API maps each code to an HTTP status through `SQL_RESULT_MAP`; clients branch on `error.code`, never on message text. Errors always look like:

```json
{"error": {"code": "order_expired", "message": "This order was not approved in time. Please start a new one."}}
```

## Customer wording

Decision O-8: until a physical printer proves what completion evidence we get, no customer text says "printed". The completed state reads **"Sent to printer."** The full table is in `apps/api/app/wording.py`.

## Pricing

Integer paise only. Total printed sides = selected pages × copies. The slab containing that total gives one rate, applied to every side. Page ranges (`1-3, 5`) select unique pages. Worked examples, including 3 pages at ₹2 = ₹6, are in `apps/api/tests/test_pricing.py`. The API prices; the browser only estimates and the server's quote is authoritative. The database re-checks ownership, page bounds and the total, and refuses a total that does not equal the sum of the lines.

## Credentials

| Who | Credential | Sent as | Stored as |
|---|---|---|---|
| Customer | Order secret, 64 hex characters, shown once at order creation | `X-Order-Secret` header | SHA-256 only |
| Shop PC | Device id + device secret, shown once at enrollment | `X-Device-Id`, `X-Device-Secret` | SHA-256 only; secret kept on the PC with Windows DPAPI |
| Print attempt | Attempt token, shown once at claim | request body | SHA-256 only |
| Enrollment | One-time code issued by a founder script, 30 minutes | request body | SHA-256 only |

No cookies anywhere (decision D-11). No account, no password, no OTP in the MVP.

## Agent protocol (shop desktop app ↔ API)

All calls are HTTPS requests with the device headers. A WebSocket carries only wake-up signals (decision D-10); it is an optimisation and the app must work with it down.

1. **Enroll once.** `POST /v1/agent/enroll` with the code. Store the device secret with DPAPI. Never log it.
2. **Heartbeat** every 20 s while running, independent of printing. The shop shows as "online" for 45 s after the last heartbeat.
3. **Wake-up.** On any WebSocket message, or at least every 30 s, list jobs and, if idle, claim.
4. **Claim.** `POST /v1/agent/claim` returns `no_job` or one job with: attempt id, attempt token, `spooler_job_name`, a lease, document access, and options. A device holds one live attempt at a time (`busy` otherwise).
5. **Before printing.** Write the intent to the local journal. Download the document, verify its SHA-256 against the claim, check the chosen printer exists. Save the file as `<spooler_job_name>.pdf`.
6. **Print.** Start the engine with a timeout. Then `POST /v1/agent/attempts/{id}/sent`.
7. **Observe** the spooler for the job by name until it leaves the queue or the wait limit passes (30 s + 2.5 s per page per copy, minimum 60 s). Renew the lease while waiting.
8. **Report** `completed` with evidence (below), or `failed` / `uncertain`. The server refuses `completed` when the evidence does not satisfy the rule.
9. **Clean up** the local file, and delete any spooler job it left behind.
10. **After a restart or crash.** Read the journal. Any attempt that may have reached the spooler is reported `uncertain`. Look for leftover spooler jobs named `apjob_*` and report them; never reprint.

Evidence sent with `completed` (rule version 2; see `docs/PRINT_SPIKE_REPORT.md`, addendum). The pages-printed number is informational only and is not required:

```json
{"rule_version": 2, "spooler_job_seen": true, "printing_seen": true, "left_queue": true,
 "flags_seen": ["SPOOLING", "PRINTING", "RETAINED"], "max_pages_printed": 3, "expected_pages": 3,
 "seconds_in_queue": 12.4}
```

Evidence never contains file names, URLs, tokens or document content.

## Not yet defined

WebSocket message formats; the C# client; the signed-upload details (Phase 3); notification channels; FinFlow payment calls (Phase 9).
