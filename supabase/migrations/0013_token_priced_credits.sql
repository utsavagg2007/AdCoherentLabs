-- 0013_token_priced_credits.sql — one price, everywhere: 2 credits per 1,000
-- engine tokens.
--
-- 0012 built the escrow (reserve → meter → settle) and priced effort from a
-- per-tier rate card: free paid 0.08/0.25 credits per 1k in/out tokens, design
-- paid 3/14. A run's charge also had a FLOOR — the published base price for
-- accepting the creative — so a run that used almost no model time still cost
-- the base price.
--
-- Product decision 2026-08-23: the deduction is the token count and nothing
-- else. Two credits per 1,000 tokens the engine consumes, input and output
-- alike, identical on every tier. No floor, no per-kind base price, no tier
-- multiplier.
--
--   charge = ceil((input_tokens + output_tokens) / 1000 * 2)
--
-- The escrow machinery is unchanged and still does the work: this migration
-- only moves the numbers it reads. `settle_hold` computes
-- `greatest(floor_credits, ceil(metered))`, so passing floor_credits = 0 from
-- the API (backend/app/routes/submissions.py) reduces that to `ceil(metered)`,
-- and setting both LLM rates to 2 makes `metered` equal
-- `(in + out) / 1000 * 2`. Nothing else needed changing to get the formula.
--
-- Decision notes (deviations recorded here per the ground rules):
--   * Every non-LLM unit goes to ZERO rather than being dropped. OCR pages, CV
--     frames, RAG queries and video seconds are still METERED into
--     effort_events — the margin view keeps working and the units can be
--     priced later — they just do not charge. Dropping them would throw away
--     the cost data the next pricing decision needs.
--   * credit_costs and app.credit_cost are NOT dropped. They remain the
--     PUBLISHED price list that GET /v1/plans serves and the marketing page
--     renders. They no longer participate in charging. Conflating "what we
--     advertise" with "what we charge" is what made 0011 hard to reason about.
--   * credit_forecast is rewritten because its cold-start branch was
--     `floor_c * 3` — a multiple of a base price that no longer means
--     anything. Under the new rate a text run meters ~73 credits while
--     `floor_c * 3` is ~9, and the escrow is a HARD ceiling: the engine reads
--     `headroom` off every meter_effort call and stops when it hits zero. An
--     un-resized forecast would not merely under-charge, it would truncate
--     every run mid-analysis. This is the part of the change that had to
--     happen atomically with the rate change.
--   * A PRICING EPOCH is introduced for the same reason. credit_forecast's
--     warm path takes p95 of the last 30 days of settled holds; every one of
--     those settled at the old rate and would drag the forecast down to about
--     a tenth of what a run now needs. The epoch marker makes the warm path
--     ignore holds settled before this migration, so it stays cold (and
--     generous) until 20 runs have settled under the new price.
--   * token_rates is updated in lockstep even though it is deprecated. It
--     still backs app.settle_run_tokens, which is the fallback for runs that
--     were enqueued before 0012 and have no hold. Leaving it at the old
--     numbers would price those runs differently from every other run.
--
-- Idempotent: safe to re-run.

begin;

-- ---------------------------------------------------------------------------
-- 1. The rate card: 2 credits per 1k tokens, every tier, input and output.

update public.effort_rates
   set credits = 2, updated_at = now()
 where unit in ('llm_input_1k', 'llm_output_1k');

-- Any tier added since 0012 that has no row yet.
insert into public.effort_rates (tier, unit, credits)
select t.tier, u.unit, 2
from public.plan_entitlements t
cross join (values ('llm_input_1k'), ('llm_output_1k')) as u(unit)
on conflict (tier, unit) do update set credits = 2, updated_at = now();

-- Everything else meters but does not charge. Still recorded in
-- effort_events, so app.run_margin keeps showing what these units cost.
update public.effort_rates
   set credits = 0, updated_at = now()
 where unit not in ('llm_input_1k', 'llm_output_1k');

-- The 0011 fallback path, kept consistent so a pre-0012 run in flight is
-- priced the same as everything else.
update public.token_rates set in_per_1k = 2, out_per_1k = 2;

-- ---------------------------------------------------------------------------
-- 2. Pricing epoch — the boundary the forecast must not look past.

create table if not exists public.pricing_epochs (
  effective_from timestamptz primary key default now(),
  note           text
);

insert into public.pricing_epochs (effective_from, note)
select now(), '0013: flat 2 credits per 1k engine tokens, no floor'
where not exists (
  select 1 from public.pricing_epochs
   where note like '0013:%');

-- ---------------------------------------------------------------------------
-- 3. Expected token spend per creative kind — the cold-start forecast.
--
-- These are ESTIMATES and only one of them is measured: a 3-round free-tier
-- text run was observed at 36,473 tokens (14,074 in / 22,399 out) on
-- 2026-07-22. The rest are scaled off it by how much input a kind adds — OCR
-- text for PDFs, frame descriptions for video. They exist to size an escrow
-- that gets refunded, not to price anything, so erring high costs a user
-- nothing but a temporarily larger hold.
--
-- The warm path in credit_forecast replaces these with observed p95 as soon as
-- 20 runs of a kind have settled under the current epoch. Tune here only if
-- runs are being truncated before that happens.

create table if not exists public.expected_tokens (
  kind       text primary key,
  tokens     bigint not null check (tokens > 0),
  measured   boolean not null default false,
  updated_at timestamptz not null default now()
);

