-- 0007_engine_integration.sql — columns/status the connected engine needs.
-- The 4-layer engine (engine/saas.py) persists every run here. Three additions:
--   * status 'human_review' — a run that exhausted its LLM callback budget and
--     is waiting for operator interference is neither complete nor failed;
--   * engine_run_id — the engine's internal id ("run_<hex>") stamped on every
--     EngineRunResult / JSON report, so DB rows and report files correlate;
--   * resumed_from_run_id — operator-guidance resumes create a NEW run linked
--     to the run they resume (audit trail of human interference).
-- Idempotent: safe to re-run.

begin;

alter table public.analysis_runs drop constraint if exists analysis_runs_status_check;
alter table public.analysis_runs add constraint analysis_runs_status_check
  check (status in ('queued','running_cv','running_nlp','running_llm',
                    'running_rules','reconciling','complete','failed',
                    'human_review'));

alter table public.analysis_runs add column if not exists engine_run_id text;
alter table public.analysis_runs add column if not exists resumed_from_run_id
  uuid references public.analysis_runs(id) on delete set null;

create index if not exists analysis_runs_engine_run_idx
  on public.analysis_runs (engine_run_id);

-- The active-runs partial index predates 'human_review'; rebuild it so runs
-- waiting on an operator still count as "not finished".
drop index if exists analysis_runs_status_idx;
create index analysis_runs_status_idx on public.analysis_runs (status)
  where status not in ('complete','failed');

commit;
