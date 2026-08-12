"""GET /v1/plans — the PUBLIC pricing + entitlements document.

The marketing page and the billing page render exclusively from this payload:
prices come from plan_pricing / pack_pricing (backend-owned; what is published
is what the dev checkout charges and what Stripe is configured to match),
entitlements from plan_entitlements, base run prices from credit_costs, and
the metered rates from effort_rates. No frontend hardcoding.

effort_rates is what the engine actually bills against (0012), so it MUST be
published here: the ground rule since 0008 is that the published price list is
the enforced one. Enforcing a rate we do not publish would break that.
token_rates is still emitted for one release — pre-0012 clients read it.

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
    effort = await db.fetch_all(
        "select tier, unit, credits from public.effort_rates order by tier, unit")

    cost_by_tier: dict[str, dict[str, int]] = {}
    for row in costs:
        cost_by_tier.setdefault(row["tier"], {})[row["asset_kind"]] = row["credits"]

    effort_by_tier: dict[str, dict[str, float]] = {}
    for row in effort:
        effort_by_tier.setdefault(row["tier"], {})[row["unit"]] = float(row["credits"])

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
            # Base price of a run — now a FLOOR, not the whole price. Metered
            # effort is charged above it at effort_rates.
            "credit_costs": cost_by_tier.get(t["tier"], {}),
            "effort_rates": effort_by_tier.get(t["tier"], {}),
        } for t in tiers],
        "packs": [dict(p) for p in packs],
        "effort_rates": [{"tier": r["tier"], "unit": r["unit"],
                          "credits": float(r["credits"])} for r in effort],
        # DEPRECATED (0012): superseded by effort_rates (units llm_input_1k /
        # llm_output_1k). Kept one release so pre-0012 clients keep rendering.
        "token_rates": [{**dict(r),
                         "in_per_1k": float(r["in_per_1k"]),
                         "out_per_1k": float(r["out_per_1k"])} for r in rates],
    }
