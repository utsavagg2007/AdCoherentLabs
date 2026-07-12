# AdCoherent Labs — Frontend

The SaaS frontend for the AdCoherent compliance engine, built to the **Build
Playbook** (Phase 7 stack: Next.js App Router + TypeScript + Tailwind) against
the data plane already defined in `../supabase/` (self-hosted Supabase,
migrations 0001–0006).

**What's inside**

| Surface | Route | Notes |
|---|---|---|
| Marketing + pricing | `/` | Five-tier pricing from the entitlements model |
| Auth | `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/verify-email` | Email+password, magic link, Google/GitHub OAuth, email verification enforced |
| Onboarding | `/onboarding` | Creates the org via `app.create_org()` (atomic org + owner + free tier) |
| Dashboard | `/dashboard` | Quota, open findings by severity, active runs, compliance rate |
| Submission flow | `/submissions/new` | Direct-to-storage upload (org-scoped policy), URL assets, quota pre-check |
| Analysis viewer | `/runs/[id]` | **Realtime** 4-layer pipeline, findings with evidence/remediation, bbox overlays on the creative, approve / flag / dismiss, provenance + per-layer outputs |
| History & reports | `/reports` | Every run with model / prompt / rule-pack / cost; JSON & CSV export |
| Billing | `/billing` | Stripe Checkout + Billing Portal + webhook sync (webhook = source of truth) |
| Settings | `/settings` | Org rename, member invites, role management (owner/admin/reviewer/viewer) |
| API keys | `/settings/api-keys` | Pro+ entitlement; sha256-hashed keys, shown once |

