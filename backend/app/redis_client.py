"""Shared async Redis client with a health latch.

Redis is rate-limit/cache/semaphore ONLY (D3/D8): the credit gate lives in
Postgres, so nothing spend-related ever depends on Redis being up. When it is
down, callers see is_healthy() False and follow §9.4's degraded modes.
"""

from __future__ import annotations

import time

import redis.asyncio as aioredis
import structlog

from .config import settings

logger = structlog.get_logger("app.redis")

_client: aioredis.Redis | None = None
_last_failure: float = 0.0
_RETRY_SECONDS = 5.0


def client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True,
            socket_connect_timeout=1.0, socket_timeout=1.0,
        )
    return _client


def mark_failure() -> None:
    global _last_failure
    if not _last_failure:
        logger.warning("redis.down - rate limiting degraded per sec-9.4")
    _last_failure = time.monotonic()


def mark_success() -> None:
    global _last_failure
    if _last_failure:
        logger.info("redis.recovered")
    _last_failure = 0.0


def recently_failed() -> bool:
    """True while inside the retry back-off window after a failure."""
    return bool(_last_failure) and (time.monotonic() - _last_failure) < _RETRY_SECONDS


async def ping() -> bool:
    try:
        ok = await client().ping()
        mark_success()
        return bool(ok)
    except Exception:
        mark_failure()
        return False


async def close() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:   # shutdown must never fail on a dead connection
            pass
        _client = None
