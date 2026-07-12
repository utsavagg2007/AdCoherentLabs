-- 0005_storage_and_realtime.sql — asset bucket with org-scoped policies, and
-- realtime publication for live run status.
--
-- Storage path convention (enforced by policy):
--   assets/<org_id>/<submission_id>/<random-key>.<ext>
-- Files are private; the app serves them via short-lived signed URLs only.

begin;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'assets', 'assets', false,
  52428800,  -- 50 MB per object; per-tier caps enforced in the API
  array['application/pdf','image/png','image/jpeg','image/webp','image/gif',
        'text/plain','text/html','video/mp4']
)
on conflict (id) do update set
  public             = excluded.public,
  file_size_limit    = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- Members read their org's files (first path segment = org_id).
drop policy if exists "assets org member read" on storage.objects;
create policy "assets org member read" on storage.objects for select to authenticated
  using (
    bucket_id = 'assets'
    and exists (select 1 from app.user_org_ids() o
                where o::text = (storage.foldername(name))[1])
  );

-- Reviewer+ upload into their org's prefix only.
drop policy if exists "assets org reviewer insert" on storage.objects;
create policy "assets org reviewer insert" on storage.objects for insert to authenticated
  with check (
    bucket_id = 'assets'
    and exists (select 1 from public.memberships m
                where m.user_id = auth.uid()
                  and m.role in ('owner','admin','reviewer')
                  and m.org_id::text = (storage.foldername(name))[1])
  );

-- Admin+ delete.
drop policy if exists "assets org admin delete" on storage.objects;
create policy "assets org admin delete" on storage.objects for delete to authenticated
  using (
    bucket_id = 'assets'
    and exists (select 1 from public.memberships m
                where m.user_id = auth.uid()
                  and m.role in ('owner','admin')
                  and m.org_id::text = (storage.foldername(name))[1])
  );

-- ---------------------------------------------------------------------------
-- Realtime: the UI subscribes to run-status flips and new findings instead of
-- polling. RLS still applies to what each subscriber can see.

do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public' and tablename = 'analysis_runs') then
    alter publication supabase_realtime add table public.analysis_runs;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public' and tablename = 'findings') then
    alter publication supabase_realtime add table public.findings;
  end if;
end $$;

commit;
