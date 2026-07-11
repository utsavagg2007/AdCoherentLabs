# Supabase — AdCoherent Labs SaaS Data Plane

How the self-hosted Supabase stack is configured for the AdCoherent SaaS, and
every step needed to (re)configure, harden, operate, and launch it. Follows
the *AdCoherent Labs Build Playbook* (Phases 1–3, 6, 8; Appendices B–D).

- Stack location: `/Users/utsavaggarwal/Documents/supabase-data/supabase-project`
- Migrations: `supabase/migrations/` (this repo) — applied with `supabase/apply.sh`
- Tenant-isolation test: `supabase/tests/rls_isolation_test.sql`

---

## 1. Architecture

Self-hosted Supabase (Docker Compose) is the **data plane** for the SaaS:

| Container | Role |
|---|---|
| `supabase-db` | Postgres 15 + `pgvector` — SaaS schema, RAG corpus, embeddings |
| `supabase-auth` | GoTrue — email/password, magic link, OAuth; issues JWTs |
| `supabase-rest` | PostgREST — auto REST API over the schema, RLS-enforced |
| `supabase-storage` (+`imgproxy`) | Uploaded ad assets (private `assets` bucket) |
| `realtime-dev.supabase-realtime` | Live run-status / findings pushes to the UI |
| `supabase-kong` | API gateway — the only thing that should ever be public (`:8000`) |
| `supabase-pooler` | Supavisor — session (`:5432`) and transaction (`:6543`) pooling |
| `supabase-studio` / `supabase-meta` | Admin dashboard (keep private) |
| `adcoherent-rag-db-proxy` | socat sidecar `127.0.0.1:54322 → supabase-db:5432` (direct conn for DDL/maintenance) |

**Trust boundaries** (playbook §2): clients only ever reach Kong with the
`anon`/user JWT; RLS is the tenant wall; the `service_role` key bypasses RLS
and lives **only** in the API/worker environment.

### Connection strings — which to use where

| Consumer | Connection | Notes |
|---|---|---|
| Next.js app / browser | `http://localhost:8000` (Kong) + `ANON_KEY` | Prod: your HTTPS domain |
| API routes / AI worker | Kong + `SERVICE_ROLE_KEY`, or Postgres via pooler | Service role = root: server-side only |
| App DB pools (many short conns) | `postgresql://postgres.<POOLER_TENANT_ID>:<PW>@host:6543/postgres` | Transaction mode — no prepared statements/LISTEN |
| Long-lived worker / RAG engine | Pooler session port `5432` (current `rag-engine/.env`) | Session mode behaves like direct |
| Migrations, DDL, backups | socat proxy `127.0.0.1:54322` (direct to `supabase-db`) | Bypasses the pooler entirely |

---

## 2. What is already configured (state as of 2026-07-07)

- Full stack up and healthy (`docker compose ps` in the stack directory).
- Pooler `_supabase` database repaired 2026-07-06 (was corrupt on disk); both
  pooler ports verified. If it recurs: recreate `_supabase` +
  `_analytics`/`_supavisor` schemas from `volumes/db/*.sql`, restart
  `supabase-pooler`.
- **SaaS schema applied** via `supabase/migrations/0001–0006` (see §4).
- RAG corpus loaded (11k+ chunks) and locked away from the public API (§4.6).
- RLS cross-tenant isolation test **passing**.
- `POSTGRES_PASSWORD` and `DASHBOARD_PASSWORD` customized.

**Not yet done (blockers before any public exposure):** JWT secret rotation
(§3), production SMTP (§5), TLS/reverse proxy + firewall (§8), backups (§7).

---

## 3. CRITICAL — rotate the default secrets first

`grep "your-super-secret" .env` in the stack directory currently matches:
**`JWT_SECRET`, `VAULT_ENC_KEY`, and `SECRET_KEY_BASE` are still the public
defaults from the Supabase repo.** Anyone who knows the defaults can mint a
valid `service_role` JWT and read every tenant's data. The playbook treats
this as launch-blocking; do it before anything is exposed beyond localhost.

