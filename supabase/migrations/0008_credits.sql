-- 0008_credits.sql — the credit system (Backend Architecture spec §7–§8, App. B).
-- Credits replace the scans/month quota as the single usage currency:
--   cost = base(asset kind) x multiplier(tier model class), published in
--   credit_costs (the same table renders the pricing page — what is published
--   is literally what is enforced).
-- Two buckets per org: subscription (monthly allowance, resets, no rollover)
-- and purchased (packs, never expire, consumed after allowance). Hard stop at
-- zero. The ledger is append-only; balances are derived state, reconciled
-- nightly against the ledger by the scheduler.
--
-- Decision notes (deviations are recorded here per the spec's ground rules):
--   * enterprise (credits_per_month is null): no automatic cycle grant and no
--     cycle expiry — balances are contract-provisioned via grant.manual.
--     Consumption is still enforced against the balance (a starved enterprise
--     org gets 402 and a manual top-up, never an unmetered run), so every
--     ledger/balance invariant holds for all tiers.
--   * app.org_cycle_key(org) is THE single derivation of the allowance cycle
--     key (paid: subscription id + period start + tier; free: calendar month).
--     Webhook and scheduler both call app.ensure_cycle_grant(org), which uses
--     it — two writers can never disagree on the idempotency key.
--   * user_rpm / submissions_per_day columns: §9.2 tiers browser-session and
--     submission-creation limits; they live here with api_rpm/api_burst so
--     every tiered limit resolves from plan_entitlements.
-- Idempotent: safe to re-run.

begin;

-- ---------------------------------------------------------------------------
-- Balances: one lockable row per org (SELECT ... FOR UPDATE is the
-- concurrency control for every credit mutation).

create table if not exists public.credit_balances (
  org_id               uuid primary key references public.orgs(id) on delete cascade,
  subscription_credits int not null default 0 check (subscription_credits >= 0),
  purchased_credits    int not null default 0 check (purchased_credits >= 0),
  cycle_start          date,             -- current allowance window (from Stripe period)
  cycle_end            date,
  updated_at           timestamptz not null default now()
);

-- Append-only ledger: the source of truth an auditor reads.
create table if not exists public.credit_ledger (
  id            bigserial primary key,
  org_id        uuid not null references public.orgs(id) on delete cascade,
  delta         int  not null check (delta <> 0),   -- + grants/refunds, - consumption
  bucket        text not null check (bucket in ('subscription','purchased')),
  reason        text not null check (reason in ('grant.cycle','grant.pack','grant.manual',
                     'consume.run','refund.system_failure','adjust.manual','expire.cycle')),
  run_id        uuid references public.analysis_runs(id) on delete set null,
  stripe_ref    text,                    -- checkout session / cycle key for grants
  balance_after int not null,            -- bucket balance after this entry
  actor         uuid,
  created_at    timestamptz not null default now()
);

create index if not exists ix_ledger_org on public.credit_ledger (org_id, id desc);
create index if not exists ix_ledger_run on public.credit_ledger (run_id) where run_id is not null;
create unique index if not exists uq_ledger_pack on public.credit_ledger (stripe_ref)
  where reason = 'grant.pack';           -- pack grant idempotency
create unique index if not exists uq_ledger_cycle on public.credit_ledger (org_id, reason, stripe_ref)
  where reason = 'grant.cycle';          -- one grant per org per cycle key

-- Append-only enforcement, mirroring audit_logs (0003): corrections are new
-- compensating entries, never edits. Referential actions must still work —
-- the GDPR erasure path deletes an org and cascades here, and deleting a
-- submission set-nulls run_id — so mutations arriving from an FK action
-- (pg_trigger_depth() > 1) pass; direct UPDATE/DELETE by ANY role is blocked.
create or replace function app.credit_ledger_block_mutation() returns trigger
language plpgsql as $$
begin
  if pg_trigger_depth() > 1 then
    if tg_op = 'DELETE' then
      return old;
    end if;
    return new;
  end if;
  raise exception 'credit_ledger is append-only';
end $$;

drop trigger if exists credit_ledger_append_only on public.credit_ledger;
create trigger credit_ledger_append_only
  before update or delete on public.credit_ledger
  for each row execute function app.credit_ledger_block_mutation();

revoke update, delete, truncate on public.credit_ledger from anon, authenticated, service_role;

-- Published price list (flat cost model, D4). 'carousel_card' is the price of
-- each card beyond the first; a carousel costs image + (cards-1) x carousel_card.
create table if not exists public.credit_costs (
  asset_kind text not null check (asset_kind in ('text','image','html','carousel_card')),
  tier       text not null references public.plan_entitlements(tier),
  credits    int  not null check (credits > 0),
  primary key (asset_kind, tier)
);

-- ---------------------------------------------------------------------------
-- plan_entitlements: credit + rate-limit columns (App. B).

alter table public.plan_entitlements
  add column if not exists credits_per_month   int,            -- null = custom/uncapped (enterprise)
  add column if not exists api_rpm             int,            -- null = no API entitlement
  add column if not exists api_burst           int,
  add column if not exists user_rpm            int not null default 60,
  add column if not exists max_concurrent_runs int not null default 1,
  add column if not exists max_upload_mb       int not null default 10,
  add column if not exists submissions_per_day int,            -- null = unlimited (credits govern)
  add column if not exists credit_packs_allowed boolean not null default false;

-- Seed (App. B — launch placeholders; the margin dashboard re-prices pre-GA).
update public.plan_entitlements set credits_per_month = 25,    api_rpm = null, api_burst = null, user_rpm = 60,  max_concurrent_runs = 1,  max_upload_mb = 10, submissions_per_day = 5,    credit_packs_allowed = false where tier = 'free';
update public.plan_entitlements set credits_per_month = 400,   api_rpm = null, api_burst = null, user_rpm = 120, max_concurrent_runs = 1,  max_upload_mb = 20, submissions_per_day = 50,   credit_packs_allowed = true  where tier = 'hobby';
update public.plan_entitlements set credits_per_month = 6000,  api_rpm = 60,   api_burst = 120,  user_rpm = 120, max_concurrent_runs = 3,  max_upload_mb = 30, submissions_per_day = 500,  credit_packs_allowed = true  where tier = 'pro';
update public.plan_entitlements set credits_per_month = 50000, api_rpm = 300,  api_burst = 600,  user_rpm = 240, max_concurrent_runs = 6,  max_upload_mb = 50, submissions_per_day = null, credit_packs_allowed = true  where tier = 'design';
update public.plan_entitlements set credits_per_month = null,  api_rpm = 1000, api_burst = 2000, user_rpm = 600, max_concurrent_runs = 10, max_upload_mb = 50, submissions_per_day = null, credit_packs_allowed = true  where tier = 'enterprise';

-- credit_costs seed (credits per run, App. B). Multipliers: free x1, hobby x2,
-- pro x5, design x10, enterprise x10 over base text 1 / image 2 / html 2 /
-- extra carousel card 1.
insert into public.credit_costs (asset_kind, tier, credits) values
  ('text',          'free', 1),  ('text',          'hobby', 2),  ('text',          'pro', 5),  ('text',          'design', 10), ('text',          'enterprise', 10),
  ('image',         'free', 2),  ('image',         'hobby', 4),  ('image',         'pro', 10), ('image',         'design', 20), ('image',         'enterprise', 20),
  ('html',          'free', 2),  ('html',          'hobby', 4),  ('html',          'pro', 10), ('html',          'design', 20), ('html',          'enterprise', 20),
  ('carousel_card', 'free', 1),  ('carousel_card', 'hobby', 2),  ('carousel_card', 'pro', 5),  ('carousel_card', 'design', 10), ('carousel_card', 'enterprise', 10)
on conflict (asset_kind, tier) do update set credits = excluded.credits;

-- ---------------------------------------------------------------------------
-- Functions. All security definer, owned by the migration role (postgres);
-- execute is revoked from anon/authenticated except the two member-safe reads,
-- which verify membership internally when called under a user JWT.

-- Price of one run for this org, BEFORE execution (D4: enforceable before
-- expensive work). kind: text | image | html | carousel (cards = card count).
create or replace function app.credit_cost(target_org uuid, kind text, cards int default 1)
returns int
language plpgsql stable security definer set search_path = public, extensions as $$
declare
  t text := app.org_tier(target_org);
  n int;
  c int;
begin
  if auth.uid() is not null and not app.is_org_member(target_org) then
    raise exception 'not a member of org %', target_org;
  end if;
  if kind in ('text','image','html') then
    select credits into c from public.credit_costs where asset_kind = kind and tier = t;
  elsif kind = 'carousel' then
    n := least(greatest(coalesce(cards, 1), 1), 10);   -- cards capped at 10
    select (select credits from public.credit_costs where asset_kind = 'image' and tier = t)
         + (n - 1) * (select credits from public.credit_costs where asset_kind = 'carousel_card' and tier = t)
      into c;
  else
    raise exception 'unknown asset kind % (text|image|html|carousel)', kind;
  end if;
  if c is null then
    raise exception 'no credit_costs row for kind=% tier=%', kind, t;
  end if;
  return c;
end $$;

-- Make sure the org has a lockable balance row, then lock it. Every credit
-- mutation goes through this: per-org serialisation via the row lock.
create or replace function app._lock_credit_balance(target_org uuid)
returns public.credit_balances
language plpgsql security definer set search_path = public, extensions as $$
declare b public.credit_balances;
begin
  insert into public.credit_balances (org_id) values (target_org)
  on conflict (org_id) do nothing;
  select * into b from public.credit_balances where org_id = target_org for update;
  return b;
end $$;

-- Atomic consume-or-reject. Spends allowance first, then packs; both-bucket
-- splits produce one ledger row per bucket. Rejections mutate nothing.
create or replace function app.consume_credits(target_org uuid, target_run uuid, cost int)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  b public.credit_balances;
  from_sub  int;
  from_pack int;
  total     int;
begin
  if cost is null or cost < 0 then
    raise exception 'invalid cost %', cost;
  end if;
  b := app._lock_credit_balance(target_org);
  total := b.subscription_credits + b.purchased_credits;
  if cost = 0 then
    return jsonb_build_object('allowed', true, 'charged', 0,
                              'sub_bal', b.subscription_credits,
                              'pack_bal', b.purchased_credits);
  end if;
  if total < cost then
    perform app.log_audit_event(target_org, null, 'credits.rejected',
      case when target_run is null then null else 'analysis_run:' || target_run::text end,
      jsonb_build_object('needed', cost, 'balance', total));
    return jsonb_build_object('allowed', false, 'needed', cost, 'balance', total,
                              'sub_bal', b.subscription_credits,
                              'pack_bal', b.purchased_credits);
  end if;
  from_sub  := least(b.subscription_credits, cost);
  from_pack := cost - from_sub;
  update public.credit_balances
     set subscription_credits = subscription_credits - from_sub,
         purchased_credits    = purchased_credits    - from_pack,
         updated_at = now()
   where org_id = target_org;
  if from_sub > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, -from_sub, 'subscription', 'consume.run', target_run,
            b.subscription_credits - from_sub);
  end if;
  if from_pack > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, -from_pack, 'purchased', 'consume.run', target_run,
            b.purchased_credits - from_pack);
  end if;
  perform app.log_audit_event(target_org, null, 'credits.consumed',
    case when target_run is null then null else 'analysis_run:' || target_run::text end,
    jsonb_build_object('cost', cost, 'from_subscription', from_sub, 'from_purchased', from_pack,
                       'sub_bal', b.subscription_credits - from_sub,
                       'pack_bal', b.purchased_credits - from_pack));
  return jsonb_build_object('allowed', true, 'charged', cost,
                            'sub_bal', b.subscription_credits - from_sub,
                            'pack_bal', b.purchased_credits - from_pack);
