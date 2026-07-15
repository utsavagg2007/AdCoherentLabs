-- 0010_billing_events.sql — Stripe webhook idempotency + API idempotency keys
-- + async-submission columns (spec §6.2, §9, §12).
--
-- Decision notes:
--   * billing_events / idempotency_keys live in the `app` schema (service
--     paths only, invisible to PostgREST) — same reasoning as app.job_queue.
--   * Idempotency-Key storage is Postgres, not Redis: the 24 h replay
--     guarantee must survive a Redis restart, and the submissions route
--     already holds a DB transaction. The scheduler purges expired rows.
--   * subscriptions.grace_until backs the §12.2 grace policy (payment failed →
--     7 days read-only warnings → submissions blocked with 403 billing_hold).
--   * submissions.target_jurisdictions/params: the async worker rebuilds the
--     engine input from DB rows (the job payload deliberately carries no
--     execution parameters — the DB decides).
-- Idempotent: safe to re-run.

begin;

-- Stripe webhook idempotency: insert-or-skip on receipt; the handler marks
-- processed_at; a replayed event id is a no-op (§12.2).
create table if not exists app.billing_events (
  id           text primary key,          -- Stripe event id (evt_...)
  type         text not null,
  payload      jsonb not null,
  processed_at timestamptz,
  error        text,
  received_at  timestamptz not null default now()
);

create index if not exists ix_billing_events_unprocessed
  on app.billing_events (received_at) where processed_at is null;

revoke all on app.billing_events from anon, authenticated;

-- Client Idempotency-Key on POST /v1/submissions: the key→response mapping is
-- stored for 24 h and the original 202 is replayed on duplicates (§6.2).
create table if not exists app.idempotency_keys (
  org_id       uuid not null references public.orgs(id) on delete cascade,
  key          text not null,
  endpoint     text not null,
  request_hash text,                      -- detects same-key-different-body misuse
  status_code  int,
  response     jsonb,
  created_at   timestamptz not null default now(),
  expires_at   timestamptz not null default now() + interval '24 hours',
  primary key (org_id, endpoint, key)
);

create index if not exists ix_idem_expiry on app.idempotency_keys (expires_at);

revoke all on app.idempotency_keys from anon, authenticated;

create or replace function app.purge_expired_idempotency_keys()
returns int
language sql security definer set search_path = app, public, extensions as $$
  with gone as (
    delete from app.idempotency_keys where expires_at < now() returning 1)
  select count(*)::int from gone
$$;

revoke all on function app.purge_expired_idempotency_keys() from public, anon, authenticated;
grant execute on function app.purge_expired_idempotency_keys() to service_role;

-- ---------------------------------------------------------------------------
-- Billing grace (§12.2): invoice.payment_failed / past_due → 7-day read-only
-- grace; after grace_until, submissions return 403 billing_hold until resolved.
-- Data is never deleted for a billing hold.

alter table public.subscriptions
  add column if not exists grace_until timestamptz;

-- ---------------------------------------------------------------------------
-- Async submissions: the worker rebuilds the engine input from these rows.

alter table public.submissions
  add column if not exists target_jurisdictions text[],
  add column if not exists params jsonb not null default '{}'::jsonb;

-- Operator guidance for resumed runs travels on the run row (auditable,
-- org-scoped, and the job payload stays parameter-free — the DB decides).
alter table public.analysis_runs
  add column if not exists operator_guidance text;

-- Optional per-key rate cap (≤ org cap), set at issuance (§9.2 key:{prefix}).
alter table public.api_keys
  add column if not exists rate_limit_rpm int check (rate_limit_rpm is null or rate_limit_rpm > 0);

-- The worker persists the complete EngineRunResult as a fifth layer output so
-- GET /v1/runs/{id}/report returns the engine's document verbatim.
alter table public.layer_outputs drop constraint if exists layer_outputs_layer_check;
alter table public.layer_outputs add constraint layer_outputs_layer_check
  check (layer in ('cv','nlp','llm','rule','report'));

commit;