Authorization follows the playbook's two axes everywhere: **role** (what the
user may do) and **entitlement** (what the org's plan unlocks) — both enforced
server-side, with Postgres RLS as the second layer of defence.

---

## 1. How to run

Requirements: **Node.js 20.9+** (Next.js 16).

```sh
cd frontend
npm install
npm run dev        # http://localhost:3000
```

### Demo mode (zero setup)

With no env vars set, the app boots in **demo mode**: the full product is
browsable with realistic fixture data (a completed loan-ad run with real
TILA/FTC/CFPB findings, a simulated live run that walks the four layers, a
failed malware-scan run, billing, members, API keys). Writes are disabled and
a banner says so. This is the fastest way to evaluate the UI.

Force it on/off explicitly with `NEXT_PUBLIC_DEMO_MODE=true|false`.

### Production build

```sh
npm run build
npm start
```

---

## 2. How to connect the backend

The backend is the self-hosted Supabase stack documented in `../supabase.md`
(Kong on `:8000`, migrations applied via `../supabase/apply.sh`).

### Step 1 — env vars

```sh
cp .env.example .env.local
```

| Variable | Value | Notes |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `http://localhost:8000` | The Kong gateway. Production: your HTTPS API domain |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `ANON_KEY` from the stack's `.env` | RLS-bound, safe for the browser |
| `SUPABASE_SERVICE_ROLE_KEY` | `SERVICE_ROLE_KEY` from the stack's `.env` | **Server only.** Used for: atomic quota consumption, member invites (auth admin), Stripe webhook sync. The app runs without it, with those features degraded |
| `NEXT_PUBLIC_SITE_URL` | `http://localhost:3000` | Used in auth-email redirects and Stripe return URLs |

> Rotate the stack's default JWT secret **before** exposing anything —
> `../supabase.md` §3 treats this as launch-blocking. Rotating changes both
> keys above.

### Step 2 — expose the RPC helpers (one-time SQL)

PostgREST only serves the `public` schema by default, but the SaaS helpers
(`app.create_org`, `app.check_quota`, `app.consume_scan_quota`) live in the
`app` schema. Apply the wrapper migration shipped in this repo:

```sh
# option A: via the migration runner
cp frontend/db/0007_app_rpc_wrappers.sql supabase/migrations/
supabase/apply.sh

# option B: straight into the DB
docker exec -i supabase-db psql -U postgres -d postgres \
  < frontend/db/0007_app_rpc_wrappers.sql
```

Without this, sign-up works but **Create organization** fails with a clear
error message pointing here.

### Step 3 — GoTrue (auth) settings

In the Supabase stack's `.env` (then `docker compose up -d supabase-auth`):

- `SITE_URL=http://localhost:3000` — email links redirect into this app
- `ADDITIONAL_REDIRECT_URLS=http://localhost:3000/auth/callback`
- Keep `ENABLE_EMAIL_AUTOCONFIRM=false` — this app enforces verified email
  before analysis features (playbook Phase 3)
- **SMTP must be real** (Resend/Postmark/SES) or signup/magic-link/recovery
  emails never arrive — see `../supabase.md` §5
- OAuth (optional): set `GOTRUE_EXTERNAL_GOOGLE_*` / `GOTRUE_EXTERNAL_GITHUB_*`
  on the auth container; the login page's buttons use them as-is

The auth callback in this app (`/auth/callback`) handles all GoTrue link
styles: PKCE `?code=`, and `?token_hash=&type=` for confirmation, invites,
magic links and recovery.

### Step 4 — storage & realtime

Nothing to configure if migrations 0001–0006 are applied:

- Uploads go **directly from the browser** to the private `assets` bucket at
  `<org_id>/<submission_id>/<random>.<ext>` — the org-scoped storage policies
  from migration 0005 are the enforcement. Previews use short-lived signed
  URLs (never proxied through the app origin).
- The run viewer subscribes to Supabase Realtime (`analysis_runs` updates +
  `findings` inserts, both in the publication from migration 0005). RLS
  applies to realtime payloads, so a browser only receives its org's rows.

### Step 5 — the worker contract

The frontend **enqueues** work; the AI worker (rag-engine / Phase 4 service)
executes it. Submitting runs this sequence:

1. `submissions` insert (user JWT, RLS-checked, `created_by = auth.uid()`)
2. Browser uploads files to storage; `assets` rows registered with
   `scan_status='pending'` and a sha256 checksum
3. Server calls `consume_scan_quota(org)` with the service role — quota is
   enforced **before** expensive work; over-quota submissions are rejected
4. `analysis_runs` insert with `status='queued'` and the tier at run time

The worker should then (all via service role, **always setting `org_id`**):

- claim queued runs, ClamAV-scan assets (`scan_status` → `clean`/`infected`)
- walk the layers, updating `analysis_runs.status` through
  `running_cv → running_nlp → running_llm → running_rules → reconciling →
  complete | failed` (the UI's pipeline visual maps these exactly)
- persist each layer's payload to `layer_outputs` (rendered in the
  Provenance panel)
- insert `findings` rows (`framework`, `rule_ref`, `severity`, `verdict`,
  `confidence`, `location.bbox` in 0–1 coords for overlays, `message`,
  `remediation`) — they stream into the open run viewer live
- stamp provenance on the run: `model_id`, `prompt_version`,
  `rulepack_version`, `rag_corpus_hash`, tokens, `cost_cents`
- write `usage_events` rows (`token_spend` per model call)

### Step 6 — Stripe (Phase 6)

1. Create a Product+Price per paid tier; put the price IDs in
   `STRIPE_PRICE_HOBBY|PRO|DESIGN|ENTERPRISE`, plus `STRIPE_SECRET_KEY`.
2. Point a webhook at `POST /api/billing/webhook` subscribed to
   `customer.subscription.created`, `...updated`, `...deleted`; set
   `STRIPE_WEBHOOK_SECRET`. Local testing:
   `stripe listen --forward-to localhost:3000/api/billing/webhook`.
3. Flow: Billing page → `/api/billing/checkout?tier=pro` (Checkout session
   carries `org_id` in subscription metadata) → webhook verifies the
   signature and upserts `subscriptions` with the service role → entitlements
   resolve from the DB on the next request. **The client never sets its own
   tier.** The Billing Portal (`/api/billing/portal`) handles self-serve
   changes and cancellation.

---

## 3. Project structure

```
frontend/
├── db/0007_app_rpc_wrappers.sql   # one-time SQL to expose app.* RPCs
├── src/
│   ├── proxy.ts                   # session refresh + route protection (Next 16 middleware)
│   ├── app/
│   │   ├── page.tsx               # marketing + pricing
│   │   ├── (auth)/…               # login, signup, verify, forgot/reset
│   │   ├── auth/callback/         # GoTrue redirect handler
│   │   ├── onboarding/            # create org
│   │   ├── (app)/…                # dashboard, submissions, runs, reports, billing, settings
│   │   ├── api/billing/…          # checkout, portal, webhook
│   │   ├── api/runs/[id]/export/  # JSON / CSV report export
│   │   └── actions.ts             # server actions (all auth+role checked)
│   ├── lib/
│   │   ├── supabase/              # browser / server (RLS) / admin (service-role) clients
│   │   ├── data.ts                # server data layer (branches to fixtures in demo mode)
│   │   ├── entitlements.ts        # mirror of plan_entitlements seed + pricing display
│   │   ├── stripe.ts              # SDK-free Stripe REST + signature helpers
│   │   └── demo/fixtures.ts       # demo dataset (mirrors real engine output shapes)
│   └── components/                # ui primitives + pipeline, badges, shell, overlays
└── .env.example
```

## 4. Security posture (what's enforced where)

- **Session**: validated in `proxy.ts` *and* re-checked in every server
  component/action — client state is never trusted for gating.
- **Tenant isolation**: all user-JWT queries ride on RLS; the org id comes
  from the verified session (cookie is validated against memberships), never
  from request params. Service-role paths set `org_id` explicitly.
- **Roles**: viewer < reviewer < admin < owner, checked in actions *and* by
  RLS policies (defence in depth).
- **Entitlements**: resolved from `subscriptions` + `plan_entitlements` on the
  server per request; quota consumed atomically before enqueueing.
- **Files**: browser-direct upload to a private bucket under org-scoped
  policies; previews via 10-minute signed URLs; checksums recorded; the
  malware-scan verdict is surfaced in the UI.
- **Stripe webhook**: HMAC signature verified (timing-safe compare, 5-minute
  replay window) before any DB write.
- **API keys**: generated server-side, stored as sha256 hash only, plaintext
  shown exactly once, revocable.

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| "create_org RPC is not exposed" on onboarding | Apply `db/0007_app_rpc_wrappers.sql` (Step 2) |
| Signup emails never arrive | Configure real SMTP on the auth container (`../supabase.md` §5) |
| Run stays `queued` forever | No worker is consuming `analysis_runs` — see Step 5 |
| Run viewer doesn't live-update | Check migration 0005 realtime publication and that Kong `:8000` websockets are reachable |
| PostgREST 404 on a new table/function | `docker compose restart supabase-rest` or `notify pgrst, 'reload schema';` |
| Member invites fail | `SUPABASE_SERVICE_ROLE_KEY` missing on the app server |
| Everything shows demo data | Supabase env vars absent or `NEXT_PUBLIC_DEMO_MODE=true` |

---

*AdCoherent assists compliance review; it is decision support, not legal
advice — keep a human accountable for final approval (playbook §16).*
