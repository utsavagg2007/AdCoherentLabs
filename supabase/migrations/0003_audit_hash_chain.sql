-- 0003_audit_hash_chain.sql — tamper-evident audit log.
-- Playbook Phase 2: each entry stores sha256(prev_hash + canonical event), so
-- any retroactive edit breaks the chain. The table is append-only for every
-- role, including service_role.

begin;

-- Chain trigger. The advisory xact lock serialises concurrent inserts so two
-- transactions can't both chain off the same predecessor.
create or replace function app.audit_log_hash() returns trigger
language plpgsql security definer set search_path = public, extensions as $$
declare prev text;
begin
  perform pg_advisory_xact_lock(hashtext('audit_logs_chain'));
  select hash into prev from public.audit_logs order by id desc limit 1;
  new.created_at := coalesce(new.created_at, now());
  new.prev_hash  := prev;
  new.hash := encode(
    extensions.digest(
      coalesce(prev, 'genesis') || jsonb_build_object(
        'org_id',     new.org_id,
        'actor',      new.actor,
        'action',     new.action,
        'target',     new.target,
        'meta',       new.meta,
        'created_at', new.created_at
      )::text,
      'sha256'),
    'hex');
  return new;
end $$;

drop trigger if exists audit_hash_chain on public.audit_logs;
create trigger audit_hash_chain
  before insert on public.audit_logs
  for each row execute function app.audit_log_hash();

-- Append-only enforcement (defence in depth on top of revoked grants).
create or replace function app.audit_block_mutation() returns trigger
language plpgsql as $$
begin
  raise exception 'audit_logs is append-only';
end $$;

drop trigger if exists audit_append_only on public.audit_logs;
create trigger audit_append_only
  before update or delete on public.audit_logs
  for each row execute function app.audit_block_mutation();

revoke update, delete, truncate on public.audit_logs from anon, authenticated, service_role;

-- Convenience writer for API/worker code paths.
create or replace function app.log_audit_event(
  p_org uuid, p_actor uuid, p_action text, p_target text,
  p_meta jsonb default '{}'::jsonb
) returns bigint
language plpgsql security definer set search_path = public, extensions as $$
declare new_id bigint;
begin
  insert into public.audit_logs (org_id, actor, action, target, meta)
  values (p_org, p_actor, p_action, p_target, coalesce(p_meta, '{}'::jsonb))
  returning id into new_id;
  return new_id;
end $$;

revoke all on function app.log_audit_event(uuid, uuid, text, text, jsonb) from public, anon;
grant execute on function app.log_audit_event(uuid, uuid, text, text, jsonb)
  to authenticated, service_role;

-- Verification: walk the chain and recompute every hash.
-- select * from app.verify_audit_chain() where not ok;  → 0 rows = intact.
create or replace function app.verify_audit_chain()
returns table (id bigint, ok boolean)
language plpgsql stable security definer set search_path = public, extensions as $$
declare
  r public.audit_logs%rowtype;
  expected_prev text := null;
  recomputed text;
begin
  for r in select * from public.audit_logs order by public.audit_logs.id loop
    recomputed := encode(
      extensions.digest(
        coalesce(expected_prev, 'genesis') || jsonb_build_object(
          'org_id',     r.org_id,
          'actor',      r.actor,
          'action',     r.action,
          'target',     r.target,
          'meta',       r.meta,
          'created_at', r.created_at
        )::text,
        'sha256'),
      'hex');
    id := r.id;
    ok := (r.hash = recomputed) and (r.prev_hash is not distinct from expected_prev);
    return next;
    expected_prev := r.hash;
  end loop;
end $$;

revoke all on function app.verify_audit_chain() from public, anon, authenticated;
grant execute on function app.verify_audit_chain() to service_role;

commit;
