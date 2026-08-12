-- 0012_metered_credits.sql — real-time effort metering: reserve → meter → settle.
--
-- 0011 metered the LLM component AFTER the run and clamped the charge to
-- whatever balance remained (`charge := least(cost, total)`), forgiving the
-- shortfall. That is an unbounded overspend: a free-tier org (25 credits) could
-- burn hundreds of credits of provider tokens and pay 25. This migration
-- replaces post-hoc settlement with an escrow:
--
--   1. ENQUEUE  app.reserve_credits  — debit floor + forecast into a hold.
--   2. RUN      app.meter_effort     — each unit of engine effort decrements
--                                      the hold as it happens; the engine gets
--                                      live headroom back and stops when it is
--                                      gone.
--   3. FINISH   app.settle_hold      — charge max(floor, ceil(metered)) capped
--                                      at the reserve; return the remainder.
--
-- The escrow is a HARD ceiling: a run can never charge more than was reserved,
-- so overspend is structurally impossible rather than policy-prevented.
--
-- Decision notes (deviations recorded here per the ground rules):
--   * credit_costs is reinterpreted as a FLOOR, not the price. It still covers
--     ingest/CV/storage — the fixed cost of accepting a creative. Effort is
--     charged above it. When the engine reports no effort at all, the charge is
--     exactly today's base price, which is what makes shadow rollout a no-op
--     and rollback a matter of zeroing effort_rates.
--   * meter_effort touches ONLY credit_holds, never credit_balances. Charging
--     the balance incrementally would take the org's balance row lock on every
--     meter event and serialise all of that org's concurrent runs against each
--     other. The hold is taken once, under the existing lock, and metered
--     lock-free thereafter (one row lock per RUN, not per org).
--   * credit_holds.metered is numeric, not int. Metering fires dozens of times
--     per run; rounding each event to an integer would compound into real
--     drift. Rounding happens exactly once, at settle.
--   * Settlement writes TWO ledger entries (hold.release +reserved, then
--     consume.metered -charge) rather than one net entry. Both reconcile
--     identically under app.reconcile_credit_balances, but two entries let an
--     auditor read what was actually held vs actually charged. The bucket split
--     is recorded on the hold at reserve time so the release restores exactly
--     the buckets that were debited.
--   * token_rates and app.settle_run_tokens are NOT dropped. They stay one
--     release for rollback and for runs already in flight across the deploy
--     (settle_hold returns 'no_hold' for those so the caller can fall back).
--
-- Idempotent: safe to re-run.

begin;

-- ---------------------------------------------------------------------------
-- 1. Effort rate card — generalises token_rates. Tokens become two units
--    among many, so CV/OCR/RAG effort becomes chargeable on the same rail.

create table if not exists public.effort_rates (
  tier       text not null references public.plan_entitlements(tier),
  unit       text not null check (unit in (
               'llm_input_1k','llm_output_1k','llm_call',
               'ocr_page','cv_frame','video_second',
               'rag_query','embed_1k')),
  credits    numeric(10,4) not null check (credits >= 0),
  updated_at timestamptz not null default now(),
  primary key (tier, unit)
);

-- LLM units seed from the LIVE token_rates values, so day-one pricing is
-- byte-identical to 0011. Never hardcode these: whatever ops has tuned
-- token_rates to is what carries over.
insert into public.effort_rates (tier, unit, credits)
select tier, 'llm_input_1k',  in_per_1k  from public.token_rates
union all
select tier, 'llm_output_1k', out_per_1k from public.token_rates
on conflict (tier, unit) do update set credits = excluded.credits,
                                       updated_at = now();

-- Non-LLM units ship at ZERO. They are wired end-to-end and metered from the
-- first run, but charge nothing until the margin view (§5) shows what they
-- actually cost. Pricing an unmeasured unit is a guess; metering it is not.
insert into public.effort_rates (tier, unit, credits)
select t.tier, u.unit, 0
from public.plan_entitlements t
cross join (values ('llm_call'),('ocr_page'),('cv_frame'),
                   ('video_second'),('rag_query'),('embed_1k')) as u(unit)
