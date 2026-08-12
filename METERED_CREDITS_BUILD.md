# Metered Credits — Built, Not Yet Deployed

Real-time, effort-based credit deduction: **reserve → meter → settle**.

Status: **code complete, nothing applied.** Migration `0012` has not been run
against any database, and the test suite has not been executed. Everything
below is what you deploy and how you verify it.

---

## What changed, and why

### The problem this fixes

0011 already metered LLM tokens, but it settled *after* the run and clamped the
charge to whatever balance remained:

```sql
-- 0011:244
charge := least(cost, total);   -- clamp, never negative
```

The shortfall was written to the audit log and forgiven. A free-tier org (25
credits/month) could submit a 60-second video, burn hundreds of credits of real
provider tokens, and pay ≤25 — repeatably. No rate change fixes that; it is a
missing pre-authorization, not a mispricing.

### The model now

```
ENQUEUE          DURING THE RUN                   FINISH
   |                    |                            |
reserve  ─────────►  meter effort  ─────────────►  settle
floor+forecast      decrements the escrow,        charge max(floor, metered),
into escrow         engine stops when spent       capped at reserve; rest returns
```

The escrow is a **hard ceiling**. A run cannot charge more than was reserved,
so overspend is structurally impossible rather than policy-prevented.

`credit_costs` is now the **floor**, not the price:

```
charge = max( floor(kind, tier), ceil(Σ effort_units × rate) )
```

With `effort_rates` at zero, that reduces to exactly today's flat price —
which is what makes the staged rollout below safe.

---

## Files

### New

| File | What |
|---|---|
| `supabase/migrations/0012_metered_credits.sql` | `effort_rates`, `credit_holds`, `effort_events`, `provider_costs`; `reserve_credits` / `meter_effort` / `settle_hold` / `release_hold` / `reset_hold_meter` / `effort_cost` / `credit_forecast` / `provider_cost_cents`; `app.run_margin` view; `credit_balance` gains `held` + `effort_rates` |
| `backend/tests/test_metered_credits.py` | 19 tests — overspend, concurrency, idempotency, reconciliation, floor semantics |

### Modified

| File | What |
|---|---|
| `engine/saas.py` | `reserve_credits`, `meter_effort`, `settle_hold`, `release_hold`, `reset_hold_meter`, `provider_cost_cents` wrappers; `_persist_outcome` settles the hold and **populates `cost_cents`** |
| `engine/llm_layer.py` | `BudgetExhausted`; `meter` callback; per-round token metering; `budget_stopped` gate before each round |
| `engine/orchestrator.py` | `meter` threaded through `prepare_asset` / `review_and_verify` / `resume_with_human_guidance`; OCR/frame/video/retrieval metering; budget-stop reclassified out of `llm_error` |
| `backend/app/routes/submissions.py` | reserve instead of consume; floor + forecast in the 402 body |
| `backend/app/routes/runs.py` | run detail returns live escrow; new `GET /v1/runs/{id}/effort`; **resume now escrows its round** |
| `backend/app/routes/plans.py` | publishes `effort_rates` |
| `backend/app/services/credits.py` | `reserve_tx`, `forecast_tx`, `hold_for_run`, `effort_breakdown` |
| `backend/worker/executor.py` | meter closure wired into the engine; DLQ releases the hold |
| `backend/worker/main.py`, `backend/scheduler/main.py` | requeue resets the meter; watchdog releases holds |
| `backend/app/metrics.py` | `CREDITS_RESERVED` |
| frontend `types.ts` / `labels.ts` / `api.ts` + billing, submit, pricing, FAQ | reserve-vs-charge language, `held` balance line, effort units |

---

## Design decisions worth knowing

**Metering never takes the balance lock.** `meter_effort` touches only
`credit_holds`, one row per run. Charging the balance incrementally would take
the org's `credit_balances` lock on every meter event and serialise all of that
org's concurrent runs against each other. `test_metering_different_runs_does_not_serialise`
guards this.

**Settlement writes two ledger lines, not one.** `hold.release +reserved` then
`consume.metered −charge`. Net is `−charge`, so `app.reconcile_credit_balances()`
is untouched — but an auditor reads *reserved 100, released 100, charged 60*
instead of a bare `−60`. The bucket split is stored on the hold at reserve time
so the release restores exactly the buckets that were debited.

**`credit_holds.metered` is `numeric`.** Metering fires dozens of times per run;
integer-rounding each event compounds into real drift. Rounding happens once, at
settle.

