"""PDF validation by parsing structure, never by scanning raw bytes.

V3 rejected any file containing the three bytes "/JS" anywhere. Compressed image data contains
that sequence by chance, so valid files were refused at random (about 6% of 1 MB files and over
75% of 25 MB files). This module parses the document and inspects the real objects instead.

Limits: size is checked by the caller against the declared size; here we cap pages and wall time.
A parser that never returns cannot be killed from a thread, so the worker pool is small and the
caller gets an answer after the timeout; a pathological file is a known limitation (docs/ARCHITECTURE.md).
"""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass

from pypdf import PdfReader

MAX_PAGES = 2000
TIMEOUT_SECONDS = 15.0
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf-validate")


class PdfRejected(Exception):
    """The file cannot be accepted. `code` is a key in app.errors.CATALOG."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PdfInfo:
    page_count: int


def _has_javascript(reader: PdfReader) -> bool:
    """True when the document declares JavaScript through its catalog (names tree or open action)."""
    root = reader.trailer["/Root"]
    names = root.get("/Names")
    if names is not None and "/JavaScript" in names.get_object():
        return True
    action = root.get("/OpenAction")
    if action is not None:
        obj = action.get_object()
        if hasattr(obj, "get") and obj.get("/S") == "/JavaScript":
            return True
    return False


def _starts_like_pdf(data: bytes) -> bool:
    ws = bytes([0x20, 0x09, 0x0D, 0x0A, 0x00])
    prefix_len = len(data) - len(data.lstrip(ws))
    return prefix_len <= 16 and data[prefix_len:prefix_len + 5] == b"%PDF-"


def _inspect(data: bytes) -> PdfInfo:
    # The header must be at the very start (a few whitespace bytes are tolerated). Looking for it
    # anywhere in the first kilobyte would accept a multipart/form-data envelope that merely
    # contains a PDF, which is exactly what V3's upload bug produced.
    if not _starts_like_pdf(data):
        raise PdfRejected("file_not_pdf")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise PdfRejected("pdf_encrypted")
        count = len(reader.pages)
        if count < 1 or count > MAX_PAGES:
            raise PdfRejected("pdf_unreadable")
        if _has_javascript(reader):
            raise PdfRejected("pdf_unreadable")
        reader.pages[0]            # force the first page to parse
        return PdfInfo(page_count=count)
    except PdfRejected:
        raise
    except Exception:
        # Whatever the parser trips over, the answer for the customer is the same: this file cannot be read.
        # A list of known error types was not enough: a damaged page tree raises pypdf's LimitReachedError, which
        # is not a PdfReadError, and it surfaced as HTTP 500 with the document stuck in "pending" for good.
        raise PdfRejected("pdf_unreadable") from None


def validate_pdf(data: bytes) -> PdfInfo:
    future = _pool.submit(_inspect, data)
    try:
        return future.result(timeout=TIMEOUT_SECONDS)
    except FutureTimeout:
        future.cancel()
        raise PdfRejected("pdf_unreadable") from None
