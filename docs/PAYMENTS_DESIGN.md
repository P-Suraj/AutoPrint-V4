# Payments design: AutoPrint V4 with FinFlow

Written 6 October 2026. Research and design only: no code, migration, deployment or live call was made.
FinFlow was read, not run. Every claim about either system cites a file; anything not checked by running is marked **unverified**.

Decisions designed for: P-1 to P-6, F-9, F-10, O-2 (`docs/DECISIONS.md`) and Phase 9 (`docs/BUILD_PHASES.md`, lines 482 to 498).

## 0. Summary

1. **FinFlow today cannot take a payment from a customer.** Creating a payment intent only writes a database row. Nothing creates a provider order or returns anything a customer can pay with (`F:\Projects\finflow\src\main\java\com\finflow\paymentintent\service\PaymentIntentService.java`, `create`; response fields in `paymentintent\dto\PaymentIntentResponse.java`).
2. **FinFlow is built for the opposite money model to P-1.** It assumes one platform Razorpay account that collects everything, takes a 10% fee, and pays shops out later (`F:\Projects\finflow\docs\architecture\provider-decision.md`; `webhook\provider\CaptureEventHandler.java`; `src\main\resources\application.yml`, `fee-basis-points` default 1000). P-1 says each shop is paid directly through its own account. There is no per-shop provider account anywhere in FinFlow.
3. **AutoPrint has a payment record but no eligibility check.** `docs/BUILD_PHASES.md` line 199 says one is in the schema. It is not: `ap.approve_job` and `ap.claim_next_job` never look at the payment (`supabase/migrations/0002_functions.sql`).
4. The AutoPrint side can be built and tested now against a fake FinFlow, behind a per-shop setting that defaults to OFF. Real money waits on the FinFlow gaps, hosting, and the founder questions in section 8.

---

## 1. What FinFlow really provides today