end $$;

-- THE cycle-key derivation — the only place an allowance cycle is named.
-- Paid: subscription id + Stripe period start + tier (a mid-cycle upgrade
-- makes a fresh key, so the new tier's allowance grants immediately, §8.2).
-- Free (no Stripe object): calendar month.
create or replace function app.org_cycle_key(target_org uuid)
returns text
language sql stable security definer set search_path = public, extensions as $$
  select case
    when s.org_id is not null and s.status in ('trialing','active','past_due')
      then coalesce(s.stripe_subscription_id, 'sub-' || s.org_id::text)
           || ':' || coalesce(extract(epoch from s.current_period_start)::bigint::text, 'noperiod')
           || ':' || app.org_tier(target_org)
    else 'free:' || to_char(now(), 'YYYY-MM')
  end
  from (select 1) one
  left join public.subscriptions s on s.org_id = target_org
$$;

-- Idempotent per cycle key: expires the old allowance (ledger 'expire.cycle'),
-- sets subscription_credits = tier allowance, stamps the cycle window.
create or replace function app.grant_cycle_credits(
  target_org uuid, cycle_key text,
  p_cycle_start date default null, p_cycle_end date default null)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  b public.credit_balances;
  allowance int;
begin
  select credits_per_month into allowance
  from public.plan_entitlements where tier = app.org_tier(target_org);
  if allowance is null then
    -- enterprise/custom: contract-governed via grant.manual; never auto-reset.
    return jsonb_build_object('granted', false, 'reason', 'uncapped_tier');
  end if;
  b := app._lock_credit_balance(target_org);
  if exists (select 1 from public.credit_ledger
             where org_id = target_org and reason = 'grant.cycle' and stripe_ref = cycle_key) then
    return jsonb_build_object('granted', false, 'reason', 'already_granted', 'cycle_key', cycle_key);
  end if;
  if b.subscription_credits > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, stripe_ref, balance_after)
    values (target_org, -b.subscription_credits, 'subscription', 'expire.cycle', cycle_key, 0);
  end if;
  update public.credit_balances
     set subscription_credits = allowance,
         cycle_start = coalesce(p_cycle_start, now()::date),
         cycle_end   = p_cycle_end,
         updated_at  = now()
   where org_id = target_org;
  insert into public.credit_ledger (org_id, delta, bucket, reason, stripe_ref, balance_after)
  values (target_org, allowance, 'subscription', 'grant.cycle', cycle_key, allowance)
  on conflict (org_id, reason, stripe_ref) where reason = 'grant.cycle' do nothing;
  perform app.log_audit_event(target_org, null, 'credits.cycle_granted', null,
    jsonb_build_object('cycle_key', cycle_key, 'allowance', allowance,
                       'expired', b.subscription_credits));
  return jsonb_build_object('granted', true, 'cycle_key', cycle_key, 'allowance', allowance);
