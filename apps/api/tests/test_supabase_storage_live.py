"""Live checks of SupabaseStorage against the real V4 project (HTTPS only).

Skipped unless AUTOPRINT_V4_SUPABASE_URL and AUTOPRINT_V4_SUPABASE_SECRET_KEY are set; the repository's
git-ignored .env is loaded automatically for local runs. Each test uses a throwaway key and deletes it.
"""
import os
import uuid
from pathlib import Path

import httpx
import pytest

import pdfs
from app.storage import SupabaseStorage


def _load_dotenv():
    f = Path(__file__).resolve().parents[3] / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


_load_dotenv()
URL, KEY = os.environ.get("AUTOPRINT_V4_SUPABASE_URL"), os.environ.get("AUTOPRINT_V4_SUPABASE_SECRET_KEY")
pytestmark = pytest.mark.skipif(not (URL and KEY), reason="no V4 Supabase credentials in the environment")


@pytest.fixture
def store():
    return SupabaseStorage(URL, KEY)


@pytest.fixture
def key():
    k = f"tests/{uuid.uuid4().hex}.pdf"
    yield k
    SupabaseStorage(URL, KEY).delete(k)


def test_raw_put_read_signed_download_and_delete(store, key):
    data = pdfs.blank(3)
    grant = store.create_upload(key, len(data))
    assert key.split("/")[-1] in grant.url and "token=" in grant.url
    put = httpx.put(grant.url, content=data, headers=grant.headers, timeout=30)       # no apikey: the signed token is the credential
    assert put.status_code == 200, put.text
    assert store.read(key, len(data)) == data
    assert httpx.get(store.create_download_url(key), timeout=30).content == data
    store.delete(key)
    assert store.read(key, 10) is None
    store.delete(key)                                                                  # deleting a missing object is not an error


def test_object_is_private_without_a_signature(store, key):
    data = pdfs.blank(1)
    httpx.put(store.create_upload(key, len(data)).url, content=data, headers={"Content-Type": "application/pdf"}, timeout=30)
    anon = httpx.get(f"{URL}/storage/v1/object/public/print-documents/{key}", timeout=30)
    assert anon.status_code in (400, 404) and anon.content != data
    assert httpx.get(f"{URL}/storage/v1/object/print-documents/{key}", timeout=30).status_code in (400, 401, 403, 404)


def test_non_pdf_content_type_is_refused_by_the_bucket(store, key):
    grant = store.create_upload(key, 10)
    r = httpx.put(grant.url, content=b"hello", headers={"Content-Type": "text/plain"}, timeout=30)
    assert r.status_code >= 400


def test_signed_upload_url_cannot_be_reused_for_another_object(store, key):
    data = pdfs.blank(1)
    grant = store.create_upload(key, len(data))
    other = grant.url.replace(key.split("/")[-1], uuid.uuid4().hex + ".pdf")
    assert httpx.put(other, content=data, headers=grant.headers, timeout=30).status_code >= 400


def test_read_stops_just_past_the_declared_size(store, key):
    data = pdfs.blank(5)
    httpx.put(store.create_upload(key, len(data)).url, content=data, headers={"Content-Type": "application/pdf"}, timeout=30)
    assert len(store.read(key, 100)) == 101           # one byte past the limit, so the caller can detect an oversize file