on conflict (tier, unit) do nothing;   -- never zero a rate ops has already set

-- ---------------------------------------------------------------------------
-- 2. Holds (the escrow)

create table if not exists public.credit_holds (
  run_id         uuid primary key references public.analysis_runs(id) on delete cascade,
  org_id         uuid not null references public.orgs(id) on delete cascade,
  reserved       int not null check (reserved >= 0),
  reserved_sub   int not null default 0 check (reserved_sub  >= 0),
  reserved_pack  int not null default 0 check (reserved_pack >= 0),
  floor_credits  int not null default 0 check (floor_credits >= 0),
  metered        numeric(14,4) not null default 0 check (metered >= 0),
  charged        int,                        -- set at settle
  status         text not null default 'open'
                   check (status in ('open','settled','released')),
  created_at     timestamptz not null default now(),
  settled_at     timestamptz
);

create index if not exists ix_holds_open on public.credit_holds (org_id)
  where status = 'open';

alter table public.credit_holds enable row level security;

drop policy if exists credit_holds_member_read on public.credit_holds;
create policy credit_holds_member_read on public.credit_holds
  for select to authenticated
  using (org_id in (select app.user_org_ids()));

grant select on public.credit_holds to authenticated;
-- writes are service paths only (no authenticated write policy on purpose)