Do all of this in the stack directory (`supabase-data/supabase-project`):

```sh
# 1. Generate new secrets
openssl rand -hex 32     # → JWT_SECRET  (≥ 32 chars)
openssl rand -hex 16     # → VAULT_ENC_KEY (32 hex chars)
openssl rand -hex 32     # → SECRET_KEY_BASE
openssl rand -hex 16     # → PG_META_CRYPTO_KEY (if still default)
```

```python
# 2. Mint the anon + service_role API keys from the NEW JWT_SECRET
#    (pip install pyjwt) — 10-year expiry like Supabase's defaults
import time, jwt
secret = "<NEW_JWT_SECRET>"
now = int(time.time())
for role in ("anon", "service_role"):
    print(role, "=", jwt.encode(
        {"role": role, "iss": "supabase", "iat": now, "exp": now + 10*365*24*3600},
        secret, algorithm="HS256"))
```

```sh
# 3. Update .env: JWT_SECRET, ANON_KEY, SERVICE_ROLE_KEY, VAULT_ENC_KEY,
#    SECRET_KEY_BASE (+ SUPABASE_PUBLISHABLE_KEY / SUPABASE_SECRET_KEY if you
#    use the new-style keys). Then restart everything:
docker compose down && docker compose up -d
```

After rotation:

- Every client holding the old `ANON_KEY`/`SERVICE_ROLE_KEY` must be updated
  (Next.js env, worker env). Existing user sessions are invalidated.
- `rag-engine/.env` is unaffected (it authenticates with the Postgres
  password, not JWTs) unless you also rotate `POSTGRES_PASSWORD`.
- Keep the `service_role` key out of anything client-side, forever. Treat it
  like a root password.
- Put real values only in per-environment secret stores; never commit them.

---

## 4. SaaS schema & migrations

### Applying

```sh
cd supabase
./apply.sh                       # idempotent; records files in app.schema_migrations
# custom connection: PSQL="psql $DATABASE_URL" ./apply.sh
```

New migrations: add `supabase/migrations/NNNN_name.sql` (next number), make it
idempotent (`if not exists` / `drop policy if exists`), run `./apply.sh`.
Forward-only; take a backup before destructive changes (playbook Phase 11).

### What each migration creates

| File | Contents |
|---|---|
| `0001_saas_core.sql` | Tenancy (`orgs`, `memberships`), Stripe-synced `subscriptions`, pipeline (`submissions`, `assets`, `analysis_runs`, `layer_outputs`, `findings`), Layer-4 `rule_packs`/`rules`, `usage_events`, `audit_logs`, `api_keys`, `plan_entitlements`, indexes, `updated_at` triggers |
| `0002_rls_policies.sql` | RLS on every table + helper fns `app.user_org_ids()`, `app.is_org_member()`, `app.has_org_role()`, and `app.create_org(name)` (atomic org + owner membership + free subscription) |
| `0003_audit_hash_chain.sql` | Tamper-evident audit log: hash-chain trigger, append-only enforcement, `app.log_audit_event(...)`, `app.verify_audit_chain()` |
| `0004_entitlements_and_quota.sql` | Tier seed (below) + `app.org_tier()`, `app.scans_used()`, `app.check_quota()`, `app.consume_scan_quota()` |
| `0005_storage_and_realtime.sql` | Private `assets` bucket + org-scoped storage policies; realtime publication for `analysis_runs` and `findings` |
| `0006_lock_rag_tables.sql` | RLS (no policies) on all `rag_*` tables → invisible through the public API; RAG engine unaffected (direct owner connection) |

### Tier → entitlements (single source of truth: `plan_entitlements`)

