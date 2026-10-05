"""Document storage behind a small interface.

LocalStorage is for development and tests. The Supabase implementation is added in Phase 3's
deployment step, once a V4 Supabase project exists, and verified against it. Nothing here claims
to work against Supabase.

Rules every implementation must follow:
  * objects are private; access is only by short-lived signed URL or by the API itself
  * the upload URL accepts a raw PUT of the PDF bytes (no multipart) up to the declared size
  * delete() of a missing object is not an error
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


@dataclass(frozen=True)
class UploadGrant:
    url: str
    headers: dict[str, str]


class Storage(Protocol):
    def create_upload(self, key: str, max_bytes: int) -> UploadGrant: ...
    def read(self, key: str, max_bytes: int) -> Optional[bytes]: ...
    def create_download_url(self, key: str) -> str: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Files under a directory. Signed URLs point at this API's /v1/dev-storage route."""

    def __init__(self, directory: str, public_base_url: str, signing_key: str,
                 upload_ttl: int = 900, download_ttl: int = 300):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.base = public_base_url
        self.key = signing_key.encode()
        self.upload_ttl = upload_ttl
        self.download_ttl = download_ttl

    # -- paths ---------------------------------------------------------------
    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("object key escapes the storage directory")
        return p

    # -- signing -------------------------------------------------------------
    def _sign(self, verb: str, key: str, exp: int, max_bytes: int) -> str:
        msg = f"{verb}|{key}|{exp}|{max_bytes}".encode()
        return hmac.new(self.key, msg, hashlib.sha256).hexdigest()

    def verify(self, verb: str, key: str, exp: int, max_bytes: int, sig: str) -> bool:
        return exp >= int(time.time()) and hmac.compare_digest(self._sign(verb, key, exp, max_bytes), sig)

    # -- interface -----------------------------------------------------------
    def create_upload(self, key: str, max_bytes: int) -> UploadGrant:
        exp = int(time.time()) + self.upload_ttl
        sig = self._sign("PUT", key, exp, max_bytes)
        return UploadGrant(url=f"{self.base}/v1/dev-storage/{key}?exp={exp}&max={max_bytes}&sig={sig}",
                           headers={"Content-Type": "application/pdf"})

    def create_download_url(self, key: str) -> str:
        exp = int(time.time()) + self.download_ttl
        sig = self._sign("GET", key, exp, 0)
        return f"{self.base}/v1/dev-storage/{key}?exp={exp}&max=0&sig={sig}"

    def write(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def read(self, key: str, max_bytes: int) -> Optional[bytes]:
        p = self._path(key)
        if not p.exists():
            return None
        if p.stat().st_size > max_bytes:
            return p.read_bytes()[: max_bytes + 1]   # caller compares length with the declared size
        return p.read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def exists(self, key: str) -> bool:
        return self._path(key).exists()
