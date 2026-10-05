"""Request and response models. These generate contracts/openapi.json, which is the only
contract the web app and the desktop app are built from (decision D-13).

Enumerations below must equal the SQL enumerations in supabase/migrations/0001_core_schema.sql;
tests/test_contract.py compares them.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = 1


class OrderStatus(str, Enum):
    draft = "draft"; submitted = "submitted"; closed = "closed"; cancelled = "cancelled"; expired = "expired"


class DocumentStatus(str, Enum):
    pending_upload = "pending_upload"; validated = "validated"; rejected = "rejected"; deleted = "deleted"


class PaymentMode(str, Enum):
    pay_at_counter = "pay_at_counter"; finflow = "finflow"


class PaymentStatus(str, Enum):
    not_required = "not_required"; pending = "pending"; paid = "paid"; failed = "failed"; refunded = "refunded"


class JobStatus(str, Enum):
    awaiting_approval = "awaiting_approval"; approved = "approved"; printing = "printing"; completed = "completed"
    failed = "failed"; needs_attention = "needs_attention"; rejected = "rejected"; cancelled = "cancelled"; expired = "expired"


class AttemptStatus(str, Enum):
    claimed = "claimed"; sent_to_spooler = "sent_to_spooler"; completed = "completed"; failed = "failed"; uncertain = "uncertain"


class Outcome(str, Enum):
    completed = "completed"; failed = "failed"; uncertain = "uncertain"


class Resolution(str, Enum):
    completed = "completed"; failed = "failed"; retry = "retry"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(Strict):
    code: str = Field(description="Stable machine-readable code from the error catalog")
    message: str = Field(description="Human-readable text; never branch on it")


class ErrorResponse(Strict):
    error: ErrorBody


# ---------------------------------------------------------------- customer
class ShopPublic(Strict):
    code: str
    name: str
    accepting_orders: bool
    agent_online: bool = Field(description="True when the shop's desktop app has checked in recently")


class Slab(Strict):
    from_sides: int = Field(ge=1)
    to_sides: Optional[int] = Field(default=None, ge=1)
    paise_per_side: int = Field(ge=0)


class RateTable(Strict):
    simplex: list[Slab]
    duplex: list[Slab]


class RateCardPublic(Strict):
    version: int
    currency: str = "INR"
    bw: RateTable
    color: RateTable


class CreateOrderResponse(Strict):
    order_id: UUID
    order_secret: str = Field(description="Shown once. Send it as X-Order-Secret on every later call.")
    short_code: str = Field(description="Four characters the shopkeeper sees, e.g. A91F")
    expires_at: datetime
    access_until: datetime


class RegisterDocumentRequest(Strict):
    file_name: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(ge=1, le=26_214_400)
    content_type: str = Field(pattern="^application/pdf$")


class RegisterDocumentResponse(Strict):
    document_id: UUID
    upload_url: str = Field(description="Signed URL. PUT the raw PDF bytes, Content-Type application/pdf, no multipart.")
    upload_headers: dict[str, str]


class FinalizeDocumentResponse(Strict):
    document_id: UUID
    page_count: int
    sha256: str


class PrintOptions(Strict):
    copies: int = Field(default=1, ge=1, le=100)
    color: bool = False
    duplex: bool = False
    page_range: Optional[str] = Field(default=None, max_length=200, description="e.g. 1-3, 5. Null prints every page.")


class QuoteItemRequest(Strict):
    document_id: UUID
    options: PrintOptions


class CreateQuoteRequest(Strict):
    items: list[QuoteItemRequest] = Field(min_length=1, max_length=20)


class QuoteItem(Strict):
    document_id: UUID
    selected_pages: int
    printed_sides: int
    paise_per_side: int
    amount_paise: int


class QuoteResponse(Strict):
    quote_id: UUID
    items: list[QuoteItem]
    total_paise: int
    currency: str = "INR"
    rate_card_version: int


class SubmitOrderRequest(Strict):
    quote_id: UUID


class SubmitOrderResponse(Strict):
    order_id: UUID
    job_ids: list[UUID]
    approval_expires_at: datetime
    payment_mode: PaymentMode
    payment_status: PaymentStatus
    amount_paise: int


class OrderJobView(Strict):
    job_id: UUID
    document_name: str
    status: JobStatus
    customer_message: str = Field(description="Conservative wording. Never says 'printed'.")


class OrderView(Strict):
    order_id: UUID
    short_code: str
    shop_name: str
    status: OrderStatus
    approval_expires_at: Optional[datetime]
    payment_mode: Optional[PaymentMode]
    payment_status: Optional[PaymentStatus]
    amount_paise: Optional[int]
    can_cancel: bool
    jobs: list[OrderJobView]


class CancelOrderResponse(Strict):
    order_id: UUID
    status: OrderStatus


# ---------------------------------------------------------------- shop desktop app / agent
class EnrollRequest(Strict):
    enrollment_code: str = Field(min_length=8, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)


class EnrollResponse(Strict):
    device_id: UUID
    device_secret: str = Field(description="Shown once. Store with Windows DPAPI.")
    shop_code: str
    shop_name: str


class HeartbeatRequest(Strict):
    agent_version: str = Field(max_length=40)


class HeartbeatResponse(Strict):
    server_time: datetime
    contract_version: int = CONTRACT_VERSION


class JobSummary(Strict):
    job_id: UUID
    order_short_code: str
    document_name: str
    page_count: int
    copies: int
    color: bool
    duplex: bool
    page_range: Optional[str]
    amount_paise: int
    status: JobStatus
    created_at: datetime
    approval_expires_at: Optional[datetime]


class JobListResponse(Strict):
    jobs: list[JobSummary]


class DocumentAccess(Strict):
    download_url: str = Field(description="Short-lived signed URL. Never log it.")
    sha256: str
    byte_size: int


class ClaimResponse(Strict):
    status: str = Field(pattern="^(claimed|no_job)$")
    job_id: Optional[UUID] = None
    attempt_id: Optional[UUID] = None
    attempt_token: Optional[str] = Field(default=None, description="Shown once; hashed in the database")
    spooler_job_name: Optional[str] = Field(default=None, description="The agent must print the file under exactly this name")
    lease_expires_at: Optional[datetime] = None
    document: Optional[DocumentAccess] = None
    options: Optional[PrintOptions] = None


class RejectRequest(Strict):
    reason: Optional[str] = Field(default=None, max_length=200)


class ResolveRequest(Strict):
    resolution: Resolution
    note: Optional[str] = Field(default=None, max_length=200)


class AttemptAuth(Strict):
    attempt_token: str = Field(min_length=64, max_length=64)


class RenewRequest(AttemptAuth):
    lease_seconds: int = Field(default=300, ge=30, le=900)


class OutcomeRequest(AttemptAuth):
    outcome: Outcome
    evidence: dict = Field(default_factory=dict, description="Structured spooler evidence; see docs/CONTRACTS.md")


class JobStatusResponse(Strict):
    job_id: UUID
    status: JobStatus