**Round 1 is never budget-gated.** The gate runs *before* a round's provider
call, and only from round 2 on. So the escrow bounds overrun to at most one
round, and every run still produces a report. A budget stop is reclassified out
of `llm_error` in `review_and_verify` so it does not trigger the DLQ refund.

**A retry does not bill the dead attempt.** `reset_hold_meter` zeroes the meter
on requeue; the burned tokens stay in `effort_events` marked `absorbed`. Without
this a run that retried twice would bill three attempts for one report.

**Failed runs still refund in full (`keep=0`).** The failure is ours. What
changed is that the absorbed cost is now *visible* — `effort_events` holds the
quantity, `app.run_margin` holds the dollars. Not being able to see that bill
was the actual problem; billing users for our failures would be the wrong fix.

**Metering failures degrade to unmetered, never to a failed run.** Both `_meter`
wrappers swallow exceptions. A billing outage must not cost a paying user their
report; the cost lands on us, which is the correct way round.

---

## Deploy

### 1. Apply the migration

```bash
psql "$DATABASE_URL_MIGRATIONS" -v ON_ERROR_STOP=1 -f supabase/migrations/0012_metered_credits.sql
```

It is idempotent and additive: new tables and functions, plus one
`create or replace` on `app.credit_balance` that preserves every existing key.
`token_rates` and `app.settle_run_tokens` are **not** dropped — they stay one
release for rollback and for runs enqueued before the deploy.

Sanity check:

```bash
psql "$DATABASE_URL_MIGRATIONS" -c "select tier, unit, credits from public.effort_rates order by tier, unit;"
```

The `llm_input_1k` / `llm_output_1k` rows must equal your current `token_rates`
values — the seed reads them from the live table, so nothing reprices on
deploy. Every other unit is `0`.

### 2. Run the tests

```bash
cd backend && python -m pytest tests/test_metered_credits.py -v
```

These create and delete throwaway orgs. The one that matters is
`test_overspend_is_impossible` — it meters 500 credits of effort against a
12-credit escrow and asserts the charge is 12.

Then the suites whose assertions changed with the semantics:

```bash
cd backend && python -m pytest tests/test_credit_lifecycle.py tests/test_credit_race.py tests/test_atomicity_and_submit.py tests/test_e2e_worker.py -v
```

### 3. Deploy code

API, worker, and scheduler together — the worker's `settle_hold` and the API's
`reserve_credits` are two halves of one contract. A run enqueued by an old API
and finished by a new worker has no hold; `settle_hold` returns `no_hold` and
`_persist_outcome` falls back to the 0011 path, so a straggler is handled — but
do not run split versions longer than the drain.

### 4. Watch

```sql
-- forecast quality: reserved vs charged. Near 1.0 = too tight (users will hit
-- spurious budget stops). Near 3.0 = credits frozen for nothing.
select r.tier, avg(h.reserved::numeric / nullif(h.charged, 0)) as ratio,
       count(*) filter (where h.charged = h.reserved) as capped
from public.credit_holds h
join public.analysis_runs r on r.id = h.run_id
where h.status = 'settled' group by 1;
```

`capped > 0` means real users are hitting the ceiling — raise the forecast
before raising rates.

---

## Then: price the non-LLM units

Every non-LLM rate ships at `0`. They are metered from the first run but charge
nothing, so `effort_events` accumulates real quantities while `cost_cents`
accumulates real dollars. After ~2 weeks:

```sql
select * from app.run_margin;
```

That view is the first time this system can answer "what does a run actually
cost us". Set `ocr_page`, `cv_frame`, `video_second`, `rag_query` from it — not
before. The "2.5–3× list price" claim in the 0011 header was never verifiable;
now it is.

**Publish before you enforce.** `GET /v1/plans` already emits `effort_rates`.
The rule since 0008 is that the published price list is the enforced one —
raising a rate without it appearing there breaks that.

---

## Rollback

1. `update public.effort_rates set credits = 0;` — every run charges its floor,
   i.e. exactly pre-0012 pricing. Instant, no deploy.
2. If you need the old code path: revert `_persist_outcome` to call
   `settle_run_tokens` and `submissions.py` to call `consume_tx`. Both are still
   present and marked deprecated.
3. Full revert: `drop table public.credit_holds, public.effort_events,
   public.effort_rates cascade;` and re-run 0011's `credit_balance` definition.
   Open holds must be settled or released first or their credits are stranded.
