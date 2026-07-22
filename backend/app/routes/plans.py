"""GET /v1/plans — the PUBLIC pricing + entitlements document.

The marketing page and the billing page render exclusively from this payload:
prices come from plan_pricing / pack_pricing (backend-owned; what is published
is what the dev checkout charges and what Stripe is configured to match),
entitlements from plan_entitlements, run prices from credit_costs, and the
token-settlement rates from token_rates. No frontend hardcoding.

Unauthenticated by design (it is a pricing page); the IP rate-limit
middleware still fronts it.
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import db

router = APIRouter(prefix="/v1/plans", tags=["plans"])

_NAMES = {"free": "Free", "hobby": "Hobby", "pro": "Pro",
          "design": "Design", "enterprise": "Enterprise"}


@router.get("")
async def list_plans():
    tiers = await db.fetch_all(
        "select p.tier, p.monthly_usd_cents, p.display_order, p.tagline, "
        "       e.credits_per_month, e.max_upload_mb, e.seats, e.api_access, "
        "       e.credit_packs_allowed, e.allowed_kinds, e.max_video_seconds, "
        "       e.max_concurrent_runs, e.submissions_per_day "
        "from public.plan_pricing p "
        "join public.plan_entitlements e on e.tier = p.tier "
        "where p.is_public order by p.display_order")
    packs = await db.fetch_all(
        "select pack, credits, usd_cents from public.pack_pricing "
        "where is_public order by usd_cents")
    costs = await db.fetch_all(
        "select asset_kind, tier, credits from public.credit_costs")
    rates = await db.fetch_all(
        "select tier, in_per_1k, out_per_1k, min_credits from public.token_rates")

    cost_by_tier: dict[str, dict[str, int]] = {}
    for row in costs:
        cost_by_tier.setdefault(row["tier"], {})[row["asset_kind"]] = row["credits"]

    return {
        "plans": [{
            "tier": t["tier"],
            "name": _NAMES.get(t["tier"], t["tier"].title()),
            "tagline": t["tagline"],
            "monthly_usd_cents": t["monthly_usd_cents"],   # null = contact sales
            "credits_per_month": t["credits_per_month"],   # null = custom
            "max_upload_mb": t["max_upload_mb"],
            "seats": t["seats"],
            "api_access": t["api_access"],
            "credit_packs_allowed": t["credit_packs_allowed"],
            "allowed_kinds": t["allowed_kinds"],
            "max_video_seconds": t["max_video_seconds"],
            "max_concurrent_runs": t["max_concurrent_runs"],
            "submissions_per_day": t["submissions_per_day"],
            "credit_costs": cost_by_tier.get(t["tier"], {}),
        } for t in tiers],
        "packs": [dict(p) for p in packs],
        "token_rates": [{**dict(r),
                         "in_per_1k": float(r["in_per_1k"]),
                         "out_per_1k": float(r["out_per_1k"])} for r in rates],
    }
