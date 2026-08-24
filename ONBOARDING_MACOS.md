# AdCoherent Labs — onboarding on macOS (Apple Silicon)

The macOS version of [ONBOARDING.md](ONBOARDING.md). Every command here is
native — no path translation, no Rosetta.

Written for **Apple Silicon** (M1–M4). Intel Macs work identically except that
Homebrew installs to `/usr/local` instead of `/opt/homebrew`; wherever that path
appears, substitute it.

**You do not need a database.** The data plane is a shared Supabase Cloud
project — you get credentials, not a data dump.

---

## 1. Install the tooling

### Homebrew

If you do not already have it:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the "Next steps" it prints — on Apple Silicon it asks you to add
`/opt/homebrew/bin` to your `PATH`, and nothing below works until you do.

### Git, Python 3.11, libmagic

```bash
brew install git python@3.11 libmagic
```

**Python must be 3.11.** macOS ships 3.9, and 3.12+ breaks PaddleOCR. Homebrew
installs it as `python3.11`, alongside any other version you have.

**`libmagic` is required and easy to miss.** The backend does MIME sniffing
through `python-magic`, which on macOS is a thin ctypes wrapper around the
system `libmagic` — unlike Windows, where `python-magic-bin` bundles it. Skip
this and imports fail with `failed to find libmagic`.

### Node (optional)

Only if you want to run the frontend outside Docker:

```bash
brew install node
```

### Docker Desktop

Download the **Apple Silicon** build from
<https://www.docker.com/products/docker-desktop/> and install it.

Then raise its memory — this is not optional:

> Docker Desktop → Settings → Resources → Memory → **8 GB or more**

The backend image installs torch and PaddleOCR. At the 4–8 GB default the build
is killed by the OOM killer, which surfaces as a build that simply stops with
no useful error.

While you are there, confirm **VirtioFS** is selected under
Settings → General. It is the default on current versions and is dramatically
faster than the legacy file sharing for the read-only repo mount this project
uses.

Verify:

```bash
docker --version && docker compose version && python3.11 --version && git --version
```

Compose must be **v2.20 or newer** — the root compose file uses `include`.

---

## 2. Credentials to collect

Ask the project owner. These are never in the repository.

| Value | Source |
|---|---|
| Supabase project ref | the `<ref>` in `https://<ref>.supabase.co` |
| Database password | project owner only — not in the dashboard |
| `service_role` key | Supabase → Project Settings → API |
| `anon` key | Supabase → Project Settings → API |
| JWT secret | Supabase → Project Settings → API Keys |
| `OPENROUTER_API_KEY` | for live LLM runs (free/hobby tiers) |

Also ask to be added to the Supabase project and the GitHub repo.

> The `service_role` key bypasses row-level security completely. Root `.env`
> only — never `frontend/.env.local`, never a commit.

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

Open both and replace every `__PLACEHOLDER__`:

```bash
open -e .env frontend/.env.local     # or: code .env frontend/.env.local
```

**Root `.env`:**

| Placeholder | Replace with | Occurrences |
|---|---|---|
| `__PROJECT_REF__` | project ref | 7 |
| `__PASTE_DB_PASSWORD__` | database password | 5 |
| `__PASTE_SERVICE_ROLE_KEY__` | `service_role` key | 1 |
| `__PASTE_ANON_KEY__` | `anon` key | 1 |
| `__PASTE_JWT_SECRET__` | JWT secret | 1 |
| `__GENERATE_A_RANDOM_HEX_STRING__` | **your own**, below | 2 |

12 lines in total. There is an eighth `__PROJECT_REF__` in the file's comment
header — that one is prose explaining the mechanism, and it stays.

The Redis password is yours alone — Redis is a container on your Mac. Generate
one and use the *same* value in `REDIS_PASSWORD` and inside `REDIS_URL`:

```bash
python3.11 -c "import secrets; print(secrets.token_hex(16))"
```

**`frontend/.env.local`:** project URL and the **anon** key only. Everything in
that file is compiled into the browser bundle.

Sanity-check that nothing was missed. The `grep -v ":#"` matters — without it
you get a permanent false positive from the placeholder named in the file's own
comment header:

```bash
grep -n "__" .env frontend/.env.local | grep -v ":#"
```

