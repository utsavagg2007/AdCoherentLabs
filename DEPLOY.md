# Deploying AdCoherent

Decisions this runbook assumes (taken 2026-08-23, superseding the 2026-08-03
Firebase plan):

- **Supabase is the data plane.** Postgres, pgvector, Storage, Auth.
- **Supabase Auth is the identity provider.** No second one is being adopted.
- **There is no Firebase and no Google Cloud in this stack.** The hosting layer
  is a single Linux VM running the same `docker compose` that runs locally.

The Firebase Hosting + Cloud Run path was removed rather than kept alongside.
Two deploy targets meant two sets of environment assumptions, and the Cloud Run
one could never run ClamAV honestly (see below).

---

## What runs where

| Piece of the app | Runs on | Notes |
|---|---|---|
| Next.js frontend | the VM, container | `frontend/Dockerfile` |
| FastAPI API | the VM, container | `backend/Dockerfile --target runtime` |
| Queue worker | the VM, container | polls the queue; not request-driven |
| Scheduler | the VM, container | periodic jobs |
| Redis | the VM, container | `redis:7-alpine`, password from `.env` |
| ClamAV | the VM, container | real volume, fails **closed** |
| TLS / CDN / routing | Caddy on the VM | `deploy/Caddyfile` |
| Postgres + pgvector | **Supabase Cloud** | unchanged |
| Auth | **Supabase Auth** | unchanged |
| File storage | **Supabase Storage** | unchanged |

Two files describe the deployment:

- `docker-compose.prod.yml` — an overlay on the existing compose files. It does
  three things: builds the `runtime` backend target instead of `dev`, drops the
  `..:/repo:ro` bind mount, and adds Caddy.
- `deploy/Caddyfile` — the routing that `firebase.json` used to hold.

The overlay deliberately does not restate the services. They still come from
`docker-compose.yml` and `backend/docker-compose.backend.yml`, so the local and
production definitions cannot drift.

---

## Why one box rather than a managed platform

Worth reading before provisioning anything, because three components of this
application are handled badly by a serverless runtime:

**ClamAV.** It wants ~2 GB of RAM and a writable, persistent virus database that
takes minutes to populate on first start. On a scale-to-zero platform the honest
options were to pay for an always-on service or to set `CLAMAV_REQUIRED=false` —
which is a fail-**open** upload scanner, i.e. no scanner. On a VM it is a
container with a volume, and `CLAMAV_REQUIRED=true` stays true.

**The worker.** It polls the job queue; it is not request-driven. Platforms that
bill per request throttle CPU outside a request, which is exactly when this
process does its work.

**PaddleOCR models.** Roughly 200 MB, downloaded on first use into
`/root/.paddlex`. The `paddlex-models` volume warms them once. Without a
persistent volume, every container replacement re-downloads them mid-job.

The trade is real: you give up scale-to-zero and managed rollouts, and the box
is a single point of failure. At pre-launch volume, one predictable bill in the
$30–50/month range beats $100+ for a platform that still cannot run the virus
scanner.

---

## Why one origin

`deploy/Caddyfile` routes `/v1/*` and the other API paths to the API, and
everything else to Next.js, both under `https://$SITE_DOMAIN`. The browser never
makes a cross-origin request, so CORS stops being a deployment variable and
session cookies stay first-party.

One path is easy to miss when writing that routing by hand: **`/webhooks/stripe`
is top-level, not under `/v1`** — `backend/app/routes/billing.py` declares its
router with no prefix. Send it to Next.js by accident and Stripe's POSTs get a
404, Stripe retries for three days, and every checkout silently fails to credit
the account. The `@api` matcher lists it explicitly.

`/metrics` is deliberately **not** proxied. It stays reachable on the VM's
loopback for a local scraper; publishing it requires setting
`METRICS_BASIC_AUTH` first.

---

## 1. Provision the box

4 vCPU / 16 GB / 80 GB SSD is the working size — ClamAV alone reserves ~2 GB,
and the API and worker each import the embedding model. Hetzner CPX41, an 8 GB
droplet at minimum, or equivalent.

**Region.** The data plane is on AWS `us-west-1` (N. California) — confirm
against the host in your `SUPABASE_DB_URL`. The API makes dozens of round trips
per request, so co-locating compute with the database dominates latency far more
than distance to the user. Pick a west-coast US region and keep it.

