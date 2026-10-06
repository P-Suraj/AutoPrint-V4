"""Configuration from environment variables. Every variable is prefixed AUTOPRINT_V4_ so a
leftover V3 variable (SUPABASE_URL, DATABASE_URL, ...) can never be picked up by accident."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str
    storage_backend: str = "local"                 # "local" (dev/test) or "supabase" (not wired yet)
    local_storage_dir: str = ".localstorage"
    public_base_url: str = "http://127.0.0.1:8000"  # used to build signed upload URLs for local storage
    signing_key: str = field(default="", repr=False)
    supabase_url: str = ""
    supabase_secret_key: str = field(default="", repr=False)
    supabase_publishable_key: str = ""             # public by design; used for email sign-in (Supabase Auth)
    web_base_url: str = "https://autoprint-v4.vercel.app"   # where the sign-in email sends the shopkeeper back to
    storage_bucket: str = "print-documents"
    maintenance_token: str = field(default="", repr=False)
    background_maintenance: bool = True           # False on serverless hosts, where a scheduler calls /v1/internal/maintenance
    max_upload_bytes: int = 26_214_400              # 25 MiB
    upload_url_ttl_seconds: int = 900
    download_url_ttl_seconds: int = 300
    agent_online_seconds: int = 45
    maintenance_interval_seconds: int = 60
    environment: str = "development"
    allowed_origins: tuple[str, ...] = ()

    def validate(self) -> "Settings":
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ConfigError("AUTOPRINT_V4_DATABASE_URL must be a PostgreSQL URL")
        if self.storage_backend not in {"local", "supabase"}:
            raise ConfigError("AUTOPRINT_V4_STORAGE_BACKEND must be 'local' or 'supabase'")
        if self.storage_backend == "supabase" and not (self.supabase_url.startswith("https://") and self.supabase_secret_key):
            raise ConfigError("AUTOPRINT_V4_SUPABASE_URL (https) and AUTOPRINT_V4_SUPABASE_SECRET_KEY are required for supabase storage")
        if self.storage_backend == "local" and len(self.signing_key) < 32:
            raise ConfigError("AUTOPRINT_V4_SIGNING_KEY must be at least 32 characters for local storage")
        if self.environment == "production":
            if self.storage_backend == "local":
                raise ConfigError("local storage is for development and tests only")
            if "*" in self.allowed_origins or not self.allowed_origins:
                raise ConfigError("AUTOPRINT_V4_ALLOWED_ORIGINS must list explicit origins in production")
        return self


def _origins(raw: str) -> tuple[str, ...]:
    return tuple(o.strip() for o in raw.split(",") if o.strip())


def load_settings(env: dict | None = None) -> Settings:
    e = os.environ if env is None else env
    url = e.get("AUTOPRINT_V4_DATABASE_URL", "")
    if not url:
        raise ConfigError("AUTOPRINT_V4_DATABASE_URL is required")
    return Settings(
        database_url=url,
        storage_backend=e.get("AUTOPRINT_V4_STORAGE_BACKEND", "local"),
        local_storage_dir=e.get("AUTOPRINT_V4_LOCAL_STORAGE_DIR", ".localstorage"),
        public_base_url=e.get("AUTOPRINT_V4_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        signing_key=e.get("AUTOPRINT_V4_SIGNING_KEY", ""),
        supabase_url=e.get("AUTOPRINT_V4_SUPABASE_URL", ""),
        supabase_secret_key=e.get("AUTOPRINT_V4_SUPABASE_SECRET_KEY", ""),
        supabase_publishable_key=e.get("AUTOPRINT_V4_SUPABASE_PUBLISHABLE_KEY", ""),
        web_base_url=e.get("AUTOPRINT_V4_WEB_BASE_URL", "https://autoprint-v4.vercel.app").rstrip("/"),
        storage_bucket=e.get("AUTOPRINT_V4_STORAGE_BUCKET", "print-documents"),
        maintenance_token=e.get("AUTOPRINT_V4_MAINTENANCE_TOKEN", ""),
        background_maintenance=e.get("AUTOPRINT_V4_BACKGROUND_MAINTENANCE", "true").strip().lower() in {"1", "true", "yes"},
        environment=e.get("AUTOPRINT_V4_ENVIRONMENT", "development"),
        allowed_origins=_origins(e.get("AUTOPRINT_V4_ALLOWED_ORIGINS", "")),
    ).validate()