No output means you are done. The app refuses to boot while any placeholder
survives in a data-plane URL, so a half-filled file fails loudly rather than
connecting somewhere wrong.

---

## 4. Run it

```bash
docker compose up -d --build
```

- Frontend → <http://127.0.0.1:3000>
- API → <http://127.0.0.1:8080> (`/docs` for the OpenAPI browser)

The first build takes 10–20 minutes on Apple Silicon: it compiles the full ML
stack for arm64. Later builds are cached.

Every image is arm64-native — no emulation, no `platform:` overrides. ClamAV is
pinned to `clamav/clamav:stable-debian` specifically because the default
`stable` tag is Alpine and publishes amd64 only.

### Confirm it works

```bash
curl http://127.0.0.1:8080/readyz
```

`{"ready":true,"db":true}` means your container reached Supabase Cloud.

```bash
docker compose ps
docker compose logs -f api
```

ClamAV reports `unhealthy` for the first few minutes while it downloads its
virus database. That is expected — its health check allows 180 s.

Now open <http://127.0.0.1:3000>, sign up, and **create your own org**.

### Running only part of the stack

Backend only:

```bash
docker compose -f backend/docker-compose.backend.yml up -d --build
```

Frontend on your Mac against the containerised API — much faster hot reload:

```bash
docker compose up -d api redis clamav
cd frontend && npm install && npm run dev
```

---

## 5. Before you test: the shared-database rules

Everyone develops against one Supabase project.

### Stop your worker when you are not testing

```bash
docker compose stop worker
```

Your worker and everyone else's poll the **same** `app.job_queue`. Jobs never
process twice — `app.lease_job` uses `FOR UPDATE SKIP LOCKED`, an advisory lock
and 300-second leases — but leasing is first-come-first-served *across
machines*. A teammate submits a run and your worker may lease it, execute it
with your branch and your keys, and write results back that look like theirs.

```bash
docker compose start worker      # when you need to process your own jobs
```

### Use your own org

Credits, rate limits and row-level security all scope per-org.

### `test_credit_race.py` executes 50 runs

Do not run it casually against the shared database.

---

## 6. Python environment for tests

The virtualenv is gitignored — build your own. Both layer repos and the backend
install into this **single** venv.

```bash
python3.11 -m venv CV-RULE_ENG-NLP/.venv
```

```bash
CV-RULE_ENG-NLP/.venv/bin/pip install --upgrade pip
CV-RULE_ENG-NLP/.venv/bin/pip install \
  -r CV-RULE_ENG-NLP/requirements.txt \
  -r rag-engine/requirements.txt \
  -r backend/requirements.txt
```

This pulls torch and PaddleOCR — several GB and several minutes.

Confirm the arm64 pieces landed, including the libmagic binding:

```bash
CV-RULE_ENG-NLP/.venv/bin/python -c "import paddle, torch, magic; print('paddle', paddle.__version__, '| torch', torch.__version__, '| libmagic ok')"
```

If that raises `failed to find libmagic`, run `brew install libmagic`. If it is
already installed and still not found — which happens on Apple Silicon because
`/opt/homebrew/lib` is not on the default dynamic-loader path — add this to your
`~/.zshrc`:

```bash
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH"
```

Below, `PY` is `CV-RULE_ENG-NLP/.venv/bin/python`. Optionally:

```bash
export PY="$PWD/CV-RULE_ENG-NLP/.venv/bin/python"
```

---

## 7. Tests

Run in this order — the first two need no database.

### 1. Engine wiring, offline

```bash
$PY -m engine.selftest
```

Expect `SELFTEST PASSED` (33/33 checks).

### 2. CV / NLP / rule engine — 184 tests

```bash
cd CV-RULE_ENG-NLP && .venv/bin/python -m pytest; cd ..
```

### 3. RAG — 67 tests

```bash
cd rag-engine && ../CV-RULE_ENG-NLP/.venv/bin/python -m pytest tests; cd ..
```

### 4. Backend API — 46 tests

**Stop your worker first**, or it races your test process for queued jobs and
tests fail intermittently:

```bash
docker compose stop worker
cd backend && ../CV-RULE_ENG-NLP/.venv/bin/python -m pytest; cd ..
```

Needs Redis and ClamAV reachable on `127.0.0.1` — `docker compose up` provides
both.

### 5. Live data plane

