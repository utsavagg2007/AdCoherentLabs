"""Rate-limit behaviour (§9): bucket exhaustion + Retry-After, headers on
authenticated routes, ban list, and the §9.4 Redis-down degraded modes."""

from __future__ import annotations

import uuid

import pytest
from fastapi import Response

from app.errors import ApiError
from app.services import ratelimit

from .conftest import auth, mint_jwt

pytestmark = [pytest.mark.needs_db, pytest.mark.needs_redis]


@pytest.fixture(autouse=True)
async def _require_redis(dbpool):
    from app import redis_client
    if not await redis_client.ping():
        pytest.skip("Redis unreachable")
    yield


async def test_bucket_exhaustion_and_retry_after():
    key = f"unit:{uuid.uuid4().hex[:8]}"
    resp = Response()
    for _ in range(3):
        await ratelimit.enforce(key, rpm=3, response=resp)   # capacity 3
    with pytest.raises(ApiError) as exc:
        await ratelimit.enforce(key, rpm=3, response=resp)
    assert exc.value.status == 429
    assert int(exc.value.headers["Retry-After"]) >= 1
    assert resp.headers["X-RateLimit-Limit"] == "3"


async def test_burst_over_rpm():
    key = f"unit:{uuid.uuid4().hex[:8]}"
    resp = Response()
    for _ in range(5):                                        # burst 5 > rpm 2
        await ratelimit.enforce(key, rpm=2, burst=5, response=resp)
    with pytest.raises(ApiError):
        await ratelimit.enforce(key, rpm=2, burst=5, response=resp)


async def test_sustained_abuse_earns_ban():
    key = f"unit:{uuid.uuid4().hex[:8]}"
    for _ in range(12):                                       # >10/min threshold
        await ratelimit.record_429(key)
    assert await ratelimit.is_banned(key) > 0
    with pytest.raises(ApiError) as exc:
        await ratelimit.enforce(key, rpm=1000, response=Response())
    assert "banned" in exc.value.message


async def test_redis_down_degrades_open_for_browser_closed_for_api(monkeypatch):
    from app import redis_client
    monkeypatch.setattr(redis_client, "recently_failed", lambda: True)
    d = await ratelimit.check_bucket(f"u:{uuid.uuid4().hex[:6]}", 10,
                                     audience="browser")
    assert d.degraded and d.allowed          # in-process fallback at 50%
    with pytest.raises(ApiError) as exc:     # strictest audience: fail closed
        await ratelimit.check_bucket(f"k:{uuid.uuid4().hex[:6]}", 10,
                                     audience="api_key")
    assert exc.value.status == 503


async def test_fallback_still_limits():
    limiter = ratelimit._FallbackLimiter()
    key = f"fb:{uuid.uuid4().hex[:6]}"
    allowed = sum(limiter.check(key, capacity=10, refill_per_sec=0.001).allowed
                  for _ in range(10))
    assert allowed == 5                      # 50% of configured capacity


async def test_headers_on_authenticated_route(client, tenant):
    tok = mint_jwt(tenant["users"]["owner"], f"owner-{tenant['tag']}@bt.local")
    r = await client.get("/v1/credits", headers=auth(tok, tenant["org"]))
    assert r.status_code == 200
    assert r.headers["X-RateLimit-Limit"] == "60"            # free user_rpm
    assert int(r.headers["X-RateLimit-Remaining"]) < 60


async def test_daily_submission_wall(client, tenant, monkeypatch):
    """free = 5 submissions/day (§9.2). Burn the window with cheap denials by
    pre-loading the day counter, then expect 429 with Retry-After."""
    from app import redis_client
    import time
    day = time.strftime("%Y%m%d", time.gmtime())
    key = f"rlday:org:{tenant['org']}:submit:{day}"
    await redis_client.client().set(key, 5, ex=3600)
    tok = mint_jwt(tenant["users"]["reviewer"], f"reviewer-{tenant['tag']}@bt.local")
    r = await client.post("/v1/submissions",
                          json={"kind": "text", "content": "hi"},
                          headers=auth(tok, tenant["org"]))
    assert r.status_code == 429
    assert r.headers.get("Retry-After")
