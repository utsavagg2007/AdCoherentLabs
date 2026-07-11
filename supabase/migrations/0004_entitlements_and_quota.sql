-- 0004_entitlements_and_quota.sql — five SaaS tiers + quota enforcement.
-- Tier → model routing matches the implemented LLM review layer
-- (rag-engine/adcoherent_rag/review/tiers.py). NOTE: the playbook's
-- Appendix A lists Pro = Opus 4.7, but the product decision implemented in
-- the engine is Pro = claude-sonnet-5 — this table is the single source of
-- truth the app should read.
--
-- Quota numbers follow the playbook's placeholders — replace them from a
-- real cost + margin model before launch.

begin;

insert into public.plan_entitlements
  (tier, llm_provider, llm_model, max_output_tokens, scans_per_month, seats,
   api_access, sso, sla, frameworks)
values
  ('free',       'qwen',      'qwen-turbo',      1500,  20,   1,  false, false, false, '["FTC"]'::jsonb),
  ('hobby',      'qwen',      'qwen-max',        3000,  150,  2,  false, false, false, '["FTC","GDPR"]'::jsonb),
  ('pro',        'anthropic', 'claude-sonnet-5', 8000,  1000, 8,  true,  false, false, '"all"'::jsonb),
  ('design',     'anthropic', 'claude-opus-4-8', 16000, 4000, 20, true,  false, false, '"all"'::jsonb),
  ('enterprise', 'anthropic', 'claude-opus-4-8', 32000, null, null, true, true, true,  '"all"'::jsonb)
on conflict (tier) do update set
  llm_provider      = excluded.llm_provider,
  llm_model         = excluded.llm_model,
  max_output_tokens = excluded.max_output_tokens,
  scans_per_month   = excluded.scans_per_month,
  seats             = excluded.seats,
  api_access        = excluded.api_access,
  sso               = excluded.sso,
  sla               = excluded.sla,
  frameworks        = excluded.frameworks,
  updated_at        = now();

-- ---------------------------------------------------------------------------
-- Tier resolution: active-ish subscription wins, else free.

create or replace function app.org_tier(target_org uuid) returns text
language sql stable security definer set search_path = public, extensions as $$
  select coalesce(
    (select tier from public.subscriptions
     where org_id = target_org
       and status in ('trialing','active','past_due')),
    'free')
$$;

-- Scans consumed in the current billing period (subscription period if known,
-- else calendar month).
create or replace function app.scans_used(target_org uuid) returns int
language sql stable security definer set search_path = public, extensions as $$
  select count(*)::int
  from public.usage_events u
  where u.org_id = target_org
    and u.kind = 'scan'
    and u.created_at >= coalesce(
      (select s.current_period_start from public.subscriptions s
       where s.org_id = target_org),
      date_trunc('month', now()))
$$;

-- Quota snapshot for dashboards and pre-flight checks.
-- remaining = null means custom/uncapped (enterprise).
create or replace function app.check_quota(target_org uuid) returns jsonb
language sql stable security definer set search_path = public, extensions as $$
  select jsonb_build_object(
    'tier',       t.tier,
    'model',      t.llm_model,
    'limit',      t.scans_per_month,
    'used',       app.scans_used(target_org),
    'remaining',  case when t.scans_per_month is null then null
                       else greatest(t.scans_per_month - app.scans_used(target_org), 0) end,
    'api_access', t.api_access)
  from public.plan_entitlements t
  where t.tier = app.org_tier(target_org)
$$;

revoke all on function app.org_tier(uuid) from public, anon;
revoke all on function app.scans_used(uuid) from public, anon;
revoke all on function app.check_quota(uuid) from public, anon;
grant execute on function app.org_tier(uuid) to authenticated, service_role;
grant execute on function app.scans_used(uuid) to authenticated, service_role;
grant execute on function app.check_quota(uuid) to authenticated, service_role;

-- Atomic consume-or-reject: the API calls this BEFORE enqueueing a run, so
-- quota is enforced before expensive work. Serialised per org via advisory
-- lock so parallel submissions can't slip past the cap. service_role only.
create or replace function app.consume_scan_quota(target_org uuid, target_run uuid default null)
returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare
  cap int;
  used int;
begin
  perform pg_advisory_xact_lock(hashtext('scan_quota:' || target_org::text));
  select scans_per_month into cap
  from public.plan_entitlements where tier = app.org_tier(target_org);
  used := app.scans_used(target_org);
  if cap is not null and used >= cap then
    return jsonb_build_object('allowed', false, 'used', used, 'limit', cap);
  end if;
  insert into public.usage_events (org_id, run_id, kind, meta)
  values (target_org, target_run, 'scan', jsonb_build_object('source', 'consume_scan_quota'));
  return jsonb_build_object('allowed', true, 'used', used + 1, 'limit', cap);
end $$;

revoke all on function app.consume_scan_quota(uuid, uuid) from public, anon, authenticated;
grant execute on function app.consume_scan_quota(uuid, uuid) to service_role;

commit;
