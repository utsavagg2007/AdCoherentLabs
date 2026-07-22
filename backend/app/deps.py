"""AuthContext — the one dependency every /v1 route hangs off (§6.1 #5–6).

Resolution order per request:
  1. Authenticate: Supabase JWT (local HS256) OR X-API-Key (sha256 lookup).
  2. Org context: memberships lookup (Redis-cached 60 s); a requested org id
     only SELECTS among the caller's own memberships — membership is always
     re-verified in the DB (client-supplied org_id is never authority).
  3. Tier + entitlements from plan_entitlements via app.org_tier (cached 60 s,
     invalidated by the Stripe webhook on tier change).

Email-confirmed and role gates raise before any handler business logic runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog
from fastapi import Depends, Request

from . import db, redis_client
from .auth.api_keys import verify as verify_api_key
from .auth.jwt import verify_supabase_jwt
from .config import settings
from .errors import ApiError

logger = structlog.get_logger("app.auth")

ROLE_RANK = {"viewer": 0, "reviewer": 1, "admin": 2, "owner": 3}
_CACHE_TTL = 60


@dataclass
class AuthContext:
    principal: str                      # "user" | "api_key"
    org_id: str
    role: str
    tier: str
    entitlements: dict[str, Any]
    user_id: str | None = None
    email: str | None = None
    email_confirmed: bool = False
    aal: str = "aal1"                   # GoTrue assurance level from the JWT
    mfa_verified: bool = False          # user has a verified TOTP factor
    api_key_id: str | None = None
    api_key_scopes: list[str] = field(default_factory=list)
    api_key_rpm: int | None = None
    memberships: list[dict] = field(default_factory=list)

    def require_role(self, minimum: str) -> None:
        if ROLE_RANK.get(self.role, -1) < ROLE_RANK[minimum]:
            raise ApiError(403, "forbidden",
                           f"This action requires the '{minimum}' role or higher.")

    def require_entitlement(self, flag: str) -> None:
        if not self.entitlements.get(flag):
            raise ApiError(403, "forbidden",
                           f"The '{self.tier}' plan does not include '{flag}'.")

    def require_scope(self, scope: str) -> None:
        if self.principal == "api_key" and scope not in self.api_key_scopes:
            raise ApiError(403, "forbidden", f"API key lacks the '{scope}' scope.")

    def require_step_up(self) -> None:
        """Privileged actions (API keys, membership, billing, admin credit
        ops) require an MFA-challenged session (aal2) from users who have a
        verified factor enrolled. Users without MFA pass (optional-MFA
        policy — see AUTH_AUDIT_AND_PLAN.md §13); API keys are
        pre-authorized machine credentials and are exempt."""
        if self.principal == "user" and self.mfa_verified and self.aal != "aal2":
            raise ApiError(403, "step_up_required",
                           "This action requires a recent MFA challenge - "
                           "re-authenticate with your second factor.",
                           {"aal": self.aal})

    @property
    def is_staff(self) -> bool:
        return bool(self.email) and self.email.lower() in settings.admin_email_set


# ---------------------------------------------------------------------------
# Cached lookups (Redis 60 s; DB is always the source of truth on a miss).

async def _cached(key: str, loader, ttl: int = _CACHE_TTL):
    r = None
    if not redis_client.recently_failed():
        try:
            r = redis_client.client()
            hit = await r.get(key)
            if hit is not None:
                redis_client.mark_success()
                return json.loads(hit)
        except Exception:
            redis_client.mark_failure()
            r = None
    value = await loader()
    if r is not None:
        try:
            await r.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception:
            redis_client.mark_failure()
    return value


async def _user_context(user_id: str) -> dict:
    async def load():
        # EMAIL confirmation only: phone_confirmed_at is excluded on purpose
        # (GoTrue phone autoconfirm would otherwise mint zero-verification
        # accounts — AUTH_AUDIT_AND_PLAN.md W2).
        user = await db.fetch_one(
            "select id::text, email, "
            "  email_confirmed_at is not null as confirmed, "
            "  exists (select 1 from auth.mfa_factors f "
            "          where f.user_id = auth.users.id "
            "            and f.status = 'verified') as mfa_verified "
            "from auth.users where id = %s", (user_id,))
        if user is None:
            raise ApiError(401, "unauthenticated", "Unknown user.")
        memberships = await db.fetch_all(
            "select org_id::text, role from public.memberships "
            "where user_id = %s order by created_at", (user_id,))
        return {"email": user["email"], "confirmed": user["confirmed"],
                "mfa_verified": bool(user["mfa_verified"]),
                "memberships": memberships}
    return await _cached(f"authn:{user_id}", load)


async def get_entitlements(org_id: str) -> dict:
    async def load():
        row = await db.fetch_one(
            "select e.*, app.org_tier(%(org)s) as resolved_tier, "
            "       s.status as sub_status, s.grace_until "
            "from public.plan_entitlements e "
            "left join public.subscriptions s on s.org_id = %(org)s "
            "where e.tier = app.org_tier(%(org)s)", {"org": org_id})
        if row is None:
            raise ApiError(500, "internal", "Org resolves to an unknown tier.")
        row.pop("updated_at", None)
        return dict(row)
    return await _cached(f"ent:{org_id}", load)


async def invalidate_org_caches(org_id: str) -> None:
    """Called by the Stripe webhook on tier change (§9.2)."""
    try:
        await redis_client.client().delete(f"ent:{org_id}")
    except Exception:
        redis_client.mark_failure()


async def invalidate_user_cache(user_id: str) -> None:
    """Membership set changed (org created / member added) — drop the 60 s
    authn cache so the next request sees it immediately."""
    try:
        await redis_client.client().delete(f"authn:{user_id}")
    except Exception:
        redis_client.mark_failure()


# ---------------------------------------------------------------------------
# The dependency.

async def auth_context(request: Request) -> AuthContext:
    api_key = request.headers.get("X-API-Key")
    authz = request.headers.get("Authorization", "")
    requested_org = request.headers.get("X-Org-Id") or request.query_params.get("org")

    if api_key:
        row = await verify_api_key(api_key)
        ent = await get_entitlements(row["org_id"])
        scopes = list(row["scopes"] or [])
        role = "admin" if "admin" in scopes else ("reviewer" if "submit" in scopes else "viewer")
        if requested_org and requested_org != row["org_id"]:
            raise ApiError(404, "not_found", "The requested resource does not exist.")
        return AuthContext(
            principal="api_key", org_id=row["org_id"], role=role,
            tier=ent["resolved_tier"], entitlements=ent,
            api_key_id=row["key_id"], api_key_scopes=scopes,
            api_key_rpm=row["rate_limit_rpm"])

    if authz.lower().startswith("bearer "):
        claims = verify_supabase_jwt(authz[7:].strip(),
                                     settings.supabase_jwt_secret,
                                     settings.supabase_jwt_issuer)
        ctx_data = await _user_context(claims.user_id)
        memberships = ctx_data["memberships"]
        if not memberships:
            raise ApiError(403, "forbidden",
                           "No org membership - create an org first (POST /v1/orgs).")
        if requested_org:
            match = next((m for m in memberships if m["org_id"] == requested_org), None)
            if match is None:
                # Never reveal whether the org exists (§11).
                raise ApiError(404, "not_found", "The requested resource does not exist.")
        elif len(memberships) == 1:
            match = memberships[0]
        else:
            raise ApiError(400, "validation_error",
                           "You belong to several orgs - pass X-Org-Id.",
                           {"org_ids": [m["org_id"] for m in memberships]})
        ent = await get_entitlements(match["org_id"])
        return AuthContext(
            principal="user", org_id=match["org_id"], role=match["role"],
            tier=ent["resolved_tier"], entitlements=ent,
            user_id=claims.user_id, email=ctx_data["email"],
            email_confirmed=bool(ctx_data["confirmed"]),
            aal=claims.aal,
            mfa_verified=bool(ctx_data.get("mfa_verified")),
            memberships=memberships)

    raise ApiError(401, "unauthenticated",
                   "Provide a Bearer token or X-API-Key.")


async def user_only_context(request: Request) -> AuthContext:
    """A verified user session WITHOUT the org-membership requirement —
    exclusively for first-org creation (POST /v1/orgs), where demanding a
    membership would be circular. Email must be confirmed; org-scoped
    fields are deliberately blank and must not be read by the route."""
    authz = request.headers.get("Authorization", "")
    if not authz.lower().startswith("bearer "):
        raise ApiError(401, "unauthenticated", "Provide a Bearer token.")
    claims = verify_supabase_jwt(authz[7:].strip(),
                                 settings.supabase_jwt_secret,
                                 settings.supabase_jwt_issuer)
    ctx_data = await _user_context(claims.user_id)
    if not ctx_data["confirmed"]:
        raise ApiError(403, "forbidden",
                       "Confirm your email before creating an organization.")
    return AuthContext(
        principal="user", org_id="", role="owner", tier="free",
        entitlements={}, user_id=claims.user_id, email=ctx_data["email"],
        email_confirmed=True, aal=claims.aal,
        mfa_verified=bool(ctx_data.get("mfa_verified")),
        memberships=ctx_data["memberships"])


async def confirmed_reviewer(ctx: AuthContext = Depends(auth_context)) -> AuthContext:
    """Role floor for analysis routes: reviewer+ with a confirmed email
    (API keys inherit the org's standing; scope checked at the route)."""
    ctx.require_role("reviewer")
    if ctx.principal == "user" and not ctx.email_confirmed:
        raise ApiError(403, "forbidden",
                       "Confirm your email before running analyses.")
    return ctx


async def billing_ok(ctx: AuthContext = Depends(auth_context)) -> AuthContext:
    """§12.2 grace policy: past_due beyond grace_until blocks submissions
    (403 billing_hold); data is never deleted for this."""
    status = ctx.entitlements.get("sub_status")
    grace = ctx.entitlements.get("grace_until")
    if status == "past_due" and grace is not None:
        from datetime import datetime, timezone
        g = grace if isinstance(grace, datetime) else datetime.fromisoformat(str(grace))
        if g.tzinfo is None:
            g = g.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > g:
            raise ApiError(403, "billing_hold",
                           "Payment is past due - resolve billing to submit again.",
                           {"grace_expired": True})
    return ctx
