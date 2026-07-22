# AdCoherent Labs — SaaS Backend

Implements `AdCoherent_Backend_Architecture.pdf` v1.0: a credit-metered,
tier-rate-limited, security-first FastAPI backend over the frozen 4-layer
compliance engine. One codebase, three processes (**api / worker /
scheduler**) from one Docker image, joined to the existing self-hosted
Supabase stack.

> Reports are decision support, not legal advice — the disclaimer rides on
> every report response.

## P0 — before anything faces a network

The moved Supabase stack still carries the **public default secrets**. Rotate
first, then regenerate the backend env from the rotated values:

```powershell
python supabase\harden.py          # rotates JWT/DB/API secrets, loopback-binds ports
python scripts\sync_env.py         # regenerates the single root .env (backend+engine)
                                   # from the stack .env + the password the DB ACTUALLY
                                   # accepts (warns loudly if a rotation is half-applied)
python -m engine.cli saas-selftest # confirm the data plane still passes
```

**The project has exactly two env files:** the root `.env` (the WHOLE backend +
engine) and `frontend/.env.local` (the Next.js app). `scripts/sync_env.py`
regenerates both from the stack `.env`; it probes the DB so a partial rotation
surfaces as a warning instead of silently breaking retrieval. Inside containers
the host `127.0.0.1` endpoints are swapped for `supabase-db`/`supabase-kong`/
`redis` by `backend/docker-entrypoint.sh` (APP_IN_CONTAINER=1) — so there is no
`backend/.env` and no compose `${...}` interpolation. `backend/scripts/gen_env.py`
is a deprecated alias for `sync_env.py --only root`.

`sync_env.py` **refuses** to write an env from default secrets (override for
throwaway dev only with `--allow-defaults`). The API refuses to boot in
`APP_ENV=prod` with default secrets.

## Run it (dev, this machine)

```powershell
cd supabase; ./apply.sh; cd ..            # migrations 0001–0010 (idempotent)
python scripts\sync_env.py                 # after harden.py (see P0) - writes the single .env
docker compose -f backend\docker-compose.backend.yml up -d --build
# api → http://127.0.0.1:8080 (healthz/readyz/docs)  ·  worker + scheduler headless
```

Host-run alternative (Windows, no containers for the api):
`python -m app.devserver` from `backend/` using `CV-RULE_ENG-NLP\.venv`
(redis + clamav still come from compose).

## The request that spends money

`POST /v1/submissions` → auth (JWT or `X-API-Key`) → role/email/billing gates
→ rate buckets (user / org-api / per-key / org-daily) → upload pipeline
(magic-byte sniff → allowlist → tier size cap → clamd → Pillow re-encode →
sha256 → private storage) → **one transaction**: cycle grant → `app.credit_cost`
→ submission/assets/run rows → `app.consume_credits` (row-locked) →
`app.enqueue_run` → COMMIT → `202 {submission_id, run_id, credits_charged,
balance}`. Insufficient balance → `402 insufficient_credits`, with the
rejected run recorded and audited. `Idempotency-Key` replays the original
response for 24 h.

The engine never runs in the API process: workers lease via
`app.lease_job` (FOR UPDATE SKIP LOCKED; tier priority, per-org concurrency
wall, least-recently-served-org fairness), heartbeat every 30 s, retry with
60/300 s backoff, and DLQ after 3 attempts with an **automatic ledger-derived
refund**. Tier and model are re-fetched from the DB (`app.org_tier`) at
execution time — never from the job payload.

### Accepted media, per plan (migration 0011)

The upload pipeline accepts images, text, HTML, **PDF, DOCX and video**
(mp4/mov/webm). *Which* of those a tenant may submit is a plan entitlement
checked before any expensive work and before anything is charged:

| Tier | `allowed_kinds` | `max_video_seconds` |
|---|---|---|
| free | text · html · image · pdf · docx | — (no video) |
| hobby | + video | 60 |
| pro · design · enterprise | + video | unlimited (MB cap still applies) |

Structural probes run in the API: PDFs must parse and are capped at 40 pages
(password-protected → 422), DOCX must contain `word/document.xml`, video must
decode and report a duration (absolute ceiling 900 s regardless of tier).
Rejections are `403 plan_restricted` / `413 payload_too_large` /
`415 unsupported_media_type`, and never charge. `engine/media.py` converts
each format for the CV/NLP layers (see `ENGINE.md` §5).

### What a run costs

Two components, both published by `GET /v1/plans` (no prices in the frontend):

1. **Base price**, charged at enqueue from `credit_costs` — covers extraction,
   retrieval and verification. It is what the confirm dialog quotes.
2. **Metered model usage**, settled after the run by `app.settle_run_tokens`
   from the tokens actually consumed **summed across every LLM round**, at the
   tier's `token_rates` (ledger reason `consume.tokens`). The charge clamps to
   the available balance — the report already exists, so a shortfall is
   audited rather than failing the run.

`GET /v1/runs/{id}/events` streams the sanitized live-activity feed the
workspace renders while a run executes: fixed message templates plus
aggregate counts only — never ad content, retrieved regulation text, prompts,
or model reasoning.

`POST /v1/orgs` is the one route a zero-membership user may call (dependency
`user_only_context`: verified JWT + confirmed email, no org required), so a
fresh signup can create its first workspace; self-serve accounts are capped at
3 orgs.

