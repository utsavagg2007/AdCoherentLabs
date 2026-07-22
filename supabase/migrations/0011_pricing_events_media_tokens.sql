-- 0011_pricing_events_media_tokens.sql — four additions for the product build:
--
--   1. Published tier + credit-pack PRICING owned by the backend (the
--      marketing page renders GET /v1/plans; what is published is literally
--      what checkout charges). Stripe price IDs remain the billing rail when
--      configured; this table is the display/dev-checkout source of truth.
--   2. run_events — the sanitized live-activity feed a user watches while
--      the engine runs (stage transitions + aggregate counts ONLY; never
--      prompts, retrieved chunks, or model reasoning).
--   3. Media entitlements — per-tier allowed asset kinds and a video length
--      cap (free: text/html/image/pdf/docx; hobby: + video <= 60s;
--      pro/design/enterprise: video uncapped up to the upload MB cap).
--      credit_costs gains pdf/docx/video rows and app.credit_cost learns the
--      new kinds.
--   4. Token-metered settlement — the LLM component of a run is charged from
--      actual input/output tokens at published per-tier rates (calibrated
--      ~2.5-3x provider list price; the base kind cost charged at enqueue
--      covers CV/OCR/RAG/infra). app.settle_run_tokens consumes the token
--      component post-run; ledger reason 'consume.tokens'. If the balance
--      cannot cover it the charge clamps to the available balance and the
--      shortfall is audited (the run already happened — we never fail the
--      report over the residual).
--
-- Idempotent: safe to re-run.

begin;

-- ---------------------------------------------------------------------------
-- 1. Published pricing

create table if not exists public.plan_pricing (
  tier              text primary key references public.plan_entitlements(tier),
  monthly_usd_cents int,                 -- null = custom / contact sales
  display_order     int not null default 0,
  tagline           text not null default '',
  is_public         boolean not null default true,
  updated_at        timestamptz not null default now()
);

insert into public.plan_pricing (tier, monthly_usd_cents, display_order, tagline) values
  ('free',       0,     1, 'Evaluate the review loop on real creatives.'),
  ('hobby',      1900,  2, 'For a founder or solo marketer shipping steadily.'),
  ('pro',        9900,  3, 'For compliance teams reviewing every launch.'),
  ('design',     39900, 4, 'For agencies and studios running review at volume.'),
  ('enterprise', null,  5, 'Custom provisioning, custom controls.')
on conflict (tier) do update
  set monthly_usd_cents = excluded.monthly_usd_cents,
      display_order     = excluded.display_order,
      tagline           = excluded.tagline;

create table if not exists public.pack_pricing (
  pack      text primary key,            -- starter | growth | scale
  credits   int  not null check (credits > 0),
  usd_cents int  not null check (usd_cents > 0),
  is_public boolean not null default true,
  updated_at timestamptz not null default now()
);

insert into public.pack_pricing (pack, credits, usd_cents) values
  ('starter',   500,   900),
  ('growth',  2500,  3900),
  ('scale',  12000, 14900)
on conflict (pack) do update
  set credits = excluded.credits, usd_cents = excluded.usd_cents;

-- ---------------------------------------------------------------------------
-- 2. Live-activity events (sanitized; polled via the backend API)

create table if not exists public.run_events (
  id         bigserial primary key,
  run_id     uuid not null references public.analysis_runs(id) on delete cascade,
  org_id     uuid not null references public.orgs(id) on delete cascade,
  stage      text not null check (stage in
               ('queued','ingest','cv','nlp','retrieval','llm','rules','report','done','error')),
  event      text not null,              -- machine code, e.g. 'cv.segments'
  message    text not null,              -- user-facing line, pre-sanitized
  detail     jsonb not null default '{}'::jsonb,  -- aggregate counts only
  created_at timestamptz not null default now()
);

create index if not exists ix_run_events_run on public.run_events (run_id, id);

alter table public.run_events enable row level security;

drop policy if exists run_events_member_read on public.run_events;
create policy run_events_member_read on public.run_events
  for select to authenticated
  using (org_id in (select app.user_org_ids()));

grant select on public.run_events to authenticated;
-- writes are service paths only (no authenticated write policy on purpose)

-- ---------------------------------------------------------------------------
-- 3. Media entitlements + credit costs for the new kinds

alter table public.plan_entitlements
  add column if not exists allowed_kinds     jsonb not null default '["text","html","image"]'::jsonb,
  add column if not exists max_video_seconds int;   -- null = no per-length cap (MB cap still applies)

