"""The error catalog: one place that says what every failure means.

Every result code returned by a SQL function in supabase/migrations must appear in SQL_RESULT_MAP
(tests/test_contract.py enforces it). Clients branch on `code`, never on `message`.
Messages are written for the person who will read them and never contain internal detail.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiError:
    code: str
    http_status: int
    message: str


CATALOG: dict[str, ApiError] = {e.code: e for e in [
    # customer-facing
    ApiError("shop_not_found", 404, "This shop code is not recognised."),
    ApiError("shop_not_accepting", 409, "This shop is not taking orders right now."),
    ApiError("order_not_found", 404, "This order link is not valid any more."),
    ApiError("order_not_draft", 409, "This order has already been submitted."),
    ApiError("order_expired", 410, "This order was not approved in time. Please start a new one."),
    ApiError("order_not_cancellable", 409, "This order can no longer be cancelled."),
    ApiError("too_late", 409, "Printing has already started, so this order can no longer be cancelled."),
    ApiError("too_many_documents", 422, "Too many documents in one order."),
    ApiError("document_not_found", 404, "Document not found."),
    ApiError("document_not_pending", 409, "This document was already processed."),
    ApiError("document_not_ready", 409, "This document is not ready yet."),
    ApiError("invalid_items", 422, "The print settings are not valid for this document."),
    ApiError("quote_not_found", 404, "Price quote not found. Please check the price again."),
    ApiError("no_rate_card", 409, "This shop has not set its prices yet."),
    ApiError("file_too_large", 413, "The file is larger than 25 MB."),
    ApiError("file_not_pdf", 422, "Only PDF files can be printed."),
    ApiError("pdf_unreadable", 422, "This PDF could not be read. Try saving or exporting it again."),
    ApiError("pdf_encrypted", 422, "This PDF is password-protected. Remove the password and try again."),
    ApiError("upload_missing", 409, "The file was not received. Please upload it again."),
    ApiError("upload_size_mismatch", 422, "The uploaded file does not match what was announced. Please try again."),
    ApiError("invalid_page_range", 422, "Page range must look like 1-5, 8, 11-15 and stay within the document."),
    ApiError("invalid_copies", 422, "Copies must be between 1 and 100."),
    ApiError("try_again", 503, "The service is busy. Please try again."),
    # shop/agent-facing
    ApiError("unauthorized", 401, "This device is not authorised."),
    ApiError("invalid_enrollment_code", 400, "This enrollment code is invalid or has expired."),
    ApiError("pairing_not_found", 404, "This pairing code was not found."),
    ApiError("pairing_expired", 410, "This pairing code has expired. Start again on the shop PC."),
    ApiError("pairing_already_approved", 409, "This pairing code was already approved."),
    ApiError("device_not_found", 404, "That computer was not found."),
    ApiError("job_not_found", 404, "Job not found."),
    ApiError("not_actionable", 409, "This job is no longer in a state where that action is possible."),
    ApiError("device_busy", 409, "This device is already printing a job."),
    ApiError("stale_attempt", 409, "This print attempt is no longer current."),
    ApiError("evidence_insufficient", 409, "The evidence does not support marking this job completed."),
    ApiError("invalid_outcome", 422, "Unknown outcome."),
    ApiError("invalid_evidence", 422, "The evidence is malformed or too large."),
    ApiError("invalid_resolution", 422, "Unknown resolution."),
    ApiError("invalid_lease", 422, "Lease must be between 30 and 900 seconds."),
    # protocol / platform
    ApiError("invalid_request", 422, "The request is not valid."),
    ApiError("contract_mismatch", 426, "This app is out of date. Please update AutoPrint."),
    ApiError("rate_limited", 429, "Too many requests. Please wait a moment."),
    ApiError("not_implemented", 501, "Not implemented yet."),
    ApiError("internal_error", 500, "Something went wrong on our side. Please try again."),
]}

# SQL result code -> API error code. "ok", "claimed" and "no_job" are successes, not errors.
SQL_SUCCESS = {"ok", "claimed", "no_job"}
SQL_RESULT_MAP: dict[str, str] = {
    "shop_not_found": "shop_not_found",
    "shop_not_accepting": "shop_not_accepting",      # the shop's queue of jobs waiting for approval is full
    "order_not_found": "order_not_found",
    "order_not_draft": "order_not_draft",
    "order_expired": "order_expired",
    "order_not_cancellable": "order_not_cancellable",
    "too_late": "too_late",
    "too_many_documents": "too_many_documents",
    "document_not_found": "document_not_found",
    "document_not_pending": "document_not_pending",
    "document_not_ready": "document_not_ready",
    "invalid_items": "invalid_items",
    "quote_not_found": "quote_not_found",
    "no_rate_card": "no_rate_card",
    "try_again": "try_again",
    "unauthorized": "unauthorized",
    "invalid_code": "invalid_enrollment_code",
    "pairing_not_found": "pairing_not_found",
    "device_not_found": "device_not_found",
    "login_not_found": "device_not_found",
    "pairing_expired": "pairing_expired",
    "pairing_already_approved": "pairing_already_approved",
    "job_not_found": "job_not_found",
    "not_actionable": "not_actionable",
    "busy": "device_busy",
    "stale_attempt": "stale_attempt",
    "evidence_insufficient": "evidence_insufficient",
    "invalid_outcome": "invalid_outcome",
    "invalid_evidence": "invalid_evidence",
    "invalid_resolution": "invalid_resolution",
    "invalid_lease": "invalid_lease",
    # The API computes the total itself, so a mismatch means a bug, never a user error.
    "total_mismatch": "internal_error",
}


def error(code: str) -> ApiError:
    return CATALOG[code]