end $$;

-- Grant the current cycle if it has not been granted yet. Called by the
-- Stripe webhook after a subscriptions upsert, by the scheduler sweep, and
-- opportunistically by the API before a consume — all idempotent by key.
create or replace function app.ensure_cycle_grant(target_org uuid)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  k text := app.org_cycle_key(target_org);
  s record;
begin
  if exists (select 1 from public.credit_ledger
             where org_id = target_org and reason = 'grant.cycle' and stripe_ref = k) then
    return jsonb_build_object('granted', false, 'reason', 'already_granted', 'cycle_key', k);
  end if;
  select current_period_start::date as cs, current_period_end::date as ce into s
  from public.subscriptions where org_id = target_org;
  return app.grant_cycle_credits(target_org, k, s.cs, s.ce);
end $$;

-- Pack purchase (Stripe checkout.session.completed). Idempotent by stripe_ref.
create or replace function app.grant_purchased_credits(target_org uuid, n int, ref text)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare b public.credit_balances;
begin
  if n is null or n <= 0 then
    raise exception 'invalid pack size %', n;
  end if;
  if ref is null or ref = '' then
    raise exception 'grant_purchased_credits requires a stripe_ref';
  end if;
  b := app._lock_credit_balance(target_org);
  if exists (select 1 from public.credit_ledger
             where reason = 'grant.pack' and stripe_ref = ref) then
    return jsonb_build_object('granted', false, 'reason', 'already_granted', 'stripe_ref', ref);
  end if;
  update public.credit_balances
     set purchased_credits = purchased_credits + n, updated_at = now()
   where org_id = target_org;
  insert into public.credit_ledger (org_id, delta, bucket, reason, stripe_ref, balance_after)
  values (target_org, n, 'purchased', 'grant.pack', ref, b.purchased_credits + n)
  on conflict (stripe_ref) where reason = 'grant.pack' do nothing;
  perform app.log_audit_event(target_org, null, 'credits.pack_granted', null,
    jsonb_build_object('credits', n, 'stripe_ref', ref));
  return jsonb_build_object('granted', true, 'credits', n,
                            'pack_bal', b.purchased_credits + n);
