-- 0006_lock_rag_tables.sql — the regulation corpus (Layer-3 RAG) is internal.
-- Enabling RLS with NO policies denies all access through the Supabase API
-- (anon/authenticated). The RAG engine and worker are unaffected: they
-- connect directly as the postgres table owner (DATABASE_URL), which is not
-- subject to these policies.

begin;

do $$
declare t text;
begin
  foreach t in array array[
    'rag_sources','rag_regulation_versions','rag_chunks',
    'rag_raw_snapshots','rag_ingest_runs','rag_ingest_events']
  loop
    if exists (select 1 from pg_tables
               where schemaname = 'public' and tablename = t) then
      execute format('alter table public.%I enable row level security;', t);
      execute format('revoke all on public.%I from anon, authenticated;', t);
    end if;
  end loop;
end $$;

commit;
