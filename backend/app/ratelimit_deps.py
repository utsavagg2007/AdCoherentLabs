"""Rate-limit dependencies for authenticated routes (§9.2, middleware slot #7).

Browser JWT → user:{sub} at plan_entitlements.user_rpm.
API key     → org:{id}:api at api_rpm/api_burst AND key:{prefix} at the
              optional per-key cap (≤ org cap, set at issuance).
Submissions additionally hit org:{id}:submit (fixed daily window).
"""

from __future__ import annotations

from fastapi import Depends, Response

from .deps import AuthContext, auth_context, billing_ok, confirmed_reviewer
from .errors import ApiError
from .services import ratelimit


async def _standard(ctx: AuthContext, response: Response) -> AuthContext:
    if ctx.principal == "api_key":
        rpm = ctx.entitlements.get("api_rpm")
        if not rpm:
            raise ApiError(403, "forbidden",
                           f"The '{ctx.tier}' plan does not include API access.")
        burst = ctx.entitlements.get("api_burst") or rpm
        await ratelimit.enforce(f"org:{ctx.org_id}:api", rpm, response,
                                burst=burst, audience="api_key")
        if ctx.api_key_rpm:
            key_rpm = min(ctx.api_key_rpm, rpm)
            await ratelimit.enforce(f"key:{ctx.api_key_id}", key_rpm, response,
                                    audience="api_key")
    else:
        rpm = ctx.entitlements.get("user_rpm") or 60
        await ratelimit.enforce(f"user:{ctx.user_id}", rpm, response,
                                audience="browser")
    return ctx


async def rate_limited(response: Response,
                       ctx: AuthContext = Depends(auth_context)) -> AuthContext:
    """auth + org context + standard buckets — the default /v1 dependency."""
    return await _standard(ctx, response)


async def rate_limited_reviewer(response: Response,
                                ctx: AuthContext = Depends(confirmed_reviewer),
                                ) -> AuthContext:
    return await _standard(ctx, response)


async def submit_gate(response: Response,
                      ctx: AuthContext = Depends(billing_ok)) -> AuthContext:
    """POST /v1/submissions: reviewer+ role, confirmed email, billing OK,
    standard buckets, plus the per-plan daily submission wall."""
    ctx.require_role("reviewer")
    if ctx.principal == "user" and not ctx.email_confirmed:
        raise ApiError(403, "forbidden", "Confirm your email before running analyses.")
    ctx.require_scope("submit")
    await _standard(ctx, response)
    await ratelimit.enforce_daily(
        f"org:{ctx.org_id}:submit", ctx.entitlements.get("submissions_per_day"),
        response)
    return ctx
