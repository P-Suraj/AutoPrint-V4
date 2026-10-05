"""AutoPrint V4 API.

Phase 2: routes are declared so the contract can be generated; every handler answers
501 `not_implemented`. Phase 3 replaces the handlers one by one without changing signatures.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from app import schemas as s
from app.errors import CATALOG

API_VERSION = "0.1.0"

ERR = {400: {"model": s.ErrorResponse}, 401: {"model": s.ErrorResponse}, 404: {"model": s.ErrorResponse},
       409: {"model": s.ErrorResponse}, 410: {"model": s.ErrorResponse}, 413: {"model": s.ErrorResponse},
       422: {"model": s.ErrorResponse}, 426: {"model": s.ErrorResponse}, 429: {"model": s.ErrorResponse},
       500: {"model": s.ErrorResponse}, 501: {"model": s.ErrorResponse}, 503: {"model": s.ErrorResponse}}


class ApiException(Exception):
    def __init__(self, code: str):
        self.error = CATALOG[code]


def not_implemented():
    raise ApiException("not_implemented")


def create_app() -> FastAPI:
    app = FastAPI(title="AutoPrint V4 API", version=API_VERSION, openapi_url="/openapi.json",
                  description="Single contract for the customer web app and the shop desktop app.")

    @app.exception_handler(ApiException)
    async def api_exception_handler(_: Request, exc: ApiException):
        e = exc.error
        return JSONResponse(status_code=e.http_status, content={"error": {"code": e.code, "message": e.message}})

    customer = APIRouter(prefix="/v1", tags=["customer"], responses=ERR)
    agent = APIRouter(prefix="/v1/agent", tags=["shop-agent"], responses=ERR)

    # ------------------------------------------------------------ customer (no account; X-Order-Secret after creation)
    @customer.get("/shops/{shop_code}", response_model=s.ShopPublic, operation_id="getShop")
    def get_shop(shop_code: str):
        not_implemented()

    @customer.get("/shops/{shop_code}/rates", response_model=s.RateCardPublic, operation_id="getShopRates")
    def get_rates(shop_code: str):
        not_implemented()

    @customer.post("/shops/{shop_code}/orders", response_model=s.CreateOrderResponse, status_code=201, operation_id="createOrder")
    def create_order(shop_code: str):
        not_implemented()

    @customer.post("/orders/{order_id}/documents", response_model=s.RegisterDocumentResponse, status_code=201, operation_id="registerDocument")
    def register_document(order_id: UUID, body: s.RegisterDocumentRequest, x_order_secret: str = Header(...)):
        not_implemented()

    @customer.post("/orders/{order_id}/documents/{document_id}/finalize", response_model=s.FinalizeDocumentResponse, operation_id="finalizeDocument")
    def finalize_document(order_id: UUID, document_id: UUID, x_order_secret: str = Header(...)):
        not_implemented()

    @customer.post("/orders/{order_id}/quote", response_model=s.QuoteResponse, status_code=201, operation_id="createQuote")
    def create_quote(order_id: UUID, body: s.CreateQuoteRequest, x_order_secret: str = Header(...)):
        not_implemented()

    @customer.post("/orders/{order_id}/submit", response_model=s.SubmitOrderResponse, operation_id="submitOrder")
    def submit_order(order_id: UUID, body: s.SubmitOrderRequest, x_order_secret: str = Header(...)):
        not_implemented()

    @customer.post("/orders/{order_id}/cancel", response_model=s.CancelOrderResponse, operation_id="cancelOrder")
    def cancel_order(order_id: UUID, x_order_secret: str = Header(...)):
        not_implemented()

    @customer.get("/orders/{order_id}", response_model=s.OrderView, operation_id="getOrder")
    def get_order(order_id: UUID, x_order_secret: str = Header(...)):
        not_implemented()

    # ------------------------------------------------------------ shop desktop app (X-Device-Id + X-Device-Secret)
    @agent.post("/enroll", response_model=s.EnrollResponse, status_code=201, operation_id="enrollDevice")
    def enroll(body: s.EnrollRequest):
        not_implemented()

    @agent.post("/heartbeat", response_model=s.HeartbeatResponse, operation_id="heartbeat")
    def heartbeat(body: s.HeartbeatRequest, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    @agent.get("/jobs", response_model=s.JobListResponse, operation_id="listJobs")
    def list_jobs(x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    @agent.get("/jobs/{job_id}/document", response_model=s.DocumentAccess, operation_id="getJobDocument")
    def job_document(job_id: UUID, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    @agent.post("/jobs/{job_id}/approve", response_model=s.JobStatusResponse, operation_id="approveJob")
    def approve(job_id: UUID, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    @agent.post("/jobs/{job_id}/reject", response_model=s.JobStatusResponse, operation_id="rejectJob")
    def reject(job_id: UUID, body: s.RejectRequest, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    @agent.post("/jobs/{job_id}/resolve", response_model=s.JobStatusResponse, operation_id="resolveJob")
    def resolve(job_id: UUID, body: s.ResolveRequest, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    @agent.post("/claim", response_model=s.ClaimResponse, operation_id="claimNextJob")
    def claim(x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    @agent.post("/attempts/{attempt_id}/renew", response_model=s.HeartbeatResponse, operation_id="renewLease")
    def renew(attempt_id: UUID, body: s.RenewRequest, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    @agent.post("/attempts/{attempt_id}/sent", response_model=s.HeartbeatResponse, operation_id="markSentToSpooler")
    def sent(attempt_id: UUID, body: s.AttemptAuth, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    @agent.post("/attempts/{attempt_id}/outcome", response_model=s.JobStatusResponse, operation_id="reportOutcome")
    def outcome(attempt_id: UUID, body: s.OutcomeRequest, x_device_id: UUID = Header(...), x_device_secret: str = Header(...)):
        not_implemented()

    app.include_router(customer)
    app.include_router(agent)

    @app.get("/health", tags=["platform"], operation_id="health")
    def health():
        return {"status": "live", "contract_version": s.CONTRACT_VERSION}

    return app


app = create_app()
