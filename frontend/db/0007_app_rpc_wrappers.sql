-- 0007_app_rpc_wrappers.sql — public-schema wrappers for the frontend.
--
-- WHY: PostgREST (supabase-js .rpc()) only serves schemas listed in
-- PGRST_DB_SCHEMAS (default: public, storage, graphql_public). The SaaS
-- helper functions live in the `app` schema (migrations 0002/0004), so the
-- Next.js frontend cannot call them until they are wrapped in `public`.
--
-- HOW TO APPLY: copy this file into supabase/migrations/ and run
-- supabase/apply.sh — or pipe it straight into psql:
--   docker exec -i supabase-db psql -U postgres -d postgres < 0007_app_rpc_wrappers.sql
--
-- (Alternative: add `app` to PGRST_DB_SCHEMAS and call
-- supabase.schema('app').rpc(...) instead — then this file is unnecessary.)
--
-- Idempotent: safe to re-run.

begin;

-- Org creation (authenticated): atomic org + owner membership + free tier.
create or replace function public.create_org(org_name text) returns uuid
language sql volatile security invoker as
$$ select app.create_org(org_name) $$;

revoke all on function public.create_org(text) from public, anon;
grant execute on function public.create_org(text) to authenticated, service_role;

-- Quota snapshot (authenticated): used by dashboards / pre-flight checks.
create or replace function public.check_quota(target_org uuid) returns jsonb
language sql stable security invoker as
$$ select app.check_quota(target_org) $$;

revoke all on function public.check_quota(uuid) from public, anon;
grant execute on function public.check_quota(uuid) to authenticated, service_role;

-- Atomic consume-or-reject (SERVICE ROLE ONLY — called by the app server
-- before enqueueing a run, playbook Phase 4 "quota before expensive work").
create or replace function public.consume_scan_quota(
  target_org uuid, target_run uuid default null
) returns jsonb
language sql volatile security invoker as
$$ select app.consume_scan_quota(target_org, target_run) $$;

revoke all on function public.consume_scan_quota(uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.consume_scan_quota(uuid, uuid) to service_role;

-- PostgREST discovers new functions on schema reload:
notify pgrst, 'reload schema';

commit;
