"""AutoPrint V4 API.

Customer routes, shop desktop app routes, shopkeeper dashboard routes and the founder's internal routes.

Rules for every handler: no business logic here (it lives in SQL functions), expected failures
become the error envelope through the catalog, and nothing secret is ever logged.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import schemas as s
from app.db import Database, sha256_hex
from app.email_auth import EmailAuth, EmailAuthError, make_email_auth
from app.errors import CATALOG, SQL_RESULT_MAP, SQL_SUCCESS
from app.pdf_validation import PdfRejected, validate_pdf
from app.pricing import PricingError, price_job, validate_rules
from app.settings import Settings, load_settings
from app.storage import LocalStorage, Storage, SupabaseStorage
from app.wording import CUSTOMER_MESSAGE

API_VERSION = "0.2.0"
log = logging.getLogger("autoprint.api")

ERR = {400: {"model": s.ErrorResponse}, 401: {"model": s.ErrorResponse}, 404: {"model": s.ErrorResponse},
       409: {"model": s.ErrorResponse}, 410: {"model": s.ErrorResponse}, 413: {"model": s.ErrorResponse},
       422: {"model": s.ErrorResponse}, 426: {"model": s.ErrorResponse}, 429: {"model": s.ErrorResponse},
       500: {"model": s.ErrorResponse}, 501: {"model": s.ErrorResponse}, 503: {"model": s.ErrorResponse}}

CAN_CANCEL_JOB_STATES = {"awaiting_approval", "approved"}


class ApiException(Exception):
    def __init__(self, code: str):
        self.error = CATALOG[code]


def not_implemented():
    raise ApiException("not_implemented")


def check(result: dict) -> dict:
    """Turn a SQL result into success (returned) or the matching API error (raised)."""
    code = result.get("result")
    if code in SQL_SUCCESS:
        return result
    raise ApiException(SQL_RESULT_MAP.get(code, "internal_error"))


def make_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_dir, settings.public_base_url, settings.signing_key,
                            settings.upload_url_ttl_seconds, settings.download_url_ttl_seconds)
    return SupabaseStorage(settings.supabase_url, settings.supabase_secret_key, settings.storage_bucket,
                           settings.upload_url_ttl_seconds, settings.download_url_ttl_seconds)


def run_maintenance_once(db: Database, storage: Storage) -> dict:
    """Idempotent. Called every minute by the API process and directly by tests."""
    swept = db.call("sweep")
    return {**swept, "documents_deleted": delete_due_documents(db, storage)}


def delete_due_documents(db: Database, storage: Storage, limit: int = 100) -> int:
    deleted = 0
    for document_id, key in db.rows("SELECT document_id, object_key FROM ap.documents_due_for_deletion(%s)", (limit,)):
        storage.delete(key)                      # delete the object first; mark only after it is gone
        db.one("SELECT ap.mark_document_deleted(%s)", (document_id,))
        deleted += 1
    return deleted


def create_app(settings: Optional[Settings] = None, *, contract_only: bool = False, email_auth: Optional[EmailAuth] = None) -> FastAPI:
    """contract_only builds the routes without a database; used to export contracts/openapi.json."""
    db: Optional[Database] = None
    storage: Optional[Storage] = None
    stop = threading.Event()

    if not contract_only:
        settings = settings or load_settings()
        db = Database(settings.database_url)
        storage = make_storage(settings)
        email_auth = email_auth or make_email_auth(settings.supabase_url, settings.supabase_publishable_key)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        thread = None
        if not contract_only and settings.background_maintenance:
            def loop():
                while not stop.wait(settings.maintenance_interval_seconds):
                    try:
                        run_maintenance_once(db, storage)
                    except Exception:
                        log.exception("maintenance failed")
            thread = threading.Thread(target=loop, name="maintenance", daemon=True)
            thread.start()
        yield
        stop.set()
        if db:
            db.close()

    app = FastAPI(title="AutoPrint V4 API", version=API_VERSION, openapi_url="/openapi.json", lifespan=lifespan,
                  description="Single contract for the customer web app and the shop desktop app.")

    if settings and settings.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "X-Order-Secret", "X-AutoPrint-Contract-Version"])

    # ------------------------------------------------------------ cross-cutting
    @app.middleware("http")
    async def guard(request: Request, call_next):
        started = time.perf_counter()
        sent = request.headers.get("x-autoprint-contract-version")
        if sent is not None and sent != str(s.CONTRACT_VERSION) and request.url.path != "/health":
            e = CATALOG["contract_mismatch"]
            return JSONResponse(status_code=e.http_status, content={"error": {"code": e.code, "message": e.message}})
        response = await call_next(request)
        route = request.scope.get("route")
        # log the route template only: never the URL (signed URLs), headers (secrets) or body (documents)
        log.info("%s %s %s %dms", request.method, getattr(route, "path", "-"), response.status_code,
                 (time.perf_counter() - started) * 1000)
        response.headers["X-AutoPrint-Contract-Version"] = str(s.CONTRACT_VERSION)
        return response

    @app.exception_handler(ApiException)
    async def api_exception_handler(_: Request, exc: ApiException):
        e = exc.error
        return JSONResponse(status_code=e.http_status, content={"error": {"code": e.code, "message": e.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, __: RequestValidationError):
        e = CATALOG["invalid_request"]       # never echo the offending input back
        return JSONResponse(status_code=e.http_status, content={"error": {"code": e.code, "message": e.message}})

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception):
        log.error("unhandled %s on %s", type(exc).__name__, getattr(request.scope.get("route"), "path", "-"))
        e = CATALOG["internal_error"]
        return JSONResponse(status_code=e.http_status, content={"error": {"code": e.code, "message": e.message}})

    def authorize_order(order_id: UUID, secret: str) -> None:
        found = db.one("SELECT ap.order_for_secret(%s)", (sha256_hex(secret),))[0]
        if found is None or str(found) != str(order_id):
            raise ApiException("order_not_found")          # same answer for "wrong secret" and "no such order"

    customer = APIRouter(prefix="/v1", tags=["customer"], responses=ERR)
    agent = APIRouter(prefix="/v1/agent", tags=["shop-agent"], responses=ERR)

    # ------------------------------------------------------------ customer (no account; X-Order-Secret after creation)
    @customer.get("/shops/{shop_code}", response_model=s.ShopPublic, operation_id="getShop")
    def get_shop(shop_code: str):
        code = shop_code.strip().upper()
        row = db.one("SELECT name, is_active FROM ap.shops WHERE code = %s", (code,))
        if row is None:
            raise ApiException("shop_not_found")
        online = db.one(
            "SELECT EXISTS (SELECT 1 FROM ap.devices d JOIN ap.shops s ON s.id = d.shop_id WHERE s.code = %s "
            "AND d.status = 'active' AND d.last_seen_at > now() - make_interval(secs => %s))",
            (code, settings.agent_online_seconds))[0]
        return s.ShopPublic(code=code, name=row[0], accepting_orders=bool(row[1]), agent_online=bool(online))

    @customer.get("/shops/{shop_code}/rates", response_model=s.RateCardPublic, operation_id="getShopRates")
    def get_rates(shop_code: str):
        row = db.one("SELECT r.version, r.rules FROM ap.rate_cards r JOIN ap.shops s ON s.id = r.shop_id "
                     "WHERE s.code = %s AND r.retired_at IS NULL", (shop_code.strip().upper(),))
        if row is None:
            raise ApiException("no_rate_card")
        try:
            validate_rules(row[1])
        except PricingError:
            raise ApiException("no_rate_card") from None
        return s.RateCardPublic(version=row[0], bw=s.RateTable(**row[1]["bw"]), color=s.RateTable(**row[1]["color"]))

    def limit(request: Request, purpose: str, maximum: int, window_seconds: int, scope: str = "", by_address: bool = True) -> None:
        """Fixed-window limit per caller address (hashed with a server secret; the address is never stored).
        If the limiter itself fails the request is allowed: a broken counter must not stop a shop's customers."""
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?"))
        bucket = sha256_hex(f"{settings.signing_key}|{purpose}|{scope}|{ip if by_address else '-'}")[:40]
        try:
            ok = db.call_scalar("rate_hit", bucket, window_seconds, maximum)
        except Exception:
            log.exception("rate limiter failed; allowing the request")
            return
        if not ok:
            raise ApiException("rate_limited")

    @customer.post("/shops/{shop_code}/orders", response_model=s.CreateOrderResponse, status_code=201, operation_id="createOrder")
    def create_order(shop_code: str, request: Request):
        # one address (a whole campus can share one) gets 60 new orders per 10 minutes; one shop 300 in total
        limit(request, "order", 60, 600)
        limit(request, "order-shop", 300, 600, scope=shop_code.strip().upper(), by_address=False)
        secret = secrets.token_hex(32)
        res = check(db.call("create_order", shop_code.strip().upper(), sha256_hex(secret)))
        return s.CreateOrderResponse(order_id=res["order_id"], order_secret=secret, short_code=res["short_code"],
                                     expires_at=res["expires_at"], access_until=res["access_until"])

    @customer.post("/orders/{order_id}/documents", response_model=s.RegisterDocumentResponse, status_code=201, operation_id="registerDocument")
    def register_document(order_id: UUID, body: s.RegisterDocumentRequest, request: Request, x_order_secret: str = Header(...)):
        limit(request, "upload", 150, 600)
        authorize_order(order_id, x_order_secret)
        if body.byte_size > settings.max_upload_bytes:
            raise ApiException("file_too_large")
        key = f"orders/{order_id}/{uuid4().hex}.pdf"
        res = check(db.call("register_document", order_id, body.file_name, body.byte_size, key))
        grant = storage.create_upload(key, body.byte_size)
        return s.RegisterDocumentResponse(document_id=res["document_id"], upload_url=grant.url, upload_headers=grant.headers)

    @customer.post("/orders/{order_id}/documents/{document_id}/finalize", response_model=s.FinalizeDocumentResponse, operation_id="finalizeDocument")
    def finalize_document(order_id: UUID, document_id: UUID, x_order_secret: str = Header(...)):
        authorize_order(order_id, x_order_secret)
        row = db.one("SELECT object_key, declared_bytes, status, sha256, page_count FROM ap.documents WHERE id = %s AND order_id = %s",
                     (document_id, order_id))
        if row is None:
            raise ApiException("document_not_found")
        key, declared, status, sha, pages = row
        if status == "validated":
            return s.FinalizeDocumentResponse(document_id=document_id, page_count=pages, sha256=sha)
        if status != "pending_upload":
            raise ApiException("document_not_pending")

        def refuse(code: str):
            db.call("reject_document", document_id, code)
            storage.delete(key)
            raise ApiException(code)

        data = storage.read(key, declared)
        if data is None:
            raise ApiException("upload_missing")              # not rejected: the customer may still be uploading
        if len(data) != declared:
            refuse("upload_size_mismatch")
        try:
            info = validate_pdf(data)                         # the object is read once and parsed once
        except PdfRejected as exc:
            refuse(exc.code)
        digest = hashlib.sha256(data).hexdigest()
        res = check(db.call("finalize_document", document_id, digest, len(data), info.page_count))
        return s.FinalizeDocumentResponse(document_id=document_id, page_count=res["page_count"], sha256=res["sha256"])

    @customer.post("/orders/{order_id}/quote", response_model=s.QuoteResponse, status_code=201, operation_id="createQuote")
    def create_quote(order_id: UUID, body: s.CreateQuoteRequest, request: Request, x_order_secret: str = Header(...)):
        limit(request, "quote", 300, 600)
        authorize_order(order_id, x_order_secret)
        rate = db.one("SELECT r.id, r.version, r.rules FROM ap.rate_cards r JOIN ap.orders o ON o.shop_id = r.shop_id "
                      "WHERE o.id = %s AND r.retired_at IS NULL", (order_id,))
        if rate is None:
            raise ApiException("no_rate_card")
        rate_id, version, rules = rate
        pages = {str(r[0]): r[1] for r in db.rows(
            "SELECT id, page_count FROM ap.documents WHERE order_id = %s AND status = 'validated'", (order_id,))}
        items, total = [], 0
        for item in body.items:
            page_count = pages.get(str(item.document_id))
            if page_count is None:
                raise ApiException("document_not_ready")
            try:
                price = price_job(page_count=page_count, copies=item.options.copies, color=item.options.color,
                                  duplex=item.options.duplex, page_range=item.options.page_range, rules=rules)
            except PricingError as exc:
                raise ApiException(exc.code) from None
            total += price.amount_paise
            items.append({"document_id": str(item.document_id), "copies": item.options.copies, "color": item.options.color,
                          "duplex": item.options.duplex, "page_range": item.options.page_range or None,
                          "selected_pages": price.selected_pages, "printed_sides": price.printed_sides,
                          "amount_paise": price.amount_paise, "paise_per_side": price.paise_per_side})
        res = check(db.call("create_quote", order_id, [{k: v for k, v in i.items() if k != "paise_per_side"} for i in items],
                            total, rate_id))
        return s.QuoteResponse(
            quote_id=res["quote_id"], total_paise=total, rate_card_version=version,
            items=[s.QuoteItem(document_id=i["document_id"], selected_pages=i["selected_pages"], printed_sides=i["printed_sides"],
                               paise_per_side=i["paise_per_side"], amount_paise=i["amount_paise"]) for i in items])

    @customer.post("/orders/{order_id}/submit", response_model=s.SubmitOrderResponse, operation_id="submitOrder")
    def submit_order(order_id: UUID, body: s.SubmitOrderRequest, x_order_secret: str = Header(...)):
        authorize_order(order_id, x_order_secret)
        res = check(db.call("submit_order", order_id, body.quote_id))
        pay = db.one("SELECT mode, status, amount_paise FROM ap.payments WHERE order_id = %s", (order_id,))
        return s.SubmitOrderResponse(order_id=order_id, job_ids=res["job_ids"], approval_expires_at=res["expires_at"],
                                     payment_mode=pay[0], payment_status=pay[1], amount_paise=pay[2])

    @customer.post("/orders/{order_id}/cancel", response_model=s.CancelOrderResponse, operation_id="cancelOrder")
    def cancel_order(order_id: UUID, x_order_secret: str = Header(...)):
        authorize_order(order_id, x_order_secret)
        check(db.call("cancel_order", order_id))
        return s.CancelOrderResponse(order_id=order_id, status=s.OrderStatus.cancelled)

    @customer.get("/orders/{order_id}", response_model=s.OrderView, operation_id="getOrder")
    def get_order(order_id: UUID, x_order_secret: str = Header(...)):
        # One database round trip: the secret check and the whole view happen in ap.order_view.
        v = db.call("order_view", sha256_hex(x_order_secret))
        if v["result"] != "ok" or v["order_id"] != str(order_id):
            raise ApiException("order_not_found")
        return s.OrderView(
            order_id=order_id, short_code=v["short_code"], shop_name=v["shop_name"], status=v["status"],
            approval_expires_at=v["approval_expires_at"], payment_mode=v["payment_mode"], payment_status=v["payment_status"],
            amount_paise=v["amount_paise"], can_cancel=v["can_cancel"],
            jobs=[s.OrderJobView(job_id=j["job_id"], document_name=j["document_name"], status=j["status"],
                                 customer_message=CUSTOMER_MESSAGE[s.JobStatus(j["status"])]) for j in v["jobs"]])

    # ------------------------------------------------------------ shop desktop app (X-Device-Id + X-Device-Secret)
    def device(x_device_id: UUID, x_device_secret: str) -> UUID:
        """Authenticate a device. Returns its id or raises 401. One extra round trip; the poll avoids it."""
        res = db.call("authenticate_device", x_device_id, sha256_hex(x_device_secret))
        if res["result"] != "ok":
            raise ApiException("unauthorized")
        return x_device_id

    @agent.post("/enroll", response_model=s.EnrollResponse, status_code=201, operation_id="enrollDevice")
    def enroll(body: s.EnrollRequest):
        secret = secrets.token_hex(32)
        res = check(db.call("consume_enrollment", sha256_hex(body.enrollment_code.strip().upper()),
                            body.display_name, sha256_hex(secret)))
        return s.EnrollResponse(device_id=res["device_id"], device_secret=secret, shop_code=res["shop_code"], shop_name=res["shop_name"])

    @agent.post("/pair/start", response_model=s.PairStartResponse, status_code=201, operation_id="startPairing")
    def pair_start(body: s.PairStartRequest, request: Request):
        limit(request, "pair", 12, 600)
        res = check(db.call("pair_start", sha256_hex(body.poll_token), sha256_hex(body.device_secret), body.display_name))
        code = res["code"]
        return s.PairStartResponse(pair_code=f"{code[:4]}-{code[4:]}", expires_at=res["expires_at"])

    @agent.post("/pair/poll", response_model=s.PairPollResponse, operation_id="pollPairing")
    def pair_poll(body: s.PairPollRequest):
        res = check(db.call("pair_poll", sha256_hex(body.poll_token)))
        return s.PairPollResponse(status=res["status"], device_id=res.get("device_id"), shop_code=res.get("shop_code"), shop_name=res.get("shop_name"))

    @agent.get("/jobs", response_model=s.JobListResponse, operation_id="listJobs")
    def list_jobs(x_device_id: UUID = Header(...), x_device_secret: str = Header(...), x_agent_version: str = Header("")):
        """The poll. Authenticates, records the heartbeat, sweeps when due, returns the queue: one round trip."""
        res = check(db.call("agent_poll", x_device_id, sha256_hex(x_device_secret), x_agent_version or None))
        if res.get("swept"):
            delete_due_documents(db, storage, limit=10)       # at most once a minute, a few objects
        return s.JobListResponse(shop_code=res["shop_code"], shop_name=res["shop_name"], jobs=res["jobs"])

    @agent.get("/jobs/{job_id}/document", response_model=s.DocumentAccess, operation_id="getJobDocument")
    def job_document(job_id: UUID, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        device(x_device_id, x_device_secret)
        res = check(db.call("job_document", job_id, x_device_id))
        return s.DocumentAccess(download_url=storage.create_download_url(res["object_key"]), sha256=res["sha256"], byte_size=res["bytes"])

    @agent.post("/jobs/{job_id}/approve", response_model=s.JobStatusResponse, operation_id="approveJob")
    def approve(job_id: UUID, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        device(x_device_id, x_device_secret)
        check(db.call("approve_job", job_id, x_device_id))
        return s.JobStatusResponse(job_id=job_id, status=s.JobStatus.approved)

    @agent.post("/jobs/{job_id}/reject", response_model=s.JobStatusResponse, operation_id="rejectJob")
    def reject(job_id: UUID, body: s.RejectRequest, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        device(x_device_id, x_device_secret)
        check(db.call("reject_job", job_id, x_device_id, body.reason))
        return s.JobStatusResponse(job_id=job_id, status=s.JobStatus.rejected)

    @agent.post("/jobs/{job_id}/resolve", response_model=s.JobStatusResponse, operation_id="resolveJob")
    def resolve(job_id: UUID, body: s.ResolveRequest, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        device(x_device_id, x_device_secret)
        res = check(db.call("resolve_job", job_id, x_device_id, body.resolution.value, body.note))
        return s.JobStatusResponse(job_id=job_id, status=res["job_status"])

    @agent.post("/claim", response_model=s.ClaimResponse, operation_id="claimNextJob")
    def claim(x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        device(x_device_id, x_device_secret)
        res = check(db.call("claim_next_job", x_device_id, 300))
        if res["result"] == "no_job":
            return s.ClaimResponse(status="no_job")
        doc = res["document"]
        return s.ClaimResponse(
            status="claimed", job_id=res["job_id"], attempt_id=res["attempt_id"], attempt_token=res["attempt_token"],
            spooler_job_name=res["spooler_job_name"], lease_expires_at=res["lease_expires_at"],
            document=s.DocumentAccess(download_url=storage.create_download_url(doc["object_key"]), sha256=doc["sha256"],
                                      byte_size=doc["bytes"], page_count=doc["pages"]),
            options=s.PrintOptions(copies=res["options"]["copies"], color=res["options"]["color"], duplex=res["options"]["duplex"],
                                   page_range=res["options"]["page_range"]))

    @agent.post("/attempts/{attempt_id}/renew", response_model=s.LeaseResponse, operation_id="renewLease")
    def renew(attempt_id: UUID, body: s.RenewRequest, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        device(x_device_id, x_device_secret)
        res = check(db.call("renew_lease", attempt_id, body.attempt_token, x_device_id, body.lease_seconds))
        return s.LeaseResponse(lease_expires_at=res["lease_expires_at"])

    @agent.post("/attempts/{attempt_id}/sent", response_model=s.AckResponse, operation_id="markSentToSpooler")
    def sent(attempt_id: UUID, body: s.AttemptAuth, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        device(x_device_id, x_device_secret)
        check(db.call("mark_sent", attempt_id, body.attempt_token, x_device_id))
        return s.AckResponse()

    @agent.post("/attempts/{attempt_id}/outcome", response_model=s.OutcomeResponse, operation_id="reportOutcome")
    def outcome(attempt_id: UUID, body: s.OutcomeRequest, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        device(x_device_id, x_device_secret)
        res = check(db.call("report_outcome", attempt_id, body.attempt_token, x_device_id, body.outcome.value, body.evidence))
        return s.OutcomeResponse(job_status=res.get("job_status") or ("needs_attention" if body.outcome.value == "uncertain" else body.outcome.value))

    # ------------------------------------------------------------ shop owner dashboard (X-Shop-Key)
    # The key is the credential of one shop login (method "link" today; phone/email later map to the same key check).
    shop = APIRouter(prefix="/v1/shop", tags=["shop-owner"], responses=ERR)

    @shop.post("/email/start", response_model=s.EmailStartResponse, status_code=202, operation_id="shopEmailStart")
    def shop_email_start(body: s.EmailStartRequest, request: Request):
        """Emails a sign-in link, but only to an address the founder registered. The answer is the same either way, so
        nobody can use this to find out which addresses are registered. That includes a provider failure: only a
        registered address can cause one, so it is logged and never shown to the caller."""
        email = body.email.strip().lower()
        h = sha256_hex(email)
        limit(request, "email-start", 5, 600)
        limit(request, "email-start-address", 3, 3600, scope=h, by_address=False)
        if db.call_scalar("shop_email_known", h):
            try:
                email_auth.send_link(email, f"{settings.web_base_url}/shop")
            except EmailAuthError:
                log.warning("sign-in email could not be sent")
        return s.EmailStartResponse(status="sent_if_registered")

    @shop.post("/email/finish", response_model=s.ShopSignedIn, operation_id="shopEmailFinish")
    def shop_email_finish(body: s.EmailFinishRequest, request: Request):
        """The shopkeeper came back from the email link with a provider token. If it proves a registered address, they get
        a normal shop key (stored only as a hash)."""
        limit(request, "email-finish", 20, 600)
        try:
            email = email_auth.verified_email(body.access_token)
        except EmailAuthError:
            raise ApiException("try_again") from None
        if not email:
            raise ApiException("unauthorized")
        key = secrets.token_hex(32)
        res = check(db.call("shop_email_login", sha256_hex(email.strip().lower()), sha256_hex(key)))
        return s.ShopSignedIn(key=key, shop_code=res["shop_code"], shop_name=res["shop_name"])

    @shop.get("/me", response_model=s.ShopMe, operation_id="shopMe")
    def shop_me(x_shop_key: str = Header(...)):
        res = check(db.call("shop_login_resolve", sha256_hex(x_shop_key)))
        return s.ShopMe(shop_code=res["shop_code"], shop_name=res["shop_name"])

    @shop.get("/pair/{pair_code}", response_model=s.ShopPairLookup, operation_id="shopPairLookup")
    def shop_pair_lookup(pair_code: str, x_shop_key: str = Header(...)):
        res = check(db.call("shop_pair_lookup", sha256_hex(x_shop_key), pair_code))
        return s.ShopPairLookup(display_name=res["display_name"], expired=res["expired"], approved=res["approved"], shop_name=res["shop_name"])

    @shop.post("/pair/approve", response_model=s.ShopPairApproved, operation_id="shopPairApprove")
    def shop_pair_approve(body: s.ShopPairApproveRequest, x_shop_key: str = Header(...)):
        res = check(db.call("shop_pair_approve", sha256_hex(x_shop_key), body.pair_code))
        return s.ShopPairApproved(device_id=res["device_id"], display_name=res["display_name"])

    @shop.get("/devices", response_model=s.ShopDeviceList, operation_id="shopDevices")
    def shop_devices(x_shop_key: str = Header(...)):
        res = check(db.call("shop_devices", sha256_hex(x_shop_key)))
        return s.ShopDeviceList(devices=[s.ShopDevice(device_id=d["device_id"], name=d["name"], last_seen_at=d["last_seen_at"], revoked=d["revoked"]) for d in res["devices"]])

    @shop.post("/devices/{device_id}/revoke", status_code=204, operation_id="shopDeviceRevoke")
    def shop_device_revoke(device_id: UUID, x_shop_key: str = Header(...)):
        check(db.call("shop_device_revoke", sha256_hex(x_shop_key), device_id))
        return Response(status_code=204)

    app.include_router(shop)
    app.include_router(customer)
    app.include_router(agent)

    # ------------------------------------------------------------ development storage (local backend only)
    if isinstance(storage, LocalStorage):
        @app.put("/v1/dev-storage/{key:path}", include_in_schema=False)
        async def dev_put(key: str, request: Request, exp: int, max: int, sig: str):
            if not storage.verify("PUT", key, exp, max, sig):
                raise ApiException("unauthorized")
            declared = request.headers.get("content-length")
            if declared is not None and int(declared) > max:
                raise ApiException("file_too_large")
            body = await request.body()
            if len(body) > max:
                raise ApiException("file_too_large")
            storage.write(key, body)
            return Response(status_code=200)

        @app.get("/v1/dev-storage/{key:path}", include_in_schema=False)
        async def dev_get(key: str, exp: int, max: int, sig: str):
            if not storage.verify("GET", key, exp, max, sig):
                raise ApiException("unauthorized")
            data = storage.read(key, 26_214_400)
            if data is None:
                raise ApiException("document_not_found")
            return Response(content=data, media_type="application/pdf")

    def require_maintenance_token(token: str) -> None:
        import hmac
        if not settings.maintenance_token or not hmac.compare_digest(
                sha256_hex(token), sha256_hex(settings.maintenance_token)):
            raise ApiException("unauthorized")

    @app.post("/v1/internal/maintenance", include_in_schema=False)
    def maintenance(x_maintenance_token: str = Header("")):
        """Called by a scheduler (free GitHub Actions cron) on hosts with no background thread."""
        require_maintenance_token(x_maintenance_token)
        return run_maintenance_once(db, storage)

    @app.post("/v1/internal/migrate", include_in_schema=False)
    def migrate(x_maintenance_token: str = Header("")):
        """Applies pending repo migration files. Needed because the database port is not reachable from the
        founder's network; the deployed API can reach it. Runs repo files only, never request input."""
        require_maintenance_token(x_maintenance_token)
        from app.migrate import apply_pending
        return apply_pending(settings.database_url)

    @app.post("/v1/internal/shop", include_in_schema=False)
    def provision_shop(body: dict, x_maintenance_token: str = Header("")):
        """Founder tool: creates a shop (if the code is new) and/or publishes a new rate card version, in one transaction.
        Needed because the database port is not reachable from the founder PC."""
        import json as _json
        import re as _re
        require_maintenance_token(x_maintenance_token)
        code, name, rules = str(body.get("code", "")).strip().upper(), str(body.get("name", "")).strip(), body.get("rules")
        if not _re.fullmatch(r"[A-Z]{3}[0-9]{3}", code):
            raise ApiException("shop_not_found")
        if rules is not None:
            try:
                validate_rules(rules)
            except PricingError as e:
                raise ApiException(e.code) from None

        def work(cur):
            cur.execute("SELECT id FROM ap.shops WHERE code = %s FOR UPDATE", (code,))
            row = cur.fetchone()
            created = row is None
            if created:
                if not (1 <= len(name) <= 80):
                    raise ApiException("invalid_items")
                cur.execute("INSERT INTO ap.shops (code, name) VALUES (%s, %s) RETURNING id", (code, name))
                row = cur.fetchone()
            version = None
            if rules is not None:
                cur.execute("SELECT COALESCE(max(version), 0) + 1 FROM ap.rate_cards WHERE shop_id = %s", (row[0],))
                version = cur.fetchone()[0]
                cur.execute("UPDATE ap.rate_cards SET retired_at = now() WHERE shop_id = %s AND retired_at IS NULL", (row[0],))
                cur.execute("INSERT INTO ap.rate_cards (shop_id, version, rules) VALUES (%s, %s, %s::jsonb)", (row[0], version, _json.dumps(rules)))
            return {"code": code, "created": created, "rate_card_version": version}

        return db.transaction(work)

    @app.post("/v1/internal/shop-email", include_in_schema=False)
    def register_shop_email(body: dict, x_maintenance_token: str = Header("")):
        """Founder tool: allow (or stop allowing) an email address to sign in to a shop dashboard."""
        require_maintenance_token(x_maintenance_token)
        email = str(body.get("email", "")).strip().lower()
        if "@" not in email or len(email) > 254:
            raise ApiException("invalid_items")
        h = sha256_hex(email)
        if body.get("remove"):
            check(db.call("shop_email_remove", h))
            return {"removed": True}
        check(db.call("shop_email_add", str(body.get("shop_code", "")), h, str(body.get("label", "owner"))[:80]))
        return {"registered": True}

    @app.get("/v1/internal/whoami", include_in_schema=False)
    def whoami(request: Request, x_maintenance_token: str = Header("")):
        """Shows which caller address headers the app sees, so the rate limiter can be checked behind the host."""
        require_maintenance_token(x_maintenance_token)
        h = request.headers
        return {"x_forwarded_for": h.get("x-forwarded-for"), "x_real_ip": h.get("x-real-ip"), "x_vercel_forwarded_for": h.get("x-vercel-forwarded-for"),
                "client_host": request.client.host if request.client else None}

    @app.post("/v1/internal/purge", include_in_schema=False)
    def purge_order(body: dict, x_maintenance_token: str = Header("")):
        """Deletes the uploaded documents of one order now (a customer asked for it). The order, job and event records stay,
        without any file. Refused while a job could still print (approved or printing) or wait for approval."""
        require_maintenance_token(x_maintenance_token)
        shop_code, short = str(body.get("shop_code", "")).strip().upper(), str(body.get("order", "")).strip().upper()
        orders = db.rows(
            "SELECT o.id FROM ap.orders o JOIN ap.shops s ON s.id = o.shop_id WHERE s.code = %s AND o.short_code = %s "
            "AND o.access_until > now() - interval '30 days'", (shop_code, short))
        if not orders:
            raise ApiException("order_not_found")
        ids = [r[0] for r in orders]
        live = db.one("SELECT count(*) FROM ap.jobs WHERE order_id = ANY(%s) AND status IN ('awaiting_approval', 'approved', 'printing')", (ids,))[0]
        if live:
            raise ApiException("not_actionable")
        # only this order's files; delete_after is set too, so the normal cleanup finishes the job if a delete fails here
        due = db.rows("UPDATE ap.documents SET delete_after = now() WHERE order_id = ANY(%s) AND deleted_at IS NULL RETURNING id, object_key", (ids,))
        n = 0
        for document_id, key in due:
            storage.delete(key)
            db.one("SELECT ap.mark_document_deleted(%s)", (document_id,))
            n += 1
        remaining = db.one("SELECT count(*) FROM ap.documents WHERE order_id = ANY(%s) AND deleted_at IS NULL", (ids,))[0]
        return {"orders_matched": len(ids), "documents_deleted_now": n, "documents_remaining": remaining}

    @app.get("/v1/internal/report/{shop_code}", include_in_schema=False)
    def shop_report(shop_code: str, hours: int = 24, x_maintenance_token: str = Header("")):
        """Founder visibility for one shop: job counts and outcomes, how long each took, and whether the shop computer is
        connected. No document names, no customer data. Same token as migrate."""
        require_maintenance_token(x_maintenance_token)
        hours = max(1, min(hours, 24 * 14))
        shop_row = db.one("SELECT id, name FROM ap.shops WHERE code = %s", (shop_code.strip().upper(),))
        if shop_row is None:
            raise ApiException("shop_not_found")
        shop_id = shop_row[0]
        jobs = db.rows(
            "SELECT o.short_code, j.status::text, j.attempt_count, j.created_at, "
            "EXTRACT(EPOCH FROM (j.updated_at - j.created_at))::int AS seconds_open "
            "FROM ap.jobs j JOIN ap.orders o ON o.id = j.order_id "
            "WHERE j.shop_id = %s AND j.created_at > now() - make_interval(hours => %s) ORDER BY j.created_at DESC LIMIT 200",
            (shop_id, hours))
        devices = db.rows(
            "SELECT display_name, status::text, last_seen_at, agent_version, created_at FROM ap.devices WHERE shop_id = %s ORDER BY created_at DESC LIMIT 20",
            (shop_id,))
        counts: dict[str, int] = {}
        for r in jobs:
            counts[r[1]] = counts.get(r[1], 0) + 1
        return {
            "shop": {"code": shop_code.upper(), "name": shop_row[1]}, "window_hours": hours,
            "counts": counts, "attention": counts.get("needs_attention", 0) + counts.get("failed", 0),
            "jobs": [{"order": r[0], "status": r[1], "attempts": r[2], "created_at": r[3], "seconds_to_final_state": r[4]} for r in jobs],
            "devices": [{"name": d[0], "status": d[1], "last_seen_at": d[2], "agent_version": d[3], "paired_at": d[4]} for d in devices],
        }

    @app.post("/v1/internal/shop-login", include_in_schema=False)
    def issue_shop_login(body: dict, x_maintenance_token: str = Header("")):
        """Founder tool: creates (method "link") or revokes a shop login without needing the database port. The key is
        returned once and only its hash is stored. Same token as migrate; never reachable by customers or shops.
        Revoking is by label within ONE shop: labels such as "owner" repeat across shops."""
        require_maintenance_token(x_maintenance_token)
        shop_code, label = str(body.get("shop_code", "")).strip().upper(), str(body.get("label", "owner"))[:80]
        if body.get("revoke_label"):
            shop_row = db.one("SELECT id FROM ap.shops WHERE code = %s", (shop_code,))
            if shop_row is None:
                raise ApiException("shop_not_found")
            n = db.one("WITH r AS (UPDATE ap.shop_logins SET revoked_at = now() WHERE shop_id = %s AND label = %s AND revoked_at IS NULL RETURNING 1) "
                       "SELECT count(*) FROM r", (shop_row[0], str(body["revoke_label"])[:80]))[0]
            return {"revoked": n}
        key = secrets.token_hex(32)
        res = check(db.call("shop_login_create", shop_code, "link", sha256_hex(key), label))
        return {"login_id": res["login_id"], "key": key}

    @app.get("/health", tags=["platform"], operation_id="health")
    def health():
        return {"status": "live", "contract_version": s.CONTRACT_VERSION}

    @app.get("/health/ready", tags=["platform"], operation_id="healthReady")
    def health_ready():
        ok = db.ping()
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "not_ready", "database": "ok" if ok else "failed"})

    return app