end $$;

-- Manual adjustment (admin route only; dual-logged there). Positive or
-- negative; negative clamps at zero rather than raising.
create or replace function app.adjust_credits_manual(
  target_org uuid, n int, bucket_name text, p_actor uuid, note text default null)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  b public.credit_balances;
  applied int;
  new_bal int;
begin
  if bucket_name not in ('subscription','purchased') then
    raise exception 'bucket must be subscription|purchased';
  end if;
  if n is null or n = 0 then
    raise exception 'adjustment must be non-zero';
  end if;
  b := app._lock_credit_balance(target_org);
  if bucket_name = 'subscription' then
    applied := greatest(n, -b.subscription_credits);
    new_bal := b.subscription_credits + applied;
    update public.credit_balances set subscription_credits = new_bal, updated_at = now()
     where org_id = target_org;
  else
    applied := greatest(n, -b.purchased_credits);
    new_bal := b.purchased_credits + applied;
    update public.credit_balances set purchased_credits = new_bal, updated_at = now()
     where org_id = target_org;
  end if;
  if applied <> 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, balance_after, actor)
    values (target_org, applied, bucket_name,
            case when applied > 0 then 'grant.manual' else 'adjust.manual' end,
            new_bal, p_actor);
  end if;
  perform app.log_audit_event(target_org, p_actor, 'credits.manual_adjust', null,
    jsonb_build_object('requested', n, 'applied', applied, 'bucket', bucket_name,
                       'note', note));
  return jsonb_build_object('applied', applied, 'bucket', bucket_name, 'balance', new_bal);
