"""Metered credit tests (migration 0012): reserve → meter → settle.

The load-bearing test in this file is test_overspend_is_impossible. Everything
else supports it. Before 0012, app.settle_run_tokens clamped its charge to the
remaining balance and forgave the shortfall, so a free-tier org could burn
unbounded provider tokens and pay whatever it happened to hold. That hole is
closed by making the escrow a hard ceiling, and this suite is what keeps it
closed.
"""

from __future__ import annotations

import concurrent.futures as cf

import pytest

from .conftest import q_all, q_one, set_tier

pytestmark = pytest.mark.needs_db


def _mk_run(org: str, user: str, kind: str = "text") -> str:
    sub = q_one(
        "insert into public.submissions (org_id, created_by, title, params) "
        "values (%s, %s, 'metered', %s::jsonb) returning id::text",
        (org, user, '{"pricing_kind": "%s", "cards": 1}' % kind))["id"]
    return q_one(
        "insert into public.analysis_runs (submission_id, org_id, status, tier) "
        "values (%s, %s, 'queued', app.org_tier(%s)) returning id::text",
        (sub, org, org))["id"]


def _balance(org: str) -> int:
    row = q_one("select app.credit_balance(%s) as b", (org,))
    return row["b"]["total"]


def _set_rate(tier: str, unit: str, credits: float) -> None:
    q_one("insert into public.effort_rates (tier, unit, credits) "
          "values (%s, %s, %s) on conflict (tier, unit) "
          "do update set credits = excluded.credits returning tier",
          (tier, unit, credits))


# ---------------------------------------------------------------------------
# The invariant this migration exists for.

def test_overspend_is_impossible(tenant):
    """An org with almost nothing reserved cannot be billed for a runaway run.

    This is the regression test for the 0011 clamp. Meter 500 credits of
    effort against a 12-credit escrow and the charge must still be 12 — never
    500, and never more than the balance held at reserve time.
    """
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_output_1k", 1.0)      # 1 credit per 1k output tokens

    # Fund exactly 12 credits, nothing more.
    q_one("select app.adjust_credits_manual(%s, %s, 'subscription', null, 'test')",
          (org, 12 - _balance(org)))
    assert _balance(org) == 12

    run = _mk_run(org, user)
    res = q_one("select app.reserve_credits(%s, %s, 1, 11) as d", (org, run))["d"]
    assert res["allowed"] is True
    assert res["reserved"] == 12
    assert _balance(org) == 0            # fully escrowed

    # The engine goes berserk: 500k output tokens = 500 credits of effort.
    reading = q_one(
        "select app.meter_effort(%s, %s, 'llm_output_1k', 500, '{}'::jsonb) as m",
        (org, run))["m"]
    assert reading["exhausted"] is True
    assert float(reading["metered"]) == 500.0

    settle = q_one("select app.settle_hold(%s, %s) as s", (org, run))["s"]
    assert settle["settled"] is True
    assert settle["capped"] is True
    assert settle["charged"] == 12, "charge must never exceed the escrow"
    assert _balance(org) == 0
    assert _balance(org) >= 0, "a balance can never go negative"


def test_unused_reserve_is_returned(tenant):
    """The common case: reserve generously, use a little, get the rest back."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_output_1k", 1.0)
    start = _balance(org)

    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 2, 30) as d", (org, run))
    assert _balance(org) == start - 32

    q_one("select app.meter_effort(%s, %s, 'llm_output_1k', 3, '{}'::jsonb) as m",
          (org, run))
    settle = q_one("select app.settle_hold(%s, %s) as s", (org, run))["s"]

    assert settle["charged"] == 3            # max(floor 2, ceil(3.0))
    assert settle["returned"] == 29
    assert _balance(org) == start - 3


def test_floor_is_the_minimum_charge(tenant):
    """A run that meters nothing charges exactly the published base price.

    This is what makes shadow rollout a no-op: with effort_rates at 0, every
    run charges what it charged before 0012.
    """
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    start = _balance(org)

    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 5, 20) as d", (org, run))
    settle = q_one("select app.settle_hold(%s, %s) as s", (org, run))["s"]

    assert settle["charged"] == 5
    assert _balance(org) == start - 5


def test_zero_rates_reproduce_pre_0012_pricing(tenant):
    """With every rate zeroed — the documented rollback — the charge is the
    flat base price no matter how much effort the engine reports."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    for unit in ("llm_input_1k", "llm_output_1k", "llm_call", "ocr_page",
                 "cv_frame", "rag_query"):
        _set_rate("free", unit, 0)
    start = _balance(org)

    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 2, 10) as d", (org, run))
    for unit, qty in (("llm_input_1k", 900), ("llm_output_1k", 400),
                      ("ocr_page", 60), ("cv_frame", 300)):
        q_one("select app.meter_effort(%s, %s, %s, %s, '{}'::jsonb) as m",
              (org, run, unit, qty))
    settle = q_one("select app.settle_hold(%s, %s) as s", (org, run))["s"]

    assert settle["charged"] == 2
    assert _balance(org) == start - 2