| Tier | Model | Max output tokens | Scans/mo | Seats | API | SSO/SLA |
|---|---|---|---|---|---|---|
| free | `qwen-turbo` | 1,500 | 20 | 1 | — | — |
| hobby | `qwen-max` | 3,000 | 150 | 2 | — | — |
| pro | `claude-sonnet-5` | 8,000 | 1,000 | 8 | ✓ | — |
| design | `claude-opus-4-8` | 16,000 | 4,000 | 20 | ✓ | — |
| enterprise | `claude-opus-4-8` | 32,000 | custom | custom | ✓ | ✓ |

Matches the implemented LLM layer (`rag-engine/adcoherent_rag/review/tiers.py`).
The playbook's Appendix A lists Pro = Opus 4.7 — superseded by the product
decision Pro = Sonnet 5. Quota numbers are the playbook's placeholders:
**re-price from a real cost model before launch** (Opus scans carry real
per-unit cost — playbook §9 margin note).

### Multi-tenancy rules (read before writing any query)

- Shared schema; every tenant row carries `org_id`; visibility derives from
  `auth.uid()` → `memberships`. **Never** trust a client-supplied `org_id`.
- Roles: `owner` > `admin` > `reviewer` > `viewer` (playbook Phase 3).
  Reviewer+ submit/annotate; admin+ manage members/keys; subscriptions,
  run-status updates, findings inserts, and metering are **service-role-only**
  writes (no authenticated policy exists on purpose).
- Orgs are created only through `select app.create_org('Acme');` — atomic org
  + owner membership + free-tier subscription.
- **`service_role` bypasses RLS.** Every worker/API code path using it must
  set `org_id` explicitly on reads and writes — there is no DB safety net.
  Keep authorisation checks in the API layer too (defence in depth).
- Quota is enforced *before* expensive work:
  `select app.consume_scan_quota('<org>');` → `{"allowed": false, ...}` means
  reject the submission (409/402), don't enqueue.

### The red-line CI test

```sh
docker exec -i supabase-db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  < supabase/tests/rls_isolation_test.sql
# → NOTICE: RLS ISOLATION TEST: PASS   (rolls itself back)
```

Proves a user in Org A cannot read/list/mutate Org B rows, cannot write
cross-tenant, and cannot escalate their own subscription. Wire it into CI;
a failure must block merge (playbook Phase 10 calls a tenancy leak
existential).

### Audit log usage

```sql
select app.log_audit_event('<org>', '<user>', 'finding.approved',
                           'finding:<id>', '{"from":"open"}');
select * from app.verify_audit_chain() where not ok;  -- 0 rows = chain intact
```

Rows are hash-chained (`sha256(prev_hash + canonical event)`) and append-only
for every role including `service_role`. Log at minimum: auth events, member
changes, submission/run lifecycle, finding approvals, billing changes,
exports. Never put secrets or raw PII in `meta`.

---

## 5. Auth (GoTrue) configuration for the SaaS

Current `.env` values and what to change:

| Setting | Now | Production |
|---|---|---|
| `SITE_URL` | `http://localhost:3000` | `https://app.adcoherentlabs.com` |
| `API_EXTERNAL_URL` / `SUPABASE_PUBLIC_URL` | `http://localhost:8000` | `https://api.adcoherentlabs.com` (Kong behind TLS) |
| `ADDITIONAL_REDIRECT_URLS` | — | Preview/staging URLs, comma-separated |
| `DISABLE_SIGNUP` | `false` | `false` (self-serve) — set `true` for invite-only beta |
| `ENABLE_EMAIL_AUTOCONFIRM` | `false` | Keep `false` — email verification is required before analysis features (playbook Phase 3) |
| `ENABLE_ANONYMOUS_USERS` | `false` | Keep `false` |
| `JWT_EXPIRY` | `3600` | 3600 is fine; refresh tokens handle longevity |
| `SMTP_*` | `supabase-mail` placeholder | **Must change**: real provider (Resend/Postmark/SES) — signup, magic-link and recovery emails do not deliver without it |

SMTP example (Resend):

```env
SMTP_ADMIN_EMAIL=noreply@adcoherentlabs.com
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USER=resend
SMTP_PASS=<api key>
SMTP_SENDER_NAME=AdCoherent Labs
```