end $$;

-- System-initiated refund for runs that failed on OUR side (DLQ / llm_error /
-- infra). Reverses exactly what the run's consume.run rows spent, per bucket,
-- minus anything already refunded — idempotent under double-fire (worker +
-- watchdog). The amount is ledger-derived; a caller-supplied n is recorded
-- but never trusted.
create or replace function app.refund_credits(
  target_org uuid, target_run uuid, n int default null,
  p_reason text default 'refund.system_failure')
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  b public.credit_balances;
  sub_spent  int;
  pack_spent int;
  r jsonb;
begin
  if p_reason <> 'refund.system_failure' then
    raise exception 'refund_credits only issues system-failure refunds (got %)', p_reason;
  end if;
  if target_run is null then
    raise exception 'refund_credits requires a run id';
  end if;
  b := app._lock_credit_balance(target_org);
  select coalesce(sum(case when reason = 'consume.run' and bucket = 'subscription' then -delta
                           when reason = 'refund.system_failure' and bucket = 'subscription' then -delta
                           else 0 end), 0),
         coalesce(sum(case when reason = 'consume.run' and bucket = 'purchased' then -delta
                           when reason = 'refund.system_failure' and bucket = 'purchased' then -delta
                           else 0 end), 0)
    into sub_spent, pack_spent
    from public.credit_ledger
   where org_id = target_org and run_id = target_run
     and reason in ('consume.run','refund.system_failure');
  if sub_spent <= 0 and pack_spent <= 0 then
    return jsonb_build_object('refunded', 0, 'reason', 'nothing_to_refund');
  end if;
  update public.credit_balances
     set subscription_credits = subscription_credits + greatest(sub_spent, 0),
         purchased_credits    = purchased_credits    + greatest(pack_spent, 0),
         updated_at = now()
   where org_id = target_org;
  if sub_spent > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, sub_spent, 'subscription', 'refund.system_failure', target_run,
            b.subscription_credits + sub_spent);
  end if;
  if pack_spent > 0 then
    insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
    values (target_org, pack_spent, 'purchased', 'refund.system_failure', target_run,
            b.purchased_credits + pack_spent);
  end if;
  perform app.log_audit_event(target_org, null, 'credits.refunded',
    'analysis_run:' || target_run::text,
    jsonb_build_object('subscription', greatest(sub_spent, 0),
                       'purchased', greatest(pack_spent, 0),
                       'caller_claimed', n));
  return jsonb_build_object('refunded', greatest(sub_spent,0) + greatest(pack_spent,0),
                            'subscription', greatest(sub_spent, 0),
                            'purchased', greatest(pack_spent, 0));
