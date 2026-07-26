"""Typed settings — every env var validated at import, fail-fast on boot (§5).

Values come from the process environment, then the repo-root .env (written by
scripts/sync_env.py AFTER supabase/harden.py has rotated the stack secrets —
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
        # ONE env file for the whole backend + engine: the repo-root .env.
        # In containers the process env (set by docker-entrypoint.sh) wins over
        # this file, so the same file serves host and container.
        env_file=(PROJECT_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- environment ---------------------------------------------------------
    env: str = Field("dev", alias="APP_ENV")           # dev | staging | prod
    log_level: str = "info"

    # -- data plane -----------------------------------------------------------
    supabase_mode: str = "local"                       # local (self-hosted stack) | cloud
                                                       # cloud => docker-entrypoint.sh leaves the
                                                       # data-plane URLs alone and require_boot_secrets
                                                       # rejects local hosts/placeholders
    supabase_url: str = "http://localhost:8000"        # Kong (self-hosted) / project URL (cloud)
    supabase_service_role_key: str = ""                # SERVER ONLY (storage/admin)
    supabase_db_url: str = ""                          # privileged role for engine.saas
    database_url_api: str = ""                         # API request pool
    database_url_worker: str = ""                      # worker/scheduler (session)
    supabase_jwt_secret: str = ""                      # HS256 verify (rotated by harden.py)
    supabase_jwt_issuer: str = ""                      # exact iss match, e.g. http://localhost:8000/auth/v1
                                                       # (empty = check skipped with a warning - dev only)
    supabase_jwks_url: str = ""                        # override; default derives from supabase_url

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

    @property
    def jwks_url(self) -> str:
        """Public keys for asymmetric (ES256) session tokens. Supabase Cloud
        signs user sessions with a project keypair; the legacy HS256 secret
        still covers anon/service_role keys and self-hosted GoTrue."""
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if not self.supabase_url:
            return ""
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

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
        if self.supabase_mode.lower() == "cloud":
            # A half-edited .env is the dangerous case: the app would come up
            # pointing at the local stack (or at nothing) while every operator
            # believes it is on Cloud. Fail at boot, not at first request.
            blob = f"{self.supabase_url} {self.supabase_db_url} {self.database_url_api} " \
                   f"{self.database_url_worker} {self.supabase_jwt_issuer}"
            if "__PROJECT_REF__" in blob or "__PASTE_" in blob:
                raise RuntimeError(
                    "SUPABASE_MODE=cloud but .env still contains placeholders - "
                    "fill in the project ref, DB password, service_role key and "
                    "JWT secret from the Supabase dashboard")
            for local_marker in ("127.0.0.1", "localhost", "supabase-db", "supabase-kong"):
                if local_marker in blob:
                    raise RuntimeError(
                        f"SUPABASE_MODE=cloud but a data-plane URL still points at "
                        f"'{local_marker}' - refusing to boot against the self-hosted "
                        f"stack while claiming to be on Cloud")


settings = Settings()
