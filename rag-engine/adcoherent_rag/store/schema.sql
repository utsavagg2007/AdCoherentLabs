-- AdCoherent Labs regulatory RAG schema.
-- Versioned, effective-dated storage: regulation text is never updated in
-- place. Live checks filter to currently-effective rows; audit replays filter
-- by the ad's run date; superseded text stays queryable forever.
--
-- NOTE: the ANN index on rag_chunks.embedding is created by db.init_db()
-- (HNSW when the installed pgvector supports it, IVFFlat fallback otherwise).

create extension if not exists vector;

create table if not exists rag_sources (
  id text primary key,
  tier int not null,
  category text not null,
  jurisdiction text not null,
  authority text,
  citation text,
  name text not null,
  url text not null,
  format text,
  ingestion text,
  url_status text,
  update_cadence text,
  topics jsonb not null default '[]',
  frameworks text[] not null default '{}',
  notes text,
  manifest_version text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists rag_raw_snapshots (
  id uuid primary key default gen_random_uuid(),
  source_id text not null references rag_sources(id),
  kind text not null,                 -- ecfr_xml | audit_pdf | uscode_html | ...
  requested_url text,
  resolved_url text,
  http_status int,
  content_type text,
  content_sha256 text not null,
  content_bytes bigint,
  storage_path text not null,        -- raw bytes kept on disk/object storage
  fetched_at timestamptz not null default now(),
  meta jsonb not null default '{}'
);
create index if not exists rag_raw_snapshots_source_idx
  on rag_raw_snapshots (source_id, kind, fetched_at desc);
create index if not exists rag_raw_snapshots_sha_idx
  on rag_raw_snapshots (source_id, content_sha256);

create table if not exists rag_regulation_versions (
  id uuid primary key default gen_random_uuid(),
  source_id text not null references rag_sources(id),
  section_key text not null,          -- stable canonical unit key, e.g. cfr/12/1030.8
  citation text not null,             -- human citation, e.g. "12 CFR § 1030.8"
  heading text,
  text_content text not null,
  text_sha256 text not null,
  effective_start date not null,
  effective_end date,                 -- null = currently effective
  snapshot_id uuid references rag_raw_snapshots(id),
  superseded_by uuid references rag_regulation_versions(id),
  created_at timestamptz not null default now(),
  unique (source_id, section_key, effective_start)
);
create index if not exists rag_versions_current_idx
  on rag_regulation_versions (source_id, section_key)
  where effective_end is null;

create table if not exists rag_chunks (
  id uuid primary key default gen_random_uuid(),
  version_id uuid not null references rag_regulation_versions(id) on delete cascade,
  -- denormalized from version -> source for cheap retrieval-time filtering
  source_id text not null references rag_sources(id),
  jurisdiction text not null,
  frameworks text[] not null default '{}',
  chunk_index int not null,
  subsection_label text,
  context_header text not null,
  text text not null,
  embedding vector(384),
  embedding_model text not null,
  embedding_dim int not null,
  tsv tsvector generated always as (to_tsvector('english', text)) stored,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique (version_id, chunk_index)
);
create index if not exists rag_chunks_tsv_idx on rag_chunks using gin (tsv);
create index if not exists rag_chunks_frameworks_idx on rag_chunks using gin (frameworks);
create index if not exists rag_chunks_version_idx on rag_chunks (version_id);

-- Ingest observability (also the substrate the future update pipeline and
-- canary evals will hang off).
create table if not exists rag_ingest_runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  stats jsonb not null default '{}'
);

create table if not exists rag_ingest_events (
  id bigserial primary key,
  run_id uuid references rag_ingest_runs(id),
  source_id text,
  status text not null,   -- fetched | unchanged | stored | skipped | error
  detail jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index if not exists rag_ingest_events_run_idx on rag_ingest_events (run_id);
