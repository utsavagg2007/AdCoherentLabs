-- 0001_saas_core.sql — AdCoherent SaaS data plane: core multi-tenant schema.
-- Playbook Phase 2 / Appendix B. Every tenant table carries org_id; RLS is
-- added in 0002. Idempotent: safe to re-run.

begin;

create schema if not exists app;

-- Bookkeeping for the migration runner (apply.sh).
create table if not exists app.schema_migrations (
  filename   text primary key,
  applied_at timestamptz not null default now()
);

-- updated_at maintenance
create or replace function app.touch_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- ---------------------------------------------------------------------------
-- Plans (seeded in 0004) — created first so subscriptions can reference it.

create table if not exists public.plan_entitlements (
  tier              text primary key,
  llm_provider      text not null,
  llm_model         text not null,
  max_output_tokens int  not null,
  scans_per_month   int,              -- null = custom / uncapped (enterprise)
  seats             int,              -- null = custom
  api_access        boolean not null default false,
  sso               boolean not null default false,
  sla               boolean not null default false,
  frameworks        jsonb   not null default '"all"'::jsonb,  -- "all" | ["FTC",...]
  updated_at        timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Tenancy

create table if not exists public.orgs (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.memberships (
  org_id     uuid not null references public.orgs(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  role       text not null check (role in ('owner','admin','reviewer','viewer')),
  created_at timestamptz not null default now(),
  primary key (org_id, user_id)
);
create index if not exists memberships_user_idx on public.memberships (user_id);

-- Stripe-synced subscription state. The Stripe webhook is the only writer
-- (service_role); tier resolves entitlements.
create table if not exists public.subscriptions (
  org_id                 uuid primary key references public.orgs(id) on delete cascade,
  stripe_customer_id     text unique,
  stripe_subscription_id text unique,
  tier                   text not null default 'free' references public.plan_entitlements(tier),
  status                 text not null default 'active'
                         check (status in ('trialing','active','past_due','canceled','incomplete','unpaid')),
  current_period_start   timestamptz,
  current_period_end     timestamptz,
  updated_at             timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Review pipeline

create table if not exists public.submissions (
  id         uuid primary key default gen_random_uuid(),
  org_id     uuid not null references public.orgs(id) on delete cascade,
  created_by uuid not null references auth.users(id),
  title      text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists submissions_org_idx on public.submissions (org_id, created_at desc);

create table if not exists public.assets (
  id            uuid primary key default gen_random_uuid(),
  submission_id uuid not null references public.submissions(id) on delete cascade,
  org_id        uuid not null references public.orgs(id) on delete cascade,
  kind          text not null check (kind in ('pdf','image','text','html','url','video')),
  storage_path  text,                 -- storage.objects path: <org_id>/<submission_id>/<key>
  source_url    text,                 -- for kind = 'url'
  checksum      text,
  scan_status   text not null default 'pending'
                check (scan_status in ('pending','clean','infected','error')),
  created_at    timestamptz not null default now()
);
create index if not exists assets_org_idx on public.assets (org_id);
create index if not exists assets_submission_idx on public.assets (submission_id);

create table if not exists public.analysis_runs (
  id               uuid primary key default gen_random_uuid(),
  submission_id    uuid not null references public.submissions(id) on delete cascade,
  org_id           uuid not null references public.orgs(id) on delete cascade,
  status           text not null default 'queued'
                   check (status in ('queued','running_cv','running_nlp','running_llm',
                                     'running_rules','reconciling','complete','failed')),
  tier             text,              -- tier at run time (audit: entitlements may change later)
  model_id         text,              -- exact model that served layer 3
  prompt_version   text,
  rulepack_version text,
  rag_corpus_hash  text,
  input_tokens     int,
  output_tokens    int,
  cost_cents       int,
  error            text,
  started_at       timestamptz,
  finished_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists analysis_runs_org_idx on public.analysis_runs (org_id, created_at desc);
create index if not exists analysis_runs_status_idx on public.analysis_runs (status)
  where status not in ('complete','failed');

-- Per-layer output (CV/NLP/LLM/Rule) for traceability and partial re-runs.
create table if not exists public.layer_outputs (
  run_id     uuid not null references public.analysis_runs(id) on delete cascade,
  org_id     uuid not null references public.orgs(id) on delete cascade,
  layer      text not null check (layer in ('cv','nlp','llm','rule')),
  payload    jsonb not null,
  created_at timestamptz not null default now(),
  primary key (run_id, layer)
);
create index if not exists layer_outputs_org_idx on public.layer_outputs (org_id);

create table if not exists public.findings (
  id           uuid primary key default gen_random_uuid(),
  run_id       uuid not null references public.analysis_runs(id) on delete cascade,
  org_id       uuid not null references public.orgs(id) on delete cascade,
  framework    text not null,
  rule_ref     text,                  -- regulation citation / rule id
  severity     text not null check (severity in ('high','medium','low')),
  verdict      text not null check (verdict in ('potential_violation','needs_review','compliant')),
  confidence   numeric check (confidence between 0 and 1),
  location     jsonb,                 -- segment/entity ids, bbox
  message      text not null,         -- reasoning
  remediation  text,                  -- scope_of_improvement from layer 3 / rule fix
  status       text not null default 'open'
               check (status in ('open','approved','flagged','dismissed')),
  reviewed_by  uuid references auth.users(id),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists findings_org_idx on public.findings (org_id, created_at desc);
create index if not exists findings_run_idx on public.findings (run_id);

-- ---------------------------------------------------------------------------
-- Layer-4 rule packs (global, not tenant-scoped; versioned)

create table if not exists public.rule_packs (
  id           uuid primary key default gen_random_uuid(),
  framework    text not null,
  jurisdiction text not null default 'US',
  version      text not null,
  description  text,
  active       boolean not null default true,
  created_at   timestamptz not null default now(),
  unique (framework, jurisdiction, version)
);

create table if not exists public.rules (
  id               uuid primary key default gen_random_uuid(),
  rule_pack_id     uuid not null references public.rule_packs(id) on delete cascade,
  rule_key         text not null,     -- e.g. ftc-apr-disclosure-proximity
  definition       jsonb not null,    -- declarative rule DSL
  severity_default text check (severity_default in ('high','medium','low')),
  active           boolean not null default true,
  unique (rule_pack_id, rule_key)
);

-- ---------------------------------------------------------------------------
-- Metering & audit

create table if not exists public.usage_events (
  id           bigint generated always as identity primary key,
  org_id       uuid not null references public.orgs(id) on delete cascade,
  run_id       uuid references public.analysis_runs(id) on delete set null,
  user_id      uuid,
  kind         text not null check (kind in ('scan','token_spend','api_call','storage')),
  model        text,
  input_tokens int,
  output_tokens int,
  cost_cents   int,
  meta         jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);
create index if not exists usage_events_org_period_idx
  on public.usage_events (org_id, kind, created_at desc);

-- Hash-chained in 0003; append-only.
create table if not exists public.audit_logs (
  id         bigint generated always as identity primary key,
  org_id     uuid,
  actor      uuid,
  action     text not null,
  target     text,
  meta       jsonb not null default '{}'::jsonb,
  prev_hash  text,
  hash       text,
  created_at timestamptz not null default now()
);
create index if not exists audit_logs_org_idx on public.audit_logs (org_id, id desc);

-- Programmatic access (Pro+): store only a hash of the key.
create table if not exists public.api_keys (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null references public.orgs(id) on delete cascade,
  name         text not null,
  key_hash     text not null unique,  -- sha256(key); plaintext never stored
  scopes       text[] not null default '{submit,read}',
  created_by   uuid not null references auth.users(id),
  created_at   timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at   timestamptz
);
create index if not exists api_keys_org_idx on public.api_keys (org_id);

-- ---------------------------------------------------------------------------
-- updated_at triggers

do $$
declare t text;
begin
  foreach t in array array['orgs','subscriptions','submissions','analysis_runs','findings']
  loop
    execute format(
      'drop trigger if exists touch_updated_at on public.%I;
       create trigger touch_updated_at before update on public.%I
       for each row execute function app.touch_updated_at();', t, t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- Grants: anon gets nothing on the SaaS tables; authenticated is governed by
-- RLS (0002); service_role keeps full access for the API/worker.

revoke all on all tables in schema public from anon;
grant usage on schema app to authenticated, service_role;

commit;