end $$;

-- Balance snapshot for the UI / GET /v1/credits.
create or replace function app.credit_balance(target_org uuid)
returns jsonb
language plpgsql stable security definer set search_path = public, extensions as $$
declare
  t text := app.org_tier(target_org);
  b public.credit_balances;
  price jsonb;
begin
  if auth.uid() is not null and not app.is_org_member(target_org) then
    raise exception 'not a member of org %', target_org;
  end if;
  select * into b from public.credit_balances where org_id = target_org;
  select jsonb_object_agg(asset_kind, credits) into price
  from public.credit_costs where tier = t;
  return jsonb_build_object(
    'tier', t,
    'subscription_credits', coalesce(b.subscription_credits, 0),
    'purchased_credits',    coalesce(b.purchased_credits, 0),
    'total',                coalesce(b.subscription_credits, 0) + coalesce(b.purchased_credits, 0),
    'cycle_start',          b.cycle_start,
    'cycle_end',            b.cycle_end,
    'credits_per_month',    (select credits_per_month from public.plan_entitlements where tier = t),
    'price_list',           coalesce(price, '{}'::jsonb));
end $$;

-- Ledger-vs-balance reconcile (scheduler, nightly). Returns rows only where
-- the derived balance disagrees with the stored one — 0 rows = clean.
create or replace function app.reconcile_credit_balances()
returns table (org_id uuid, bucket text, ledger_sum bigint, stored int)
language sql stable security definer set search_path = public, extensions as $$
  with sums as (
    select l.org_id, l.bucket, sum(l.delta) as ledger_sum
    from public.credit_ledger l group by l.org_id, l.bucket
  ), both_buckets as (
    select b.org_id, x.bucket,
           coalesce(s.ledger_sum, 0) as ledger_sum,
           case x.bucket when 'subscription' then b.subscription_credits
                         else b.purchased_credits end as stored
    from public.credit_balances b
    cross join (values ('subscription'), ('purchased')) as x(bucket)
    left join sums s on s.org_id = b.org_id and s.bucket = x.bucket
  )
  select * from both_buckets where ledger_sum <> stored
$$;

-- ---------------------------------------------------------------------------
-- app.create_org now also grants the first free-tier cycle so a fresh org can
-- run immediately (forward-only replacement of the 0002 definition).

create or replace function app.create_org(org_name text) returns uuid
language plpgsql security definer set search_path = public, extensions as $$
declare new_org uuid;
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;
  insert into public.orgs (name) values (org_name) returning id into new_org;
  insert into public.memberships (org_id, user_id, role)
  values (new_org, auth.uid(), 'owner');
  insert into public.subscriptions (org_id, tier, status,
                                    current_period_start, current_period_end)
  values (new_org, 'free', 'active', date_trunc('month', now()),
          date_trunc('month', now()) + interval '1 month');
  perform app.ensure_cycle_grant(new_org);
  return new_org;
end $$;

-- ---------------------------------------------------------------------------
-- Deprecations (kept one release for rollback — spec §7).
-- app.consume_scan_quota() / app.scans_used() are superseded by the credit
-- system; scans_per_month stays as a column but is no longer enforced.

comment on function app.consume_scan_quota(uuid, uuid) is
  'DEPRECATED (0008): superseded by app.consume_credits — kept one release for rollback.';
