-- 0009_job_queue.sql — durable Postgres-backed job queue (spec §10, D3).
-- Credit spend + run row + job row commit in ONE transaction (the API's
-- submissions route), so a crash between "charged" and "queued" is impossible
-- by construction. Workers lease with FOR UPDATE SKIP LOCKED honouring tier
-- priority, per-org concurrency caps, and least-recently-served org fairness.
--
-- Decision notes:
--   * The table lives in the `app` schema, not `public`: the spec requires
--     that members never see it, PostgREST only exposes `public`, and no
--     grants are issued — structural invisibility instead of an RLS policy.
--   * `leased_at` column (not in the spec's sketch) records when an org was
--     last served — the datum the least-recently-served-org ordering needs.
--   * app.lease_job serialises on one advisory lock. The concurrency wall
--     (org active-run count) is read inside the same lock, so two workers can
--     never over-admit an org. Lease throughput bound (~ms per lease) is
--     orders of magnitude above any plausible load (§10.1).
-- Idempotent: safe to re-run.

begin;

create table if not exists app.job_queue (
  id               bigserial primary key,
  run_id           uuid not null unique references public.analysis_runs(id) on delete cascade,
  org_id           uuid not null,
  tier             text not null,
  priority         int  not null,       -- enterprise 0 < design 10 < pro 20 < hobby 30 < free 40
  status           text not null default 'queued'
                   check (status in ('queued','leased','done','dlq')),
  attempts         int not null default 0,
  max_attempts     int not null default 3,
  not_before       timestamptz not null default now(),  -- backoff gate: 60s, 300s, 1500s
  locked_by        text,
  lease_expires_at timestamptz,          -- worker id + 300s lease
  leased_at        timestamptz,          -- org fairness datum
  last_error       text,
  created_at       timestamptz not null default now()
);

create index if not exists ix_jq_dequeue on app.job_queue (status, not_before, priority, created_at);
create index if not exists ix_jq_org_leased on app.job_queue (org_id) where status = 'leased';

revoke all on app.job_queue from anon, authenticated;

create or replace function app.tier_priority(t text) returns int
language sql immutable as $$
  select case t when 'enterprise' then 0 when 'design' then 10 when 'pro' then 20
                when 'hobby' then 30 else 40 end
$$;

-- Enqueue inside the SAME transaction as app.consume_credits + the run row
-- insert. Idempotent per run (unique run_id).
create or replace function app.enqueue_run(target_run uuid)
returns bigint
language plpgsql security definer set search_path = app, public, extensions as $$
declare
  r record;
  job_id bigint;
  t text;
begin
  select org_id into r from public.analysis_runs where id = target_run;
  if r.org_id is null then
    raise exception 'no analysis_runs row %', target_run;
  end if;
  t := app.org_tier(r.org_id);
  insert into app.job_queue (run_id, org_id, tier, priority)
  values (target_run, r.org_id, t, app.tier_priority(t))
  on conflict (run_id) do nothing
  returning id into job_id;
  if job_id is null then
    select id into job_id from app.job_queue where run_id = target_run;
  end if;
  return job_id;
end $$;

-- Atomic lease: oldest eligible job whose org is below its concurrency cap,
-- priority band first, least-recently-served org within the band. Returns the
-- leased job row (empty set when nothing is eligible).
create or replace function app.lease_job(worker_id text, lease_seconds int default 300)
returns setof app.job_queue
language plpgsql security definer set search_path = app, public, extensions as $$
declare
  j app.job_queue;
begin
  perform pg_advisory_xact_lock(hashtext('app.job_queue.lease'));
  select * into j
  from app.job_queue q
  where q.status = 'queued'
    and q.not_before <= now()
    and (select count(*) from app.job_queue a
         where a.org_id = q.org_id and a.status = 'leased'
           and a.lease_expires_at > now())
        < coalesce((select e.max_concurrent_runs from public.plan_entitlements e
                    where e.tier = app.org_tier(q.org_id)), 1)
  order by q.priority asc,
           coalesce((select max(a.leased_at) from app.job_queue a
                     where a.org_id = q.org_id), '-infinity'::timestamptz) asc,
           q.created_at asc
  for update skip locked
  limit 1;
  if j.id is null then
    return;
  end if;
  update app.job_queue
     set status = 'leased', locked_by = worker_id,
         lease_expires_at = now() + make_interval(secs => lease_seconds),
         leased_at = now(), attempts = attempts + 1
   where id = j.id;
  return query select * from app.job_queue where id = j.id;
end $$;

-- Fenced by locked_by: a worker whose lease was reclaimed cannot heartbeat,
-- complete, or fail a job that is no longer its own.
create or replace function app.heartbeat_job(job_id bigint, worker_id text,
                                             lease_seconds int default 300)
returns boolean
language sql security definer set search_path = app, public, extensions as $$
  update app.job_queue
     set lease_expires_at = now() + make_interval(secs => lease_seconds)
   where id = job_id and locked_by = worker_id and status = 'leased'
  returning true
$$;

create or replace function app.complete_job(job_id bigint, worker_id text)
returns boolean
language sql security definer set search_path = app, public, extensions as $$
  update app.job_queue
     set status = 'done', lease_expires_at = null
   where id = job_id and locked_by = worker_id and status = 'leased'
  returning true
$$;

-- Failure taxonomy §10.3: requeue with backoff (60s → 300s → 1500s) until
-- max_attempts, then DLQ. Returns the final disposition so the worker can
-- trigger refund + run-failed + alert on 'dlq'.
create or replace function app.fail_job(job_id bigint, worker_id text, err text)
returns jsonb
language plpgsql security definer set search_path = app, public, extensions as $$
declare
  j app.job_queue;
  delay int;
begin
  select * into j from app.job_queue
   where id = job_id and locked_by = worker_id and status = 'leased'
   for update;
  if j.id is null then
    return jsonb_build_object('disposition', 'not_owner');
  end if;
  if j.attempts >= j.max_attempts then
    update app.job_queue
       set status = 'dlq', last_error = left(err, 4000), lease_expires_at = null
     where id = job_id;
    perform app.log_audit_event(j.org_id, null, 'job.dlq',
      'analysis_run:' || j.run_id::text,
      jsonb_build_object('job_id', job_id, 'attempts', j.attempts,
                         'error', left(err, 500)));
    return jsonb_build_object('disposition', 'dlq', 'attempts', j.attempts,
                              'run_id', j.run_id, 'org_id', j.org_id);
  end if;
  delay := least(60 * (5 ^ (j.attempts - 1))::int, 1500);   -- 60, 300, 1500
  update app.job_queue
     set status = 'queued', locked_by = null, lease_expires_at = null,
         last_error = left(err, 4000),
         not_before = now() + make_interval(secs => delay)
   where id = job_id;
  return jsonb_build_object('disposition', 'requeued', 'attempts', j.attempts,
                            'retry_in_seconds', delay, 'run_id', j.run_id,
                            'org_id', j.org_id);
end $$;

-- Breaker-open release: put the job back WITHOUT consuming an attempt (the
-- provider being down is not this job's failure). Only the lease holder may
-- release.
create or replace function app.release_job(job_id bigint, worker_id text,
                                           delay_seconds int default 60)
returns boolean
language sql security definer set search_path = app, public, extensions as $$
  update app.job_queue
     set status = 'queued', locked_by = null, lease_expires_at = null,
         attempts = greatest(attempts - 1, 0),
         not_before = now() + make_interval(secs => delay_seconds)
   where id = job_id and locked_by = worker_id and status = 'leased'
  returning true
$$;

-- Watchdog (scheduler): reclaim expired leases — a worker that died mid-run
-- stops heartbeating and its job returns to the queue (or DLQs if the failed
-- attempt was its last). Returns one row per reclaimed job so the scheduler
-- can refund + fail the run for DLQ'd ones.
create or replace function app.requeue_expired_jobs()
returns table (job_id bigint, run_id uuid, org_id uuid, disposition text)
language plpgsql security definer set search_path = app, public, extensions as $$
declare
  j record;
begin
  for j in
    select * from app.job_queue
     where status = 'leased' and lease_expires_at < now()
     for update skip locked
  loop
    if j.attempts >= j.max_attempts then
      update app.job_queue
         set status = 'dlq', locked_by = null, lease_expires_at = null,
             last_error = coalesce(last_error, 'lease expired (worker died)')
       where id = j.id;
      perform app.log_audit_event(j.org_id, null, 'job.dlq',
        'analysis_run:' || j.run_id::text,
        jsonb_build_object('job_id', j.id, 'attempts', j.attempts,
                           'error', 'lease expired'));
      job_id := j.id; run_id := j.run_id; org_id := j.org_id; disposition := 'dlq';
    else
      update app.job_queue
         set status = 'queued', locked_by = null, lease_expires_at = null,
             last_error = coalesce(last_error, 'lease expired (worker died)'),
             not_before = now()
       where id = j.id;
      perform app.log_audit_event(j.org_id, null, 'job.lease_reclaimed',
        'analysis_run:' || j.run_id::text,
        jsonb_build_object('job_id', j.id, 'attempts', j.attempts));
      job_id := j.id; run_id := j.run_id; org_id := j.org_id; disposition := 'requeued';
    end if;
    return next;
  end loop;
end $$;

-- Admin: requeue a DLQ'd job (fresh attempts). The credits were refunded when
-- it DLQ'd, so the re-run is on the house — an ops decision, dual-audited by
-- the admin route.
create or replace function app.requeue_dlq_job(job_id bigint)
returns boolean
language sql security definer set search_path = app, public, extensions as $$
  update app.job_queue
     set status = 'queued', attempts = 0, locked_by = null,
         lease_expires_at = null, not_before = now()
   where id = job_id and status = 'dlq'
  returning true
$$;

-- Ops snapshot for /metrics and the admin API.
create or replace function app.queue_stats()
returns jsonb
language sql stable security definer set search_path = app, public, extensions as $$
  select jsonb_build_object(
    'queued', count(*) filter (where status = 'queued'),
    'leased', count(*) filter (where status = 'leased'),
    'done',   count(*) filter (where status = 'done'),
    'dlq',    count(*) filter (where status = 'dlq'),
    'oldest_queued_seconds',
      coalesce(extract(epoch from now() - min(created_at)
                                          filter (where status = 'queued')), 0)::bigint)
  from app.job_queue
$$;

-- Service paths only — members never see this table or its functions.
revoke all on function app.tier_priority(text)                    from public, anon, authenticated;
revoke all on function app.enqueue_run(uuid)                      from public, anon, authenticated;
revoke all on function app.lease_job(text, int)                   from public, anon, authenticated;
revoke all on function app.heartbeat_job(bigint, text, int)       from public, anon, authenticated;
revoke all on function app.complete_job(bigint, text)             from public, anon, authenticated;
revoke all on function app.fail_job(bigint, text, text)           from public, anon, authenticated;
revoke all on function app.release_job(bigint, text, int)         from public, anon, authenticated;
revoke all on function app.requeue_expired_jobs()                 from public, anon, authenticated;
revoke all on function app.requeue_dlq_job(bigint)                from public, anon, authenticated;
revoke all on function app.queue_stats()                          from public, anon, authenticated;

grant execute on function app.enqueue_run(uuid)                to service_role;
grant execute on function app.lease_job(text, int)             to service_role;
grant execute on function app.heartbeat_job(bigint, text, int) to service_role;
grant execute on function app.complete_job(bigint, text)       to service_role;
grant execute on function app.fail_job(bigint, text, text)     to service_role;
grant execute on function app.release_job(bigint, text, int)   to service_role;
grant execute on function app.requeue_expired_jobs()           to service_role;
grant execute on function app.requeue_dlq_job(bigint)          to service_role;
grant execute on function app.queue_stats()                    to service_role;

commit;
