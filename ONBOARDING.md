# AdCoherent Labs — developer onboarding

Everything needed to run the application, test it, and contribute changes.

**You do not need a database.** The data plane is a shared Supabase Cloud
project. You get credentials, not a data dump — no local Supabase stack, no
71 MB corpus to import.

Read **[Working on a shared database](#5-working-on-a-shared-database)** before
your first test run. It is the one section where getting it wrong wastes
somebody else's afternoon.

---

## 1. Prerequisites

| Tool | Needed for | Notes |
|---|---|---|
| **Docker Desktop** | running the app | Compose v2.20+ — `docker compose version` |
| **Git** | everything | |
| **Python 3.11** | host-side tests + engine CLI | 3.11 exactly; 3.12+ breaks PaddleOCR |
| **Node 20.9+** | frontend host dev (optional) | only if you skip the frontend container |

Docker alone is enough to *run* the app. Python is required to run the test
suites and the engine CLI on your machine.

## 2. Credentials to collect

Ask for these before you start. They are **not** in the repository and never
will be — `.env` is gitignored.

| Value | Where it comes from |
|---|---|
| Supabase project ref | the `<ref>` in `https://<ref>.supabase.co` |
| Database password | project owner only (not shown in the dashboard) |
| `service_role` key | Supabase → Project Settings → API |
| `anon` / publishable key | Supabase → Project Settings → API |
| JWT secret | Supabase → Project Settings → API Keys |
| `OPENROUTER_API_KEY` | for live LLM runs on free/hobby tiers |

Also ask to be added to the **Supabase project** and the **GitHub repo** so you
can read logs and inspect data yourself.

> Treat the `service_role` key like a root password — it bypasses row-level
> security entirely. It belongs only in the root `.env`, never in
> `frontend/.env.local`, never in a commit.

---

## 3. Clone and configure

```bash
git clone https://github.com/utsavagg2007/AdCoherentLabs.git
cd AdCoherentLabs
git checkout full-engine
```

`full-engine` is the active branch, not `main`.

```bash
cp .env.example .env
cp frontend/.env.local.example frontend/.env.local
```

Now replace every `__PLACEHOLDER__` in both files.

**Root `.env`** — the whole backend and engine:

| Placeholder | Replace with |
|---|---|
| `__PROJECT_REF__` | the project ref (appears in 6 URLs) |
| `__PASTE_DB_PASSWORD__` | the database password (appears in 5 URLs) |
| `__PASTE_SERVICE_ROLE_KEY__` | `service_role` key |
| `__PASTE_ANON_KEY__` | `anon` key |
| `__PASTE_JWT_SECRET__` | JWT secret |
| `__GENERATE_A_RANDOM_HEX_STRING__` | **your own** value, see below |

The Redis password is yours alone — Redis runs as a container on your machine.
Generate one and use the identical value in `REDIS_PASSWORD` **and** inside
`REDIS_URL`:

```bash
python -c "import secrets; print(secrets.token_hex(16))"
```

**`frontend/.env.local`** — the project URL and the **anon** key. Everything in
this file is compiled into the browser bundle, so the `service_role` key must
never appear here.

> The placeholders are load-bearing. The app refuses to boot while any
> `__PROJECT_REF__` or `__PASTE_` survives in a data-plane URL, so a half-filled
> file fails loudly instead of quietly connecting somewhere wrong.

---

## 4. Run it

```bash
docker compose up -d --build
```

- Frontend → <http://127.0.0.1:3000>
- API → <http://127.0.0.1:8080>, OpenAPI browser at `/docs`

The first build takes a while: the backend image compiles PaddleOCR and torch,
and ClamAV downloads its virus database. ClamAV legitimately reports
`unhealthy` for the first few minutes — its health check allows 180 s.

### Confirm it actually works

```bash
curl http://127.0.0.1:8080/readyz
```

`{"ready":true,"db":true}` means your container reached Supabase Cloud. Then:

```bash
docker compose ps
docker compose logs -f api
```

Sign up through the UI at <http://127.0.0.1:3000> and create **your own org** —
see the next section for why that matters.

### Running only part of the stack

Backend only, no frontend container:

```bash
docker compose -f backend/docker-compose.backend.yml up -d --build
```

Frontend on your host against the containerised API — much faster hot reload,
especially on Windows:

```bash
docker compose up -d api redis clamav
cd frontend && npm install && npm run dev
```

On Windows, run the API on the host with `python -m app.devserver` rather than
plain `uvicorn`. It installs the selector event-loop policy *before* the loop is
created; async psycopg fails on the default Proactor loop.

---

## 5. Working on a shared database

Everyone develops against one Supabase project. Three rules follow from that.

### Rule 1 — Stop your worker when you are not testing

```bash
docker compose stop worker
```

Both your worker and everyone else's poll the **same** `app.job_queue`.

Jobs are never processed twice — `app.lease_job` uses `FOR UPDATE SKIP LOCKED`,
an advisory lock and 300-second leases. But leasing is first-come-first-served
*across machines*: a teammate submits a run and **your** worker may lease it and
execute it with **your** branch and **your** API keys, writing results back that
look like theirs. Nothing corrupts; you just both debug a ghost.

Start it again when you need to process your own submissions:

```bash
docker compose start worker
```

### Rule 2 — Create your own org

Credits, rate limits and row-level security all scope per-org. Your own org
gives you an isolated credit balance and rate-limit budget. Sharing one means
whoever runs a test first spends the credits.

### Rule 3 — Never run the destructive suites casually

`test_credit_race.py` executes 50 runs. The test suites otherwise behave well —
they create their own users and orgs and delete them by id rather than
truncating shared tables — but they are still writing to the real database.

---

## 6. Testing

### Set up the Python environment (once)

Host-side tests need a virtualenv. It is gitignored, so build your own. Both
layer repos and the backend install into this **single** venv.

```bash
python3.11 -m venv CV-RULE_ENG-NLP/.venv
```

```bash
# Windows
CV-RULE_ENG-NLP/.venv/Scripts/pip install -r CV-RULE_ENG-NLP/requirements.txt -r rag-engine/requirements.txt -r backend/requirements.txt
```

```bash
# macOS / Linux
CV-RULE_ENG-NLP/.venv/bin/pip install -r CV-RULE_ENG-NLP/requirements.txt -r rag-engine/requirements.txt -r backend/requirements.txt
```

This pulls torch and PaddleOCR — expect a few GB and several minutes.

Below, `PY` means `CV-RULE_ENG-NLP/.venv/Scripts/python` on Windows and
`CV-RULE_ENG-NLP/.venv/bin/python` on macOS/Linux.

### The five suites

Run them in this order — the first two need no database.

| # | Suite | Command | Expect |
|---|---|---|---|
| 1 | Engine wiring (offline) | `$PY -m engine.selftest` | 33/33 checks |
| 2 | CV / NLP / rule engine | `cd CV-RULE_ENG-NLP && .venv/Scripts/python -m pytest` | 184 passed |
| 3 | RAG | `cd rag-engine && ../CV-RULE_ENG-NLP/.venv/Scripts/python -m pytest tests` | 67 passed |
| 4 | Backend API | `cd backend && ../CV-RULE_ENG-NLP/.venv/Scripts/python -m pytest` | 46 passed |
| 5 | Data plane (live) | `$PY -m engine.cli saas-selftest` | all checks pass |

**Before running suite 4 or 5, stop your worker container** — otherwise it
races your test process for queued jobs and tests fail intermittently:

```bash
docker compose stop worker
```

Suite 4 also needs Redis and ClamAV reachable on `127.0.0.1`, which
`docker compose up` already provides.

### End-to-end without spending money

```bash
$PY -m engine.cli check --text "Get 5.99% APR!" --tier free --stub-llm
```

`--stub-llm` exercises all four layers — CV, NLP, real pgvector retrieval, rule
engine — without calling a provider. **Use this by default.**

### Live LLM runs

| Tier | Provider | Status |
|---|---|---|
| free, hobby | OpenRouter | working |
| pro, design, enterprise | Anthropic | **`ANTHROPIC_API_KEY` is empty — these fail at the provider** |

```bash
$PY -m engine.cli check --text "Get 5.99% APR!" --tier free
```

Live runs are slow: the free/hobby models are reasoning models at roughly four
minutes per round, so a three-round run takes about twelve. They also spend real
credits from a shared budget. Check with the team before running many.

### Frontend

```bash
cd frontend && npm install && npm run lint && npm run build
```

---

## 7. Making changes

### What needs a rebuild vs. a restart

This trips people up constantly. The backend containers mount the repo
read-only at `/repo`, so most Python edits need no rebuild.

| You changed | Do this |
|---|---|
| `engine/`, `rag-engine/`, `CV-RULE_ENG-NLP/`, `backend/app/` | `docker compose restart api worker` |
| `docker-entrypoint.sh`, any `requirements.txt`, `Dockerfile` | `docker compose up -d --build` |
| `frontend/` source | `docker compose up -d --build frontend` |
| any `NEXT_PUBLIC_*` value | `docker compose build frontend` — **restart will not do it** |
| `.env` | `docker compose up -d` (recreates with new env) |

`NEXT_PUBLIC_*` values are compiled into the JavaScript bundle at build time.
Changing one and restarting leaves the old value baked in.

### Database schema changes

Migrations live in `supabase/migrations/` and are applied with
`supabase/apply.sh`. **Coordinate before applying anything** — it is the shared
production-shaped database, and `apply.sh` skips already-recorded migrations by
*filename*, so editing an applied migration does nothing until it is re-applied
by hand. Never edit an applied migration; add a new numbered one.

### Git workflow

```bash
git checkout full-engine
git pull
git checkout -b your-feature-name
# ... work ...
git add -A
git commit -m "short description of what changed"
git push -u origin your-feature-name
```

Open a pull request against `full-engine`. Before you push:

- [ ] `git status` shows **no** `.env` or `.env.local` — if it does, stop and
      say so; the fix is not just deleting the file
- [ ] the suites relevant to your change pass
- [ ] no secret in a committed file, including in a comment

---

## 8. Troubleshooting

| Symptom | Cause |
|---|---|
| `FATAL: ... unfilled placeholders` | a `__PASTE_...__` remains in `.env` |
| `FATAL: ... points at a local host` | a data-plane URL still has `127.0.0.1` |
| `refusing to boot without: SUPABASE_JWT_SECRET` | that key is empty |
| `/readyz` returns `db:false` | wrong DB password, or the wrong pooler |
| `set SUPABASE_ANON_KEY in .env` on build | the frontend build arg reads it from the **root** `.env` too |
| Uploads → 503 `scanner_unavailable` | ClamAV still downloading; wait |
| Tests fail intermittently around jobs | your worker container is running — stop it |
| `ModuleNotFoundError: engine` | running host Python outside the venv |

**Use the Session pooler (port 5432), never the transaction pooler (6543).**
psycopg3 promotes hot statements to server-side prepared statements after five
executions, and PgBouncer in transaction mode drops those between transactions.
The failures are intermittent and only begin once the app warms up.

Do **not** run `scripts/sync_env.py`. It writes self-hosted stack credentials
and will refuse while `SUPABASE_MODE=cloud`. That refusal is correct.

---

## 9. Orientation

| Path | What it is |
|---|---|
| `engine/` | orchestrates the four AI layers — start here |
| `CV-RULE_ENG-NLP/` | Layer 1 CV/OCR, Layer 2 NLP, Layer 4 rule engine |
| `rag-engine/` | Layer 3 retrieval + LLM review (pgvector) |
| `backend/` | FastAPI API, worker, scheduler |
| `frontend/` | Next.js 16 app |
| `supabase/migrations/` | the schema — RLS, credits, job queue, audit chain |

| Document | Covers |
|---|---|
| `ENGINE.md` | the four-layer engine in depth |
| `backend/README.md` | backend runbook and design notes |
| `supabase.md` | schema and data-plane detail |
| `DEPLOY_FIREBASE.md` | deployment, and its open questions |
| `AUTH_AUDIT_AND_PLAN.md` | auth hardening status |

**Reports are decision support, not legal advice.** That framing holds in the
product copy and in the code.