# ---------------------------------------------------------------------------
# Idempotency and failure paths

def test_settle_is_idempotent(tenant):
    """Worker and watchdog can both fire; the run is charged once."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_output_1k", 1.0)
    start = _balance(org)

    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 1, 20) as d", (org, run))
    q_one("select app.meter_effort(%s, %s, 'llm_output_1k', 4, '{}'::jsonb) as m",
          (org, run))

    first = q_one("select app.settle_hold(%s, %s) as s", (org, run))["s"]
    second = q_one("select app.settle_hold(%s, %s) as s", (org, run))["s"]

    assert first["charged"] == 4
    assert second["settled"] is False
    assert second["reason"] == "already_settled"
    assert _balance(org) == start - 4


def test_release_refunds_the_whole_escrow(tenant):
    """DLQ path: our failure, so the user pays nothing even though the run
    burned real tokens before dying."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_output_1k", 1.0)
    start = _balance(org)

    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 2, 20) as d", (org, run))
    q_one("select app.meter_effort(%s, %s, 'llm_output_1k', 7, '{}'::jsonb) as m",
          (org, run))

    rel = q_one("select app.release_hold(%s, %s, 0) as r", (org, run))["r"]
    assert rel["released"] is True
    assert rel["refunded"] == 22
    assert _balance(org) == start

    # ...but the absorbed effort stays visible — that is the point.
    assert float(rel["metered"]) == 7.0


def test_retry_does_not_bill_the_dead_attempt(tenant):
    """A requeued run resets its meter: the user pays for one report, not for
    however many attempts it took us to produce it."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_output_1k", 1.0)
    start = _balance(org)

    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 1, 40) as d", (org, run))

    q_one("select app.meter_effort(%s, %s, 'llm_output_1k', 9, '{}'::jsonb) as m",
          (org, run))                                    # attempt 1 dies
    q_one("select app.reset_hold_meter(%s, %s) as r", (org, run))
    q_one("select app.meter_effort(%s, %s, 'llm_output_1k', 6, '{}'::jsonb) as m",
          (org, run))                                    # attempt 2 succeeds

    settle = q_one("select app.settle_hold(%s, %s) as s", (org, run))["s"]
    assert settle["charged"] == 6, "must not include the failed attempt"
    assert _balance(org) == start - 6

    # The absorbed attempt is still recorded, marked as ours.
    absorbed = q_all(
        "select credits from public.effort_events "
        "where run_id = %s and (meta->>'absorbed')::boolean is true", (run,))
    assert absorbed, "the failed attempt's effort must stay visible as our cost"


def test_reserve_rejects_when_short(tenant):
    """The 402 contract is unchanged: rejections mutate nothing."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    q_one("select app.adjust_credits_manual(%s, %s, 'subscription', null, 'test')",
          (org, 3 - _balance(org)))

    run = _mk_run(org, user)
    res = q_one("select app.reserve_credits(%s, %s, 5, 20) as d", (org, run))["d"]

    assert res["allowed"] is False
    assert res["needed"] == 25
    assert _balance(org) == 3, "a rejected reserve must not move money"
    assert not q_all("select 1 from public.credit_holds where run_id = %s", (run,))


# ---------------------------------------------------------------------------
# Concurrency

