"""Typed settings — every env var validated at import, fail-fast on boot (§5).

Values come from the process environment, then backend/.env (written by
scripts/gen_env.py AFTER supabase/harden.py has rotated the stack secrets —
spec P0). Secrets never ship defaults; local-stack conveniences do.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- environment ---------------------------------------------------------
    env: str = Field("dev", alias="APP_ENV")           # dev | staging | prod
    log_level: str = "info"

    # -- data plane -----------------------------------------------------------
    supabase_url: str = "http://localhost:8000"        # Kong
    supabase_service_role_key: str = ""                # SERVER ONLY (storage/admin)
    supabase_db_url: str = ""                          # privileged role for engine.saas
    database_url_api: str = ""                         # API request pool
    database_url_worker: str = ""                      # worker/scheduler (session)
    supabase_jwt_secret: str = ""                      # HS256 verify (rotated by harden.py)
    supabase_jwt_issuer: str = ""                      # exact iss match, e.g. http://localhost:8000/auth/v1
                                                       # (empty = check skipped with a warning - dev only)

    # -- app -------------------------------------------------------------------
    api_port: int = 8080
    cors_allowed_origins: str = "http://localhost:3000"
    redis_url: str = "redis://localhost:6379/0"
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_required: bool = True                       # fail-closed on uploads when clamd is down
    rate_limit_fail_mode: str = "degraded"             # §9.4
    max_body_mb: int = 60                              # edge cap; tier caps from plan_entitlements
    admin_emails: str = ""                             # /v1/admin staff allowlist (comma-separated)
    docs_enabled: bool = True

    # -- workers ---------------------------------------------------------------
    worker_id_prefix: str = "wk"
    lease_seconds: int = 300
    heartbeat_seconds: int = 30
    run_max_seconds: int = 1800                        # stop extending the lease past this
    worker_poll_seconds: float = 2.0
    provider_max_parallel_anthropic: int = 4
    provider_max_parallel_openrouter: int = 8
    stop_grace_seconds: int = 120
    retention_dry_run: bool = True                     # P9 gate: dry-run first

    # -- billing ----------------------------------------------------------------
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_hobby: str = ""
    stripe_price_pro: str = ""
    stripe_price_design: str = ""
    stripe_price_enterprise: str = ""
    stripe_price_pack_starter: str = ""
    stripe_price_pack_growth: str = ""
    stripe_price_pack_scale: str = ""
    billing_grace_days: int = 7

    # -- ops ---------------------------------------------------------------------
    sentry_dsn: str = ""
    metrics_basic_auth: str = ""                       # "user:pass"; empty = internal only

    @field_validator("rate_limit_fail_mode")
    @classmethod
    def _fail_mode(cls, v: str) -> str:
        if v not in ("degraded", "closed"):
            raise ValueError("RATE_LIMIT_FAIL_MODE must be degraded|closed")
        return v

    # -- derived ------------------------------------------------------------------
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    def db_url_api(self) -> str:
        return self.database_url_api or self.supabase_db_url or self._local_default()

    def db_url_worker(self) -> str:
        return self.database_url_worker or self.supabase_db_url or self._local_default()

    @staticmethod
    def _local_default() -> str:
        raise RuntimeError(
            "no database URL configured: set DATABASE_URL_API / DATABASE_URL_WORKER "
            "/ SUPABASE_DB_URL (run backend/scripts/gen_env.py after supabase/harden.py)")

    def require_boot_secrets(self) -> None:
        """Called by the app factory: refuse to boot without the security-
        critical values (fail fast, not at first request)."""
        missing = [name for name, val in (
            ("SUPABASE_JWT_SECRET", self.supabase_jwt_secret),
            ("SUPABASE_DB_URL or DATABASE_URL_API", self.database_url_api or self.supabase_db_url),
        ) if not val]
        if missing:
            raise RuntimeError(f"refusing to boot without: {', '.join(missing)}")
        if self.is_prod and "your-super-secret" in (self.supabase_jwt_secret + self.supabase_db_url):
            raise RuntimeError(
                "refusing to boot in prod with the PUBLIC DEFAULT Supabase secrets - "
                "run python supabase/harden.py first (spec P0)")


settings = Settings()