Open 22, 80 and 443 only. Every application port in the compose files is bound
to `127.0.0.1`; Caddy is the sole process that listens publicly.

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
```

Then add yourself to the `docker` group, log out and back in, and check the
Compose version — the overlay needs v2.24+ for `!override`:

```bash
docker compose version
```

`!override` in `docker-compose.prod.yml` is load-bearing, not cosmetic. Compose
merges list entries by default, so on an older version the `..:/repo:ro` mount
survives the overlay, shadows the source baked into the runtime image, and every
container dies on `ModuleNotFoundError: engine`.

## 3. Code and environment

```bash
git clone <repo> /opt/adcoherent
```

Then `cp .env.example .env` and fill it in by hand. **Do not run
`scripts/sync_env.py` here** — it regenerates the env from a local self-hosted
Supabase stack, which does not exist on this box.

When pasting secrets on the server, use `printf %s`, never `echo`. `echo`
appends a newline, and a trailing `\n` inside a database URL or a JWT secret
produces authentication failures that look nothing like a formatting problem.

What must change from the template:

| Key | Production value |
|---|---|
| `APP_ENV` | `prod` — this is what makes `require_boot_secrets` strict |
| `SITE_DOMAIN` | the bare hostname, e.g. `app.example.com` (no scheme) |
| `NEXT_PUBLIC_API_URL` | `https://app.example.com` — same origin, **build arg** |
| `NEXT_PUBLIC_SITE_URL` | `https://app.example.com` — OAuth return origin |
| `CORS_ALLOWED_ORIGINS` | the real origin only, no localhost |
| `DOCS_ENABLED` | `false` unless `/docs` should be public |
| `CLAMAV_REQUIRED` | `true` — leave it |
| `RETENTION_DRY_RUN` | `true` until the retention job is verified once |
| `ADMIN_EMAILS` | real staff addresses |
| `REDIS_PASSWORD` / `REDIS_URL` | a fresh value, same password in both |
| `SENTRY_DSN`, `STRIPE_*` | real keys, or billing routes 503 cleanly |

`NEXT_PUBLIC_*` values are compiled into the JavaScript bundle by `next build`.
Changing one needs a frontend rebuild, not a restart.

Then, in the Supabase dashboard, add `https://app.example.com/auth/callback` to
**Authentication → URL Configuration → Redirect URLs**. Social sign-in fails
with a redirect error until you do.

## 4. Point DNS at the box

An `A` record for `SITE_DOMAIN` to the VM's IP, **before** the first start.
Caddy requests its certificate over an ACME HTTP-01 challenge on port 80; if the
name does not resolve yet it retries with a backoff, and the site serves nothing
in the meantime.

## 5. Start it

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The first run builds both images and downloads the ClamAV virus database. The
clamav healthcheck carries a 180 s `start_period` for that reason, and `api`
waits on `service_healthy` — a first boot taking several minutes is expected,
not a hang. Watch it with:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api
```

## 6. Verify

```bash
curl -fsS https://app.example.com/readyz
```

`/readyz` is the check that matters: it exercises the database, Redis and
ClamAV. `require_boot_secrets` will already have refused to boot if `.env` still
holds template placeholders, or points at `127.0.0.1` while claiming
`SUPABASE_MODE=cloud`.

Then exercise the real path once: sign in, submit an ad, and confirm a report
comes back and credits are debited.

---

## Updating

```bash
git -C /opt/adcoherent pull
```

followed by the same `up -d --build` as above. The worker has
`stop_grace_period: 120s`, so an in-flight job drains on SIGTERM rather than
being killed. A frontend-only change still needs `--build`, because the
`NEXT_PUBLIC_*` values are baked in at build time.

To roll back, check out the previous commit and run the same command. Images
rebuild from source, so there is no registry to keep in sync — the trade is that
a rollback costs a rebuild.

## Backups

Supabase Cloud takes automatic backups; confirm the retention period on your
plan and **rehearse a restore once** before launch. Nothing on the VM holds
durable state — the volumes are a Caddy certificate cache, the ClamAV virus
database and the PaddleOCR model cache, all of which regenerate.

---

## Known gaps

Open, not solved:

- **Single point of failure.** One box, no failover. Acceptable pre-launch; the
  first thing to revisit under real traffic.
- **PaddleOCR models are not baked into the image.** The volume warms them on
  first use, so a fresh box has one slow job.
- **Auth hardening.** `AUTH_AUDIT_AND_PLAN.md` Phase 3B — retiring the
  frontend's service-role writes — is still open and matters before a public
  launch.

---

## Before you call it live

- [ ] `APP_ENV=prod`
- [ ] `.env` contains no template placeholders (the app refuses to boot if so)
- [ ] `SITE_DOMAIN` resolves to the box and Caddy has a real certificate
- [ ] `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_SITE_URL` are the public origin
- [ ] `CORS_ALLOWED_ORIGINS` set to the real origin, no localhost
- [ ] Supabase Redirect URLs include `https://<domain>/auth/callback`
- [ ] `CLAMAV_REQUIRED=true` and `/readyz` reports the scanner up
- [ ] `RETENTION_DRY_RUN` flipped only after the retention job is verified
- [ ] `DOCS_ENABLED=false` if `/docs` should not be public
- [ ] Stripe keys set and the webhook endpoint pointed at
      `https://<domain>/webhooks/stripe`, or billing routes left to 503 cleanly
- [ ] `SENTRY_DSN` set
- [ ] `ADMIN_EMAILS` set to real staff addresses
- [ ] Supabase automatic backups confirmed, and a restore rehearsed
- [ ] Firewall allows 22/80/443 only