Source root: `F:\Projects\finflow`. Paths below are relative to it. Java paths are under `src\main\java\com\finflow\`.

### 1.1 Status

| Fact | Source |
|---|---|
| 111 local tests passed on 27 Aug 2026. Not provider-sandbox verified, not staged, not deployed, not approved for live money | `HANDOVER.md` lines 5 to 7, 185 |
| Merchant-of-record and settlement model is "a legal, compliance and provider-contract decision" still open | `HANDOVER.md` lines 34, 180 |
| Stack: Spring Boot 3.4.1, Java 21, PostgreSQL 16, Redis 7, RabbitMQ 3 | `PROJECT_CONTEXT.md` section 2; `build.gradle`; `docker-compose.yml` |
| Only provider wired is Razorpay, one account for the whole platform | `webhook\provider\RazorpayProperties.java`; `application.yml` (`finflow.razorpay.*`) |

### 1.2 Calls AutoPrint could make (the `/internal/v1` routes)

Authentication: header `X-Service-Key` (compared by SHA-256 hash), optional `X-Service-Key-Id`; one key, `key-v1`, is registered from an environment variable (`security\ServiceKeyAuthFilter.java`, `security\ServiceKeyRegistry.java`).

| Route | What the code does | Source |
|---|---|---|
| `POST /internal/v1/payment-intents` | Needs `Idempotency-Key`. `X-Correlation-ID` optional. `X-Service-Environment` optional and **defaults to `live`**. Stores an intent in status `created`, writes an audit row and a `payment.created` outbox event. Same quote with a live intent returns that intent; same quote with different amount, currency, merchant, customer or hash is refused. **No provider call. No checkout link.** | `paymentintent\controller\PaymentIntentController.java`; `paymentintent\service\PaymentIntentService.java` |
| `GET /internal/v1/payment-intents/{id}` | Returns the intent, including `status`, `capturedAt`, `failedAt`, `expiredAt`, `voidedAt` | same controller; `paymentintent\dto\PaymentIntentResponse.java` |
| `POST /internal/v1/payment-intents/{id}/cancel-or-void` | Voids an intent that is not yet captured. Refuses a captured one ("must be refunded via /refunds"). The `Idempotency-Key` header is read but not used, so a second call on a voided intent is refused, not repeated. Nothing is cancelled at the provider | `PaymentIntentController.java` (`cancelOrVoid`); `PaymentIntentService.java` (`cancelOrVoid`) |
| `POST /internal/v1/refunds` | Needs `Idempotency-Key`. Body: payment id, `external_cancellation_id`, amount, reason. One refund per (payment, cancellation id). Only for captured or partly refunded intents. Checks each request against the original amount, **not the running total** | `refund\controller\RefundController.java`; `refund\service\RefundService.java` |
| `GET /internal/v1/refunds/{id}` | Returns the refund | `RefundController.java` |

Request fields for creating an intent (`paymentintent\dto\CreatePaymentIntentRequest.java`): order id, quote id, quote hash (exactly 64 characters), customer id, merchant id, amount in paise (positive), currency, purpose, expiry (must be in the future), optional metadata.

**Field names on the wire are unverified.** The contract file uses snake_case (`docs\contracts\openapi-internal-v1.yaml`), but the Java records are camelCase with no naming rule configured anywhere under `src\main` (searched for `JsonProperty`, `JsonNaming`, `property-naming`, `snake`: no match). Spring's default would be camelCase (`externalOrderId`). No test posts JSON to these routes. This must be settled by running FinFlow once.

Documented but **not implemented** (no controller exists): `/merchants/{id}/receivables`, `/settlements/{id}`, `/reconciliation/payments/{id}` (`docs\contracts\openapi-internal-v1.yaml` lines 433 to 479; controllers present are listed in section 1.6).

### 1.3 How FinFlow learns a payment succeeded

`POST /provider/webhooks/razorpay` (`webhook\provider\ProviderWebhookIngressController.java`):
- Verifies `X-Razorpay-Signature` as HMAC-SHA256 of the raw body with one global secret (`RazorpaySignatureVerifier.java`).
- Stores the raw event in `webhook_inbox`, unique on (provider, event id); a repeat is answered `200 duplicate_acknowledged`.
- `payment.captured`: finds the intent by `notes.payment_intent_id`, then provider order id, then provider payment id; marks it captured; posts the ledger entries; creates a shop receivable; queues `payment.captured` for AutoPrint (`CaptureEventHandler.java`).
- `payment.failed`: marks the intent failed and queues `payment.failed` (`RazorpayEventProcessor.java`).
- `refund.processed` **and `refund.created`**: marks the refund succeeded, reverses the ledger, queues `refund.succeeded` (`RazorpayEventProcessor.java`, `RefundEventHandler.java`).

The intent is found only if somebody created the provider order with the intent id in its notes. Nothing in FinFlow does that (section 3, gap FF-1).

### 1.4 The outbound signed event to AutoPrint: exists, but not as documented

`outbox\service\OutboxDeliveryWorker.java` runs every 5 seconds and posts each queued event to **one** configured URL (`outbox\config\OutboxProperties.java`, default path `/webhooks/finflow`).

| Item | In the code | In `docs\contracts\event-schema.md` |
|---|---|---|
| Signature | HMAC-SHA256 hex of the whole request body, one global secret | `v1=<hex>` over timestamp + nonce + event id + base64 payload |
| Headers | `X-FinFlow-Signature` (bare hex), `X-FinFlow-Event-Id` | `X-FinFlow-Signature: v1=...`, `X-FinFlow-Timestamp` |
| Timestamp header, nonce, key id header | none (the body has `occurred_at`; `key_id` is stored but not sent) | all required |
| Retries | 5 attempts, waits 30 s, 60 s, 120 s, 240 s, then status `dead`. No redelivery route | not stated |
| Events really emitted | `payment.created`, `payment.captured`, `payment.failed`, `payment.voided`, `refund.pending`, `refund.succeeded`, `refund.failed` | also lists `payment.pending`, `payment.authorized`, `payment.expired`, settlement events |

Body shape, as built in `PaymentIntentService.java` and `CaptureEventHandler.java`: `event_id`, `event_type`, `schema_version`, `aggregate_id`, `aggregate_version`, `occurred_at`, `correlation_id`, and `payload` with `payment_id`, `external_order_id`, `external_quote_id`, `quote_hash`, `merchant_id`, `customer_id`, `amount_paise`, `currency`, `previous_status`, `new_status`, `environment` (captured adds `provider`, `provider_payment_id`, `provider_order_id`). Refund events differ between emitters: `refund.succeeded` uses `payment_intent_id` and has no order id (`RefundEventHandler.java`); `refund.failed` has `failure_reason` (`RefundExecutionWorker.java`).

`payment.expired` is never sent because `expireStaleIntents()` has no caller and no schedule (`PaymentIntentService.java`; searched all `@Scheduled` under `src\main`).

### 1.5 Refunds and money movement

- `refund\service\RefundExecutionWorker.java` runs every 10 seconds, calls `https://api.razorpay.com/v1/payments/{id}/refund` with the one global key pair, moves the refund to `pending`; 3 attempts, then `failed` and a `refund.failed` event. Success arrives only by provider webhook.
- On capture FinFlow books the money as received by the platform and splits 90/10 (`CaptureEventHandler.java`); a daily job batches receivables and `settlement2\service\PayoutExecutionWorker.java` calls `https://api.razorpay.com/v1/payouts`. `docs\architecture\merchant-settlement-model.md` and `provider-decision.md` describe this as the chosen model.

### 1.6 Other things found

| Finding | Source |
|---|---|
| Controllers that exist: Ledger, Merchant, Payment (old wallet API), PaymentIntent, Refund, Wallet, Webhook (old), ProviderWebhookIngress | file list under `src\main\java\com\finflow` |
| `POST /api/v1/merchants` is open to anyone and takes only a business name and email. `Merchant` has no provider account, KYC or bank fields | `config\SecurityConfig.java`; `merchant\entity\Merchant.java`; `PROJECT_CONTEXT.md` section 5 |
| The intent's `merchant_id` is stored as given; it is not checked against the merchants table | `PaymentIntentService.java` |
| The four "kill switches" in the runbook are set in `application.yml` but no Java code reads them | `docs\operations\runbook-and-rollback.md` section 2; search of `src\main\java` for the flag names: no match |
| On a signature mismatch FinFlow logs the signature it computed. That is the valid signature for the forged body | `RazorpaySignatureVerifier.java` |
| `README.md` shows a full-length `ff_live_...` key in an example. Treat as exposed; remove or rotate (not repeated here) | `README.md`, "Pre-Configured Console Access" |

### 1.7 Real runtime needs

