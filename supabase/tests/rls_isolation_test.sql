-- rls_isolation_test.sql — THE test the playbook calls existential:
-- an authenticated user in Org A must not be able to read, list, or mutate
-- any Org B row. Runs entirely inside a transaction and rolls back.
--
--   docker exec -i supabase-db psql -U postgres -d postgres \
--     -v ON_ERROR_STOP=1 -f - < tests/rls_isolation_test.sql
--
-- Prints "RLS ISOLATION TEST: PASS" on success; raises an exception on any
-- isolation failure.

begin;

do $$
declare
  u1 uuid := gen_random_uuid();  -- member of org A (owner)
  u2 uuid := gen_random_uuid();  -- member of org B (owner)
  org_a uuid;
  org_b uuid;
  sub_a uuid;
  sub_b uuid;
  run_a uuid;
  run_b uuid;
  n int;
  write_blocked boolean;
begin
  -- Seed two users (minimal auth.users rows), two orgs, one finding each.
  insert into auth.users (instance_id, id, aud, role, email, created_at, updated_at)
  values ('00000000-0000-0000-0000-000000000000', u1, 'authenticated',
          'authenticated', 'rls-test-a@example.com', now(), now()),
         ('00000000-0000-0000-0000-000000000000', u2, 'authenticated',
          'authenticated', 'rls-test-b@example.com', now(), now());

  insert into public.orgs (name) values ('rls-test-org-a') returning id into org_a;
  insert into public.orgs (name) values ('rls-test-org-b') returning id into org_b;
  insert into public.memberships (org_id, user_id, role)
  values (org_a, u1, 'owner'), (org_b, u2, 'owner');

  insert into public.submissions (org_id, created_by, title)
  values (org_a, u1, 'A submission') returning id into sub_a;
  insert into public.submissions (org_id, created_by, title)
  values (org_b, u2, 'B submission') returning id into sub_b;

  insert into public.analysis_runs (submission_id, org_id, status)
  values (sub_a, org_a, 'complete') returning id into run_a;
  insert into public.analysis_runs (submission_id, org_id, status)
  values (sub_b, org_b, 'complete') returning id into run_b;

  insert into public.findings (run_id, org_id, framework, severity, verdict, message)
  values (run_a, org_a, 'FTC', 'high', 'potential_violation', 'A finding'),
         (run_b, org_b, 'FTC', 'high', 'potential_violation', 'B finding');

  insert into public.usage_events (org_id, kind) values (org_a, 'scan'), (org_b, 'scan');

  -- ---- Act as user 1 (org A) --------------------------------------------
  perform set_config('request.jwt.claims',
                     json_build_object('sub', u1, 'role', 'authenticated')::text,
                     true);
  execute 'set local role authenticated';

  select count(*) into n from public.findings;
  if n <> 1 then
    raise exception 'FAIL: user A sees % findings, expected exactly their own 1', n;
  end if;

  select count(*) into n from public.findings where org_id = org_b;
  if n <> 0 then
    raise exception 'FAIL: user A can read org B findings';
  end if;

  select count(*) into n from public.submissions where org_id = org_b;
  if n <> 0 then
    raise exception 'FAIL: user A can read org B submissions';
  end if;

  select count(*) into n from public.usage_events where org_id = org_b;
  if n <> 0 then
    raise exception 'FAIL: user A can read org B usage events';
  end if;

  -- Cross-tenant write must be rejected by RLS.
  write_blocked := false;
  begin
    insert into public.submissions (org_id, created_by, title)
    values (org_b, u1, 'cross-tenant write');
  exception when insufficient_privilege or check_violation then
    write_blocked := true;
  end;
  if not write_blocked then
    raise exception 'FAIL: user A inserted a submission into org B';
  end if;

  -- Mutating another org's finding must silently affect 0 rows.
  update public.findings set status = 'approved' where org_id = org_b;
  get diagnostics n = row_count;
  if n <> 0 then
    raise exception 'FAIL: user A updated % org B finding(s)', n;
  end if;

  -- Subscriptions are read-only for authenticated users (webhook-only writes).
  write_blocked := false;
  begin
    update public.subscriptions set tier = 'enterprise' where org_id = org_a;
    get diagnostics n = row_count;
    write_blocked := (n = 0);
  exception when insufficient_privilege then
    write_blocked := true;
  end;
  if not write_blocked then
    raise exception 'FAIL: user A escalated their own subscription tier';
  end if;

  execute 'reset role';
  raise notice 'RLS ISOLATION TEST: PASS';
end $$;

rollback;