update public.plan_entitlements set
  allowed_kinds = '["text","html","image","pdf","docx"]'::jsonb,
  max_video_seconds = null
  where tier = 'free';
update public.plan_entitlements set
  allowed_kinds = '["text","html","image","pdf","docx","video"]'::jsonb,
  max_video_seconds = 60
  where tier = 'hobby';
update public.plan_entitlements set
  allowed_kinds = '["text","html","image","pdf","docx","video"]'::jsonb,
  max_video_seconds = null
  where tier in ('pro','design','enterprise');

-- credit_costs: widen the kind vocabulary (constraint predates pdf/docx/video)
alter table public.credit_costs drop constraint if exists credit_costs_asset_kind_check;
alter table public.credit_costs add constraint credit_costs_asset_kind_check
  check (asset_kind in ('text','image','html','carousel_card','pdf','docx','video'));

-- Base run prices for the new kinds (same x1/x2/x5/x10/x10 tier multipliers
-- as 0008; video is priced for keyframe-sampled CV work).
insert into public.credit_costs (asset_kind, tier, credits) values
  ('pdf',   'free', 3),  ('pdf',   'hobby', 6),  ('pdf',   'pro', 15), ('pdf',   'design', 30),  ('pdf',   'enterprise', 30),
  ('docx',  'free', 2),  ('docx',  'hobby', 4),  ('docx',  'pro', 10), ('docx',  'design', 20),  ('docx',  'enterprise', 20),
  ('video', 'free', 10), ('video', 'hobby', 20), ('video', 'pro', 50), ('video', 'design', 100), ('video', 'enterprise', 100)
on conflict (asset_kind, tier) do update set credits = excluded.credits;

-- app.credit_cost learns the new kinds (forward-only replacement of 0008).
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
  if kind in ('text','image','html','pdf','docx','video') then
    select credits into c from public.credit_costs where asset_kind = kind and tier = t;
  elsif kind = 'carousel' then
    n := least(greatest(coalesce(cards, 1), 1), 10);   -- cards capped at 10
    select (select credits from public.credit_costs where asset_kind = 'image' and tier = t)
         + (n - 1) * (select credits from public.credit_costs where asset_kind = 'carousel_card' and tier = t)
      into c;
  else
    raise exception 'unknown asset kind % (text|image|html|pdf|docx|video|carousel)', kind;
  end if;
  if c is null then
    raise exception 'no credit_costs row for kind=% tier=%', kind, t;
  end if;
  return c;
end $$;

-- ---------------------------------------------------------------------------
-- 4. Token-metered settlement

-- Published per-tier token rates: credits per 1,000 tokens, split in/out.
-- Calibrated ~2.5-3x the routed provider's list price at ~USD 0.015/credit
-- (free/hobby -> OpenRouter qwen3.7-plus/max, pro -> claude-sonnet-5,
-- design/enterprise -> claude-opus-4-8). Rounded UP to keep the margin.
create table if not exists public.token_rates (
  tier            text primary key references public.plan_entitlements(tier),
  in_per_1k       numeric(8,3) not null check (in_per_1k  >= 0),
  out_per_1k      numeric(8,3) not null check (out_per_1k >= 0),
  min_credits     int not null default 0 check (min_credits >= 0),
  updated_at      timestamptz not null default now()
);

insert into public.token_rates (tier, in_per_1k, out_per_1k, min_credits) values
  ('free',       0.080,  0.250, 0),
  ('hobby',      0.300,  1.200, 1),
  ('pro',        0.600,  3.000, 2),
  ('design',     3.000, 14.000, 5),
  ('enterprise', 3.000, 14.000, 5)
on conflict (tier) do update
  set in_per_1k = excluded.in_per_1k, out_per_1k = excluded.out_per_1k,
      min_credits = excluded.min_credits;

alter table public.plan_pricing  enable row level security;
alter table public.pack_pricing  enable row level security;
alter table public.token_rates   enable row level security;

drop policy if exists plan_pricing_public_read on public.plan_pricing;
create policy plan_pricing_public_read on public.plan_pricing
  for select to anon, authenticated using (true);
drop policy if exists pack_pricing_public_read on public.pack_pricing;
create policy pack_pricing_public_read on public.pack_pricing
  for select to anon, authenticated using (true);
drop policy if exists token_rates_public_read on public.token_rates;
create policy token_rates_public_read on public.token_rates
  for select to anon, authenticated using (true);

