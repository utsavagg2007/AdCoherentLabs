"""Subscription checkout + Billing Portal (owner/admin) and the Stripe
webhook — the only billing writer, signature-verified, idempotent (§12)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..deps import AuthContext
from ..errors import ApiError
from ..ratelimit_deps import rate_limited
from ..schemas import SubscriptionCheckout
from ..services import dev_billing, stripe_sync

router = APIRouter(tags=["billing"])


@router.post("/v1/billing/checkout")
async def subscription_checkout(body: SubscriptionCheckout,
                                ctx: AuthContext = Depends(rate_limited)):
    ctx.require_role("admin")
    if ctx.principal != "user":
        raise ApiError(403, "forbidden", "Billing requires a user session.")
    ctx.require_step_up()          # billing change (audit spec)
    if dev_billing.enabled():      # Stripe unconfigured + non-prod: simulate
        url = await dev_billing.simulate_subscription_checkout(
            ctx.org_id, ctx.user_id, body.tier)
        return {"checkout_url": url, "simulated": True}
    url = await stripe_sync.create_subscription_checkout(
        ctx.org_id, body.tier, body.interval)
    return {"checkout_url": url}


@router.post("/v1/billing/portal")
async def billing_portal(ctx: AuthContext = Depends(rate_limited)):
    ctx.require_role("admin")
    if ctx.principal != "user":
        raise ApiError(403, "forbidden", "Billing requires a user session.")
    ctx.require_step_up()
    return {"portal_url": await stripe_sync.create_portal_link(ctx.org_id)}


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request):
    payload = await request.body()                       # raw body preserved
    signature = request.headers.get("Stripe-Signature", "")
    return await stripe_sync.handle_webhook(payload, signature)
