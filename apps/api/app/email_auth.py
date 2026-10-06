"""Proof that a person owns an email address, behind a small interface.

SupabaseEmailAuth uses Supabase Auth (free tier): it emails a one-time sign-in link, and later tells us which verified
address a returned access token belongs to. The API never sees a password and keeps no Supabase session; it only turns
"this verified address is registered for shop X" into an ordinary shop login key (see migration 0009).

Written against the documented Supabase Auth REST endpoints (POST /auth/v1/otp, GET /auth/v1/user). NOT yet verified
against the live project: it needs the publishable key, the redirect URL allowed in the Supabase dashboard, and a real email.
"""
from __future__ import annotations

from typing import Optional, Protocol

import httpx


class EmailAuthError(Exception):
    """The provider could not be reached or refused. Never carries secrets."""


class EmailAuth(Protocol):
    def send_link(self, email: str, redirect_to: str) -> None: ...
    def verified_email(self, access_token: str) -> Optional[str]: ...


class DisabledEmailAuth:
    """Used when no provider is configured (local development, or before the founder sets it up)."""

    def send_link(self, email: str, redirect_to: str) -> None:
        raise EmailAuthError("email sign-in is not configured")

    def verified_email(self, access_token: str) -> Optional[str]:
        return None


class SupabaseEmailAuth:
    def __init__(self, base_url: str, publishable_key: str, timeout: float = 15.0):
        self._base = base_url.rstrip("/") + "/auth/v1"
        self._key = publishable_key
        self._http = httpx.Client(timeout=timeout)

    def send_link(self, email: str, redirect_to: str) -> None:
        try:
            r = self._http.post(f"{self._base}/otp", params={"redirect_to": redirect_to}, headers={"apikey": self._key},
                                json={"email": email, "create_user": True})
        except httpx.HTTPError as e:
            raise EmailAuthError("could not reach the email provider") from e
        if r.status_code >= 400:
            raise EmailAuthError(f"the email provider refused the request (HTTP {r.status_code})")

    def verified_email(self, access_token: str) -> Optional[str]:
        try:
            r = self._http.get(f"{self._base}/user", headers={"apikey": self._key, "Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as e:
            raise EmailAuthError("could not reach the email provider") from e
        if r.status_code in (401, 403):
            return None
        if r.status_code >= 400:
            raise EmailAuthError(f"the email provider refused the request (HTTP {r.status_code})")
        user = r.json()
        if not user.get("email") or not user.get("email_confirmed_at"):
            return None                                       # only an address the provider has confirmed counts
        return str(user["email"])


def make_email_auth(supabase_url: str, publishable_key: str) -> EmailAuth:
    if supabase_url.startswith("https://") and publishable_key:
        return SupabaseEmailAuth(supabase_url, publishable_key)
    return DisabledEmailAuth()