-- Per-run effort detail: what was metered, when, at what rate. This is the
-- line-item backing of a metered charge — the answer to "why 47 credits?".
create table if not exists public.effort_events (
  id         bigserial primary key,
  run_id     uuid not null references public.analysis_runs(id) on delete cascade,
  org_id     uuid not null references public.orgs(id) on delete cascade,
  unit       text not null,
  quantity   numeric(14,4) not null,
  rate       numeric(10,4) not null,
  credits    numeric(14,4) not null,
  meta       jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists ix_effort_events_run on public.effort_events (run_id, id);

alter table public.effort_events enable row level security;

drop policy if exists effort_events_member_read on public.effort_events;
create policy effort_events_member_read on public.effort_events
  for select to authenticated
  using (org_id in (select app.user_org_ids()));

grant select on public.effort_events to authenticated;

-- ---------------------------------------------------------------------------
-- 3. Ledger vocabulary

alter table public.credit_ledger drop constraint if exists credit_ledger_reason_check;
alter table public.credit_ledger add constraint credit_ledger_reason_check
  check (reason in ('grant.cycle','grant.pack','grant.manual','consume.run',
                    'consume.tokens','consume.metered',
                    'hold.reserve','hold.release',
                    'refund.system_failure','adjust.manual','expire.cycle'));

-- ---------------------------------------------------------------------------
-- 4. Functions

-- Credits for `qty` of `unit` at this org's CURRENT tier. Unpriced units
-- return 0 rather than raising: a new engine build that meters a unit this
-- migration has not seen must degrade to free, never fail a paid run.
create or replace function app.effort_cost(target_org uuid, unit_name text, qty numeric)
returns numeric
language sql stable security definer set search_path = public, extensions as $$
  select coalesce(
    (select r.credits from public.effort_rates r
      where r.tier = app.org_tier(target_org) and r.unit = unit_name), 0)
    * greatest(coalesce(qty, 0), 0)
$$;

-- Escrow `floor + forecast` for a run. Same consume-or-reject contract and
-- same return shape as app.consume_credits (0008) so the 402 path is unchanged.
create or replace function app.reserve_credits(
  target_org uuid, target_run uuid, floor_credits int, forecast int default 0)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  b public.credit_balances;
  want      int;
  total     int;
  from_sub  int;
  from_pack int;
begin
  if target_run is null then
    raise exception 'reserve_credits requires a run id';
  end if;
  if floor_credits is null or floor_credits < 0 then
    raise exception 'invalid floor %', floor_credits;
  end if;
  want := floor_credits + greatest(coalesce(forecast, 0), 0);

  b := app._lock_credit_balance(target_org);
  total := b.subscription_credits + b.purchased_credits;

  -- Re-entry (idempotent submit replay): an open hold already covers this run.
  if exists (select 1 from public.credit_holds
             where run_id = target_run and status = 'open') then
    return jsonb_build_object('allowed', true, 'reserved',
                              (select reserved from public.credit_holds where run_id = target_run),
                              'replay', true,
                              'sub_bal', b.subscription_credits,
                              'pack_bal', b.purchased_credits);
  end if;

  if total < want then
    perform app.log_audit_event(target_org, null, 'credits.rejected',
      'analysis_run:' || target_run::text,
      jsonb_build_object('needed', want, 'balance', total, 'floor', floor_credits,
                         'forecast', forecast));
    return jsonb_build_object('allowed', false, 'needed', want, 'balance', total,
                              'sub_bal', b.subscription_credits,
                              'pack_bal', b.purchased_credits);
  end if;

  from_sub  := least(b.subscription_credits, want);
  from_pack := want - from_sub;

  update public.credit_balances
     set subscription_credits = subscription_credits - from_sub,
         purchased_credits    = purchased_credits    - from_pack,
         updated_at = now()
   where org_id = target_org;

  insert into public.credit_holds (run_id, org_id, reserved, reserved_sub,
                                   reserved_pack, floor_credits)
  values (target_run, target_org, want, from_sub, from_pack, floor_credits);

  if from_sub > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, -from_sub, 'subscription', 'hold.reserve', target_run,
            b.subscription_credits - from_sub);
  end if;
  if from_pack > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, -from_pack, 'purchased', 'hold.reserve', target_run,
            b.purchased_credits - from_pack);
  end if;

  perform app.log_audit_event(target_org, null, 'credits.reserved',
    'analysis_run:' || target_run::text,
    jsonb_build_object('reserved', want, 'floor', floor_credits,
                       'forecast', forecast,
                       'from_subscription', from_sub, 'from_purchased', from_pack,
                       'sub_bal', b.subscription_credits - from_sub,
                       'pack_bal', b.purchased_credits - from_pack));

  return jsonb_build_object('allowed', true, 'reserved', want,
                            'charged', want,          -- back-compat key
                            'floor', floor_credits,
                            'sub_bal', b.subscription_credits - from_sub,
                            'pack_bal', b.purchased_credits - from_pack);
end $$;

-- THE hot path. Called many times per run, from inside the engine, as effort
-- happens. Touches credit_holds ONLY — no balance lock, so concurrent runs of
-- the same org never serialise against each other.
-- Returns live headroom; `exhausted` is the signal the engine stops on.
create or replace function app.meter_effort(
  target_org uuid, target_run uuid, unit_name text, qty numeric,
  meta jsonb default '{}'::jsonb)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  rate     numeric;
  cost     numeric;
  h        public.credit_holds;
  headroom int;
begin
  select r.credits into rate from public.effort_rates r
   where r.tier = app.org_tier(target_org) and r.unit = unit_name;
  rate := coalesce(rate, 0);
  cost := rate * greatest(coalesce(qty, 0), 0);

  update public.credit_holds
     set metered = metered + cost
   where run_id = target_run and status = 'open'
  returning * into h;

  if h.run_id is null then
    -- No open hold: a pre-0012 run still in flight, or an already-settled one.
    -- Record the effort for margin analysis, charge nothing, tell the engine
    -- it has room (it must not stop over a billing gap).
    insert into public.effort_events (run_id, org_id, unit, quantity, rate, credits, meta)
    values (target_run, target_org, unit_name, coalesce(qty, 0), rate, cost,
            meta || jsonb_build_object('unbilled', true, 'reason', 'no_open_hold'));
    return jsonb_build_object('metered', 0, 'reserved', 0, 'headroom', null,
                              'exhausted', false, 'billed', false);
  end if;

  insert into public.effort_events (run_id, org_id, unit, quantity, rate, credits, meta)
  values (target_run, target_org, unit_name, coalesce(qty, 0), rate, cost, meta);

  headroom := h.reserved - ceil(h.metered)::int;

  return jsonb_build_object(
    'metered',   h.metered,
    'reserved',  h.reserved,
    'headroom',  headroom,
    'exhausted', headroom <= 0,
    'billed',    true);
