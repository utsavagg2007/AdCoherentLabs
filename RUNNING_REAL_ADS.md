# Running Real Ads Through AdCoherent — The Complete Guide

How to submit a real advertising creative (text, image, HTML, or carousel)
to the 4-layer compliance engine and read the final verdict — via the CLI
(fastest for a single ad) or the full SaaS pipeline (what customers use).
Every command below was verified on this machine on 2026-07-14.

> Reports are **decision support for a compliance desk, not legal advice** —
> `status: passed` means the review is *trustworthy* (complete, grounded,
> deterministically verified), **not** that the ad is clean. The ad's
> problems are in `llm_review.findings` and `verification.asset_defects`.

---

## 0. Prerequisites

| Need | How |
|---|---|
| Supabase stack up (11 containers) | Docker Desktop running; stack auto-starts. Check: `docker ps` → `supabase-db … healthy`, `adcoherent-rag-db-proxy` present |
| Backend containers (SaaS path) | `cd backend && docker compose -f docker-compose.backend.yml up -d` → `curl http://127.0.0.1:8080/readyz` → `{"ready":true,…}` |
| **LLM provider key** (real reviews) | Put in the **root `.env`**: `OPENROUTER_API_KEY=` (free/hobby tiers → `qwen/qwen3.7-plus` / `qwen/qwen3.7-max`) and/or `ANTHROPIC_API_KEY=` (pro/design/enterprise → Claude). Then run `python scripts/sync_env.py` (propagates the key + DB creds into every env file) and `docker compose -f backend/docker-compose.backend.yml restart worker` |
| **One command for all env files** | `python scripts/sync_env.py` regenerates root `.env`, `rag-engine/.env`, and `backend/.env` from the stack `.env` + the password the DB actually accepts. Run it after any `harden.py` rotation — it also warns if a rotation is half-applied |
| No key yet? | Everything still runs with `--stub-llm` (CLI) — a deterministic offline Layer 3. Zero spend, real Layers 1/2/4 |
| RAG grounding | Already loaded: 11,061 regulation chunks in the local corpus. Without a DB the engine degrades loudly (empty retrieval → reviews lean on `needs_review`) |
| Security note | Before anything leaves localhost: `python supabase/harden.py` then `python backend/scripts/gen_env.py` (spec P0; see `AUTH_AUDIT_AND_PLAN.md`) |

The Python for all host commands is the working venv:
`CV-RULE_ENG-NLP\.venv\Scripts\python.exe` (run from the repo root).

---

## 1. Path A — CLI: one ad, one command

No accounts, no credits — pure engine. Great for evaluating the engine on
your real creatives.

```powershell
$py = "CV-RULE_ENG-NLP\.venv\Scripts\python.exe"

# TEXT ad (uses ANTHROPIC_API_KEY because tier=pro):
& $py -m engine.cli check --text "Get 5.99% APR, guaranteed approval!" `
      --tier pro --jurisdictions US-CA --out report.json

# IMAGE ad through real PaddleOCR, free tier (uses OPENROUTER_API_KEY):
& $py -m engine.cli check --image my-banner.png --tier free --out report.json

# CAROUSEL = several images:
& $py -m engine.cli check --image card1.png card2.png card3.png --tier design

# HTML creative:
& $py -m engine.cli check --html-file landing.html --tier hobby

# Audit replay against the regulations effective on a past date:
& $py -m engine.cli check --text "..." --tier enterprise --as-of 2026-01-15

# No API keys yet — full pipeline with the deterministic stub LLM:
& $py -m engine.cli check --image my-banner.png --tier free --stub-llm
```

**Exit codes:** `0` passed · `2` human_review (operator input needed — add
`--interactive` to answer the engine's questions live) · `3` llm_error ·
`4` quota/permission (SaaS mode) · `1` usage error.

**Output:** the JSON report at `--out` (see §4 for how to read it). First
image run downloads the OCR models once (~a minute); later runs are warm.

### SaaS-mode CLI (tier comes from the DB, run is persisted + charged)

```powershell
& $py -m engine.cli check --text "..." --user you@yourco.com     # --tier is IGNORED: app.org_tier decides
& $py -m engine.cli quota --user you@yourco.com                  # credit balance/price list
```

---

## 2. Path B — the SaaS pipeline (what a customer's run looks like)

Browser flow: the Next.js app in `frontend/` has the full signup → submit →
watch → report UI (`npm run dev`, set `NEXT_PUBLIC_SUPABASE_URL` +
`NEXT_PUBLIC_SUPABASE_ANON_KEY` in `frontend/.env.local` to leave demo
mode). Below is the same flow as raw API calls — useful for testing and for
Pro+ programmatic integration.

### 2.1 Get a user + org + JWT

Dev reality: the stack's SMTP is a placeholder, so **verification emails do
not deliver locally**. Two options:

**Option 1 — sign up via GoTrue, confirm via SQL:**

```powershell
$env:ANON = (Select-String '^ANON_KEY=' C:\Users\HP\supabase-project\.env).Line.Split('=')[1]
curl -s -X POST "http://127.0.0.1:8000/auth/v1/signup" -H "apikey: $env:ANON" `
     -H "Content-Type: application/json" `
     -d '{"email":"you@yourco.com","password":"A-Strong-Passw0rd!"}'
