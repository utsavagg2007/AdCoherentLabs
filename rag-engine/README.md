# AdCoherent Labs — Regulatory RAG Engine

Layer-3 ingestion + retrieval for the compliance engine. Ingests the
regulatory corpus defined in `adcoherent_regulatory_sources.json`, normalizes
it into canonical section units, chunks per subsection, embeds locally with
`sentence-transformers/all-MiniLM-L6-v2` (384-dim), and stores everything in
Postgres (Supabase) with pgvector + tsvector hybrid RRF retrieval.

Storage is **versioned and effective-dated**: regulation text is never
updated in place. Each section lives in `rag_regulation_versions` with
`effective_start` / `effective_end`; chunks are foreign-keyed to a version.
Live checks filter to currently-effective rows; audit replays filter by the
ad's run date. Raw fetched bytes are hashed (SHA-256) and kept under
`data/raw/` with a `rag_raw_snapshots` row — the substrate the future
update-detection pipeline (Federal Register poller, eCFR versions diff, state
re-scrape hashing) plugs into.

## Setup

```bash
cd rag-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Config comes from the ONE monorepo-root .env (this package loads ../.env).
# Generate/refresh it with:  python ../scripts/sync_env.py
# DATABASE_URL there points at the Supabase Postgres.
```

Use a **direct connection** (not a transaction pooler): DDL and the psycopg
prepared statements need it. `pgvector` must be available (Supabase ships
it; `init-db` runs `create extension if not exists vector`).

**Local self-hosted Supabase (current dev setup):** `.env` uses the stack's
supavisor session port — `postgresql://postgres.<POOLER_TENANT_ID>:<pw>@127.0.0.1:5432/postgres`.
(The pooler's `_supabase` metadata DB was corrupt — "base/16754 is not a valid
data directory" — and was rebuilt on 2026-07-06 from the stack's own init
scripts: recreate the DB + `_analytics`/`_supavisor` schemas, restart
`supabase-pooler`.) A direct-connection fallback for DDL-heavy maintenance
also exists:

```bash
docker run -d --name adcoherent-rag-db-proxy --restart unless-stopped \
  --network supabase_default -p 127.0.0.1:54322:5432 \
  alpine/socat tcp-listen:5432,fork,reuseaddr tcp-connect:supabase-db:5432
# -> postgresql://postgres:<pw>@127.0.0.1:54322/postgres
# remove with: docker rm -f adcoherent-rag-db-proxy
```

## Usage

```bash
python -m adcoherent_rag.cli init-db          # create schema + indexes
python -m adcoherent_rag.cli ingest           # tier-1 federal + CA/NY/TX/FL/IL/MA/NJ
python -m adcoherent_rag.cli ingest --all     # full manifest: 50 states + DC + references
python -m adcoherent_rag.cli ingest --source-id cfpb-reg-dd-tisa   # one source
python -m adcoherent_rag.cli retrieve "APY advertising disclosure requirements" \
    --framework Reg_DD --k 8
python -m adcoherent_rag.cli retrieve "..." --as-of 2026-01-15     # audit replay
python -m adcoherent_rag.cli stats
```

Re-running `ingest` is idempotent: unchanged sources are skipped via snapshot
hash; changed sections get a new effective-dated version (old one is closed,
never deleted).

Env knobs for verification sweeps: `HTTP_CONNECT_TIMEOUT`, `HTTP_TIMEOUT`,
`HTTP_RETRIES` (fail fast on geo-blocked hosts), `EMBEDDING_FAKE=1`
(deterministic embedder — tests/dry-runs only).

## Layout

```
adcoherent_rag/
  config.py            env + constants
  models.py            shared datatypes (frozen contracts)
  manifest.py          manifest loading, framework routing, handler families,
                       MANUAL_STUB_SOURCES (id -> reason)
  fetch/               per-source-family fetchers (eCFR API, govinfo PDFs,
                       uscode/FINRA HTML, all-states registry in states.py)
  normalize/           raw bytes -> canonical SectionUnits
                       (statute_html.py: CHAPTER_SPLITS config registry)
  chunk/chunker.py     structure-aware chunking (one chunk per subsection)
  embed/embedder.py    MiniLM embeddings (FakeEmbedder for tests)
  store/               schema.sql, connections, versioned repository
  retrieval/hybrid.py  pgvector + tsvector RRF hybrid retrieval
  pipeline.py          ingest orchestration
  cli.py               command-line entry points
tests/                 offline unit tests (EMBEDDING_FAKE=1)
```

## State coverage (live-probed 2026-07-05)

State sources dispatch per **source id** through `fetch/states.py`:
bespoke fetchers for CA/NY/TX/FL/IL/MA, a declarative `STATE_STRATEGIES`
registry for the rest (per-section pages, chapter HTML with regex splits,
official chapter PDFs, link-following listings). Strategies are tried in
order; chapter pages verify their section markers at fetch time.

- **Verified working from the dev machine:** AZ, DC, DE, HI, IA, KS,
  KY (chapter listing → per-section PDFs), ME, MD (mgaleg StatuteText;
  en-dash-normalized guard), MN, MT, ND, SC, SD (statute API), VA,
  WA (RCW `?pdf=true`), WY, plus CA/TX/FL and the CA DFPI CCFPL
  (Fin. Code div. 24 via leginfo). U.S. Code sources fall back to the
  govinfo annual edition when uscode.house.gov blocks/throttles.
- **Official URL kept, host geo/WAF-blocks this network:** CO, CT, IL, MA,
  MI, MO, NC, NE, NH, NV, NY (nysenate 403), OH, OR, PA, RI, UT, VT, WI,
  WV. These error cleanly here and are expected to work from US-based
  infrastructure (note IL/MA/NY are priority states — run ingest from a US
  IP to load them).
- **Manual stubs (`manifest.MANUAL_STUB_SOURCES`, skipped with a per-source
  reason):** AL, AK, AR, GA, IN, LA, MS, NM, OK, TN, NJ (SPA/LexisNexis/
  doc-id-only viewers; the Justia mirror bot-blocks scrapers) and
  `us-ny-dfs-crypto-ads` (23 NYCRR 200 text is Westlaw-only). These need a
  licensed feed, a manual snapshot, or a headless-browser worker.

## Notes / known limitations (v0)

- `effective_start` is exact for CFR sources (eCFR per-section amendment
  dates); for statutes/state sources it falls back to the fetch date.
- Update-detection (Federal Register poller, scheduled re-scrapes) and canary
  evals are the next phase; the schema and snapshot hashing already support
  them.
- Tier-3 references: the two NCLC PDFs and the Cozen chart download fine;
  the Justia 50-state survey page bot-blocks scrapers (errors cleanly).
