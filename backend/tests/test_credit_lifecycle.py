"""Credit lifecycle unit tests (§16): cost matrix, bucket order, cycle grant
idempotency, expire-on-rollover, refund guards, pack idempotency."""

from __future__ import annotations

import uuid

import pytest

from .conftest import q_all, q_one, set_tier

pytestmark = pytest.mark.needs_db


def _mk_run(org: str, user: str) -> str:
    sub = q_one(
        "insert into public.submissions (org_id, created_by, title) "
        "values (%s, %s, 'unit') returning id::text", (org, user))["id"]
    return q_one(
        "insert into public.analysis_runs (submission_id, org_id, status) "
        "values (%s, %s, 'queued') returning id::text", (sub, org))["id"]


def test_cost_matrix_appendix_b(tenant):
    org = tenant["org"]
    expected = {
        "free":       {"text": 1, "image": 2, "html": 2, ("carousel", 3): 4},
        "hobby":      {"text": 2, "image": 4, "html": 4, ("carousel", 3): 8},
        "pro":        {"text": 5, "image": 10, "html": 10, ("carousel", 3): 20},
        "design":     {"text": 10, "image": 20, "html": 20, ("carousel", 3): 40},
        "enterprise": {"text": 10, "image": 20, "html": 20, ("carousel", 3): 40},
    }
    for tier, prices in expected.items():
        set_tier(org, tier)
        for kind, price in prices.items():
            k, cards = kind if isinstance(kind, tuple) else (kind, 1)
            got = q_one("select app.credit_cost(%s, %s, %s) as c",
                        (org, k, cards))["c"]
            assert got == price, f"{tier}/{k}x{cards}: {got} != {price}"
    # cards cap at 10: an 11-card carousel prices like a 10-card one
    set_tier(org, "free")
    assert q_one("select app.credit_cost(%s, 'carousel', 11) as c",
                 (org,))["c"] == \
           q_one("select app.credit_cost(%s, 'carousel', 10) as c", (org,))["c"]


def test_bucket_order_allowance_then_packs(tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    # 50 sub (fixture) + 30 purchased
    q_one("select app.grant_purchased_credits(%s, 30, %s) as g",
          (org, f"pack-{tenant['tag']}"))
    run = _mk_run(org, owner)
    d = q_one("select app.consume_credits(%s, %s, 60) as d", (org, run))["d"]
    assert d["allowed"] and d["sub_bal"] == 0 and d["pack_bal"] == 20
    rows = q_all("select bucket, delta from public.credit_ledger "
                 "where run_id = %s order by bucket", (run,))
    assert [(r["bucket"], r["delta"]) for r in rows] == [
        ("purchased", -10), ("subscription", -50)]


def test_cycle_grant_idempotent_and_expires(tenant):
    org = tenant["org"]
    g1 = q_one("select app.grant_cycle_credits(%s, 'unit-cycle-1') as g", (org,))["g"]
    assert g1["granted"] and g1["allowance"] == 25          # free tier
    again = q_one("select app.grant_cycle_credits(%s, 'unit-cycle-1') as g", (org,))["g"]
    assert not again["granted"] and again["reason"] == "already_granted"
    bal = q_one("select subscription_credits from public.credit_balances "
                "where org_id = %s", (org,))
    assert bal["subscription_credits"] == 25                # 50 expired, 25 granted
    expired = q_one(
        "select delta from public.credit_ledger where org_id = %s "
        "and reason = 'expire.cycle' and stripe_ref = 'unit-cycle-1'", (org,))
    assert expired["delta"] == -50                          # no rollover
    # next cycle key expires the current allowance again
    g2 = q_one("select app.grant_cycle_credits(%s, 'unit-cycle-2') as g", (org,))["g"]
    assert g2["granted"]
    assert q_one("select subscription_credits from public.credit_balances "
                 "where org_id = %s", (org,))["subscription_credits"] == 25


def test_enterprise_null_allowance_never_auto_grants(tenant):
    org = tenant["org"]
    set_tier(org, "enterprise")
    g = q_one("select app.ensure_cycle_grant(%s) as g", (org,))["g"]
    assert not g["granted"] and g["reason"] == "uncapped_tier"
    # balance untouched (contract-provisioned via grant.manual only)
    assert q_one("select subscription_credits from public.credit_balances "
                 "where org_id = %s", (org,))["subscription_credits"] == 50


def test_refund_is_system_failure_only_and_ledger_derived(tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    run = _mk_run(org, owner)
    q_one("select app.consume_credits(%s, %s, 7) as d", (org, run))
    with pytest.raises(Exception, match="system-failure"):
        q_one("select app.refund_credits(%s, %s, 7, 'adjust.manual')", (org, run))
    r = q_one("select app.refund_credits(%s, %s, 999) as r", (org, run))["r"]
    assert r["refunded"] == 7          # ledger-derived, caller's 999 ignored
    r2 = q_one("select app.refund_credits(%s, %s) as r", (org, run))["r"]
    assert r2["refunded"] == 0         # idempotent


def test_pack_grant_idempotent_by_ref(tenant):
    org = tenant["org"]
    ref = f"cs_{tenant['tag']}"
    g1 = q_one("select app.grant_purchased_credits(%s, 500, %s) as g", (org, ref))["g"]
    g2 = q_one("select app.grant_purchased_credits(%s, 500, %s) as g", (org, ref))["g"]
    assert g1["granted"] and not g2["granted"]
    assert q_one("select purchased_credits from public.credit_balances "
                 "where org_id = %s", (org,))["purchased_credits"] == 500


def test_rejection_mutates_nothing(tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    run = _mk_run(org, owner)
    d = q_one("select app.consume_credits(%s, %s, 10000) as d", (org, run))["d"]
    assert not d["allowed"] and d["needed"] == 10000 and d["balance"] == 50
    assert q_one("select count(*) as n from public.credit_ledger "
                 "where run_id = %s", (run,))["n"] == 0
    drift = q_all("select * from app.reconcile_credit_balances() "
                  "where org_id = %s", (org,))
    assert drift == []