# confirm the email (dev only - production uses the real email link):
docker exec supabase-db psql -U postgres -d postgres -c `
  "update auth.users set email_confirmed_at = now() where email = 'you@yourco.com';"
```

**Option 2 — create the user fully in SQL** (GoTrue needs the empty-string
token columns or logins 500):

```sql
insert into auth.users (instance_id, id, aud, role, email, encrypted_password,
  email_confirmed_at, created_at, updated_at, raw_app_meta_data, raw_user_meta_data,
  confirmation_token, recovery_token, email_change_token_new, email_change,
  email_change_token_current, phone_change, phone_change_token, reauthentication_token,
  is_sso_user, is_anonymous)
values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), 'authenticated',
  'authenticated', 'you@yourco.com', crypt('A-Strong-Passw0rd!', gen_salt('bf')),
  now(), now(), now(), '{"provider":"email","providers":["email"]}', '{}',
  '', '', '', '', '', '', '', '', false, false);
```

**Org** (first login has no org; create one — this also grants the first
free-tier credit cycle):

```sql
-- as the user, through PostgREST/frontend it's: select app.create_org('YourCo');
-- dev shortcut with a known user id:
docker exec supabase-db psql -U postgres -d postgres -c "
  with u as (select id from auth.users where email = 'you@yourco.com')
  insert into public.orgs (name) values ('YourCo') returning id;"
-- then memberships (owner) + subscriptions (free) rows, or just use the frontend/onboarding.
```

**Login → JWT** (expires in 1 h; refresh via GoTrue or just re-login):

```powershell
$tok = (curl -s -X POST "http://127.0.0.1:8000/auth/v1/token?grant_type=password" `
   -H "apikey: $env:ANON" -H "Content-Type: application/json" `
   -d '{"email":"you@yourco.com","password":"A-Strong-Passw0rd!"}' | ConvertFrom-Json).access_token
```

### 2.2 Submit the ad (this is where credits are charged)

```powershell
# TEXT / HTML (JSON):
curl -s -X POST http://127.0.0.1:8080/v1/submissions `
  -H "Authorization: Bearer $tok" -H "Content-Type: application/json" `
  -d '{"kind":"text","content":"Get 5.99% APR, guaranteed approval!","title":"Q3 banner","target_jurisdictions":["US-CA"]}'

# IMAGE (multipart) — png/jpeg/webp/gif; sniffed, scanned, re-encoded:
curl -s -X POST http://127.0.0.1:8080/v1/submissions `
  -H "Authorization: Bearer $tok" `
  -F "file=@my-banner.png" -F "title=Q3 banner" -F "target_jurisdictions=US-CA"

# CAROUSEL — repeat the file field (2–10 cards):
curl -s ... -F "file=@card1.png" -F "file=@card2.png" -F "file=@card3.png"
```

→ `202 {"submission_id","run_id","credits_charged","balance":{...}}`
→ `402 insufficient_credits` when the balance can't fund it (nothing runs,
nothing charged; the attempt is recorded + audited)
→ `422/415/413` when the file fails the security pipeline (infected /
spoofed type / oversized).

Add an `Idempotency-Key: <uuid>` header on retries — duplicates replay the
original response for 24 h instead of double-charging.

**Price (credits) = base × tier multiplier** — published, flat, charged
before execution:

| kind | free | hobby | pro | design | enterprise |
|---|---|---|---|---|---|
| text | 1 | 2 | 5 | 10 | 10 |
| image / html | 2 | 4 | 10 | 20 | 20 |
| 3-card carousel | 4 | 8 | 20 | 40 | 40 |
| monthly allowance | 25 | 400 | 6,000 | 50,000 | custom |

`GET /v1/credits` shows balance + the full price list. Failed-on-our-side
runs refund automatically; a delivered review never does.

### 2.3 Watch the run

The worker picks the job up within ~2 s and streams status onto the run row:
`queued → running_cv → running_nlp → running_llm → reconciling → complete |
human_review | failed` — the frontend subscribes via Supabase Realtime;
programmatically:

```powershell
curl -s http://127.0.0.1:8080/v1/runs/$RUN_ID -H "Authorization: Bearer $tok"
# → {"run":{"status":"complete",...},"queue":null,...}
```

A tier's real LLM is used (free/hobby → Qwen via OpenRouter; pro+ →
Claude). Text runs finish in ~seconds-to-a-minute; first image run adds OCR
warm-up.

### 2.4 Get the final output

```powershell
curl -s http://127.0.0.1:8080/v1/runs/$RUN_ID/report -H "Authorization: Bearer $tok" > report.json
curl -s "http://127.0.0.1:8080/v1/findings?run_id=$RUN_ID" -H "Authorization: Bearer $tok"
# approve / flag / dismiss a finding (reviewer+):
curl -s -X PATCH http://127.0.0.1:8080/v1/findings/$FINDING_ID `
  -H "Authorization: Bearer $tok" -H "Content-Type: application/json" `
  -d '{"status":"approved"}'
```