Restart `supabase-auth` after any auth env change:
`docker compose up -d supabase-auth`.

OAuth providers (Google/GitHub/Azure) are enabled with
`GOTRUE_EXTERNAL_<PROVIDER>_*` env vars on the auth container; SSO/SAML is the
Enterprise entitlement — plan it as config, not a separate codebase.

**App-side session rules** (playbook Phase 3): validate the session in Next.js
middleware *and* in server components/route handlers; never gate on client
state; check role + entitlement server-side on every action.

---

## 6. Storage, Realtime, and the upload pipeline

**Bucket `assets`** — private, 50 MB/object, MIME allowlist (pdf, png, jpeg,
webp, gif, txt, html, mp4). Path convention is enforced by policy:

```
assets/<org_id>/<submission_id>/<random-key>.<ext>
```

- Members read their org's prefix; reviewer+ upload into it; admin+ delete.
- Serve files to the UI via **short-lived signed URLs** only
  (`supabase.storage.from('assets').createSignedUrl(path, 60)`); never proxy
  user files through the app origin (playbook Phase 8).
- Upload flow (security-critical, playbook Phase 4): validate real MIME by
  sniffing bytes → enforce per-tier size caps in the API → ClamAV scan →
  store under a random key → write the `assets` row (`scan_status='pending'`,
  then `clean`/`infected` from the worker) → enqueue.
- URL/landing-page assets: fetch server-side through an egress allowlist,
  block private/link-local/metadata IP ranges, render in a network-isolated
  sandbox (SSRF — playbook Phase 4 box).

**Realtime** — `analysis_runs` and `findings` are in the `supabase_realtime`
publication. The UI subscribes instead of polling:

```ts
supabase.channel('runs')
  .on('postgres_changes',
      { event: 'UPDATE', schema: 'public', table: 'analysis_runs',
        filter: `org_id=eq.${orgId}` },
      handleRunUpdate)
  .subscribe();
```

RLS applies to realtime payloads; a subscriber only receives rows their JWT
can see.

---

## 7. Backups & recovery (self-hosting makes this yours)

Minimum viable, tonight:

```sh
# nightly logical backup, encrypted, shipped OFF this machine
docker exec supabase-db pg_dump -U postgres -d postgres -Fc \
  > backup_$(date +%F).dump
age -r <recipient> backup_$(date +%F).dump > backup_$(date +%F).dump.age  # or gpg
# cron it daily; retain 7 daily + 4 weekly; store in R2/S3/offsite
```

Production-grade: WAL archiving for point-in-time recovery — either
`wal-g`/`pgbackrest` against the `supabase-db` data volume, or (simpler)
migrate the DB to a managed Postgres with PITR when revenue justifies it.

