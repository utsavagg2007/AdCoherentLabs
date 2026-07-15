"""Stripe webhook contract (§12.2): signature verified, billing_events
insert-or-skip, replay no-op, tier change grants exactly once, pack purchase
credits exactly once, payment failure starts the grace clock."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest

from app.config import settings
from app.services import stripe_sync

from .conftest import q_all, q_one

pytestmark = pytest.mark.needs_db

WHSEC = "whsec_test_" + "0" * 24


def _signed(event: dict) -> tuple[bytes, str]:
    payload = json.dumps(event).encode()
    t = int(time.time())
    sig = hmac.new(WHSEC.encode(), f"{t}.".encode() + payload,
                   hashlib.sha256).hexdigest()
    return payload, f"t={t},v1={sig}"


def _sub_event(org: str, tier: str, event_id: str, period_start: int) -> dict:
    return {
        "id": event_id, "object": "event", "api_version": "2024-06-20",
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": f"sub_{org[:8]}", "object": "subscription",
            "customer": f"cus_{org[:8]}", "status": "active",
            "metadata": {"org_id": org, "tier": tier},
            "current_period_start": period_start,
            "current_period_end": period_start + 30 * 86400,
            "items": {"data": [{"price": {"id": "price_test_pro"}}]},
        }},
    }


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", WHSEC)


async def test_bad_signature_rejected(dbpool):
    payload, _ = _signed({"id": "evt_x", "type": "noop", "data": {"object": {}}})
    from app.errors import ApiError
    with pytest.raises(ApiError) as exc:
        await stripe_sync.handle_webhook(payload, "t=1,v1=deadbeef")
    assert exc.value.status == 400


async def test_subscription_event_flips_tier_and_grants_once(dbpool, tenant):
    org = tenant["org"]
    evt = f"evt_{uuid.uuid4().hex[:12]}"
    period = int(time.time())
    payload, sig = _signed(_sub_event(org, "pro", evt, period))

    out = await stripe_sync.handle_webhook(payload, sig)
    assert out == {"received": True}
    row = q_one("select tier, status from public.subscriptions where org_id = %s",
                (org,))
    assert row == {"tier": "pro", "status": "active"}
    grants = q_all("select stripe_ref from public.credit_ledger "
                   "where org_id = %s and reason = 'grant.cycle'", (org,))
    assert len(grants) == 1                                  # pro allowance granted
    bal = q_one("select subscription_credits from public.credit_balances "
                "where org_id = %s", (org,))
    assert bal["subscription_credits"] == 6000               # pro credits/mo

    # replay: same event id → no-op, no double grant
    out2 = await stripe_sync.handle_webhook(payload, sig)
    assert out2.get("replay") is True
    assert len(q_all("select 1 from public.credit_ledger "
                     "where org_id = %s and reason = 'grant.cycle'", (org,))) == 1
    assert q_one("select processed_at from app.billing_events where id = %s",
                 (evt,))["processed_at"] is not None


async def test_pack_purchase_credits_exactly_once(dbpool, tenant):
    org = tenant["org"]
    q_one("update public.subscriptions set tier = 'pro' where org_id = %s "
          "returning org_id", (org,))
    session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
    event = {
        "id": f"evt_{uuid.uuid4().hex[:12]}", "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"id": session_id, "object": "checkout.session",
                            "customer": "cus_x",
                            "metadata": {"org_id": org, "kind": "credit_pack",
                                         "credits": "2500", "pack": "growth"}}},
    }
    payload, sig = _signed(event)
    await stripe_sync.handle_webhook(payload, sig)
    # a RETRY arrives as a NEW event id but the same checkout session
    event["id"] = f"evt_{uuid.uuid4().hex[:12]}"
    payload2, sig2 = _signed(event)
    await stripe_sync.handle_webhook(payload2, sig2)
    bal = q_one("select purchased_credits from public.credit_balances "
                "where org_id = %s", (org,))
    assert bal["purchased_credits"] == 2500                  # once, not twice


async def test_payment_failed_starts_grace_clock(dbpool, tenant):
    org = tenant["org"]
    event = {
        "id": f"evt_{uuid.uuid4().hex[:12]}", "object": "event",
        "type": "invoice.payment_failed",
        "data": {"object": {"id": "in_x", "object": "invoice",
                            "customer": "cus_x",
                            "metadata": {"org_id": org}}},
    }
    payload, sig = _signed(event)
    await stripe_sync.handle_webhook(payload, sig)
    row = q_one("select status, grace_until from public.subscriptions "
                "where org_id = %s", (org,))
    assert row["status"] == "past_due" and row["grace_until"] is not None