### 2.5 When the engine asks for a human (`human_review`)

The LLM exhausted its 3-round budget without producing a review that passes
all ~50 deterministic checks. Read `report.human_review.instructions`, then:

```powershell
curl -s -X POST http://127.0.0.1:8080/v1/runs/$RUN_ID/resume `
  -H "Authorization: Bearer $tok" -H "Content-Type: application/json" `
  -d '{"guidance":"The APR claim is substantiated by the rate sheet on file; evaluate clm_2 against TILA 1026.24(d) and clear it if the disclosure block satisfies it."}'
```

Costs **0 credits** (same creative), runs ONE steered round, returns a new
`run_id` linked via `resumed_from_run_id`. Repeat as needed.

### 2.6 Programmatic access (Pro+ tiers)

```powershell
# mint once (admin; secret shown exactly once; sha256 at rest):
curl -s -X POST http://127.0.0.1:8080/v1/api-keys -H "Authorization: Bearer $tok" `
  -H "Content-Type: application/json" -d '{"name":"ci-bot","scopes":["submit","read"]}'
# then use X-API-Key instead of the JWT on /v1/*:
curl -s http://127.0.0.1:8080/v1/runs -H "X-API-Key: ack_..."
```

Interactive API docs: http://127.0.0.1:8080/docs · OpenAPI JSON:
`/v1/openapi.json`.

---

## 3. Where every output lives

| Artifact | Where |
|---|---|
| Full engine report (`EngineRunResult`) | `GET /v1/runs/{id}/report` (persisted as the `report` layer output); CLI `--out report.json`; sample: `engine-sample-report.json` |
| Reviewable findings (LLM findings + deterministic asset defects) | `findings` table / `GET /v1/findings?run_id=` |
| Per-layer traces (OCR/NLP asset, LLM rounds, rule verdicts) | `layer_outputs` (`cv`,`nlp`,`llm`,`rule`,`report`) |
| Charges/refunds | `GET /v1/credits/ledger` |
| Tamper-evident history | `audit_logs` (hash-chained; owners/admins can read their org's) |
| Run provenance (model, prompt version, corpus hash, ruleset) | on the run row + inside the report's `provenance` block |

## 4. Reading the report

```jsonc
{
  "status": "passed",            // passed | human_review | llm_error
  "llm_review": {
    "findings": [ /* the JUDGMENTS: framework, severity, verdict
                     (potential_violation|needs_review|compliant),
                     quoted_evidence, regulation_citations, reasoning,
                     scope_of_improvement */ ],
    "reviewed_clear": [ /* claims examined and found unproblematic */ ]
  },
  "verification": {
    "review_passed": true,       // the ~50 deterministic checks
    "asset_defects": [ /* TRUE statements about the creative itself:
                          contrast floors, disclosure prominence,
                          prohibited wording - no re-review changes these */ ],
    "advisories": [ /* applicability flags, informational */ ]
  },
  "rounds": [ /* full audit trail incl. the exact feedback each round saw */ ],
  "human_review": null,          // instructions when operator input is needed
  "provenance": { /* model, prompt_version, rag_corpus_hash, ruleset hashes,
                     ocr_backend, saas ids - reproduce the verdict months later */ }
}
```

Decision procedure: `status=passed` → trust the report; act on `findings`
by severity and fix `asset_defects` in the creative. `human_review` → §2.5.
`llm_error` → our side; in the SaaS path it retries and auto-refunds if it
can't complete (you'll see `refund.system_failure` in the ledger).

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `402 insufficient_credits` | `GET /v1/credits`; free = 25/mo. Top up: change tier, buy a pack (paid tiers), or dev: `select app.adjust_credits_manual('<org>', 100, 'subscription', null, 'dev top-up');` |
| Run stuck `queued` | worker container down? `docker compose -f backend/docker-compose.backend.yml up -d worker`. Provider breaker open (no/bad API key) keeps jobs queued — check `docker logs adcoherent-backend-worker-1` |
| Run `failed`, ledger shows a refund | provider errors after 3 attempts (missing key, outage). Fix the key in `backend/.env`, restart worker, resubmit — the failed run cost you nothing |
| `403 Confirm your email` | email confirmation is required (and ONLY email — see AUTH_AUDIT_AND_PLAN.md W2). Dev: the SQL confirm in §2.1 |
| `401` with a fresh token | token expired (1 h) or minted by a different environment (issuer check) — re-login |
| `429` | per-plan rate walls (`X-RateLimit-*` headers, `Retry-After`); free tier = 5 submissions/day |
| First image run very slow | one-time PaddleOCR model download (named volume `paddlex-models` keeps it warm across container restarts) |
| Host pytest suite fails oddly | stop the worker container first — it races the suite for queued jobs |
