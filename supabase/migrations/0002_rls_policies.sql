-- 0002_rls_policies.sql — Row-Level Security: tenant isolation at the DB layer.
-- Playbook Phase 2. Pattern: a row is visible only to members of its org,
-- derived from the JWT (auth.uid()) — never from a request parameter.
--
-- REMEMBER: the worker/API use the service_role key, which BYPASSES all of
-- this. Every service_role code path must set org_id explicitly.

begin;

-- ---------------------------------------------------------------------------
-- Helpers (security definer so policies don't recurse into memberships RLS).
-- search_path pins to public + extensions (pgcrypto etc. live in extensions).

create or replace function app.user_org_ids() returns setof uuid
language sql stable security definer set search_path = public, extensions as
$$ select org_id from public.memberships where user_id = auth.uid() $$;

create or replace function app.is_org_member(target_org uuid) returns boolean
language sql stable security definer set search_path = public, extensions as
$$ select exists (select 1 from public.memberships
                  where org_id = target_org and user_id = auth.uid()) $$;

create or replace function app.has_org_role(target_org uuid, roles text[]) returns boolean
language sql stable security definer set search_path = public, extensions as
$$ select exists (select 1 from public.memberships
                  where org_id = target_org and user_id = auth.uid()
                    and role = any(roles)) $$;

revoke all on function app.user_org_ids() from public, anon;
revoke all on function app.is_org_member(uuid) from public, anon;
revoke all on function app.has_org_role(uuid, text[]) from public, anon;
grant execute on function app.user_org_ids() to authenticated, service_role;
grant execute on function app.is_org_member(uuid) to authenticated, service_role;
grant execute on function app.has_org_role(uuid, text[]) to authenticated, service_role;

-- Atomic org creation: org + owner membership in one definer call
-- (there is deliberately no INSERT policy on orgs for authenticated).
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
  return new_org;
end $$;

revoke all on function app.create_org(text) from public, anon;
grant execute on function app.create_org(text) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Enable RLS everywhere (deny-by-default once enabled).

do $$
declare t text;
begin
  foreach t in array array[
    'orgs','memberships','subscriptions','submissions','assets',
    'analysis_runs','layer_outputs','findings','rule_packs','rules',
    'usage_events','audit_logs','api_keys','plan_entitlements']
  loop
    execute format('alter table public.%I enable row level security;', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- orgs: members read; owner/admin rename; create only via app.create_org().

drop policy if exists orgs_member_read on public.orgs;
create policy orgs_member_read on public.orgs for select to authenticated
  using (id in (select app.user_org_ids()));

drop policy if exists orgs_admin_update on public.orgs;
create policy orgs_admin_update on public.orgs for update to authenticated
  using (app.has_org_role(id, array['owner','admin']))
  with check (app.has_org_role(id, array['owner','admin']));

-- memberships: members see their orgs' rosters; owner/admin manage; a user
-- may always remove their own membership (leave org).

drop policy if exists memberships_member_read on public.memberships;
create policy memberships_member_read on public.memberships for select to authenticated
  using (org_id in (select app.user_org_ids()));

drop policy if exists memberships_admin_insert on public.memberships;
create policy memberships_admin_insert on public.memberships for insert to authenticated
  with check (app.has_org_role(org_id, array['owner','admin']));

drop policy if exists memberships_admin_update on public.memberships;
create policy memberships_admin_update on public.memberships for update to authenticated
  using (app.has_org_role(org_id, array['owner','admin']))
  with check (app.has_org_role(org_id, array['owner','admin']));

drop policy if exists memberships_delete on public.memberships;
create policy memberships_delete on public.memberships for delete to authenticated
  using (user_id = auth.uid() or app.has_org_role(org_id, array['owner','admin']));

-- subscriptions: members read; ONLY the Stripe webhook (service_role) writes.

drop policy if exists subscriptions_member_read on public.subscriptions;
create policy subscriptions_member_read on public.subscriptions for select to authenticated
  using (org_id in (select app.user_org_ids()));

-- submissions: members read; reviewer+ create (as themselves); admin+ delete.

drop policy if exists submissions_member_read on public.submissions;
create policy submissions_member_read on public.submissions for select to authenticated
  using (org_id in (select app.user_org_ids()));

drop policy if exists submissions_reviewer_insert on public.submissions;
create policy submissions_reviewer_insert on public.submissions for insert to authenticated
  with check (created_by = auth.uid()
              and app.has_org_role(org_id, array['owner','admin','reviewer']));

drop policy if exists submissions_reviewer_update on public.submissions;
create policy submissions_reviewer_update on public.submissions for update to authenticated
  using (app.has_org_role(org_id, array['owner','admin','reviewer']))
  with check (app.has_org_role(org_id, array['owner','admin','reviewer']));

drop policy if exists submissions_admin_delete on public.submissions;
create policy submissions_admin_delete on public.submissions for delete to authenticated
  using (app.has_org_role(org_id, array['owner','admin']));

-- assets: members read; reviewer+ register uploads; scan_status is updated by
-- the worker (service_role) — no authenticated update policy.

drop policy if exists assets_member_read on public.assets;
create policy assets_member_read on public.assets for select to authenticated
  using (org_id in (select app.user_org_ids()));

drop policy if exists assets_reviewer_insert on public.assets;
create policy assets_reviewer_insert on public.assets for insert to authenticated
  with check (app.has_org_role(org_id, array['owner','admin','reviewer']));

drop policy if exists assets_admin_delete on public.assets;
create policy assets_admin_delete on public.assets for delete to authenticated
  using (app.has_org_role(org_id, array['owner','admin']));

-- analysis_runs: members read; reviewer+ enqueue; the worker owns all
-- status/model/cost updates (service_role).

drop policy if exists runs_member_read on public.analysis_runs;
create policy runs_member_read on public.analysis_runs for select to authenticated
  using (org_id in (select app.user_org_ids()));

drop policy if exists runs_reviewer_insert on public.analysis_runs;
create policy runs_reviewer_insert on public.analysis_runs for insert to authenticated
  with check (app.has_org_role(org_id, array['owner','admin','reviewer']));

-- layer_outputs: members read (traceability); worker-only writes.

drop policy if exists layer_outputs_member_read on public.layer_outputs;
create policy layer_outputs_member_read on public.layer_outputs for select to authenticated
  using (org_id in (select app.user_org_ids()));

-- findings: members read; reviewer+ update review status; engine-only inserts.

drop policy if exists findings_member_read on public.findings;
create policy findings_member_read on public.findings for select to authenticated
  using (org_id in (select app.user_org_ids()));

drop policy if exists findings_reviewer_update on public.findings;
create policy findings_reviewer_update on public.findings for update to authenticated
  using (app.has_org_role(org_id, array['owner','admin','reviewer']))
  with check (app.has_org_role(org_id, array['owner','admin','reviewer']));

-- rule_packs / rules / plan_entitlements: global reference data — readable by
-- any signed-in user; maintained only via service_role.

drop policy if exists rule_packs_read on public.rule_packs;
create policy rule_packs_read on public.rule_packs for select to authenticated using (true);

drop policy if exists rules_read on public.rules;
create policy rules_read on public.rules for select to authenticated using (true);

drop policy if exists plan_entitlements_read on public.plan_entitlements;
create policy plan_entitlements_read on public.plan_entitlements for select
  to authenticated using (true);

-- usage_events: members read their org's metering; system-only writes.

drop policy if exists usage_member_read on public.usage_events;
create policy usage_member_read on public.usage_events for select to authenticated
  using (org_id in (select app.user_org_ids()));

-- audit_logs: owner/admin read; system-only writes (hash chain in 0003).

drop policy if exists audit_admin_read on public.audit_logs;
create policy audit_admin_read on public.audit_logs for select to authenticated
  using (org_id is not null and app.has_org_role(org_id, array['owner','admin']));

-- api_keys: owner/admin manage; key_hash only (plaintext never stored).

drop policy if exists api_keys_admin_all on public.api_keys;
create policy api_keys_admin_all on public.api_keys for all to authenticated
  using (app.has_org_role(org_id, array['owner','admin']))
  with check (app.has_org_role(org_id, array['owner','admin']));

commit;