def test_parallel_reserves_cannot_overspend(tenant):
    """Ten concurrent submissions against a balance that funds three. The
    row lock in _lock_credit_balance decides; the balance never goes negative."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    q_one("select app.adjust_credits_manual(%s, %s, 'subscription', null, 'test')",
          (org, 30 - _balance(org)))

    runs = [_mk_run(org, user) for _ in range(10)]

    def reserve(run: str) -> bool:
        return q_one("select app.reserve_credits(%s, %s, 10, 0) as d",
                     (org, run))["d"]["allowed"]

    with cf.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(reserve, runs))

    assert sum(results) == 3, f"expected exactly 3 winners, got {sum(results)}"
    assert _balance(org) == 0


def test_metering_different_runs_does_not_serialise(tenant):
    """meter_effort must not take the org's balance lock — if it did, every
    concurrent run of one org would queue behind every other."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_output_1k", 0.1)
    q_one("select app.adjust_credits_manual(%s, %s, 'subscription', null, 'test')",
          (org, 500 - _balance(org)))

    runs = [_mk_run(org, user) for _ in range(6)]
    for r in runs:
        q_one("select app.reserve_credits(%s, %s, 1, 40) as d", (org, r))

    def meter_many(run: str) -> float:
        for _ in range(10):
            q_one("select app.meter_effort(%s, %s, 'llm_output_1k', 1, "
                  "'{}'::jsonb) as m", (org, run))
        return float(q_one("select metered from public.credit_holds "
                           "where run_id = %s", (run,))["metered"])

    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        totals = list(pool.map(meter_many, runs))

    # Each run accumulated its own 10 x 0.1 independently — no lost updates.
    assert all(abs(t - 1.0) < 1e-6 for t in totals), totals


# ---------------------------------------------------------------------------
# Ledger integrity

def test_ledger_reconciles_after_full_cycle(tenant):
    """app.reconcile_credit_balances must stay clean across reserve → meter →
    settle. This is what proves the two-entry (release + charge) ledger design
    is arithmetically sound rather than merely readable."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_output_1k", 1.0)

    for i in range(3):
        run = _mk_run(org, user)
        q_one("select app.reserve_credits(%s, %s, 2, 15) as d", (org, run))
        q_one("select app.meter_effort(%s, %s, 'llm_output_1k', %s, "
              "'{}'::jsonb) as m", (org, run, i + 1))
        q_one("select app.settle_hold(%s, %s) as s", (org, run))

    drift = q_all("select * from app.reconcile_credit_balances() "
                  "where org_id = %s", (org,))
    assert drift == [], f"ledger and balances disagree: {drift}"


def test_ledger_shows_reserve_release_and_charge(tenant):
    """An auditor reading one run's ledger sees what was held and what was
    actually taken — not just a net number."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_output_1k", 1.0)

    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 2, 18) as d", (org, run))
    q_one("select app.meter_effort(%s, %s, 'llm_output_1k', 6, '{}'::jsonb) as m",
          (org, run))
    q_one("select app.settle_hold(%s, %s) as s", (org, run))

    rows = q_all("select reason, delta from public.credit_ledger "
                 "where run_id = %s order by id", (run,))
    by_reason = {r["reason"]: r["delta"] for r in rows}

    assert by_reason["hold.reserve"] == -20
    assert by_reason["hold.release"] == 20
    assert by_reason["consume.metered"] == -6
    assert sum(r["delta"] for r in rows) == -6, "net movement is the charge"