insert into public.expected_tokens (kind, tokens, measured) values
  ('text',           40000, true),   -- 36,473 observed, rounded up
  ('html',           45000, false),  -- markup inflates the input side
  ('image',          55000, false),  -- + OCR text and CV descriptors
  ('pdf',            70000, false),  -- multi-page OCR dominates
  ('docx',           55000, false),
  ('video',          90000, false),  -- frame sampling, largest input
  ('carousel_card',  15000, false)   -- PER ADDITIONAL card beyond the first
on conflict (kind) do nothing;       -- never clobber a tuned value

-- ---------------------------------------------------------------------------
-- 4. credit_forecast — same signature, token-denominated.
--
-- Returns the escrow to hold ON TOP of the floor. The API now passes floor 0,
-- so in practice this IS the whole escrow.

create or replace function app.credit_forecast(
  target_org uuid, kind text, cards int default 1)
returns int
language plpgsql stable security definer set search_path = public, extensions as $$
declare
  t       text := app.org_tier(target_org);
  epoch   timestamptz;
  n       int;
  p95     numeric;
  toks    bigint;
  per_card bigint;
begin
  select max(effective_from) into epoch from public.pricing_epochs;
  epoch := coalesce(epoch, '-infinity'::timestamptz);

  -- Warm path: what runs of this kind and tier actually cost, under the
  -- CURRENT price. The epoch filter is what keeps old-rate holds out.
  select count(*), percentile_cont(0.95) within group (order by h.charged)
    into n, p95
  from public.credit_holds h
  join public.analysis_runs r on r.id = h.run_id
  join public.submissions s   on s.id = r.submission_id
  where h.status = 'settled'
    and h.charged is not null
    and r.tier = t
    and coalesce(s.params->>'pricing_kind', '') = kind
    and h.settled_at > greatest(epoch, now() - interval '30 days');

  if n >= 20 and p95 is not null then
    -- Headroom above p95 so the 95th-percentile run itself does not clip.
    return greatest(ceil(p95 * 1.25)::int, 1);
  end if;

  -- Cold path: expected tokens for this kind, priced at this org's rate, with
  -- the same 25% headroom. Unknown kinds fall back to the text estimate.
  select tokens into toks from public.expected_tokens where expected_tokens.kind = credit_forecast.kind;
  if toks is null then
    select tokens into toks from public.expected_tokens where expected_tokens.kind = 'text';
  end if;
  toks := coalesce(toks, 40000);

  if greatest(coalesce(cards, 1), 1) > 1 then
    select tokens into per_card from public.expected_tokens
     where expected_tokens.kind = 'carousel_card';
    toks := toks + coalesce(per_card, 0) * (greatest(cards, 1) - 1);
  end if;

  -- Split evenly between input and output: harmless while both rates are 2,
  -- and the place to revisit if they ever diverge (the measured run was
  -- 14,074 in / 22,399 out, so an even split under-weights output).
  -- Price through the live rate card rather than hardcoding 2,
  -- so retuning effort_rates retunes the forecast with it.
  return greatest(
    ceil((app.effort_cost(target_org, 'llm_input_1k',  toks / 2000.0)
        + app.effort_cost(target_org, 'llm_output_1k', toks / 2000.0)) * 1.25)::int,
    1);
end $$;

revoke all on function app.credit_forecast(uuid, text, int) from public, anon;
grant execute on function app.credit_forecast(uuid, text, int)
  to authenticated, service_role;

comment on function app.credit_forecast(uuid, text, int) is
  '0013: escrow size in credits. Warm path = p95 of settled holds for this '
  'tier+kind within the current pricing epoch (>=20 samples); cold path = '
  'public.expected_tokens priced through public.effort_rates. Both carry 25% '
  'headroom. Sizing only - the unused remainder is returned at settle.';

comment on table public.expected_tokens is
  'Cold-start token estimates for app.credit_forecast. Only kind=text is '
  'measured (36,473 tokens, 3-round free-tier run, 2026-07-22); the rest are '
  'scaled by expected input volume. Superseded per tier+kind by observed p95 '
  'once 20 runs settle in the current pricing epoch.';

comment on table public.pricing_epochs is
  'Marks a change in what a credit buys. app.credit_forecast ignores holds '
  'settled before the latest epoch so an old-rate p95 cannot undersize a '
  'new-rate escrow.';

comment on table public.credit_costs is
  '0013: PUBLISHED price list only (GET /v1/plans, marketing). No longer '
  'charges: the API reserves with floor_credits = 0 and the whole charge is '
  'metered tokens at public.effort_rates.';

-- ---------------------------------------------------------------------------
-- 5. Plan allowances — NOT changed here. Read this before shipping.
--
-- At 2 credits per 1k tokens, the one measured run (36,473 tokens) charges 73
-- credits, against 7 under the old rate. Today's monthly allowances buy:
--
--     tier         credits/mo    runs at 73 credits    runs before 0013
--     free                 25          0  (blocked)                   3
--     hobby               400          5                             57
--     pro               6,000         82                            857
--     design           50,000        685                          7,142
--
-- Free tier cannot complete a single review, and hobby drops from ~57 to ~5.
-- Allowances are a pricing decision, not a schema one, so this migration does
-- not touch them. Multiplying every allowance by 10 restores roughly today's
-- run counts (73/7 = 10.4):
--
--   update public.plan_entitlements set credits_per_month = 250    where tier = 'free';
--   update public.plan_entitlements set credits_per_month = 4000   where tier = 'hobby';
--   update public.plan_entitlements set credits_per_month = 60000  where tier = 'pro';
--   update public.plan_entitlements set credits_per_month = 500000 where tier = 'design';
--
-- Enterprise is null (unmetered) and needs nothing. Pack sizes in
-- public.pack_pricing want the same treatment if allowances move.

commit;
