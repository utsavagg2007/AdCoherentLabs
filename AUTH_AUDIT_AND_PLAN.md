# AdCoherent Labs — Authentication Security Audit & Migration Plan

*Produced per `supabase-auth-creation.txt` (Phase 1: audit + threat model;
Phase 2: architecture + migration plan for approval). Audited 2026-07-14
against the live repo and the running self-hosted stack — every claim below
was verified by inspection or by probing the deployed services; nothing is
assumed from documentation alone.*

**Identity provider: our self-hosted Supabase Auth (GoTrue v2.189.0) only.**
No hosted Supabase, no `*.supabase.co`, no third-party IdP. The FastAPI
backend (`backend/`) remains the sole owner of business logic, authorization,
tenant isolation, billing, entitlements, and audit.

**Phase 3 status:** the *smallest safe changes* (backend-only hardening: JWT
issuer validation, email-only confirmation gate, `aal2` step-up for
privileged actions) are implemented and tested in this repo. The frontend
migration (§8B) and the GoTrue configuration changes (§10C, live-stack edits
I don't apply autonomously) **await your approval / your hands**.

---

## 1. Current architecture

| Plane | Technology | Auth-relevant state (verified) |
|---|---|---|
| Identity | GoTrue v2.189.0 behind Kong `:8000` | HS256 (`GOTRUE_JWT_SECRET`), `aud=authenticated`, `exp=3600s`, `iss=http://localhost:8000/auth/v1` (probed with a real login), TOTP MFA available (`aal`/`amr` claims present), signup open, email autoconfirm **off**, **phone signup ON with autoconfirm ON**, SMTP = fake `supabase-mail` (container not even running) |
| Data plane | Postgres 15 + RLS (migrations 0001–0010) | Tenancy = `orgs`/`memberships` (uuid-keyed), tier = Stripe-synced `subscriptions`, hash-chained `audit_logs`, red-line RLS isolation test passing |
| Backend | FastAPI `backend/` (api / worker / scheduler) | Local HS256 verify (sig, `exp`, `aud`) or sha256 `X-API-Key`; org derived from `memberships` only; deny-by-default role lattice; privileged DB role scopes `org_id` explicitly; rate limits; credit gate |
| Frontend | Next.js 16 `frontend/` (@supabase/ssr + supabase-js) | Complete auth screens (login/signup/forgot/reset/verify/callback), cookie sessions, `proxy.ts` session refresh. **Runs in demo mode by default** (no env). Server actions perform business writes **directly against Postgres with the service-role key**; has its **own Stripe webhook** with hand-rolled HMAC |

The frontend predates the FastAPI backend: it was built as a
Supabase-direct app. The Backend Architecture spec (§4, "division of
labour") supersedes that design — this plan migrates it.

## 2. Current authentication flow

**Browser:** signup/login/magic-link → GoTrue via Kong with the anon key →
`@supabase/ssr` persists the session in chunked `sb-*` cookies → `proxy.ts`
refreshes tokens → server components read the session cookie-side. Login page
already guards `next=` redirects to same-origin relative paths (no open
redirect). Email verification is required by GoTrue config *and* re-checked
by the backend before analysis.

**Backend API:** `Authorization: Bearer <access_token>` → local HS256 verify
(signature, `exp`, `aud=authenticated`; **`iss` now enforced too** — see §4
W3) → user = verified `sub` claim → `auth.users` + `memberships` lookup
(Redis 60 s) → org context; a client-supplied `X-Org-Id` only *selects among*
the caller's verified memberships. Programmatic: `X-API-Key` → sha256 lookup,
scope + entitlement + revocation checks. Identity mapping is **by immutable
UUID**, never by email (email changes cannot break it).

**Worker/scheduler:** no user identity; privileged DB role; tenant scoping by
explicit `org_id` from the leased job's run row; tier re-fetched from the DB
per execution.

## 3. Current tenant model

`orgs` ←(cascade)— `memberships (org_id, user_id uuid PK pair, role ∈
owner>admin>reviewer>viewer)` — `subscriptions (org_id PK, Stripe-synced
tier/status/period/grace)`. Every tenant table carries `org_id` with FK +
RLS; storage objects live under `assets/<org_id>/…` with org-scoped
policies; `plan_entitlements` drives seats/limits. Cross-org ids answer 404
(existence never revealed). Unique constraints prevent duplicate membership;
FK cascade defines erasure. Platform-admin (`/v1/admin/*`) is a separate
path: `ADMIN_EMAILS` allowlist, dual-logged, hidden (404) from tenants.

## 4. Existing security weaknesses (found in this audit)

| # | Severity | Weakness | Disposition |
|---|---|---|---|
| W1 | **Critical** | Stack still runs the **public default** `JWT_SECRET`/anon/service keys → anyone can mint a `service_role` JWT | Staged fix exists: `python supabase/harden.py` (**you must run it — P0**); backend refuses prod boot on defaults; `sync_env.py` refuses defaults |
| W2 | **High** | `ENABLE_PHONE_SIGNUP=true` + `ENABLE_PHONE_AUTOCONFIRM=true` → zero-verification accounts; backend/engine accepted `phone_confirmed_at` as "confirmed" → the email-verification gate was bypassable | **Fixed backend-side** (email-only confirmation, §8A); stack config change for you in §10C |
| W3 | Medium | JWT `iss` was not validated → a token minted by any other GoTrue sharing the secret (staging vs prod) would verify | **Fixed**: exact-match `SUPABASE_JWT_ISSUER` (probed value `http://localhost:8000/auth/v1`); unset ⇒ boot warning (dev only) |
| W4 | Medium | Frontend server actions hold the **service-role key** and write business data directly (bypasses backend authz, credits, rate limits, hash-chained audit) | Migration plan §8B — retire in favour of bearer calls to FastAPI (needs approval) |
| W5 | Medium | **Second Stripe webhook** in Next (`src/app/api/billing/webhook`) with hand-rolled HMAC, no `billing_events` idempotency, no grant wiring — two writers for subscription state | Retire; Stripe points only at FastAPI `/webhooks/stripe` (§8B) |
| W6 | Medium (ops) | SMTP is the fake `supabase-mail` (not running) → confirmation/recovery emails are undeliverable; users cannot complete signup unaided | Real SMTP before beta (§10C/§11); dev workaround documented in `RUNNING_REAL_ADS.md` |
| W7 | Low | No MFA anywhere; privileged actions (key minting, role changes, billing) had no step-up | **Fixed backend-side**: `aal2` step-up required for those actions *when the user has a verified TOTP factor* (§8A); enrollment UI is frontend Phase 3 |
| W8 | Low | GoTrue password policy at default (min length 6, no HIBP check) | Config lines in §10C |
| W9 | Low | GoTrue rate limits at defaults; Kong was published on `0.0.0.0` (loopback binding staged, applies after harden restart); backend `ip:` buckets protect only `/v1`, not `/auth/v1` | harden.py + §10C review; edge proxy at launch (spec §9.1) |
| W10 | Info | `@supabase/ssr` session cookies are JS-readable by design (browser client needs them) → XSS = session theft | Mitigation: strict CSP on the app at launch, no third-party scripts, security headers already on the API; documented residual risk |

## 5. Proposed target architecture

GoTrue stays the **only** authenticator (signup, login, email verification,
password reset, refresh/logout, TOTP MFA). The FastAPI backend stays the
**only** authorizer and business writer.

```
Browser ── signup/login/refresh/reset/MFA ──► Kong :8000 → GoTrue   (anon key, RLS world)
Browser ── Realtime run status, signed asset URLs ─► Kong (RLS-bound reads)
Browser ── EVERY business mutation + canonical reads ──► FastAPI :8080
              Authorization: Bearer <supabase access token>
FastAPI ── verify HS256 sig+exp+aud+iss → sub → memberships → org/role/tier
        ── deny-by-default · credits · rate walls · step-up (aal2) · audit chain
service_role key: backend containers ONLY (removed from Next at cutover)
Stripe webhooks: FastAPI /webhooks/stripe ONLY
```

Sessions: the SPA pattern keeps bearer tokens (API is a separate origin;
no cookies cross it → CSRF does not apply to `/v1`). The Next server keeps
its `@supabase/ssr` cookie session solely to render shells and gate pages;
Next server-side calls to FastAPI forward the user's access token. If we
later collapse to a same-origin BFF, cookies become HttpOnly at the proxy
and a CSRF token is added — not needed in the current topology.

Signing keys: the deployed GoTrue uses **legacy HS256** (verified). The
backend validates with the shared secret server-side only (never merely
decodes), and rejects `alg` ≠ HS256. When the stack moves to asymmetric
signing, swap `auth/jwt.py` to the stack's JWKS endpoint with `kid`-based
rotation; until then rotation = `harden.py` → `sync_env.py` → restart backend
(all sessions invalidate — documented, §11).

## 6. Authentication & authorization sequence (target)

1. Browser signs up → GoTrue sends verification email → user confirms.
2. Browser logs in (password or magic link; optional TOTP challenge →
   `aal2`) → GoTrue issues access (1 h) + refresh token; `@supabase/ssr`
   stores and auto-refreshes.
3. Browser calls `POST /v1/submissions` with `Authorization: Bearer <at>`.
4. API middleware: request-id → headers → body cap → CORS → (rate limit).
5. `auth_context`: verify signature + `exp` + `aud=authenticated` + `iss`
   exact-match → `sub` → `auth.users` (email **must** be confirmed) →
   `memberships` (requested org must be among them) → role, tier,
   entitlements (cached 60 s).
6. Route gates: role floor → entitlement → billing hold → rate buckets →
   step-up (`aal2` if the user has a verified factor and the action is
   privileged) → business logic → hash-chained audit event.
7. Logout/refresh/revocation: GoTrue's; the API honours it within `exp`
   (≤ 1 h) — revoked-refresh sessions can't mint new access tokens.
   API keys revoke instantly (DB lookup per request).

## 7. Threat model (STRIDE, deltas only — full controls in the spec docs)

| Threat | Control |
|---|---|
| Forged/replayed JWT | HS256 signature + `exp` + `aud` + **`iss`** (W3 fix); secret rotation runbook; prod boot refuses default secrets |
| Cross-environment token reuse | `iss` exact match per environment |
| Zero-verification accounts | email-only confirmation gate (W2 fix) + disable phone signup (§10C) |
| Privilege escalation (horizontal) | membership re-verified in DB per request; client `org_id`/role never authority; RLS red-line test; cross-org = 404 |
| Privilege escalation (vertical) | role lattice enforced per route *and* in data plane; owner role immutable via member routes; platform-admin path separate + dual-logged |
| Session theft via XSS | CSP/security headers; no third-party scripts on app pages (launch checklist); tokens never logged (structlog fields only — verified) |
| Credential stuffing / brute force | GoTrue rate limits + IP buckets + temp bans; password policy + HIBP (§10C); privacy-safe errors (no account-existence oracle: GoTrue returns uniform errors; API returns uniform 401/404) |
| Refresh-token theft/reuse | GoTrue rotation + reuse detection (v2 default); logout revokes |
| Sensitive-action takeover from a stolen session | **step-up: `aal2` required** for API keys, membership changes, billing, admin credit ops (W7 fix) |
| CSRF | `/v1` is bearer-only (immune); Next server actions are same-origin POSTs (Next origin checks); no cookie ever authorizes `/v1` |
| Open redirect | login `next=` restricted to same-origin relative paths (verified in code); `GOTRUE_URI_ALLOW_LIST` kept empty/dev-only |
| Webhook forgery | Stripe signature + `billing_events` idempotency at the single FastAPI endpoint; Next webhook retired (W5) |
| Background jobs crossing tenants | worker derives org from the run row keyed by the charged submission; queue chaos + RLS tests |
| GoTrue outage | existing access tokens keep working ≤ `exp` (local verify); new logins fail visibly; API **fails closed** on any unverifiable token |

## 8. Files that need to change

**A. Done in this pass (smallest safe change — backend only, additive):**

| File | Change |
|---|---|
| `backend/app/config.py` | `SUPABASE_JWT_ISSUER` setting |
| `backend/app/auth/jwt.py` | exact `iss` validation (config-gated; warn-once when unset in dev) |
| `backend/app/deps.py` | confirmation = `email_confirmed_at` **only**; `aal` claim + `mfa_verified` (cached) on AuthContext; `require_step_up()` |
| `backend/app/routes/{api_keys,orgs,billing,admin}.py` | `require_step_up()` on key issue/revoke, member role change/remove, billing checkout/portal, admin credit adjust |
| `scripts/sync_env.py` + root `.env` | emit `SUPABASE_JWT_ISSUER` from the stack's `API_EXTERNAL_URL` |
| `backend/tests/…` | wrong-iss → 401; phone-only-confirmed → 403; step-up 403/pass matrix |

**B. Phase 3 (frontend migration — needs your approval, ~a day of work):**

| File | Change |
|---|---|
| `frontend/src/lib/api.ts` (new) | typed fetch wrapper → `NEXT_PUBLIC_API_URL`, forwards the Supabase access token |
| `frontend/src/app/actions.ts` | rewrite business mutations (submit, findings, members, org, API keys) as FastAPI calls; keep GoTrue-only actions |
| `frontend/src/lib/supabase/admin.ts` + service-role env | **delete** after the last call site migrates |
| `frontend/src/app/api/billing/*` , `src/lib/stripe.ts` | retire; billing buttons call `/v1/billing/*`; Stripe dashboard repointed to FastAPI webhook |
| `frontend/src/lib/data.ts` | reads via API (canonical) or RLS-bound Supabase (realtime/lists) — no service role |
| Auth screens | keep as-is (already GoTrue-only); add TOTP enrol/challenge UI (`supabase.auth.mfa.*`) |
| `frontend/.env.local` | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL` — **no** service key, **no** Stripe secret |

## 9. Database migrations required

**None.** Identity mapping already keys on the GoTrue UUID; tenancy/roles
exist; GoTrue owns its `auth.*` tables (incl. `mfa_factors`,
`audit_log_entries`). Optional later: `org_settings.mfa_required` if
org-mandated MFA becomes product policy (new migration 0011, additive).

## 10. Environment variables required

**A. Backend (in place):** `SUPABASE_JWT_SECRET`, **`SUPABASE_JWT_ISSUER`**
(new; dev: `http://localhost:8000/auth/v1`, prod:
`https://<supabase-domain>/auth/v1`), plus the existing Appendix-A set.

**B. Frontend (at cutover):** `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`. Remove
`SUPABASE_SERVICE_ROLE_KEY` and `STRIPE_*` from the Next environment.

**C. GoTrue — lines for YOU to apply in `C:\Users\HP\supabase-project\.env`
(I don't edit the live stack; restart with `docker compose up -d` after):**

```env
ENABLE_PHONE_SIGNUP=false            # closes W2 at the source
ENABLE_PHONE_AUTOCONFIRM=false
GOTRUE_PASSWORD_MIN_LENGTH=12        # W8 (add under the auth service env if not templated)
GOTRUE_PASSWORD_HIBP_ENABLED=true    # optional, breached-password check
# W6 — real SMTP before beta (Resend example; supabase.md §5):
SMTP_ADMIN_EMAIL=noreply@adcoherentlabs.com
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USER=resend
SMTP_PASS=<key>
SMTP_SENDER_NAME=AdCoherent Labs
```

## 11. Operational requirements

1. **P0 first**: `python supabase/harden.py` → `python scripts/sync_env.py`
   → restart backend compose → `python -m engine.cli saas-selftest`.
2. **JWT rotation runbook** (HS256): harden.py mints a new secret → every
   session invalidates (users re-login) → sync_env + backend restart. Rotate
   on schedule and on suspicion; order: stack → backend → frontend anon key.
3. **SMTP** (§10C) before any external user signs up.
4. **GoTrue outage behaviour**: `/readyz` stays green (API auth is local);
   logins fail at the frontend with a clear banner — add a Kong/GoTrue probe
   to uptime monitoring at launch.
5. **Auth observability**: GoTrue writes `auth.audit_log_entries`
   (login/logout/signup/MFA events, includes IPs) — set a retention window
   (suggested: 1 year) and include it in the backup policy; backend 401/403
   rates are already metered.
6. Backups/restore, incident response, account-compromise: supabase.md §7 +
   backend/README launch checklist (restore rehearsal still pending — gap).

## 12. Security & privacy assumptions + data inventory (auth scope)

| Data | Where | Class | Retention |
|---|---|---|---|
| Email, bcrypt password hash | `auth.users` | Confidential | life of account + 30 d (spec §14.1) |
| Session/refresh tokens | GoTrue tables + `sb-*` cookies | Sensitive | session lifetime; revoked on logout |
| TOTP secrets | `auth.mfa_factors` | Sensitive | until factor removal |
| Login IPs, user agents | `auth.audit_log_entries` | Confidential (PII) | set 1 y policy (§11.5) |
| JWTs / API keys | never stored (keys sha256-only), never logged | — | — |

Assumptions: single-region self-hosted US deployment; TLS terminates at the
launch proxy (dev is loopback-only); operators with stack-dir access are
trusted; no analytics/error tracker currently receives PII (Sentry, when
enabled, is configured `send_default_pii=False` — already in code).
Privacy-safe errors: uniform 401/404s; GoTrue signup/reset responses do not
reveal account existence.

## 13. Compliance-control gap report

*No compliance claim is made — this is the gap list an auditor would open with.*

- **Secrets management**: `.env` files, not a vault/KMS; no documented rotation calendar (JWT, DB, Stripe, provider keys).
- **GDPR/CCPA**: erasure + export paths exist technically (org cascade + report exports) but no user-facing DSR workflow, no DPA published, subprocessor list (Anthropic, OpenRouter, Stripe, SMTP provider, host) not yet documented, no DPIA.
- **SOC 2-style controls**: no change-management policy, no access reviews (API-key `last_used_at` exists; no review cadence), no vendor management, no formal incident-response runbook or tabletop.
- **Resilience**: backup restore never rehearsed; RPO documented but untested; no uptime monitoring yet.
- **Assurance**: no external pen test; load suite pending; `auth.audit_log_entries` retention unset.
- **MFA**: available + enforced as step-up only for enrolled users; not yet mandatory for owners/admins (product decision pending).

## 14. Rollback plan

All Phase-3A changes are additive and config-gated: unset
`SUPABASE_JWT_ISSUER` → issuer check off (warn-once); step-up only ever
fires for users with a verified factor (delete the factor or revert the
route lines to disable); the email-only confirmation gate is one line in
`deps.py` (revert restores the coalesce behaviour). No schema changed, no
data migrated, no stack file touched — `git revert` of the backend commit is
a complete rollback. The Phase-3B frontend cutover will ship behind
`NEXT_PUBLIC_API_URL` presence (unset ⇒ old Supabase-direct paths), so it
rolls back by env var.

## 15. Verification commands

```powershell
# Red lines + auth matrix + step-up + issuer tests (worker stopped first):
docker compose -f backend/docker-compose.backend.yml stop worker
cd backend; ..\CV-RULE_ENG-NLP\.venv\Scripts\python.exe -m pytest tests -q
docker compose -f backend/docker-compose.backend.yml start worker

# Live token sanity (mints a real session; see RUNNING_REAL_ADS.md §2):
#   iss must equal SUPABASE_JWT_ISSUER, aud=authenticated, aal present.

# Data-plane + isolation + chain:
python -m engine.cli saas-selftest
docker exec -i supabase-db psql -U postgres -d postgres -v ON_ERROR_STOP=1 < supabase/tests/rls_isolation_test.sql
docker exec supabase-db psql -U postgres -d postgres -c "select count(*) from app.verify_audit_chain() where not ok;"

# After harden.py: old keys must be dead
grep "your-super-secret" C:\Users\HP\supabase-project\.env   # → no matches
```

---

### Approval needed to proceed

1. **Phase 3B frontend migration** (§8B) — rewrite `actions.ts` onto the
   FastAPI API, retire the Next service-role/admin client and the duplicate
   Stripe webhook, add the TOTP enrol/challenge screens.
2. **GoTrue config changes** (§10C) — you apply + restart the auth container.
3. Product decision: make MFA **mandatory** for owner/admin roles, or keep
   it optional-with-step-up (current implementation).