| Need | Why | Source |
|---|---|---|
| A JVM process that never sleeps | Timers every 5 s (outbox), 10 s (refunds), 15 s (payouts), daily jobs; and it must answer the provider's webhook promptly | `@Scheduled` in `OutboxDeliveryWorker`, `RefundExecutionWorker`, `PayoutExecutionWorker`, `SettlementBatchingService`, `DailyReconciliationWorker` |
| A public HTTPS address | Razorpay must reach `/provider/webhooks/razorpay` | `ProviderWebhookIngressController.java` |
| PostgreSQL | All intent, refund, ledger, inbox, outbox and idempotency data | `resources\db\migration\V3__financial_core.sql` |
| Redis | Rate limiting for `X-API-KEY` merchants and the old payment API's idempotency. **Not used by the `/internal/v1` path** (its idempotency is in PostgreSQL) | `security\RateLimitingFilter.java`, `payment\IdempotencyService.java`, `idempotency2\service\IdempotencyEngine.java` |
| RabbitMQ | Old wallet-payment settlement and old webhook delivery only. **Not used by the `/internal/v1` path** | `settlement\SettlementWorker.java`, `webhook\WebhookDeliveryWorker.java` |
| Memory | Not measured. A Spring Boot service with JPA, Redis and AMQP clients usually wants more than 512 MB. **Unverified** | none |

So the path AutoPrint needs is JVM + PostgreSQL. Redis and RabbitMQ are required today only because the application starts their clients and listeners. Whether it starts cleanly without them was not tested.

---

## 2. What AutoPrint already has

| Item | What exists | Source |
|---|---|---|
| Payment record | `ap.payments`: one row per order (`order_id` unique), `mode` (`pay_at_counter`, `finflow`), `status` (`not_required`, `pending`, `paid`, `failed`, `refunded`), `amount_paise`, `external_ref` (text, for the FinFlow reference), `created_at`, `updated_at` | `supabase/migrations/0001_core_schema.sql` lines 17, 18, 142 to 152 |
| The only rule on it | `CHECK (mode = 'finflow' OR status = 'not_required')`: a pay-at-counter row can never be anything but `not_required` | same file, line 151 |
| Who writes it | Only `ap.submit_order`, which always inserts the defaults (`pay_at_counter`, `not_required`) with the quote total | `supabase/migrations/0002_functions.sql` line 256 |
| Who reads it | `ap.order_view` returns `payment_mode`, `payment_status`, `amount_paise` to the customer page; `submit_order` in the API returns the same three | `supabase/migrations/0004_agent_and_views.sql` lines 17 to 35; `apps/api/app/main.py` lines 324 to 349 |
| API types | `PaymentMode`, `PaymentStatus`, and the three fields on `SubmitOrderResponse` and `OrderView` | `apps/api/app/schemas.py` lines 27 to 32, 150 to 180 |
| Test | One assertion: after submit the payment is `not_required` | `supabase/tests/test_state_machine.py` line 36 |
| Customer text | "pay at the counter" is hard-coded | `apps/web/src/pages/OrderPage.tsx` line 172; `apps/web/src/pages/ShopPage.tsx` line 285 |

**The eligibility check does not exist.** `docs/BUILD_PHASES.md` line 199 says "The payment record and eligibility check are in the schema from Phase 2". Checked: `ap.approve_job`, `ap.claim_next_job`, `ap.resolve_job` and `ap.agent_poll` never read `ap.payments` (`0002_functions.sql`; `0004_agent_and_views.sql`; `0011_device_offline_events.sql`; no later migration mentions payments). A job whose payment was `pending` could be approved and printed today. Nothing sets `pending` yet, so there is no live fault, but the guard has to be built.

Also missing today: payment timestamps other than created and updated (F-10 asks for timestamps); any `payment` rows in `ap.allowed_transitions` (its check allows only `order`, `job`, `attempt`: `0001_core_schema.sql` line 220); any shop setting for payments or print mode (`ap.shops` has code, name, `is_active` only: lines 28 to 34); any FinFlow call, webhook route or FinFlow setting (`apps/api/app/main.py`, `apps/api/app/settings.py`); `docs/CONTRACTS.md` lists "FinFlow payment calls (Phase 9)" under "Not yet defined".

---

## 3. Gaps, the smallest change that closes each, and the owner

### 3.1 FinFlow side (owner: FinFlow)