**Test a restore before launch** (playbook: "an untested backup is a hope,
not a backup"):

```sh
docker run -d --name restore-test -e POSTGRES_PASSWORD=x postgres:15
docker exec -i restore-test pg_restore -U postgres -d postgres < backup_YYYY-MM-DD.dump
# verify: select count(*) from rag_chunks;  select * from app.verify_audit_chain() where not ok;
```

Document RPO (≤ 24 h with nightly dumps; minutes with WAL) and RTO, and keep
an incident-response runbook next to this file.

---

## 8. Production hardening checklist (before public traffic)

Ordered; the playbook treats these as launch-blocking (Appendix D).

1. **Rotate default secrets** (§3). `grep "your-super-secret" .env` must
   return nothing.
2. **Never expose**: Postgres (5432/6543/54322), Studio (3000), pg-meta,
   Logflare. Only 80/443 (reverse proxy → Kong) and key-only SSH should be
   reachable. `ufw default deny incoming; ufw allow 80,443/tcp; ufw allow <ssh>`.
3. **TLS**: front Kong with Caddy/Nginx (the stack ships
   `docker-compose.caddy.yml`/`.nginx.yml` overlays — add to `COMPOSE_FILE`).
   HSTS on; HTTPS-only cookies.
4. **Dashboard**: change `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD` (done),
   and keep Studio reachable only via VPN/SSH tunnel.
5. **Rate limiting / WAF** in front of Kong; per-org and per-key limits in
   the API; quota checked before expensive work (`app.consume_scan_quota`).
6. **Backups verified by a real restore** (§7).
7. **CI gates**: the RLS isolation test (§4), gitleaks/secret scan,
   dependency scan on every PR.
8. **Upgrades are your job now**: pin image tags, read the stack's
   `CHANGELOG.md`, snapshot + backup before `docker compose pull && up -d`,
   upgrade staging first. GoTrue/Storage/Postgres security patches are on
   your calendar, not Supabase's.
9. **PII & retention**: classify PII columns, set retention windows per data
   class (raw uploads shorter than findings), schedule deletion, and keep a
   tested GDPR-erasure path (delete org cascade covers the DB; remember
   storage objects under `assets/<org_id>/…` and provider-side data).
10. Consider the playbook's honest tradeoff: if this operational load slows
    the product, Supabase Cloud gives the same Postgres+RLS with §3/§7/§8
    mostly handled, and you can return to self-hosting when data-residency
    or contracts require it.

---

## 9. Environment variables (SaaS app + worker)

Committed as `.env.example` keys only; real values live in per-env secret
stores (playbook Appendix C):

```env
# Supabase
SUPABASE_URL=                 # Kong URL (client+server)
SUPABASE_ANON_KEY=            # client (RLS-bound)
SUPABASE_SERVICE_ROLE_KEY=    # SERVER ONLY — bypasses RLS
DATABASE_URL=                 # pooler session port for the worker; socat 54322 for migrations

# Billing
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_HOBBY= STRIPE_PRICE_PRO= STRIPE_PRICE_DESIGN= STRIPE_PRICE_ENTERPRISE=

# Model providers (server only)
ANTHROPIC_API_KEY=            # pro / design / enterprise
DASHSCOPE_API_KEY=            # free / hobby (Qwen via DashScope)
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1

# Ops
REDIS_URL=                    # queue (if BullMQ)
SENTRY_DSN=
EGRESS_PROXY_URL=             # SSRF control for URL-asset fetching
```

Stripe wiring (playbook Phase 6): webhook is the **source of truth** — on
`customer.subscription.*` / `invoice.*`, verify the signature and upsert
`subscriptions` (`tier`, `status`, `current_period_start/end`) with the
service role. Entitlements always resolve from the DB
(`app.check_quota(org)`), never from the client.

---

## 10. Operations quick reference

```sh
cd /Users/utsavaggarwal/Documents/supabase-data/supabase-project
docker compose ps                        # health
docker compose logs -f supabase-auth     # a service's logs
docker compose up -d                     # apply .env changes / restart

# psql into the DB (direct)
docker exec -it supabase-db psql -U postgres -d postgres

# apply migrations / run the isolation test (from this repo)
supabase/apply.sh
docker exec -i supabase-db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  < supabase/tests/rls_isolation_test.sql

# quota / audit spot-checks
docker exec supabase-db psql -U postgres -d postgres -c \
  "select app.check_quota('<org-uuid>');"
docker exec supabase-db psql -U postgres -d postgres -c \
  "select * from app.verify_audit_chain() where not ok;"
```

Troubleshooting notes specific to this install:

- **Pooler down / `_supabase` corruption** (seen 2026-07-06): recreate the
  `_supabase` DB + `_analytics`/`_supavisor` schemas from `volumes/db/*.sql`,
  restart `supabase-pooler`. The socat proxy (54322) keeps working meanwhile.
- **Pooler username** is `postgres.<POOLER_TENANT_ID>` — the tenant id is
  currently the literal string `your-tenant-id`; if you change it in `.env`,
  update `rag-engine/.env` too.
- **PostgREST 404s on new tables**: `docker compose restart supabase-rest`
  (schema cache), or `notify pgrst, 'reload schema';`.
