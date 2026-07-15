"""Stripe integration (§12). The webhook is the ONLY billing writer; every
event lands in app.billing_events first (insert-or-skip) so replays no-op.
Entitlements always resolve from the DB afterwards — a subscription row change
takes effect on the very next run with no code moves.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import structlog

from .. import db, metrics
from ..config import settings
from ..deps import invalidate_org_caches
from ..errors import ApiError

logger = structlog.get_logger("app.stripe")

PACKS = {"starter": 500, "growth": 2_500, "scale": 12_000}


def _stripe():
    if not settings.stripe_secret_key:
        raise ApiError(503, "billing_unavailable", "Billing is not configured.")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


def _price_for_tier(tier: str) -> str:
    price = {"hobby": settings.stripe_price_hobby,
             "pro": settings.stripe_price_pro,
             "design": settings.stripe_price_design,
             "enterprise": settings.stripe_price_enterprise}.get(tier, "")
    if not price:
        raise ApiError(503, "billing_unavailable",
                       f"No Stripe price configured for tier '{tier}'.")
    return price


def _tier_for_price(price_id: str) -> str | None:
    return {settings.stripe_price_hobby: "hobby",
            settings.stripe_price_pro: "pro",
            settings.stripe_price_design: "design",
            settings.stripe_price_enterprise: "enterprise"}.get(price_id)


def _price_for_pack(pack: str) -> str:
    price = {"starter": settings.stripe_price_pack_starter,
             "growth": settings.stripe_price_pack_growth,
             "scale": settings.stripe_price_pack_scale}.get(pack, "")
    if not price:
        raise ApiError(503, "billing_unavailable",
                       f"No Stripe price configured for pack '{pack}'.")
    return price


def _frontend_origin() -> str:
    origins = settings.cors_origins
    return origins[0] if origins else "http://localhost:3000"


async def _customer_for_org(org_id: str) -> str:
    row = await db.fetch_one(
        "select stripe_customer_id from public.subscriptions where org_id = %s",
        (org_id,))
    if row and row["stripe_customer_id"]:
        return row["stripe_customer_id"]
    org = await db.fetch_one("select name from public.orgs where id = %s", (org_id,))
    stripe = _stripe()
    customer = stripe.Customer.create(
        name=(org or {}).get("name") or org_id, metadata={"org_id": org_id})
    await db.execute(
        "insert into public.subscriptions (org_id, stripe_customer_id) "
        "values (%s, %s) "
        "on conflict (org_id) do update set stripe_customer_id = excluded.stripe_customer_id",
        (org_id, customer.id))
    return customer.id


async def create_subscription_checkout(org_id: str, tier: str, interval: str) -> str:
    stripe = _stripe()
    customer = await _customer_for_org(org_id)
    session = stripe.checkout.Session.create(
        mode="subscription", customer=customer,
        line_items=[{"price": _price_for_tier(tier), "quantity": 1}],
        subscription_data={"metadata": {"org_id": org_id, "tier": tier}},
        metadata={"org_id": org_id, "kind": "subscription", "tier": tier},
        success_url=f"{_frontend_origin()}/billing?status=success",
        cancel_url=f"{_frontend_origin()}/billing?status=cancelled")
    return session.url


async def create_pack_checkout(org_id: str, pack: str) -> str:
    stripe = _stripe()
    customer = await _customer_for_org(org_id)
    session = stripe.checkout.Session.create(
        mode="payment", customer=customer,
        line_items=[{"price": _price_for_pack(pack), "quantity": 1}],
        metadata={"org_id": org_id, "kind": "credit_pack",
                  "credits": str(PACKS[pack]), "pack": pack},
        success_url=f"{_frontend_origin()}/billing?status=pack_success",
        cancel_url=f"{_frontend_origin()}/billing?status=cancelled")
    return session.url


async def create_portal_link(org_id: str) -> str:
    stripe = _stripe()
    customer = await _customer_for_org(org_id)
    session = stripe.billing_portal.Session.create(
        customer=customer, return_url=f"{_frontend_origin()}/billing")
    return session.url


# ---------------------------------------------------------------------------
# Webhook contract (§12.2)

async def handle_webhook(payload: bytes, signature: str) -> dict:
    if not settings.stripe_webhook_secret:
        raise ApiError(503, "billing_unavailable", "Webhook secret not configured.")
    import stripe

    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret)
    except Exception:
        raise ApiError(400, "validation_error", "Invalid Stripe signature.")

    # 1. insert-or-skip; a processed replay is a no-op.
    existing = await db.fetch_one(
        "select processed_at from app.billing_events where id = %s", (event["id"],))
    if existing and existing["processed_at"] is not None:
        metrics.WEBHOOK_EVENTS.labels(type=event["type"], outcome="replay").inc()
        return {"received": True, "replay": True}
    await db.execute(
        "insert into app.billing_events (id, type, payload) "
        "values (%s, %s, %s::jsonb) on conflict (id) do nothing",
        (event["id"], event["type"], json.dumps(event["data"]["object"])))

    # 2. handle by type; 3. mark processed (errors leave processed_at null →
    # Stripe retries; alerting on stale unprocessed rows is the scheduler's).
    try:
        await _dispatch(event)
    except Exception as exc:
        await db.execute(
            "update app.billing_events set error = %s where id = %s",
            (str(exc)[:1000], event["id"]))
        metrics.WEBHOOK_EVENTS.labels(type=event["type"], outcome="error").inc()
        logger.exception("stripe.webhook_failed", event_id=event["id"],
                         event_type=event["type"])
        raise ApiError(500, "internal", "Webhook processing failed.")
    await db.execute(
        "update app.billing_events set processed_at = now(), error = null "
        "where id = %s", (event["id"],))
    metrics.WEBHOOK_EVENTS.labels(type=event["type"], outcome="processed").inc()
    return {"received": True}


async def _dispatch(event: dict) -> None:
    etype = event["type"]
    obj = event["data"]["object"]
    if etype in ("customer.subscription.created", "customer.subscription.updated",
                 "customer.subscription.deleted"):
        await _sync_subscription(obj, deleted=etype.endswith("deleted"))
    elif etype == "checkout.session.completed":
        if (obj.get("metadata") or {}).get("kind") == "credit_pack":
            await _grant_pack(obj)
    elif etype in ("invoice.payment_failed", "invoice.marked_uncollectible"):
        await _payment_failed(obj)
    elif etype in ("invoice.paid", "invoice.payment_succeeded"):
        await _payment_recovered(obj)
    else:
        logger.info("stripe.ignored", event_type=etype)


async def _org_for(obj: dict) -> str | None:
    org_id = (obj.get("metadata") or {}).get("org_id")
    if org_id:
        return org_id
    customer = obj.get("customer")
    if customer:
        row = await db.fetch_one(
            "select org_id::text from public.subscriptions "
            "where stripe_customer_id = %s", (customer,))
        if row:
            return row["org_id"]
    return None


async def _sync_subscription(sub: dict, *, deleted: bool) -> None:
    org_id = await _org_for(sub)
    if org_id is None:
        logger.error("stripe.orphan_subscription", subscription=sub.get("id"))
        return
    items = (sub.get("items") or {}).get("data") or []
    price_id = items[0]["price"]["id"] if items else ""
    tier = ((sub.get("metadata") or {}).get("tier")
            or _tier_for_price(price_id) or "free")
    status = "canceled" if deleted else str(sub.get("status") or "active")
    if status not in ("trialing", "active", "past_due", "canceled",
                      "incomplete", "unpaid"):
        status = "active"
    ps, pe = sub.get("current_period_start"), sub.get("current_period_end")
    async with db.transaction() as conn:
        await conn.execute(
            "insert into public.subscriptions "
            "  (org_id, stripe_customer_id, stripe_subscription_id, tier, status, "
            "   current_period_start, current_period_end, grace_until) "
            "values (%s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s), "
            "        case when %s = 'past_due' then now() + make_interval(days => %s) end) "
            "on conflict (org_id) do update set "
            "  stripe_customer_id = excluded.stripe_customer_id, "
            "  stripe_subscription_id = excluded.stripe_subscription_id, "
            "  tier = excluded.tier, status = excluded.status, "
            "  current_period_start = excluded.current_period_start, "
            "  current_period_end = excluded.current_period_end, "
            "  grace_until = case when excluded.status = 'past_due' "
            "                     then coalesce(public.subscriptions.grace_until, "
            "                                   now() + make_interval(days => %s)) "
            "                     else null end, "
            "  updated_at = now()",
            (org_id, sub.get("customer"), sub.get("id"), tier, status,
             ps, pe, status, settings.billing_grace_days,
             settings.billing_grace_days))
        await conn.execute(
            "select app.log_audit_event(%s, null, 'billing.subscription_synced', %s, %s::jsonb)",
            (org_id, f"subscription:{sub.get('id')}",
             json.dumps({"tier": tier, "status": status, "deleted": deleted})))
        # tier change / new period → idempotent allowance grant (§8.2)
        await conn.execute("select app.ensure_cycle_grant(%s)", (org_id,))
    await invalidate_org_caches(org_id)


async def _grant_pack(session: dict) -> None:
    org_id = (session.get("metadata") or {}).get("org_id")
    credits_n = int((session.get("metadata") or {}).get("credits") or 0)
    if not org_id or credits_n <= 0:
        logger.error("stripe.bad_pack_session", session=session.get("id"))
        return
    await db.execute("select app.grant_purchased_credits(%s, %s, %s)",
                     (org_id, credits_n, session.get("id")))


async def _payment_failed(invoice: dict) -> None:
    org_id = await _org_for(invoice)
    if org_id is None:
        return
    async with db.transaction() as conn:
        await conn.execute(
            "update public.subscriptions set status = 'past_due', "
            "  grace_until = coalesce(grace_until, now() + make_interval(days => %s)), "
            "  updated_at = now() where org_id = %s",
            (settings.billing_grace_days, org_id))
        await conn.execute(
            "select app.log_audit_event(%s, null, 'billing.payment_failed', %s, %s::jsonb)",
            (org_id, f"invoice:{invoice.get('id')}",
             json.dumps({"grace_days": settings.billing_grace_days})))
    await invalidate_org_caches(org_id)


async def _payment_recovered(invoice: dict) -> None:
    org_id = await _org_for(invoice)
    if org_id is None:
        return
    await db.execute(
        "update public.subscriptions set grace_until = null, updated_at = now() "
        "where org_id = %s and status = 'past_due'", (org_id,))
    await invalidate_org_caches(org_id)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def reconcile_sweep() -> dict:
    """Daily scheduler job: diff active Stripe subscriptions against the
    subscriptions table (webhooks are at-least-once, not forever) and alert
    on drift rather than silently writing (§12.2)."""
    if not settings.stripe_secret_key:
        return {"skipped": "stripe not configured"}
    stripe = _stripe()
    drift = []
    for sub in stripe.Subscription.list(status="all", limit=100).auto_paging_iter():
        org_id = (sub.get("metadata") or {}).get("org_id")
        if not org_id:
            continue
        row = await db.fetch_one(
            "select tier, status, extract(epoch from current_period_start)::bigint as ps "
            "from public.subscriptions where org_id = %s", (org_id,))
        items = (sub.get("items") or {}).get("data") or []
        price_id = items[0]["price"]["id"] if items else ""
        expected_tier = ((sub.get("metadata") or {}).get("tier")
                         or _tier_for_price(price_id))
        if row is None or row["status"] != sub.get("status") \
                or (expected_tier and row["tier"] != expected_tier) \
                or (row["ps"] or 0) != (sub.get("current_period_start") or 0):
            drift.append({"org_id": org_id, "stripe": sub.get("id"),
                          "db": dict(row) if row else None,
                          "stripe_status": sub.get("status")})
            await _sync_subscription(dict(sub), deleted=sub.get("status") == "canceled")
    if drift:
        logger.warning("stripe.reconcile_drift", count=len(drift), drift=drift[:10])
    return {"drift": len(drift), "cutoff": _utcnow().isoformat()}
