"""structlog JSON to stdout (§15.1) + optional Sentry. One call per process."""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(level: str = "info", *, sentry_dsn: str = "",
                  component: str = "api", release: str | None = None) -> None:
    logging.basicConfig(stream=sys.stdout, level=level.upper(), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(component=component)

    if sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=sentry_dsn, release=release,
                            traces_sample_rate=0.05, send_default_pii=False)
        except ImportError:
            structlog.get_logger("app").warning(
                "SENTRY_DSN set but sentry-sdk not installed - continuing without")