grant select on public.plan_pricing to anon, authenticated;
grant select on public.pack_pricing to anon, authenticated;
grant select on public.token_rates  to anon, authenticated;

-- Ledger vocabulary: the token component consumes under its own reason so an
-- auditor can separate the base charge from usage settlement.
alter table public.credit_ledger drop constraint if exists credit_ledger_reason_check;
alter table public.credit_ledger add constraint credit_ledger_reason_check
  check (reason in ('grant.cycle','grant.pack','grant.manual','consume.run',
                    'consume.tokens','refund.system_failure','adjust.manual',
                    'expire.cycle'));

-- Post-run settlement. Charges ceil(in/1k*rate_in + out/1k*rate_out) with the
-- tier's min floor, clamped to the available balance (the run has already
-- produced its report; the residual is audited, never a failure). Idempotent
-- per run: a second call sees the existing consume.tokens rows and no-ops.
create or replace function app.settle_run_tokens(
  target_org uuid, target_run uuid, in_tok bigint, out_tok bigint)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  b public.credit_balances;
  r public.token_rates;
  cost int;
  total int;
  charge int;
  from_sub int;
  from_pack int;
begin
  if target_run is null then
    raise exception 'settle_run_tokens requires a run id';
  end if;
  select * into r from public.token_rates where tier = app.org_tier(target_org);
  if r is null then
    return jsonb_build_object('settled', false, 'reason', 'no_rates');
  end if;
  cost := greatest(
    ceil( coalesce(in_tok, 0)::numeric / 1000 * r.in_per_1k
        + coalesce(out_tok, 0)::numeric / 1000 * r.out_per_1k )::int,
    case when coalesce(in_tok, 0) + coalesce(out_tok, 0) > 0
         then r.min_credits else 0 end);
  if cost = 0 then
    return jsonb_build_object('settled', true, 'charged', 0, 'cost', 0);
  end if;
  b := app._lock_credit_balance(target_org);
  if exists (select 1 from public.credit_ledger
             where org_id = target_org and run_id = target_run
               and reason = 'consume.tokens') then
    return jsonb_build_object('settled', false, 'reason', 'already_settled');
  end if;
  total  := b.subscription_credits + b.purchased_credits;
  charge := least(cost, total);                    -- clamp, never negative
  from_sub  := least(b.subscription_credits, charge);
  from_pack := charge - from_sub;
  if charge > 0 then
    update public.credit_balances
       set subscription_credits = subscription_credits - from_sub,
           purchased_credits    = purchased_credits    - from_pack,
           updated_at = now()
     where org_id = target_org;
    if from_sub > 0 then
      insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
      values (target_org, -from_sub, 'subscription', 'consume.tokens', target_run,
              b.subscription_credits - from_sub);
    end if;
    if from_pack > 0 then
      insert into public.credit_ledger (org_id, delta, bucket, reason, run_id, balance_after)
      values (target_org, -from_pack, 'purchased', 'consume.tokens', target_run,
              b.purchased_credits - from_pack);
    end if;
  end if;
  perform app.log_audit_event(target_org, null, 'credits.tokens_settled',
    'analysis_run:' || target_run::text,
    jsonb_build_object('input_tokens', in_tok, 'output_tokens', out_tok,
                       'cost', cost, 'charged', charge,
                       'shortfall', cost - charge,
                       'sub_bal', b.subscription_credits - from_sub,
                       'pack_bal', b.purchased_credits - from_pack));
  return jsonb_build_object('settled', true, 'cost', cost, 'charged', charge,
                            'shortfall', cost - charge);
end $$;

revoke all on function app.settle_run_tokens(uuid, uuid, bigint, bigint)
  from public, anon, authenticated;
grant execute on function app.settle_run_tokens(uuid, uuid, bigint, bigint)
  to service_role;

-- ---------------------------------------------------------------------------
-- 5. Asset vocabulary + storage bucket for the new media kinds

-- assets.kind (0001) already lists pdf/video; docx is new.
alter table public.assets drop constraint if exists assets_kind_check;
alter table public.assets add constraint assets_kind_check
  check (kind in ('pdf','image','text','html','url','video','docx'));

-- Bucket MIME allowlist (0005) gains docx + the other video containers.
update storage.buckets set allowed_mime_types = array[
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'image/png','image/jpeg','image/webp','image/gif',
  'text/plain','text/html',
  'video/mp4','video/quicktime','video/webm']
where id = 'assets';

commit;
