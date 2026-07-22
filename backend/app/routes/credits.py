"""GET /v1/credits (balance + published price list) · /v1/credits/ledger ·
POST /v1/credits/checkout (Stripe pack purchase, packs entitlement)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import AuthContext
from ..errors import ApiError
from ..ratelimit_deps import rate_limited
from ..schemas import PackCheckout
from ..services import credits, dev_billing, stripe_sync

router = APIRouter(prefix="/v1/credits", tags=["credits"])


@router.get("")
async def get_credits(ctx: AuthContext = Depends(rate_limited)):
    ctx.require_scope("read")
    return await credits.balance(ctx.org_id)


@router.get("/ledger")
async def get_ledger(ctx: AuthContext = Depends(rate_limited),
                     before_id: int | None = None, limit: int = 50):
    ctx.require_scope("read")
    rows = await credits.ledger_page(ctx.org_id, before_id, limit)
    return {"ledger": rows,
            "next_before_id": rows[-1]["id"] if rows else None}


@router.post("/checkout")
async def pack_checkout(body: PackCheckout,
                        ctx: AuthContext = Depends(rate_limited)):
    ctx.require_role("admin")
    if not ctx.entitlements.get("credit_packs_allowed"):
        raise ApiError(403, "forbidden",
                       f"The '{ctx.tier}' plan cannot purchase credit packs.",
                       {"packs": "paid tiers only"})
    # Packs also require the subscription itself to be in good standing.
    await dev_billing.require_active_subscription(ctx.org_id)
    if dev_billing.enabled():      # Stripe unconfigured + non-prod: simulate
        url = await dev_billing.simulate_pack_checkout(
            ctx.org_id, ctx.user_id, body.pack)
        return {"checkout_url": url, "simulated": True}
    url = await stripe_sync.create_pack_checkout(ctx.org_id, body.pack)
    return {"checkout_url": url}