| # | Gap | Smallest change | Blocks |
|---|---|---|---|
| FF-1 | No way to pay: no provider order, no checkout link returned | On intent creation, create the provider order or payment link **on the shop's account** with the intent id in its notes, and return a `checkout_url`. Accept a `return_url` | everything |
| FF-2 | One global provider key pair and one webhook secret. P-1 needs one account per shop | Store provider credentials (or a partner token) per merchant, encrypted; pick them by `merchant_id` for order creation, refunds and webhook verification | everything |
| FF-3 | No onboarding of a shop's own provider account; merchant registration is public and has no provider fields | A founder-only route or script to link a merchant to its provider account. Close the public registration route | live |
| FF-4 | Money model is platform collection with a 10% fee, ledger split, receivables and payouts. P-1 says AutoPrint never collects or settles | A "direct to shop" mode: on capture record the payment and notify AutoPrint; skip fee split, receivable and payout. Payout worker off | live |
| FF-5 | Outbound event: one target, one secret, no timestamp header, 5 tries in about 7.5 minutes then dead, no redelivery | Add `X-FinFlow-Timestamp` and sign timestamp + "." + body; keep retrying for 24 h; add "list events since" or "redeliver" | AUTO mode safety |
| FF-6 | Wire field names disagree between contract file and code (unverified) | Decide snake_case, enforce it, add one HTTP-level test per route | integration |
| FF-7 | Intents never expire; `payment.expired` never sent | Schedule `expireStaleIntents()` | timeout path |
| FF-8 | A capture or a second attempt arriving for a failed, voided or expired intent is refused with an error forever; the money is taken and nobody is told. Razorpay may allow a new attempt on the same order after a failed one (**unverified provider behaviour**) | Accept the capture, mark it "captured late", and either auto-refund or send AutoPrint a distinct event. Do not treat a failed attempt as the end of the order unless the provider says so | money safety |
| FF-9 | `cancel-or-void` is not idempotent and cancels nothing at the provider | Return the same result on repeat; cancel the provider order or link | timeout path |
| FF-10 | Refunds: running total not checked; `refund.created` treated as "succeeded"; no polling of refund state; global credentials | Check cumulative amount; mark succeeded only on `refund.processed`; use the shop's credentials | refunds |
| FF-11 | No per-payment reconciliation (documented route not built) | Build `POST /reconciliation/payments/{id}`: ask the provider, fix the intent | "no webhook" path |
| FF-12 | `X-Service-Environment` defaults to `live` | Default to `sandbox`, or refuse when missing | safety |
| FF-13 | Kill switches not wired; computed signature logged; exposed-looking key in README | Wire or remove the flags; stop logging the computed signature; rotate and remove the key | live |
| FF-14 | Redis and RabbitMQ needed only by old code paths | A run profile without them (see section 7) | hosting cost |
| FF-15 | Not deployed, not sandbox-verified | Section 7, then the Phase 9 sandbox list | live |

### 3.2 AutoPrint side (owner: AutoPrint)

| # | Gap | Smallest change |
|---|---|---|
| AP-1 | No shop settings | `ap.shops`: `online_payments boolean default false`, `print_mode` (`manual`, `auto`) default `manual`, `finflow_merchant_id text`. Copy the two settings onto the order at submit so a later change never alters an order in flight |
| AP-2 | No eligibility guard | `approve_job`, `claim_next_job` and the retry branch of `resolve_job` refuse unless the payment is `not_required` or `paid` |
| AP-3 | Payment record too thin | Add `paid_at`, `failed_at`, `refund_requested_at`, `refunded_at`, `refund_ref`; add statuses `refund_pending`, `refund_failed`; allow `payment` in `ap.allowed_transitions` |
| AP-4 | Unpaid job has no state | Add job status `awaiting_payment`; never send such jobs to the shop app |
| AP-5 | `submit_order` always creates pay-at-counter | Branch on the shop settings |
| AP-6 | No FinFlow client, webhook route, settings, or event record | Section 6, steps 6 to 8. One table `ap.payment_events` (event id unique, type, received time, result; no body) |
| AP-7 | Timers assume "1 hour from submit to approve" only; approved jobs never expire | Payment deadline; approval hour starts at payment; AUTO authorisation lapses (section 4.3) |
| AP-8 | Customer page hard-codes "pay at the counter"; the site's security header allows scripts and form posts only from itself (`vercel.json` line 25) | Pay by full-page redirect to FinFlow's `checkout_url`; no provider script in AutoPrint. New wording for payment states |
| AP-9 | Shop app claims a job before checking a printer is chosen, then reports `printer_not_found` (`apps/desktop/src/AutoPrint.Core/Agent/PrintOrchestrator.cs` lines 47, 72, 73); the server does not know whether a printer is ready | App: do not claim without a usable printer; send "printer ready" with each poll. Server: store it on the device |
| AP-10 | No quote hash (FinFlow requires 64 hex characters) | API computes SHA-256 of the accepted quote (id, total, item lines) when calling FinFlow. Nothing new stored |
| AP-11 | FinFlow requires a `customer_id`; customers are anonymous (F-4) | Send the order id. Founder question 10 |

---

## 4. State machines in the three modes

Four records stay separate (F-9). New values are marked **new**.

- **Order**: `draft`, `submitted`, `closed`, `cancelled`, `expired`. Unchanged.
- **Payment**: `not_required`, `pending`, `paid`, `failed`, `refund_pending` (**new**), `refunded`, `refund_failed` (**new**).
- **Job**: `awaiting_payment` (**new**), `awaiting_approval`, `approved`, `printing`, `completed`, `failed`, `needs_attention`, `rejected`, `cancelled`, `expired`.
- **Attempt**: unchanged.

### 4.1 The three rules that keep the print promises

1. **Print gate.** A job can be approved, claimed or retried only while its payment is `not_required` or `paid`. Once a refund is requested nothing can print.
2. **One authorisation, one attempt.** A confirmed payment moves a job out of `awaiting_payment` exactly once. The move is only legal from `awaiting_payment`, so a second, late or repeated confirmation changes nothing. Claiming is unchanged: one attempt per approval. A second attempt still needs a person (`resolve_job ... 'retry'`), in every mode.
3. **Refund only when printing is impossible or a person decided.** A refund is requested only when the job is in a state with no live attempt. A job in `printing` or `needs_attention` is never refunded automatically.