```bash
$PY -m engine.cli saas-selftest
```

### End-to-end without spending money

```bash
$PY -m engine.cli check --text "Get 5.99% APR!" --tier free --stub-llm
```

`--stub-llm` exercises all four layers — CV, NLP, real pgvector retrieval, rule
engine — with no provider call. **Use this by default.**

### Live LLM runs

| Tier | Provider | Status |
|---|---|---|
| free, hobby | OpenRouter | working |
| pro, design, enterprise | Anthropic | **key is empty — these fail** |

Live free/hobby runs use reasoning models at roughly four minutes per round —
about twelve minutes for three rounds — and spend from a shared budget. Check
with the team before running many.

### Frontend

```bash
cd frontend && npm install && npm run lint && npm run build
```

---

## 8. Making changes

### Rebuild vs restart

The backend containers mount the repo read-only at `/repo`, so most Python
edits need no rebuild.

| Changed | Command |
|---|---|
| `engine/`, `rag-engine/`, `CV-RULE_ENG-NLP/`, `backend/app/` | `docker compose restart api worker` |
| `docker-entrypoint.sh`, any `requirements.txt`, a `Dockerfile` | `docker compose up -d --build` |
| `frontend/` source | `docker compose up -d --build frontend` |
| any `NEXT_PUBLIC_*` value | `docker compose build frontend` — **restart will not do it** |
| `.env` | `docker compose up -d` |

`NEXT_PUBLIC_*` values are compiled into the JavaScript bundle at build time.

### Running the API on your Mac directly

Unlike Windows — which needs `python -m app.devserver` to install a selector
event-loop policy for async psycopg — macOS runs uvicorn directly:

```bash
cd backend && ../CV-RULE_ENG-NLP/.venv/bin/uvicorn app.main:app --reload --port 8080
```

### Database schema changes

Migrations live in `supabase/migrations/`, applied with `supabase/apply.sh`.
**Coordinate before applying anything** — it is the shared database. `apply.sh`
skips already-recorded migrations by *filename*, so never edit an applied
migration; add a new numbered one.

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

Open a pull request against `full-engine`. Before pushing:

- [ ] `git status` shows no `.env` or `.env.local`
- [ ] the suites relevant to your change pass
- [ ] no secret in any committed file, including comments

---

## 9. Troubleshooting on macOS

| Symptom | Fix |
|---|---|
| `failed to find libmagic` | `brew install libmagic`, then the `DYLD_FALLBACK_LIBRARY_PATH` export above |
| Build dies with no error | Docker Desktop memory too low — raise to 8 GB+ |
| `no matching manifest for linux/arm64` | an image lacks arm64; report it — everything here is arm64-native |
| `python3.11: command not found` | `brew install python@3.11`, and check `/opt/homebrew/bin` is on `PATH` |
| `ModuleNotFoundError: engine` | you are using system Python, not the venv |
| `FATAL: ... unfilled placeholders` | a `__PASTE_...__` remains in `.env` |
| `FATAL: ... points at a local host` | a data-plane URL still contains `127.0.0.1` |
| `/readyz` → `db:false` | wrong DB password, or the wrong pooler port |
| Uploads → 503 `scanner_unavailable` | ClamAV still downloading its database — wait |
| Tests fail intermittently around jobs | your worker container is running — stop it |
| Very slow file access in containers | enable VirtioFS in Docker Desktop → General |

**Use the Session pooler (port 5432), never the transaction pooler (6543).**
psycopg3 promotes hot statements to server-side prepared statements after five
executions, and PgBouncer in transaction mode drops those between transactions.
The failures are intermittent and begin only once the app warms up.

Do **not** run `scripts/sync_env.py`. It writes self-hosted stack credentials
and refuses while `SUPABASE_MODE=cloud`. That refusal is correct.

---

## 10. Orientation

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
| `ONBOARDING.md` | the same guide, Windows/Linux paths |
| `ENGINE.md` | the four-layer engine in depth |
| `backend/README.md` | backend runbook and design notes |
| `supabase.md` | schema and data-plane detail |
| `DEPLOY.md` | deployment and its open questions |
| `AUTH_AUDIT_AND_PLAN.md` | auth hardening status |

**Reports are decision support, not legal advice.** That framing holds in the
product copy and in the code.