end $$;

-- Finalise. charge = max(floor, ceil(metered)), capped at the reserve — the
-- escrow is the ceiling, which is the entire point of this migration.
-- Idempotent on status; returns 'no_hold' so callers can fall back to the
-- 0011 path for runs that predate the deploy.
create or replace function app.settle_hold(target_org uuid, target_run uuid)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  h         public.credit_holds;
  b         public.credit_balances;
  charge    int;
  uncapped  int;
  from_sub  int;
  from_pack int;
begin
  if target_run is null then
    raise exception 'settle_hold requires a run id';
  end if;

  b := app._lock_credit_balance(target_org);   -- lock BEFORE reading the hold

  select * into h from public.credit_holds where run_id = target_run for update;
  if h.run_id is null then
    return jsonb_build_object('settled', false, 'reason', 'no_hold');
  end if;
  if h.status <> 'open' then
    return jsonb_build_object('settled', false, 'reason', 'already_settled',
                              'charged', h.charged);
  end if;

  uncapped := greatest(h.floor_credits, ceil(h.metered)::int);
  charge   := least(uncapped, h.reserved);

  -- Balances: give the whole reserve back, then take the actual charge.
  -- Net movement is (reserved - charge); the two ledger lines below record
  -- both halves so the hold is auditable rather than implied.
  update public.credit_balances
     set subscription_credits = subscription_credits + h.reserved_sub,
         purchased_credits    = purchased_credits    + h.reserved_pack,
         updated_at = now()
   where org_id = target_org;

  if h.reserved_sub > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, h.reserved_sub, 'subscription', 'hold.release', target_run,
            b.subscription_credits + h.reserved_sub);
  end if;
  if h.reserved_pack > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, h.reserved_pack, 'purchased', 'hold.release', target_run,
            b.purchased_credits + h.reserved_pack);
  end if;

  from_sub  := least(b.subscription_credits + h.reserved_sub, charge);
  from_pack := charge - from_sub;

  if charge > 0 then
    update public.credit_balances
       set subscription_credits = subscription_credits - from_sub,
           purchased_credits    = purchased_credits    - from_pack,
           updated_at = now()
     where org_id = target_org;
    if from_sub > 0 then
      insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
      values (target_org, -from_sub, 'subscription', 'consume.metered', target_run,
              b.subscription_credits + h.reserved_sub - from_sub);
    end if;
    if from_pack > 0 then
      insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
      values (target_org, -from_pack, 'purchased', 'consume.metered', target_run,
              b.purchased_credits + h.reserved_pack - from_pack);
    end if;
  end if;

  update public.credit_holds
     set status = 'settled', charged = charge, settled_at = now()
   where run_id = target_run;

  perform app.log_audit_event(target_org, null, 'credits.settled',
    'analysis_run:' || target_run::text,
    jsonb_build_object('reserved', h.reserved, 'metered', h.metered,
                       'floor', h.floor_credits, 'uncapped', uncapped,
                       'charged', charge, 'returned', h.reserved - charge,
                       'capped', uncapped > h.reserved));

  return jsonb_build_object('settled', true, 'charged', charge,
                            'reserved', h.reserved, 'metered', h.metered,
                            'returned', h.reserved - charge,
                            'capped', uncapped > h.reserved);
end $$;