"Confirmed" means a verified `payment.captured` from FinFlow whose payment id, order id, quote id, amount, currency, merchant and environment all match AutoPrint's record. A match failure is not a confirmation (path 11).

### 4.2 Normal flows

```
OFF (today, default)
  submit -> payment not_required, job awaiting_approval -> approve -> approved -> claim -> printing -> ...

ON + MANUAL
  submit -> payment pending, job awaiting_payment, pay deadline set
  confirmed -> payment paid, job awaiting_approval, 1-hour approval window starts now
  shopkeeper approves -> approved -> claim -> printing -> ...

ON + AUTO
  submit -> payment pending, job awaiting_payment, pay deadline set
  confirmed -> payment paid, job approved (actor: system), authorisation deadline set
  shop app claims -> printing -> ...
```

```
PAYMENT   not_required                                  (OFF)
          pending --confirmed--> paid --refund asked--> refund_pending --> refunded
             |  ^                                              |
             v  | customer tries again (inside the window)     v
           failed                                        refund_failed (a person must act)
          failed --late capture--> paid --at once--> refund_pending
```

### 4.3 Timers (values are founder questions 5 to 7)

| Timer | Proposed | What happens at the end |
|---|---|---|
| Pay deadline | 15 minutes from submit | Check FinFlow once; if not captured: void the intent, job `expired`, payment `failed`, order `closed` |
| Approval window, ON + MANUAL | 1 hour from confirmation (as O-10, but starting at payment) | Job `expired`, refund requested |
| AUTO authorisation | 15 minutes from confirmation with no claim | Job goes back to `awaiting_approval` (a person must now approve) with a fresh 1-hour window |
| Device-reported `failed` on a paid job | 1 hour with no "Print again" | Refund requested; retry no longer possible (rule 1) |

### 4.4 Failure paths

"Shopkeeper sees" means the Windows app unless stated. Unpaid jobs are never shown to the shop.

| # | Case | Order | Payment | Job | Refund asked? | Customer sees | Shopkeeper sees |
|---|---|---|---|---|---|---|---|
| 1 | Payment fails (verified `payment.failed`) | `submitted` | `failed` | `awaiting_payment` | No | "Payment did not go through. Try again." (allowed until the pay deadline; a new intent is made) | Nothing |
| 2 | Times out: no confirmation by the deadline | `closed` | `failed` | `expired` | No. If a capture arrives later: `paid` then at once `refund_pending`, refund **yes** | "Payment was not completed in time. Start a new order." If late capture: "Your payment arrived too late. It is being refunded." | Nothing in the queue. A late capture appears in the refunds list |
| 3 | Duplicate webhook (same event id) | no change | no change | no change | No | Nothing new | Nothing new. Answered 200 so FinFlow stops retrying |
| 4 | Webhook arrives before the customer returns | `submitted` | `paid` | MANUAL: `awaiting_approval`. AUTO: `approved`, may already be `printing` | No | On return: "Paid." plus the normal job status. The return page decides nothing | MANUAL: job appears marked "Paid". AUTO: it prints |
| 5 | Customer returns, no webhook yet | `submitted` | `pending` | `awaiting_payment` | No | "Confirming your payment. Do not pay again." The page keeps checking. Nothing prints. The server asks FinFlow directly after 30 s and then each minute (founder question 8); if FinFlow never learns of it, path 2 applies | Nothing |
| 6 | Paid, then shop rejects | `closed` | `refund_pending` then `refunded` | `rejected` | Yes, the job amount | "The shop declined this print. Your payment is being refunded." | Before rejecting: "This will refund Rs X to the customer." After: "Rejected, refund in progress / refunded" |
| 7 | Paid, customer cancels before the claim | `cancelled` | `refund_pending` then `refunded` | `cancelled` | Yes. After the claim the answer is still `too_late`, printing continues, no refund | "Cancelled. Your payment is being refunded." or "Too late to cancel: it is already printing." | Job leaves the queue, or shows "Cancelled" |
| 8 | Paid job ends as failed | `closed` | Person chose "could not print": `refund_pending` at once. Shop app reported `failed`: stays `paid` for 1 hour so a person can "Print again", then `refund_pending` | `failed` | Yes | "The shop could not print this. Your payment is being refunded." | "Print again" or "Could not print: refund". `needs_attention` is never refunded automatically: the person picks completed (no refund), failed (refund) or print again |
| 9 | AUTO, shop computer offline or no printer chosen | `submitted` | Before paying: no payment is started. After paying: `paid` | `approved`, waiting. After 15 min unclaimed: `awaiting_approval`. After a further hour: `expired` | Only if it then expires, is rejected, or the customer cancels | Before paying: "The shop's printer is not ready. Ask at the counter." After: "Paid. Waiting for the shop's computer." with a cancel button | When the app comes back within 15 min it prints. After that it shows as "Paid, needs your approval" |
| 10 | Paid job would expire unapproved (MANUAL) | `closed` | `refund_pending` then `refunded` | `expired` | Yes | "The shop did not approve in time. Your payment is being refunded." | Paid jobs sit at the top with a countdown; afterwards "Expired, refunded" |
| 11 | Forged or replayed webhook | no change | no change | no change | No | Nothing | Nothing. Forged: answered 401, one event `payment.webhook_rejected` logged with no body. Replayed with a valid signature: seen event id, answered 200, no change. Valid signature but wrong amount, quote, merchant or environment: **not** treated as paid; logged as `payment.mismatch` for the founder |

