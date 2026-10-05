"""Document storage behind a small interface.

LocalStorage is for development and tests. SupabaseStorage talks to Supabase Storage over HTTPS and
was verified against a live V4 project by apps/api/tests/test_supabase_storage_live.py.

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
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol
from urllib.parse import quote

import httpx


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


class SupabaseStorage:
    """Supabase Storage over its HTTPS API (port 443 only). The bucket is private.

    The secret key stays on the server. The browser receives only a signed upload URL, which accepts
    a raw PUT of the PDF bytes.
    """

    def __init__(self, base_url: str, secret_key: str, bucket: str = "print-documents",
                 upload_ttl: int = 900, download_ttl: int = 300, timeout: float = 30.0):
        self.base = base_url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.download_ttl = download_ttl
        self._http = httpx.Client(headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}, timeout=timeout)

    def _obj(self, key: str) -> str:
        return f"{self.bucket}/{quote(key, safe='/')}"

    def create_upload(self, key: str, max_bytes: int) -> UploadGrant:
        r = self._http.post(f"{self.base}/object/upload/sign/{self._obj(key)}")
        r.raise_for_status()
        return UploadGrant(url=self.base + r.json()["url"].removeprefix("/storage/v1"),
                           headers={"Content-Type": "application/pdf"})

    def read(self, key: str, max_bytes: int) -> Optional[bytes]:
        # Supabase's CDN caches authenticated object reads: a deleted object kept coming back (HTTP 200)
        # for at least 20 s. A unique query string makes every read miss the cache, so a deleted file is
        # gone at once. Measured against the live V4 project on 5 Oct 2026; covered by the live test.
        nonce = uuid.uuid4().hex
        with self._http.stream("GET", f"{self.base}/object/{self._obj(key)}?_={nonce}") as r:
            if r.status_code in (400, 404):
                return None
            r.raise_for_status()
            data = bytearray()
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > max_bytes:       # never buffer more than a little past the declared size
                    break
            return bytes(data[: max_bytes + 1])

    def create_download_url(self, key: str) -> str:
        r = self._http.post(f"{self.base}/object/sign/{self._obj(key)}", json={"expiresIn": self.download_ttl})
        r.raise_for_status()
        return self.base + r.json()["signedURL"].removeprefix("/storage/v1")

    def delete(self, key: str) -> None:
        r = self._http.request("DELETE", f"{self.base}/object/{self.bucket}", json={"prefixes": [key]})
        if r.status_code not in (200, 404):
            r.raise_for_status()