-- Failure path: return the reserve, optionally keeping `keep` credits for
-- effort genuinely delivered before the failure. keep = 0 is a full refund.
create or replace function app.release_hold(
  target_org uuid, target_run uuid, keep int default 0)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  h         public.credit_holds;
  b         public.credit_balances;
  kept      int;
  from_sub  int;
  from_pack int;
begin
  b := app._lock_credit_balance(target_org);

  select * into h from public.credit_holds where run_id = target_run for update;
  if h.run_id is null then
    return jsonb_build_object('released', false, 'reason', 'no_hold');
  end if;
  if h.status <> 'open' then
    return jsonb_build_object('released', false, 'reason', 'already_settled');
  end if;

  kept := least(greatest(coalesce(keep, 0), 0), h.reserved);

  update public.credit_balances
     set subscription_credits = subscription_credits + h.reserved_sub,
         purchased_credits    = purchased_credits    + h.reserved_pack,
         updated_at = now()
   where org_id = target_org;

  if h.reserved_sub > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, h.reserved_sub, 'subscription', 'hold.release', target_run,
            b.subscription_credits + h.reserved_sub);
  end if;
  if h.reserved_pack > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, h.reserved_pack, 'purchased', 'hold.release', target_run,
            b.purchased_credits + h.reserved_pack);
  end if;

  from_sub  := least(b.subscription_credits + h.reserved_sub, kept);
  from_pack := kept - from_sub;

  if kept > 0 then
    update public.credit_balances
       set subscription_credits = subscription_credits - from_sub,
           purchased_credits    = purchased_credits    - from_pack,
           updated_at = now()
     where org_id = target_org;
    if from_sub > 0 then
      insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
      values (target_org, -from_sub, 'subscription', 'consume.metered', target_run,
              b.subscription_credits + h.reserved_sub - from_sub);
    end if;
    if from_pack > 0 then
      insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
      values (target_org, -from_pack, 'purchased', 'consume.metered', target_run,
              b.purchased_credits + h.reserved_pack - from_pack);
    end if;
  end if;

  update public.credit_holds
     set status = 'released', charged = kept, settled_at = now()
   where run_id = target_run;

  perform app.log_audit_event(target_org, null, 'credits.hold_released',
    'analysis_run:' || target_run::text,
    jsonb_build_object('reserved', h.reserved, 'metered', h.metered,
                       'kept', kept, 'refunded', h.reserved - kept));

  return jsonb_build_object('released', true, 'refunded', h.reserved - kept,
                            'kept', kept, 'metered', h.metered);
end $$;

-- Zero a hold's meter when its run is requeued after a failed attempt.
--
-- Without this, a retry inherits the dead attempt's metered total and the user
-- pays for our retry. The effort_events rows are NOT deleted — they are marked
-- absorbed, so the tokens stay visible as cost we ate (that visibility is the
-- point; see app.run_margin). The escrow itself is untouched: it was sized for
-- one run and still is.
create or replace function app.reset_hold_meter(target_org uuid, target_run uuid)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
begin
  update public.credit_holds
     set metered = 0
   where run_id = target_run and org_id = target_org and status = 'open';

  if not found then
    return jsonb_build_object('reset', false, 'reason', 'no_open_hold');
  end if;

  update public.effort_events
     set meta = meta || jsonb_build_object('absorbed', true,
                                           'reason', 'attempt_retried')
   where run_id = target_run
     and not coalesce((meta->>'absorbed')::boolean, false);

  return jsonb_build_object('reset', true);
end $$;

-- How much to escrow ABOVE the floor. Learned from this tier+kind's own
-- history: the p95 of what comparable runs actually cost, so 19 in 20 runs
-- finish without touching the cap.
--
-- The two failure modes are asymmetric and the defaults reflect that. Forecast
-- too LOW and users hit spurious budget stops on legitimate runs. Forecast too
-- HIGH and credits sit frozen for a few minutes, then come back at settle. The
-- second is a much cheaper mistake, so a cold start (fewer than 20 samples)
-- reserves a generous multiple of the floor rather than a tight one.
create or replace function app.credit_forecast(
  target_org uuid, kind text, cards int default 1)
