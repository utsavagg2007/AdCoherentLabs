"""Rate limiting & abuse control — §9.

Layer 2 of the three walls (credits = cost wall, THIS = abuse wall,
concurrency caps = fairness wall). Atomic Lua token bucket in Redis, shared
across api replicas; per §9.4 an unreachable Redis degrades to an in-process
bucket at 50% limits for browser sessions (degraded-open) and rejects
programmatic API-key traffic (degraded-closed, the strictest audience).

Buckets (§9.2): ip:{addr} · user:{sub} · org:{id}:api · key:{prefix} ·
org:{id}:submit (fixed daily window). Responses carry X-RateLimit-* headers;
429s include Retry-After. Sustained 429 abuse (>10/min) earns a 15-minute
Redis ban and an audit event.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

import structlog
from fastapi import Response

from .. import redis_client
from ..config import settings
from ..errors import ApiError

logger = structlog.get_logger("app.ratelimit")

_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil or ts == nil then tokens = capacity; ts = now_ms end
local elapsed = math.max(0, now_ms - ts) / 1000.0
tokens = math.min(capacity, tokens + elapsed * refill_per_sec)
local allowed = 0
if tokens >= cost then tokens = tokens - cost; allowed = 1 end
redis.call('HSET', key, 'tokens', tokens, 'ts', now_ms)
redis.call('EXPIRE', key, math.max(60, math.ceil(capacity / refill_per_sec) * 2))
local retry = 0
if allowed == 0 then retry = math.ceil((cost - tokens) / refill_per_sec) end
return {allowed, math.floor(tokens), retry}
"""

_BAN_TTL = 900          # 15 min (§9.2)
_ABUSE_WINDOW = 60
_ABUSE_THRESHOLD = 10   # >10 429s/min sustained → temp ban


@dataclass
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    degraded: bool = False

    def apply_headers(self, response: Response) -> None:
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(self.remaining, 0))
        response.headers["X-RateLimit-Reset"] = str(self.retry_after)


class _FallbackLimiter:
    """In-process token bucket at 50% of configured limits (§9.4)."""

    def __init__(self):
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, capacity: int, refill_per_sec: float) -> Decision:
        cap = max(1.0, capacity * 0.5)
        refill = max(refill_per_sec * 0.5, 1 / 3600)
        now = time.monotonic()
        with self._lock:
            tokens, ts = self._buckets.get(key, (cap, now))
            tokens = min(cap, tokens + (now - ts) * refill)
            allowed = tokens >= 1
            if allowed:
                tokens -= 1
            self._buckets[key] = (tokens, now)
            if len(self._buckets) > 50_000:      # bound memory under attack
                self._buckets.clear()
        retry = 0 if allowed else math.ceil((1 - tokens) / refill)
        return Decision(allowed, int(cap), int(tokens), retry, degraded=True)


_fallback = _FallbackLimiter()
_script_sha: str | None = None


async def _redis_bucket(key: str, capacity: int, refill_per_sec: float) -> Decision | None:
    """None → Redis unavailable (caller picks the degraded mode)."""
    global _script_sha
    if redis_client.recently_failed():
        return None
    r = redis_client.client()
    try:
        if _script_sha is None:
            _script_sha = await r.script_load(_TOKEN_BUCKET_LUA)
        now_ms = int(time.time() * 1000)
        allowed, remaining, retry = await r.evalsha(
            _script_sha, 1, key, capacity, refill_per_sec, now_ms, 1)
        redis_client.mark_success()
        return Decision(bool(allowed), capacity, int(remaining), int(retry))
    except Exception as exc:
        if "NOSCRIPT" in str(exc):
            _script_sha = None
        redis_client.mark_failure()
        return None


async def check_bucket(key: str, rpm: int, *, burst: int | None = None,
                       audience: str = "browser") -> Decision:
    """One request against bucket `key`. audience: 'browser' | 'api_key' —
    picks the §9.4 degraded mode when Redis is down."""
    capacity = burst or rpm
    refill = rpm / 60.0
    decision = await _redis_bucket(f"rl:{key}", capacity, refill)
    if decision is None:
        if audience == "api_key" or settings.rate_limit_fail_mode == "closed":
            raise ApiError(
                503, "rate_limiter_unavailable",
                "Rate limiting is temporarily unavailable for API traffic.",
                headers={"Retry-After": "30"})
        return _fallback.check(key, capacity, refill)
    return decision


async def is_banned(key: str) -> int:
    """Seconds remaining on a temp ban, 0 if none."""
    if redis_client.recently_failed():
        return 0
    try:
        ttl = await redis_client.client().ttl(f"rlban:{key}")
        return max(int(ttl), 0)
    except Exception:
        redis_client.mark_failure()
        return 0


async def record_429(key: str) -> None:
    """Track sustained 429 abuse; ban at threshold + audit."""
    from .. import metrics
    metrics.RATE_LIMIT_HITS.labels(bucket_kind=key.split(":", 1)[0]).inc()
    if redis_client.recently_failed():
        return
    try:
        r = redis_client.client()
        k = f"rl429:{key}"
        n = await r.incr(k)
        if n == 1:
            await r.expire(k, _ABUSE_WINDOW)
        if n > _ABUSE_THRESHOLD:
            await r.set(f"rlban:{key}", 1, ex=_BAN_TTL, nx=True)
            logger.warning("ratelimit.ban", key=key, count=n, ttl=_BAN_TTL)
            from .. import db
            await db.execute(
                "select app.log_audit_event(null, null, 'ratelimit.banned', %s, %s)",
                (key, '{"ttl_seconds": 900}'))
    except Exception:
        redis_client.mark_failure()


async def enforce(key: str, rpm: int, response: Response, *,
                  burst: int | None = None, audience: str = "browser") -> None:
    """check_bucket + ban list + headers + 429 with Retry-After."""
    ban = await is_banned(key)
    if ban:
        raise ApiError(429, "rate_limited",
                       "Temporarily banned for sustained rate-limit abuse.",
                       headers={"Retry-After": str(ban)})
    decision = await check_bucket(key, rpm, burst=burst, audience=audience)
    decision.apply_headers(response)
    if not decision.allowed:
        await record_429(key)
        raise ApiError(429, "rate_limited", "Rate limit exceeded.",
                       {"limit": decision.limit},
                       headers={"Retry-After": str(max(decision.retry_after, 1))})


async def enforce_daily(key: str, per_day: int | None, response: Response) -> None:
    """org:{id}:submit — fixed UTC-day window (§9.2). None = unlimited
    (credits govern). Fails open when Redis is down: the Postgres credit
    gate still hard-stops spend."""
    if per_day is None:
        return
    if redis_client.recently_failed():
        return
    try:
        r = redis_client.client()
        day = time.strftime("%Y%m%d", time.gmtime())
        k = f"rlday:{key}:{day}"
        n = await r.incr(k)
        if n == 1:
            await r.expire(k, 86_400)
        response.headers["X-RateLimit-Daily-Limit"] = str(per_day)
        response.headers["X-RateLimit-Daily-Remaining"] = str(max(per_day - n, 0))
        if n > per_day:
            await record_429(key)
            raise ApiError(429, "rate_limited",
                           "Daily submission limit reached for this plan.",
                           {"per_day": per_day}, headers={"Retry-After": "3600"})
    except ApiError:
        raise
    except Exception:
        redis_client.mark_failure()
