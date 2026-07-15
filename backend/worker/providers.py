"""Per-provider work throttles (§9.3, §10.3): Redis counting semaphores cap
parallel in-flight engine runs per LLM provider, and a circuit breaker keeps
jobs queued (users see 'queued', never a provider error) while a provider is
down. Redis being down degrades OPEN for these — the credit wall (Postgres)
does not depend on any of this.
"""

from __future__ import annotations

import structlog
import redis as redis_sync

from app.config import settings

logger = structlog.get_logger("worker.providers")

_BREAKER_THRESHOLD = 5     # consecutive failures → open
_BREAKER_OPEN_SECONDS = 60  # half-open probe cadence
_SEM_TTL = 3600

_client: redis_sync.Redis | None = None


def _redis() -> redis_sync.Redis | None:
    global _client
    if _client is None:
        try:
            _client = redis_sync.from_url(
                settings.redis_url, decode_responses=True,
                socket_connect_timeout=1, socket_timeout=1)
            _client.ping()
        except Exception:
            _client = None
    return _client


def max_parallel(provider: str) -> int:
    return {"anthropic": settings.provider_max_parallel_anthropic,
            "openrouter": settings.provider_max_parallel_openrouter,
            }.get(provider, 4)


def breaker_is_open(provider: str) -> bool:
    r = _redis()
    if r is None:
        return False
    try:
        return bool(r.exists(f"cb:{provider}:open"))
    except Exception:
        return False


def record_failure(provider: str) -> None:
    r = _redis()
    if r is None:
        return
    try:
        n = r.incr(f"cb:{provider}:failures")
        r.expire(f"cb:{provider}:failures", 300)
        if n >= _BREAKER_THRESHOLD:
            r.set(f"cb:{provider}:open", 1, ex=_BREAKER_OPEN_SECONDS)
            logger.warning("breaker.open", provider=provider, failures=n)
    except Exception:
        pass


def record_success(provider: str) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.delete(f"cb:{provider}:failures", f"cb:{provider}:open")
    except Exception:
        pass


_ACQUIRE_LUA = """
local n = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
if n > tonumber(ARGV[1]) then
  redis.call('DECR', KEYS[1])
  return 0
end
return 1
"""

_RELEASE_LUA = """
local n = redis.call('DECR', KEYS[1])
if n < 0 then redis.call('SET', KEYS[1], 0, 'EX', tonumber(ARGV[1])) end
return 1
"""


def acquire_slot(provider: str) -> bool:
    r = _redis()
    if r is None:
        return True  # degraded-open; provider 429s still hit tenacity/backoff
    try:
        ok = r.eval(_ACQUIRE_LUA, 1, f"sem:{provider}",
                    max_parallel(provider), _SEM_TTL)
        return bool(ok)
    except Exception:
        return True


def release_slot(provider: str) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.eval(_RELEASE_LUA, 1, f"sem:{provider}", _SEM_TTL)
    except Exception:
        pass