returns int
language plpgsql stable security definer set search_path = public, extensions as $$
declare
  t     text := app.org_tier(target_org);
  floor_c int := app.credit_cost(target_org, kind, cards);
  n     int;
  p95   numeric;
begin
  select count(*), percentile_cont(0.95) within group (order by h.charged)
    into n, p95
  from public.credit_holds h
  join public.analysis_runs r on r.id = h.run_id
  join public.submissions s   on s.id = r.submission_id
  where h.status = 'settled'
    and h.charged is not null
    and r.tier = t
    and coalesce(s.params->>'pricing_kind', '') = kind
    and h.settled_at > now() - interval '30 days';

  if n >= 20 and p95 is not null then
    -- Headroom above p95 so the 95th-percentile run itself does not clip.
    return greatest(ceil(p95 * 1.25)::int - floor_c, 0);
  end if;
  return floor_c * 3;      -- cold start: generous, refunded at settle
end $$;

-- ---------------------------------------------------------------------------
-- 5. Margin instrumentation — cost_cents has existed unpopulated since 0001.
--    Nothing can be priced honestly until this carries real numbers.

create table if not exists public.provider_costs (
  model            text not null,
  effective_from   date not null default current_date,
  in_per_1k_cents  numeric(10,5) not null check (in_per_1k_cents  >= 0),
  out_per_1k_cents numeric(10,5) not null check (out_per_1k_cents >= 0),
  note             text,
  primary key (model, effective_from)
);

-- List prices in USD cents per 1k tokens. Keep current: these are the
-- denominator of every margin number the business reads.
insert into public.provider_costs (model, in_per_1k_cents, out_per_1k_cents, note) values
  ('claude-opus-4-8',    1.500, 7.500, 'list'),
  ('claude-sonnet-5',    0.300, 1.500, 'list'),
  ('claude-haiku-4-5',   0.100, 0.500, 'list'),
  ('qwen3.7-plus',       0.040, 0.120, 'openrouter list'),
  ('qwen3.7-max',        0.080, 0.240, 'openrouter list')
on conflict (model, effective_from) do nothing;

-- True provider cost of a run, in cents. Unknown model → null (never a silent
-- zero: a zero would read as 100% margin on the dashboard).
create or replace function app.provider_cost_cents(
  model_name text, in_tok bigint, out_tok bigint)
returns int
language sql stable security definer set search_path = public, extensions as $$
  select ceil( coalesce(in_tok, 0)::numeric  / 1000 * c.in_per_1k_cents
             + coalesce(out_tok, 0)::numeric / 1000 * c.out_per_1k_cents )::int
  from public.provider_costs c
  where c.model = model_name and c.effective_from <= current_date
  order by c.effective_from desc
  limit 1
$$;

-- Revenue vs cost by tier and asset kind. Service-side only: this is margin
-- data, not customer data.
create or replace view app.run_margin as
  select r.tier,
         coalesce(s.params->>'pricing_kind', 'unknown') as kind,
         count(*)                                        as runs,
         sum(coalesce(h.charged, 0))                     as credits_charged,
         sum(coalesce(r.cost_cents, 0)) / 100.0          as cost_usd,
         count(*) filter (where r.cost_cents is null)    as runs_missing_cost
  from public.analysis_runs r
  join public.submissions s on s.id = r.submission_id
  left join public.credit_holds h on h.run_id = r.id
  where r.finished_at is not null
  group by 1, 2;

-- ---------------------------------------------------------------------------
-- 6. credit_balance gains held/available (forward-only replacement of 0011's
--    0008 definition — every existing key is preserved).

create or replace function app.credit_balance(target_org uuid)
returns jsonb
language plpgsql stable security definer set search_path = public, extensions as $$
declare
  t     text := app.org_tier(target_org);
  b     public.credit_balances;
  price jsonb;
  rates jsonb;
  held  int;
