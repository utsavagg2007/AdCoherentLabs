# Deploying AdCoherent on Firebase / Google Cloud

Decisions this runbook assumes (taken 2026-08-03):

- **Postgres stays.** The data plane remains Supabase Cloud.
- **Supabase Auth stays.** Firebase Auth is not being adopted.
- **Firebase is the hosting layer only.**

---

## What Firebase can and cannot do here

This is the part worth reading before anything else, because "move to Firebase"
means different things depending on which Firebase product you mean.

| Piece of the app | Runs on | Why |
|---|---|---|
| Next.js frontend | Cloud Run, fronted by Firebase Hosting | Container from `frontend/Dockerfile` |
| FastAPI API | Cloud Run | Firebase Hosting cannot execute Python |
| Queue worker | Cloud Run, always-on | Polls a queue; not request-driven |
| Scheduler | Cloud Run or Cloud Scheduler | Periodic jobs |
| Redis | Upstash or Memorystore | Firebase has no Redis |
| ClamAV | see below — this one has no clean answer | Needs ~2 GB RAM and a writable virus DB |
| Postgres + pgvector | **Supabase Cloud (unchanged)** | Firebase has no Postgres |
| File storage | **Supabase Storage (unchanged)** | Already working |

**Firebase Hosting is a CDN and a reverse proxy, not a container runtime.** It
serves static files and rewrites paths to Cloud Run. Every server process in
this application runs on Cloud Run; Firebase gives you the domain, the TLS
certificate, the CDN, and a single origin.

Firestore is not used and should not be. The data plane is 2,054 lines of SQL —
row-level security, PL/pgSQL credit functions, an append-only hash-chained audit
ledger and 11,061 pgvector chunks. Firestore has none of those primitives, so
moving would be a full rewrite that also gives up the credit-race and
append-only guarantees the schema currently enforces in the database itself.

### Why one origin

`firebase.json` routes `/v1/**` to the API and everything else to the frontend.
Both then sit on `https://<project>.web.app`, which means the browser never
makes a cross-origin request. CORS stops being a deployment variable, and
session cookies stay first-party.

---

## One-time project setup

```bash
gcloud auth login
gcloud config set project <your-project-id>
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

**Region.** Supabase is on AWS `us-west-1` (N. California). Co-locate the
compute with the database — the API makes dozens of round trips per request, so
this dominates latency far more than distance to the user. `us-west1` (Oregon,
~20 ms) is the cost-effective default; `us-west2` (Los Angeles, ~10 ms) is
closer but pricier. Pick one and keep it: changing region later means new
service URLs in `firebase.json`.

```bash
export GCP_REGION=us-west1
gcloud artifacts repositories create adcoherent \
  --repository-format=docker --location=$GCP_REGION
gcloud auth configure-docker $GCP_REGION-docker.pkg.dev
```

### Secrets

Never as `--set-env-vars` — those are readable by anyone with viewer access and
show up in `gcloud run services describe`.

```bash
printf %s 'postgresql://postgres.<ref>:<pw>@aws-0-us-west-1.pooler.supabase.com:5432/postgres?sslmode=require' \
  | gcloud secrets create SUPABASE_DB_URL --data-file=-
```

`printf %s`, not `echo`. `echo` appends a newline, and a trailing `\n` inside a
database URL or a JWT secret produces authentication failures that look nothing
like their cause.

Repeat for: `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_JWT_ISSUER`,
`SUPABASE_SERVICE_ROLE_KEY`, `REDIS_URL`, `OPENROUTER_API_KEY`,
`ANTHROPIC_API_KEY`.

Grant the runtime service account access:

```bash
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
for s in SUPABASE_DB_URL SUPABASE_URL SUPABASE_JWT_SECRET SUPABASE_JWT_ISSUER \
         SUPABASE_SERVICE_ROLE_KEY REDIS_URL OPENROUTER_API_KEY ANTHROPIC_API_KEY; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
done
```

---

## Deploy

```bash
bash scripts/deploy-cloudrun.sh api
bash scripts/deploy-cloudrun.sh worker

export NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
export NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>
export NEXT_PUBLIC_API_URL=https://<project>.web.app   # same origin, via Hosting
bash scripts/deploy-cloudrun.sh frontend
```

Then wire up Hosting:

1. In `firebase.json`, replace `__CLOUD_RUN_REGION__` with your region (4 spots).
2. In `.firebaserc`, replace `__FIREBASE_PROJECT_ID__` with your project id.

```bash
npm install -g firebase-tools
firebase login
firebase deploy --only hosting
```

**Chicken-and-egg:** the frontend bakes `NEXT_PUBLIC_API_URL` in at build time,
but you do not know the Hosting URL until the project exists. It is
deterministic — `https://<project-id>.web.app` — so you can set it up front. If
you get it wrong, rebuild and redeploy the frontend; restarting will not help.

Finally, add the public origin to `CORS_ALLOWED_ORIGINS`. Same-origin routing
means the browser should not need it, but any direct-to-Cloud-Run call will.

---

## The three pieces that do not fit cleanly

Being straight about these matters more than a tidy diagram.

### ClamAV — no good serverless answer

It needs ~2 GB of RAM and a writable, persistent virus database refreshed by
`freshclam`. Cloud Run gives ephemeral instances and no persistent volume.

- `CLAMAV_REQUIRED=false` — what `deploy-cloudrun.sh` currently sets. Uploads
  then fail **open**: unscanned files are accepted. Fine for a staging
  environment, **not acceptable for production** in a product that accepts
  customer file uploads.
- ClamAV as its own always-on Cloud Run service, 4 GB, `--min-instances=1`,
  with the API pointed at it via `CLAMAV_HOST`. Works, roughly $50/month.
- A small VM running clamd. Cheapest, needs patching.
- A scanning API (VirusTotal, Cloudmersive) instead. Changes
  `backend/app/services/uploads.py`.

**This is an open decision, not a solved problem. Do not launch on
`CLAMAV_REQUIRED=false`.**

### Redis

Memorystore has no free tier and starts around $35/month with a VPC connector.
**Upstash** is serverless, has a usable free tier, speaks TLS over the public
internet and needs no VPC — for this workload (rate limits and a 60-second
authn cache) it is the pragmatic choice. Put its URL in the `REDIS_URL` secret.

Redis being down is survivable by design: `RATE_LIMIT_FAIL_MODE=degraded` keeps
the API serving.

### The worker

It polls the job queue, so it is not request-driven. Cloud Run throttles CPU to
near zero between requests, which stalls a poll loop indefinitely — hence
`--no-cpu-throttling` and `--min-instances=1` in the deploy script. You are then
paying for an always-on 2 vCPU / 4 GB instance whether or not work arrives.

Cold starts are also real: the image imports torch and PaddleOCR, so a start is
tens of seconds, and PaddleOCR re-downloads its models on every cold start
because the compose volume that cached them (`/root/.paddlex`) does not exist on
Cloud Run. Baking the models into the image would fix that and is worth doing
before launch.

---

## Honest alternative: one VM

Given the above, Cloud Run is not obviously the right target for this
application. A single VM — Compute Engine `e2-standard-4`, or the Hetzner box
the earlier migration notes assumed — running the `docker-compose.yml` that
already works locally gets you:

- ClamAV with a real volume, no fail-open compromise
- Redis as a container, no third-party service
- The worker running normally, no CPU-throttling workaround
- PaddleOCR models cached once in a volume
- One predictable bill, roughly $30–50/month rather than $100+

You lose scale-to-zero and managed rollouts. At pre-launch volume that trade
looks favourable. Firebase Hosting can still front a VM — point the rewrites at
its IP through a load balancer, or run Caddy on the box for TLS.

The container work in this repo supports both paths: `backend/Dockerfile
--target runtime` and `frontend/Dockerfile` are plain images with no Cloud Run
dependency, and `docker-compose.yml` runs unchanged on a Linux host.

---

## Before you call it live

- [ ] `APP_ENV=prod` (this is what makes `require_boot_secrets` strict)
- [ ] `RETENTION_DRY_RUN` flipped only after the retention job is verified
- [ ] ClamAV resolved — **not** left fail-open
- [ ] `CORS_ALLOWED_ORIGINS` set to the real origin, no localhost
- [ ] `DOCS_ENABLED=false` if `/docs` should not be public
- [ ] Stripe keys set, or billing routes left to 503 cleanly
- [ ] `SENTRY_DSN` set
- [ ] Supabase automatic backups confirmed, and a restore rehearsed
- [ ] PaddleOCR models baked into the image
- [ ] `ADMIN_EMAILS` set to real staff addresses

Auth hardening is tracked separately in `AUTH_AUDIT_AND_PLAN.md` — Phase 3B
(retiring the frontend's service-role writes) is still open and matters before
a public launch.
