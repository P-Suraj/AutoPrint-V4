"""Shopkeeper sign-in by email, with a fake provider standing in for Supabase Auth."""
import dataclasses

from fastapi.testclient import TestClient

from app.email_auth import EmailAuthError
from app.main import create_app

ADMIN = {"X-Maintenance-Token": "m" * 40}


def H(key):
    return {"X-Shop-Key": key}


class FakeEmailAuth:
    """Records mails and knows which token proves which address."""

    def __init__(self):
        self.sent, self.tokens, self.fail = [], {}, False

    def send_link(self, email, redirect_to):
        if self.fail:
            raise EmailAuthError("down")
        self.sent.append((email, redirect_to))

    def verified_email(self, token):
        return self.tokens.get(token)


def app_with(settings, fake=None, ip="203.0.113.1"):
    """Each test uses its own caller address, so the per-address limits of one test never leak into another."""
    s = dataclasses.replace(settings, maintenance_token="m" * 40)
    c = TestClient(create_app(s, email_auth=fake)) if fake else TestClient(create_app(s))
    c.headers.update({"X-Forwarded-For": ip})
    return c


def test_email_sign_in_gives_a_shop_key_only_for_registered_addresses(settings, shop):
    fake = FakeEmailAuth()
    with app_with(settings, fake) as c:
        assert c.post("/v1/internal/shop-email", headers=ADMIN, json={"shop_code": shop.code, "email": "Owner@Example.com", "label": "owner"}).status_code == 200
        # an unknown address gets the same answer, but nothing is sent
        r = c.post("/v1/shop/email/start", json={"email": "stranger@example.com"})
        assert r.status_code == 202 and r.json() == {"status": "sent_if_registered"} and fake.sent == []
        # a registered address (any letter case): the mail goes out with a link back to the dashboard
        r = c.post("/v1/shop/email/start", json={"email": "owner@example.com"})
        assert r.status_code == 202 and fake.sent == [("owner@example.com", "https://autoprint-v4.vercel.app/shop")]
        # a token the provider does not recognise gets nothing
        assert c.post("/v1/shop/email/finish", json={"access_token": "x" * 40}).status_code == 401
        # a token proving a registered address gets a working key; a proven but unregistered address does not
        fake.tokens["good" * 8] = "owner@example.com"
        fake.tokens["evil" * 8] = "stranger@example.com"
        assert c.post("/v1/shop/email/finish", json={"access_token": "evil" * 8}).status_code == 401
        ok = c.post("/v1/shop/email/finish", json={"access_token": "good" * 8})
        assert ok.status_code == 200, ok.text
        key = ok.json()["key"]
        assert ok.json()["shop_code"] == shop.code
        assert c.get("/v1/shop/me", headers=H(key)).json()["shop_code"] == shop.code
        # an email address can never be used as a key
        assert c.get("/v1/shop/me", headers=H("owner@example.com")).status_code == 401
        # removing the address stops new sign-ins
        assert c.post("/v1/internal/shop-email", headers=ADMIN, json={"email": "owner@example.com", "remove": True}).status_code == 200
        assert c.post("/v1/shop/email/finish", json={"access_token": "good" * 8}).status_code == 401


def test_email_sign_in_limits_and_provider_failure(settings, shop):
    fake = FakeEmailAuth()
    with app_with(settings, fake, ip="203.0.113.2") as c:
        c.post("/v1/internal/shop-email", headers=ADMIN, json={"shop_code": shop.code, "email": "a@example.com"})
        fake.fail = True
        assert c.post("/v1/shop/email/start", json={"email": "a@example.com"}).status_code == 503   # provider down: an honest error
        fake.fail = False
        codes = [c.post("/v1/shop/email/start", json={"email": "a@example.com"}).status_code for _ in range(4)]
        assert 429 in codes and codes[0] == 202                                                      # 3 per address per hour
        assert c.post("/v1/shop/email/start", json={"email": "not-an-email"}).status_code == 422


def test_without_a_provider_sign_in_by_email_says_try_again(settings, shop):
    with app_with(settings, ip="203.0.113.3") as c:
        c.post("/v1/internal/shop-email", headers=ADMIN, json={"shop_code": shop.code, "email": "b@example.com"})
        assert c.post("/v1/shop/email/start", json={"email": "b@example.com"}).status_code == 503
        assert c.post("/v1/shop/email/finish", json={"access_token": "z" * 40}).status_code == 401