comment on function app.scans_used(uuid) is
  'DEPRECATED (0008): superseded by the credit ledger — kept one release for rollback.';
comment on column public.plan_entitlements.scans_per_month is
  'DEPRECATED (0008): no longer enforced; see credits_per_month.';

-- check_quota now reports the credit balance so existing callers keep working.
create or replace function app.check_quota(target_org uuid) returns jsonb
language sql stable security definer set search_path = public, extensions as $$
  select app.credit_balance(target_org)
      || jsonb_build_object(
           'model',      t.llm_model,
           'api_access', t.api_access,
           'limit',      t.credits_per_month,
           'used',       coalesce((select sum(-l.delta)
                                   from public.credit_ledger l
                                   join public.credit_balances b on b.org_id = l.org_id
                                   where l.org_id = target_org
                                     and l.reason = 'consume.run'
                                     and l.bucket = 'subscription'
                                     and (b.cycle_start is null
                                          or l.created_at >= b.cycle_start)), 0),
           'remaining',  (app.credit_balance(target_org)->>'total')::int,
           'currency',   'credits')
  from public.plan_entitlements t
  where t.tier = app.org_tier(target_org)
$$;

-- ---------------------------------------------------------------------------
-- RLS + grants: members read own-org balances and ledger; ALL writes are
-- service paths only (no authenticated write policies exist on purpose).
-- credit_costs is the public price list.

alter table public.credit_balances enable row level security;
alter table public.credit_ledger   enable row level security;
alter table public.credit_costs    enable row level security;

drop policy if exists credit_balances_member_read on public.credit_balances;
create policy credit_balances_member_read on public.credit_balances
  for select to authenticated
  using (org_id in (select app.user_org_ids()));

drop policy if exists credit_ledger_member_read on public.credit_ledger;
create policy credit_ledger_member_read on public.credit_ledger
  for select to authenticated
  using (org_id in (select app.user_org_ids()));

drop policy if exists credit_costs_public_read on public.credit_costs;
create policy credit_costs_public_read on public.credit_costs
  for select to anon, authenticated using (true);

grant select on public.credit_balances to authenticated;
grant select on public.credit_ledger   to authenticated;
grant select on public.credit_costs    to anon, authenticated;

-- Function grants: money-moving functions are service-side only.
revoke all on function app.credit_cost(uuid, text, int)                          from public, anon;
revoke all on function app._lock_credit_balance(uuid)                            from public, anon, authenticated;
revoke all on function app.consume_credits(uuid, uuid, int)                      from public, anon, authenticated;
revoke all on function app.org_cycle_key(uuid)                                   from public, anon, authenticated;
revoke all on function app.grant_cycle_credits(uuid, text, date, date)           from public, anon, authenticated;
revoke all on function app.ensure_cycle_grant(uuid)                              from public, anon, authenticated;
revoke all on function app.grant_purchased_credits(uuid, int, text)              from public, anon, authenticated;
revoke all on function app.adjust_credits_manual(uuid, int, text, uuid, text)    from public, anon, authenticated;
revoke all on function app.refund_credits(uuid, uuid, int, text)                 from public, anon, authenticated;
revoke all on function app.credit_balance(uuid)                                  from public, anon;
revoke all on function app.reconcile_credit_balances()                           from public, anon, authenticated;

grant execute on function app.credit_cost(uuid, text, int)     to authenticated, service_role;
grant execute on function app.credit_balance(uuid)              to authenticated, service_role;
grant execute on function app.consume_credits(uuid, uuid, int)  to service_role;
grant execute on function app.org_cycle_key(uuid)               to service_role;
grant execute on function app.grant_cycle_credits(uuid, text, date, date) to service_role;
grant execute on function app.ensure_cycle_grant(uuid)          to service_role;
grant execute on function app.grant_purchased_credits(uuid, int, text) to service_role;
grant execute on function app.adjust_credits_manual(uuid, int, text, uuid, text) to service_role;
grant execute on function app.refund_credits(uuid, uuid, int, text) to service_role;
grant execute on function app.reconcile_credit_balances()       to service_role;

commit;
