"""Simulated checkout for environments where Stripe is not configured.

Active ONLY when STRIPE_SECRET_KEY is empty AND APP_ENV != prod: the same
routes that would redirect to Stripe Checkout instead apply the purchase
directly (subscription upsert + cycle grant, or pack grant) and send the
browser straight to the success URL. Every write is audited with
simulated=true so a later Stripe cutover can distinguish the two eras.
Prices shown to the user come from plan_pricing / pack_pricing — the same
tables GET /v1/plans publishes.
"""

from __future__ import annotations

import json
import uuid

import structlog

from .. import db
from ..config import settings
from ..deps import invalidate_org_caches
from ..errors import ApiError

logger = structlog.get_logger("app.dev_billing")


def enabled() -> bool:
    return not settings.stripe_secret_key and not settings.is_prod


def _frontend_origin() -> str:
    origins = settings.cors_origins
    return origins[0] if origins else "http://localhost:3000"


async def simulate_subscription_checkout(org_id: str, user_id: str | None,
                                         tier: str) -> str:
    if tier == "enterprise":
        raise ApiError(409, "conflict",
                       "Enterprise is contract-provisioned - contact sales.")
    price = await db.fetch_one(
        "select monthly_usd_cents from public.plan_pricing where tier = %s",
        (tier,))
    if price is None or price["monthly_usd_cents"] is None:
        raise ApiError(503, "billing_unavailable",
                       f"No published price for tier '{tier}'.")
    async with db.transaction() as conn:
        await conn.execute(
            "insert into public.subscriptions "
            "  (org_id, stripe_subscription_id, tier, status, "
            "   current_period_start, current_period_end) "
            "values (%s, %s, %s, 'active', now(), now() + interval '1 month') "
            "on conflict (org_id) do update set "
            "  stripe_subscription_id = excluded.stripe_subscription_id, "
            "  tier = excluded.tier, status = 'active', "
            "  current_period_start = now(), "
            "  current_period_end = now() + interval '1 month', "
            "  grace_until = null, updated_at = now()",
            (org_id, f"sim-{uuid.uuid4()}", tier))
        await conn.execute(
            "select app.log_audit_event(%s, %s, 'billing.subscription_synced', "
            "        null, %s::jsonb)",
            (org_id, user_id, json.dumps(
                {"tier": tier, "status": "active", "simulated": True,
                 "usd_cents": price["monthly_usd_cents"]})))
        await conn.execute("select app.ensure_cycle_grant(%s)", (org_id,))
    await invalidate_org_caches(org_id)
    logger.info("dev_billing.subscription_activated", org_id=org_id, tier=tier)
    return f"{_frontend_origin()}/billing?status=success&simulated=1"


async def simulate_pack_checkout(org_id: str, user_id: str | None,
                                 pack: str) -> str:
    row = await db.fetch_one(
        "select credits, usd_cents from public.pack_pricing where pack = %s",
        (pack,))
    if row is None:
        raise ApiError(503, "billing_unavailable",
                       f"No published price for pack '{pack}'.")
    ref = f"sim-pack-{uuid.uuid4()}"
    await db.execute("select app.grant_purchased_credits(%s, %s, %s)",
                     (org_id, row["credits"], ref))
    await db.execute(
        "select app.log_audit_event(%s, %s, 'credits.pack_granted', null, %s::jsonb)",
        (org_id, user_id, json.dumps(
            {"pack": pack, "credits": row["credits"], "simulated": True,
             "usd_cents": row["usd_cents"], "ref": ref})))
    logger.info("dev_billing.pack_granted", org_id=org_id, pack=pack,
                credits=row["credits"])
    return f"{_frontend_origin()}/billing?status=pack_success&simulated=1"


async def require_active_subscription(org_id: str) -> None:
    """Credits can only be purchased on an ACTIVE (or trialing) plan."""
    row = await db.fetch_one(
        "select status, tier from public.subscriptions where org_id = %s",
        (org_id,))
    if row is None or row["status"] not in ("active", "trialing"):
        raise ApiError(403, "forbidden",
                       "Credit packs require an active subscription.",
                       {"subscription_status": row["status"] if row else "none"})