Notes:
- Path 9 with today's shop app and no printer: the app claims, then reports `failed` with `printer_not_found` (`PrintOrchestrator.cs` lines 72, 73). That is path 8: nothing reached a printer, a person chooses "Print again" or the refund follows. Gap AP-9 removes this.
- A refund that fails: payment `refund_failed`, the job is never reopened (same rule as `F:\Projects\finflow\docs\contracts\event-schema.md`, `refund.failed`). Customer: "The refund could not be completed automatically. Please ask at the counter." It goes to a person.
- An order is one payment. The customer screen allows one document today (D-15), so every refund is the full amount. Per-job partial refunds are needed only when the multi-document screen is built; FinFlow gap FF-10 must be closed first.
- Refund requests are written in the same database transaction as the event that causes them (`refund_requested_at` set, `refund_ref` empty) and sent to FinFlow afterwards; the sweep resends any that were not acknowledged. The cancellation id sent to FinFlow is the job id, so a resend can never create a second refund (`RefundService.java` deduplicates on payment id plus cancellation id).

---

## 5. The contract between AutoPrint and FinFlow

"Exists" means the code is there in FinFlow. None of it is verified against a provider.

### 5.1 AutoPrint calls FinFlow

| Item | Detail | Status |
|---|---|---|
| Authentication | `X-Service-Key`, `X-Service-Key-Id: key-v1` | Exists (`ServiceKeyAuthFilter.java`) |
| Environment | `X-Service-Environment: sandbox` or `live`, **always sent** | Exists; unsafe default (FF-12) |
| Create intent | `POST /internal/v1/payment-intents` with order id, quote id, quote hash, customer id (= order id), merchant id (= the shop's FinFlow merchant), amount in paise, `INR`, purpose `print_base_price`, expiry = pay deadline | Exists |
| ... returns a checkout link | `checkout_url` in the answer; `return_url` in the request (AutoPrint's `/o/{orderId}` page) | **To be built** (FF-1) |
| ... routed to the shop's own provider account | by `merchant_id` | **To be built** (FF-2, FF-3) |
| Field naming | snake_case as in the contract file | **To be confirmed** (FF-6) |
| Idempotency key for create | A UUID made from (payment row, attempt number). Same key and body returns the stored answer; same key, different body is refused | Exists (`IdempotencyEngine`) |
| Read intent | `GET /internal/v1/payment-intents/{id}` | Exists |
| Void before capture | `POST .../cancel-or-void` | Exists; not idempotent, no provider cancel (FF-9) |
| Refund | `POST /internal/v1/refunds` with payment id, cancellation id (= job id), amount, reason | Exists; per-shop credentials and total check **to be built** (FF-2, FF-10) |
| Read refund | `GET /internal/v1/refunds/{id}` | Exists |
| Ask FinFlow to re-check one payment with the provider | `POST /internal/v1/reconciliation/payments/{id}` | **To be built** (FF-11) |

### 5.2 FinFlow calls AutoPrint (the webhook)

Route on AutoPrint: `POST /v1/webhooks/finflow`. No customer or device credential; the signature is the credential.

| Item | Detail | Status |
|---|---|---|
| Delivery | At least once, from the outbox | Exists (`OutboxDeliveryWorker.java`) |
| Signature | `X-FinFlow-Signature`: HMAC-SHA256 hex of the raw body, shared secret | Exists |
| Event id header | `X-FinFlow-Event-Id`, equal to `event_id` in the body | Exists |
| Timestamp in the signature, `v1=` prefix, nonce, key id for rotation | as `event-schema.md` describes | **To be built** (FF-5). Until then AutoPrint uses `occurred_at` from the signed body |
| Events AutoPrint acts on | `payment.captured`, `payment.failed`, `refund.succeeded`, `refund.failed` | Exist |
| `payment.expired` | | **To be built** (FF-7) |
| "Captured late" event | | **To be built** (FF-8) |
| Retry long enough to survive an AutoPrint outage; redelivery on request | | **To be built** (FF-5) |
| One consistent refund payload (`payment_id`, order id in every refund event) | | **To be built** (differs today, section 1.4) |

What AutoPrint does with each delivery, in this order:
1. Read the raw bytes. Compute the HMAC. Compare in constant time. Wrong or missing: 401, stop.
2. Header event id must equal the body's. `occurred_at` must be no older than 24 hours and not in the future beyond 5 minutes (wide because FinFlow re-sends the same body on retry).
3. Insert the event id into `ap.payment_events`. Already there: answer 200, stop.
4. Look up the payment by `external_ref`. For `payment.captured`, every one of payment id, order id, quote id, amount, currency, merchant and environment must match. Any difference: log `payment.mismatch`, answer 200, change nothing.
5. Apply one SQL function that makes the legal transition or does nothing. Answer 200.
6. Never log the body, the signature or the secret (F-14).

A 5xx is returned only when AutoPrint's own database is unreachable, so FinFlow retries.

---

## 6. Build plan for the AutoPrint side

Everything ships behind `online_payments`, default OFF, so each step can be deployed without changing a single shop.

### 6.1 Can be built and tested now, against a fake FinFlow

The fake is a small test double with the five calls in 5.1 and a helper that signs events exactly as `OutboxDeliveryWorker.java` does. The API reaches FinFlow through one interface (as it does for storage, `apps/api/app/storage.py`), so the fake and the real client are interchangeable.

| Step | Work | Test that proves it |
|---|---|---|
| 1 | Migration: shop settings, order snapshot of the two settings, new enum values, payment columns, `ap.payment_events`, new rows in `ap.allowed_transitions` | Transition matrix test extended; old tests pass unchanged |
| 2 | Print gate in `approve_job`, `claim_next_job`, `resolve_job` retry | An unpaid or refund-pending job cannot be approved, claimed or retried |
| 3 | `submit_order` branches on the snapshot: OFF as today; ON creates `pending` + `awaiting_payment` + pay deadline | Three submit tests, one per mode; OFF output byte-for-byte as today |
| 4 | SQL functions: confirm payment, fail payment, request refund, refund succeeded, refund failed. Each idempotent | Confirm twice = one transition. MANUAL lands in `awaiting_approval`, AUTO in `approved` by `system` |
| 5 | Refund triggers inside `reject_job`, `cancel_order`, `resolve_job` failed, and the sweep | Each trigger sets `refund_pending` once; none fires for `printing` or `needs_attention` |
| 6 | Sweep: pay deadline, approval hour from payment, AUTO lapse to manual, failed-then-refund after 1 hour, resend of unacknowledged refund requests | Time-travel tests by editing deadline columns, as the existing sweep tests do |
| 7 | API: FinFlow interface + fake; `POST /v1/orders/{id}/pay` (returns the checkout link, safe to repeat); settings for URL, key, signing secret, environment | Repeat call returns the same link; FinFlow down gives 503 `try_again` and no state change |
| 8 | API: `POST /v1/webhooks/finflow` as in 5.2; new error codes; regenerate `contracts/openapi.json` and the TypeScript client | Forged, replayed, duplicate, mismatched, out-of-order and late events, each asserted against the table in 4.4 |
| 9 | Poll: hide `awaiting_payment`; add "paid" and "needs approval after auto lapse" to each job row; device "printer ready" flag; `GET /v1/shops/{code}` says whether online payment is on and whether AUTO is ready | Contract tests for web and desktop wire models |
| 10 | Web: pay button, redirect, "Confirming your payment" return state, wording for every payment state; remove the hard-coded "pay at the counter" | Unit and Playwright tests with the fake |
| 11 | Shop app: "Paid" badge and countdown, refund warning on reject, no claim without a ready printer, readiness in the poll | Core tests; no real printer needed |
| 12 | Founder tools: set the two shop settings and the merchant id through `/v1/internal/shop-update`; payment counts in the founder report | Tool tests |
| 13 | End-to-end with the fake in all three modes, including paths 1 to 11 | Recorded results |

### 6.2 Must wait

| Waiting for | What it holds up |
|---|---|
| FF-1, FF-2, FF-6 (checkout link, per-shop account, field names) | The real FinFlow client. Until then the client shape is a guess |
| FF-5, FF-7, FF-8, FF-11 | Trusting AUTO mode with real money (missed or late confirmations) |
| FinFlow deployed somewhere with a stable public address (section 7) | Any sandbox test |
| Provider sandbox account and the Phase 9 exit list (`docs/BUILD_PHASES.md` lines 494 to 498) | Any claim that payments work |
| Founder answers 1 to 4 (money model, fees, hosting, who bears refunds) | FinFlow's design, shop onboarding |
| A shop with its own verified provider account | The first live payment, and the separate live sign-off Phase 9 requires |

---

## 7. Where FinFlow could run

Needs, from section 1.7: an always-on JVM, a public HTTPS address, PostgreSQL, and today also Redis and RabbitMQ.

Web figures below were read from search results on 6 October 2026, mostly third-party summaries. **Each is unverified until checked on the provider's own page.**

| Option | Cost | Card needed? | Fits? |
|---|---|---|---|
| A. Render free web service + free PostgreSQL elsewhere (a second Supabase project, or Neon) + Upstash Redis free + CloudAMQP free | Rs 0 | Reported no | **Sandbox only.** Reported 512 MB and 0.1 CPU, and it sleeps after 15 idle minutes with a 30 to 60 s wake. While asleep the outbox, refund and expiry timers stop, and a provider webhook may time out (Razorpay is reported to expect an answer in 5 s, retry for 24 h, then disable the webhook). 512 MB may not hold this JVM (not measured). Render's own free database is reported to expire after 30 days, so it is not usable |
| B. Founder's PC + Cloudflare named tunnel | Rs 0 for the tunnel; needs a domain on Cloudflare (domain price not checked) | No | **Sandbox only.** The laptop sleeps (`docs/HANDOVER.md` section 8). The no-account "quick tunnel" gives a random address with no uptime promise, so it cannot be a registered webhook address |
| C. Oracle Cloud Always Free virtual machine | Rs 0 | **Yes**, at sign-up | Technically fits everything (reported cut to 2 cores and 12 GB in June 2026). Fails the no-card rule |
| D. Fly.io, Railway, Koyeb, Google Cloud, AWS | varies | Fly, Railway, Koyeb reported yes for new accounts; Google and AWS not checked | Fail the no-card rule |
| E. Small Indian virtual server paid by UPI, running the existing `docker-compose.yml` | Reported Rs 360 to 400 a month for 2 GB | Reported no (UPI) | **The only option found that is always-on without a card.** Not free. Inside the Rs 500 to 2,000 a month of F-11, but against O-4 as written |
| F. Slim FinFlow first (FF-14: no Redis, no RabbitMQ on the AutoPrint path), then A or E | as A or E | as A or E | Makes E comfortable on a small server and A less tight. Does not remove the need for an always-on JVM |

Honest conclusion: **nothing found is free, needs no card, and is always-on.** Free hosting is enough to build and sandbox-test. Live money needs option E (or a card), or a founder decision to change what FinFlow is.

Supabase's free plan is reported to allow two active projects and to pause a project after 7 idle days. FinFlow must not share AutoPrint's database (`F:\Projects\finflow\PROJECT_CONTEXT.md`, "Shared-Nothing Databases"), so it would be a second project or a Neon database.

Sources (all read 6 Oct 2026): [Render free tier](https://justinmckelvey.com/blog/is-render-free), [Render pricing summary](https://www.srvrlss.io/provider/render/), [Oracle free tier cut](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/), [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm), [Koyeb pricing FAQ](https://www.koyeb.com/docs/faqs/pricing), [Fly.io free tier](https://www.saaspricepulse.com/tools/flyio), [Railway](https://www.saaspricepulse.com/tools/railway), [Cloudflare quick tunnels](https://flaviocopes.com/cloudflare-quick-tunnels/), [Razorpay webhook best practices](https://razorpay.com/docs/us/webhooks/best-practices/), [Razorpay Route linked accounts](https://razorpay.com/docs/payments/route/linked-account/?preferred-country=IN), [Razorpay partner OAuth](https://razorpay.com/docs/partners/technology-partners/onboard-businesses/integrate-oauth/integration-steps/), [CloudAMQP plans](https://www.cloudamqp.com/plans.html), [Upstash free tier](https://agentdeals.dev/vendor/upstash), [Supabase pricing](https://supabase.com/pricing), [Neon free tier](https://agentdeals.dev/vendor/neon), [Indian VPS prices](https://www.vyomcloud.com/blog/cheapest-vps-hosting-provider-in-india/).

---

## 8. Questions only the founder can answer

1. **P-1 against FinFlow's design.** FinFlow is written as "platform collects, keeps 10%, pays shops later". P-1 says shops are paid directly. Which stands? *Recommendation: P-1 stands. FinFlow gets a direct-to-shop mode (FF-2, FF-4) and its ledger split and payout workers stay off. Update FinFlow's own documents to say so.*
2. **How does a shop's own account connect?** (a) the shop opens its own provider account and FinFlow holds that shop's keys, (b) the provider's partner programme, where the shop authorises FinFlow, (c) the provider's split product, where the payment is still taken on the platform's account. *Recommendation: (b) if the provider accepts AutoPrint as a partner, otherwise (a) for the pilot shop only. Not (c): it does not match P-1. Whether (a) is allowed by the provider's terms is unverified; ask the provider in writing.*
3. **Does AutoPrint take a fee on online payments?** With direct settlement a fee needs the provider's split feature or a separate invoice. *Recommendation: no fee in the pilot.*
4. **Who bears the provider's charge and the refund when a paid job is rejected, expires, or fails?** The money is in the shop's account. *Recommendation: the shop, stated in the shop's onboarding terms. Provider fee rates were not checked.*
5. **Pay deadline.** *Recommendation: 15 minutes.*
6. **A paid job the shop does not approve (MANUAL).** *Recommendation: 1 hour from payment, then expire and refund automatically, with paid jobs shown first and a countdown in the shop app.*
7. **AUTO when the shop is not ready.** *Recommendation: do not start a payment unless a shop computer is online with a ready printer; if a paid job is not picked up in 15 minutes it falls back to needing the shopkeeper's approval. It never prints hours later on its own.*
8. **Is a direct server-to-server status read from FinFlow as good as the webhook (P-4)?** FinFlow stops retrying after about 7.5 minutes. *Recommendation: yes. It is still FinFlow's server-side word, never the browser's. Without it, a missed webhook means a paid customer waits until the timeout and gets a refund.*
9. **A shop app that reports "failed" on a paid job.** *Recommendation: hold the money for 1 hour so a person can "Print again", then refund automatically. `needs_attention` is never refunded without a person.*
10. **Customer identity.** FinFlow requires a customer id; customers have no account (F-4). *Recommendation: send the order id; AutoPrint collects no phone or email for payments; refunds go back to the paying account.*
11. **Hosting (P-5) and what "no card" allows.** *Recommendation: free hosting (option A or B) for sandbox work now; a UPI-paid server of about Rs 400 a month (option E, price unverified) before the first live payment. Please confirm that a UPI-paid service is acceptable.*
12. **Who changes a shop's two settings?** *Recommendation: the founder only, through the founder tool, for the pilot.*
13. **P-6 and AUTO mode.** Physical printing is recorded on the founder's word, with no results in the repository, and the completion rule is still marked provisional (`docs/DECISIONS.md`, C-1). AUTO prints with nobody watching. *Recommendation: allow MANUAL with payments first; switch AUTO on for a shop only after that shop's printer has a recorded run of real prints and failure drills.*
14. **An order whose total is Rs 0, or below the provider's minimum.** FinFlow refuses amounts below 1 paisa (`CreatePaymentIntentRequest.java`); the provider's minimum was not checked. *Recommendation: a zero total follows today's no-payment path even when online payments are ON.*
