"""API tests run the real application against a real PostgreSQL and local file storage."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from dbtools import Db, Shop, build_database, drop_database

from sample_data import RULES  # noqa: E402


@pytest.fixture(scope="session")
def api_db_url():
    name = "v4_api_" + uuid.uuid4().hex[:10]
    url = build_database(name)
    yield url
    drop_database(name)


@pytest.fixture
def settings(api_db_url, tmp_path):
    return Settings(database_url=api_db_url, local_storage_dir=str(tmp_path / "files"), public_base_url="http://testserver",
                    signing_key="k" * 40, maintenance_interval_seconds=3600).validate()


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def raw_db(api_db_url):
    d = Db(api_db_url)
    yield d
    d.close()


@pytest.fixture
def shop(raw_db):
    """A shop with a rate card: B&W simplex 2 rupees per side."""
    s = Shop(raw_db)
    raw_db.run("UPDATE ap.rate_cards SET rules = %s::jsonb WHERE shop_id = %s", (__import__("json").dumps(RULES), s.id))
    return s


class Flow:
    """Drives the customer API the way the web app will."""

    def __init__(self, client, shop):
        self.c, self.shop = client, shop
        self.order_id = self.secret = None

    @property
    def h(self):
        return {"X-Order-Secret": self.secret}

    def create_order(self):
        r = self.c.post(f"/v1/shops/{self.shop.code}/orders")
        assert r.status_code == 201, r.text
        body = r.json()
        self.order_id, self.secret = body["order_id"], body["order_secret"]
        return body

    def register(self, size, name="doc.pdf"):
        return self.c.post(f"/v1/orders/{self.order_id}/documents", headers=self.h,
                           json={"file_name": name, "byte_size": size, "content_type": "application/pdf"})

    def upload(self, data: bytes, name="doc.pdf"):
        reg = self.register(len(data), name)
        assert reg.status_code == 201, reg.text
        body = reg.json()
        put = self.c.put(body["upload_url"], content=data, headers=body["upload_headers"])
        assert put.status_code == 200, put.text
        return body["document_id"]

    def finalize(self, doc_id):
        return self.c.post(f"/v1/orders/{self.order_id}/documents/{doc_id}/finalize", headers=self.h)

    def quote(self, items):
        return self.c.post(f"/v1/orders/{self.order_id}/quote", headers=self.h, json={"items": items})

    def submit(self, quote_id):
        return self.c.post(f"/v1/orders/{self.order_id}/submit", headers=self.h, json={"quote_id": quote_id})

    def view(self):
        return self.c.get(f"/v1/orders/{self.order_id}", headers=self.h)

    def cancel(self):
        return self.c.post(f"/v1/orders/{self.order_id}/cancel", headers=self.h)

    def full(self, data: bytes, **opts):
        """order -> upload -> finalize -> quote -> submit. Returns the pieces."""
        self.create_order()
        doc = self.upload(data)
        fin = self.finalize(doc)
        assert fin.status_code == 200, fin.text
        q = self.quote([{"document_id": doc, "options": opts}])
        assert q.status_code == 201, q.text
        s = self.submit(q.json()["quote_id"])
        assert s.status_code == 200, s.text
        return {"doc": doc, "quote": q.json(), "submit": s.json()}


@pytest.fixture
def flow(client, shop):
    return Flow(client, shop)
