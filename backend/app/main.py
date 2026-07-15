"""FastAPI application factory — middleware in the §6.1 order, error model,
routes, lifespan (fail-fast settings check, DB pool, Redis probe).

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager

if sys.platform == "win32":   # host-dev only; async psycopg needs a selector loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, redis_client
from .config import settings
from .errors import install_error_handlers
from .logging_setup import setup_logging
from .middleware.body_limit import BodyLimitMiddleware
from .middleware.ratelimit_ip import IpRateLimitMiddleware
from .middleware.request_id import RequestIdMiddleware
from .middleware.security_headers import SecurityHeadersMiddleware
from .routes import (admin, api_keys, billing, credits, findings, health,
                     orgs, runs, submissions)

logger = structlog.get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.require_boot_secrets()
    await db.open_pool()
    if not await redis_client.ping():
        logger.warning("boot.redis_unreachable - continuing degraded (sec-9.4)")
    logger.info("boot.ready", env=settings.env, port=settings.api_port)
    yield
    await db.close_pool()
    await redis_client.close()


def create_app() -> FastAPI:
    setup_logging(settings.log_level, sentry_dsn=settings.sentry_dsn,
                  component="api")
    app = FastAPI(
        title="AdCoherent Labs API",
        version="1.0.0",
        description=(
            "US fintech ad-compliance testing. Credit-metered, tier-rate-limited. "
            "Reports are decision support, not legal advice."),
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/v1/openapi.json",
    )

    # Starlette middleware is LIFO: added last = outermost. §6.1 order,
    # outermost first: request_id → security headers → body cap → CORS →
    # ip rate limit → (auth/org/limits as route dependencies) → handlers.
    app.add_middleware(IpRateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,       # exact origins, no wildcard
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key",
                       "X-Org-Id", "Idempotency-Key"],
        expose_headers=["X-Request-Id", "X-RateLimit-Limit",
                        "X-RateLimit-Remaining", "X-RateLimit-Reset",
                        "Retry-After"],
    )
    app.add_middleware(BodyLimitMiddleware,
                       max_bytes=settings.max_body_mb * 1024 * 1024)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(orgs.router)
    app.include_router(credits.router)
    app.include_router(submissions.router)
    app.include_router(runs.router)
    app.include_router(findings.router)
    app.include_router(api_keys.router)
    app.include_router(billing.router)
    app.include_router(admin.router)
    return app


app = create_app()