When `STRIPE_SECRET_KEY` is empty **and** `APP_ENV != prod`, the checkout
routes simulate the purchase directly (`services/dev_billing.py`, audited
`simulated: true`) instead of 503-ing, so the full billing UX is exercisable
before Stripe is wired.

## Gates run on 2026-07-14 (all green)

| Gate | Result |
|---|---|
| `apply.sh` twice + raw SQL re-run (idempotency) | pass |
| **RED-LINE** credit race: 50 parallel vs balance 10 | exactly 10 charged; floor held; ledger sums |
| **RED-LINE** RLS isolation | pass |
| ledger append-only (update/delete blocked; erasure cascade allowed) | pass |
| `python -m engine.cli saas-selftest` (extended: credit sections E/H/M) | all checks pass |
| `python -m engine.selftest` | pass |
| Existing engine suites | 184 passed + 67 passed (untouched) |
| backend pytest (auth matrix, rate limits + §9.4 degraded modes, upload security incl. EICAR/spoof/polyglot, queue chaos, webhook replay, charge+enqueue fault injection, E2E with stub LLM incl. resume) | 43 passed |
| compose up → `/readyz` 200 (db+redis) in containers | pass |

Run everything: `pytest` from `backend/` (uses `CV-RULE_ENG-NLP\.venv`;
stack + redis must be up; clamav-dependent tests skip when clamd is down).
**Stop the worker container first** (`docker compose stop worker`) or it will
race the suite for queued jobs on the shared dev stack.

## Decision notes (deviations from / interpretations of the spec)

1. **Enterprise (null allowance)**: no automatic cycle grant/expiry; balances
   are contract-provisioned via `grant.manual`. Consumption is still enforced
   (a starved org 402s and gets a manual top-up) so every ledger/balance
   invariant holds for all tiers.
2. **`app.org_cycle_key(org)`** is the single cycle-key derivation (paid:
   subscription+period+tier; free: calendar month). Webhook, scheduler sweep,
   and the API's opportunistic `ensure_cycle_grant` all share it — no
   double-grant is constructible. Free tiers need no webhook at all.
3. **Ledger append-only vs erasure**: referential actions
   (`pg_trigger_depth() > 1`, i.e. org-deletion cascade / run set-null) pass;
   any direct UPDATE/DELETE is blocked for every role. GDPR erasure stays a
   single `delete from orgs`.
4. **`job_queue`/`billing_events`/`idempotency_keys` live in the `app`
   schema**: PostgREST never exposes them, satisfying "members never see this
   table" structurally.
5. **Idempotency keys in Postgres, not Redis**: the 24 h replay guarantee
   survives a Redis restart; the scheduler purges expired rows.
6. **v1 analyzable kinds** are text / image (png/jpeg/webp/gif) / html /
   carousel only — pdf/mp4 remain on the storage allowlist for later phases
   but are 415 at submit (no credit price, no engine path).
7. **Uploads re-encode**: webp/gif land as PNG (first frame), JPEG stays
   JPEG — EXIF/polyglot payloads cannot survive the pixel round-trip.
8. **Dev DB URLs** use the socat direct proxy (:54322); prod uses the pooler
   per Appendix A (comments in `.env`).
9. **Per-key rate caps** (`api_keys.rate_limit_rpm`), `analysis_runs.operator_guidance`,
   and the `report` layer output were added in 0010 to carry §9.2/§11 features.
10. **`lease_job` serialises on one advisory lock** so the org-concurrency
    wall cannot be over-admitted by racing workers; lease cost ~ms, far above
    any plausible load (§10.1).

## Layout

```
backend/
  app/          # FastAPI: config, middleware (§6.1 order), auth, deps,
                # services (ratelimit/uploads/storage/credits/queue/stripe/idempotency),
                # routes (§11), schemas, metrics
  worker/       # lease loop + executor (reuses engine.saas persistence) + provider breaker/semaphores
  scheduler/    # watchdog · alerts · cycle grants · idempotency purge ·
                # retention (DRY-RUN default) · ledger reconcile · chain verify · stripe sweep
  docker-entrypoint.sh          # host 127.0.0.1 -> service names when APP_IN_CONTAINER=1
  tests/        # 43 tests incl. the two red-line gates
  Dockerfile · docker-compose.backend.yml · requirements.txt (pinned)
../scripts/sync_env.py          # THE env tool: writes root .env + frontend/.env.local
../.env                         # the single backend+engine env (gitignored)
supabase/migrations/0008..0010  # credits · job queue · billing events
supabase/tests/credit_race_test.py  # standalone red-line race test
```

## Launch path (VPS)

§15.4 verbatim: provision (ufw default-deny, fail2ban, LUKS), move the stack
volumes, re-run RLS + chain-verify + saas-selftest **before** cutover, same
two compose files up behind Caddy TLS, backups cron → encrypted offsite,
uptime on `/readyz`. Rollback = previous image tag; deploys drain workers via
SIGTERM (`stop_grace_period: 120s`) — zero dropped runs.

Still open before GA (spec P11–P12): Sentry DSN + alert routing to a real
pager, margin dashboard queries, Stripe live products + webhook endpoint,
`RETENTION_DRY_RUN=false` after reviewing one dry-run report, load suite +
external pen test, backup restore rehearsal.