begin
  if auth.uid() is not null and not app.is_org_member(target_org) then
    raise exception 'not a member of org %', target_org;
  end if;
  select * into b from public.credit_balances where org_id = target_org;
  select jsonb_object_agg(asset_kind, credits) into price
  from public.credit_costs where tier = t;
  select jsonb_object_agg(unit, credits) into rates
  from public.effort_rates where tier = t;
  select coalesce(sum(reserved), 0) into held
  from public.credit_holds where org_id = target_org and status = 'open';
  return jsonb_build_object(
    'tier', t,
    'subscription_credits', coalesce(b.subscription_credits, 0),
    'purchased_credits',    coalesce(b.purchased_credits, 0),
    -- `total` is post-reserve: an open hold is already debited from the
    -- buckets, so total == spendable. `held` is shown so a user can see why
    -- their balance dipped while a run is still in flight; part of it comes
    -- back at settle.
    'total',                coalesce(b.subscription_credits, 0) + coalesce(b.purchased_credits, 0),
    'held',                 held,
    'available',            coalesce(b.subscription_credits, 0) + coalesce(b.purchased_credits, 0),
    'cycle_start',          b.cycle_start,
    'cycle_end',            b.cycle_end,
    'credits_per_month',    (select credits_per_month from public.plan_entitlements where tier = t),
    'price_list',           coalesce(price, '{}'::jsonb),
    'effort_rates',         coalesce(rates, '{}'::jsonb));
end $$;

-- ---------------------------------------------------------------------------
-- 7. Grants. Money-moving functions are service-side only, matching 0008.

alter table public.effort_rates enable row level security;
drop policy if exists effort_rates_public_read on public.effort_rates;
create policy effort_rates_public_read on public.effort_rates
  for select to anon, authenticated using (true);
grant select on public.effort_rates to anon, authenticated;

revoke all on function app.effort_cost(uuid, text, numeric)                from public, anon;
revoke all on function app.credit_forecast(uuid, text, int)                from public, anon;
revoke all on function app.reserve_credits(uuid, uuid, int, int)           from public, anon, authenticated;
revoke all on function app.meter_effort(uuid, uuid, text, numeric, jsonb)  from public, anon, authenticated;
revoke all on function app.settle_hold(uuid, uuid)                         from public, anon, authenticated;
revoke all on function app.reset_hold_meter(uuid, uuid)                    from public, anon, authenticated;
revoke all on function app.release_hold(uuid, uuid, int)                   from public, anon, authenticated;
revoke all on function app.provider_cost_cents(text, bigint, bigint)       from public, anon, authenticated;

grant execute on function app.effort_cost(uuid, text, numeric)               to authenticated, service_role;
grant execute on function app.credit_forecast(uuid, text, int)               to authenticated, service_role;
grant execute on function app.reserve_credits(uuid, uuid, int, int)          to service_role;
grant execute on function app.meter_effort(uuid, uuid, text, numeric, jsonb) to service_role;
grant execute on function app.settle_hold(uuid, uuid)                        to service_role;
grant execute on function app.reset_hold_meter(uuid, uuid)                   to service_role;
grant execute on function app.release_hold(uuid, uuid, int)                  to service_role;
grant execute on function app.provider_cost_cents(text, bigint, bigint)      to service_role;

-- ---------------------------------------------------------------------------
-- 8. Deprecations (kept one release for rollback — the 0008 convention).

comment on function app.settle_run_tokens(uuid, uuid, bigint, bigint) is
  'DEPRECATED (0012): superseded by app.meter_effort + app.settle_hold. Kept '
  'one release for rollback and for runs enqueued before 0012 deployed (those '
  'have no hold; settle_hold returns no_hold and the caller falls back here).';
comment on table public.token_rates is
  'DEPRECATED (0012): superseded by public.effort_rates (units llm_input_1k / '
  'llm_output_1k). Still read by app.settle_run_tokens on the fallback path.';

commit;