def test_effort_events_itemise_the_charge(tenant):
    """A user billed by usage is owed the line items."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_input_1k", 0.5)
    _set_rate("free", "llm_output_1k", 2.0)

    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 1, 50) as d", (org, run))
    q_one("select app.meter_effort(%s, %s, 'llm_input_1k', 4, '{}'::jsonb) as m",
          (org, run))
    q_one("select app.meter_effort(%s, %s, 'llm_output_1k', 3, '{}'::jsonb) as m",
          (org, run))

    items = {r["unit"]: r for r in q_all(
        "select unit, quantity, rate, credits from public.effort_events "
        "where run_id = %s", (run,))}

    assert float(items["llm_input_1k"]["credits"]) == 2.0     # 4 x 0.5
    assert float(items["llm_output_1k"]["credits"]) == 6.0    # 3 x 2.0
    settle = q_one("select app.settle_hold(%s, %s) as s", (org, run))["s"]
    assert settle["charged"] == 8                             # 2 + 6


def test_meter_without_hold_is_free_not_fatal(tenant):
    """Pre-0012 runs still in flight during the deploy meter into the void
    rather than failing. Recorded as unbilled, charged nothing."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    _set_rate("free", "llm_output_1k", 1.0)
    start = _balance(org)

    run = _mk_run(org, user)          # no reserve — no hold exists
    reading = q_one(
        "select app.meter_effort(%s, %s, 'llm_output_1k', 25, '{}'::jsonb) as m",
        (org, run))["m"]

    assert reading["billed"] is False
    assert reading["exhausted"] is False, "must not stop an engine over a gap"
    assert _balance(org) == start

    unbilled = q_one("select meta from public.effort_events where run_id = %s",
                     (run,))
    assert unbilled["meta"]["unbilled"] is True


def test_settle_without_hold_reports_no_hold(tenant):
    """The fallback signal _persist_outcome uses to reach the 0011 path."""
    org, user = tenant["org"], tenant["users"]["owner"]
    run = _mk_run(org, user)
    settle = q_one("select app.settle_hold(%s, %s) as s", (org, run))["s"]
    assert settle["settled"] is False
    assert settle["reason"] == "no_hold"


# ---------------------------------------------------------------------------
# Rates and forecasting

def test_effort_rates_seeded_from_token_rates(tenant):
    """0012 must not silently reprice anything on deploy: the LLM units carry
    over whatever token_rates held."""
    rows = q_all(
        "select t.tier, t.in_per_1k, t.out_per_1k, "
        "       ei.credits as in_rate, eo.credits as out_rate "
        "from public.token_rates t "
        "join public.effort_rates ei on ei.tier = t.tier and ei.unit = 'llm_input_1k' "
        "join public.effort_rates eo on eo.tier = t.tier and eo.unit = 'llm_output_1k'")
    assert rows, "effort_rates was not seeded"
    for r in rows:
        assert float(r["in_rate"]) == float(r["in_per_1k"]), r["tier"]
        assert float(r["out_rate"]) == float(r["out_per_1k"]), r["tier"]


def test_unpriced_unit_charges_zero(tenant):
    """A newer engine metering a unit this migration never saw must degrade to
    free, not raise — a paid run cannot die over an unknown billing code."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 1, 5) as d", (org, run))

    reading = q_one(
        "select app.meter_effort(%s, %s, 'quantum_flux', 99, '{}'::jsonb) as m",
        (org, run))["m"]
    assert float(reading["metered"]) == 0.0
    assert reading["exhausted"] is False


def test_forecast_cold_start_is_generous(tenant):
    """With no history, over-reserving is the cheap mistake (credits come back
    at settle); under-reserving causes spurious budget stops."""
    org = tenant["org"]
    set_tier(org, "free")
    floor = q_one("select app.credit_cost(%s, 'image', 1) as c", (org,))["c"]
    fc = q_one("select app.credit_forecast(%s, 'image', 1) as f", (org,))["f"]
    assert fc >= floor, "cold-start forecast must leave real headroom"


def test_provider_cost_is_null_for_unknown_model(tenant):
    """An unknown model must not read as zero cost — that would show as 100%
    margin on the dashboard, which is worse than showing nothing."""
    assert q_one("select app.provider_cost_cents('no-such-model', 1000, 1000) as c"
                 )["c"] is None
    known = q_one("select app.provider_cost_cents('claude-sonnet-5', 1000, 1000) as c"
                  )["c"]
    assert known and known > 0


def test_balance_exposes_held_credits(tenant):
    """A user whose balance dipped mid-run needs to see why."""
    org, user = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")
    run = _mk_run(org, user)
    q_one("select app.reserve_credits(%s, %s, 2, 8) as d", (org, run))

    bal = q_one("select app.credit_balance(%s) as b", (org,))["b"]
    assert bal["held"] == 10
    assert "effort_rates" in bal and bal["effort_rates"]
