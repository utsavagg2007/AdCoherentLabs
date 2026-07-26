# Migration: self-hosted Supabase → Supabase Cloud + Clerk

Runbook for moving the AdCoherent data plane off the local Docker stack
(`C:\Users\HP\supabase-project`) onto a managed Supabase Cloud project, and
replacing GoTrue with Clerk as the identity provider.

**Read Part 0 first.** It changes how much work the rest of this is.

---

## Part 0 — What actually has to move

Row counts taken from the live local stack:

| Object | Rows | Migrate? |
|---|---:|---|
| `public.rag_chunks` (+ 5 sibling `rag_*` tables) | **11,061** | **YES — this is the only irreplaceable data** |
| `auth.users` | 5 | **NO** — all test fixtures, and Clerk replaces this table entirely |
| `public.orgs` / `memberships` | 5 / 5 | **NO** — test fixtures tied to those users |
| `public.analysis_runs` | 53 | **NO** — test runs, incl. 50 from the old credit-race test |
| `storage.objects` | 24 | **NO** — test uploads |
| `plan_pricing` / `pack_pricing` / `plan_entitlements` | seed | **RE-SEED** from migrations, don't dump |

**Consequence:** there is no user base to migrate. That removes the hardest part
of a Clerk cutover (dual-auth period, password migration, identity backfill).
The cloud project starts with an empty identity table and Clerk owns it from
request one.

Total real payload: **~64 MB** into a 500 MB free tier.

---

## Part 1 — Create and prepare the Supabase Cloud project

### 1.1 Create the project

Dashboard → New project.

- **Region: `us-east-1` (N. Virginia).** Decided — see below. Not changeable
  later without a full re-migration (new project, new URLs, Clerk + frontend
  env updates).

  The rule is *co-locate the VPS with the DB*, not "closest to users." Only 3
  frontend calls touch Supabase directly; the backend and worker hit it dozens
  of times per request. Hetzner's **Ashburn, VA** location sits in the same
  data-center corridor as AWS `us-east-1` — low-single-digit-ms DB latency.

  East over west: your corpus covers East-Coast-weighted financial-services
  regulation, and Virginia→Frankfurt (~85–95ms) is far better than
  Oregon→Frankfurt (~150ms) for the Europe roadmap.

  **Do not hedge the region for EU/AU.** All 11,061 `rag_chunks` are `US*`
  jurisdictions — there is no GDPR/DSA/ACCC content, and retrieval filters on
  exact jurisdiction match (`engine/llm_layer.py:54`). Those markets are gated
  behind a corpus-ingestion project, not a hosting choice. When they arrive,
  add a **separate project per region** (`eu-central-1`, `ap-southeast-2`) plus
  an org→home-region router. Clerk is global, so identity does not shard.
- **DB password:** generate a strong one, store it in your password manager now.
  You will need it in three places (VPS `.env`, migration commands, local dev).

### 1.2 Enable pgvector

Dashboard → Database → Extensions → enable `vector`.

Supabase installs it into the `extensions` schema, not `public`. Your
`rag-engine/adcoherent_rag/store/schema.sql:9` does `create extension if not
exists vector;` — that will no-op harmlessly, but any session that resolves the
`vector` type needs `extensions` on its `search_path`.

Migrations `0008`/`0011` already declare `set search_path = public, extensions`
on their functions, so they're fine. What needs checking is whether an ordinary
session resolves **unqualified** `vector` — that's what
`rag-engine/.../store/schema.sql` and the engine's queries use.

Run this through the local container (it has psql 15 and outbound internet — no
Windows install needed), against the cloud pooler URL from §1.3:

```bash
docker exec -i supabase-db psql "$CLOUD_DB" -c "select '[1,2,3]'::vector;"
```

Run it here rather than in the Dashboard SQL Editor on purpose: the Editor uses
its own session settings, so a pass there does not prove your engine's psycopg
connection will resolve the type. Test through the same pooler and role the app
uses.

- Success → done.
- `ERROR: type "vector" does not exist` → apply the fix below.

Fix — run in the **Dashboard SQL Editor**:

```sql
alter role postgres set search_path to "$user", public, extensions;
```

Two reasons for this exact form:

- **`alter role`, not `alter database`.** On Cloud, `postgres` is not superuser
  and does not own the `postgres` database, so `alter database` can fail with
  *must be owner of database*. A role may always set its own defaults, and the
  engine connects as `postgres.<ref>` → the `postgres` role.
- **SQL Editor, not bash.** In a double-quoted `psql -c` argument the shell
  expands `"$user"` to an empty string, silently corrupting the search_path.

Applies to **new connections only** — reconnect before re-running the test.

### 1.3 Get the RIGHT connection string

This is the single most common way to break this migration.

Supabase gives you three connection strings. **Use the Session pooler.**

| String | Port | Use |
|---|---|---|
| Direct connection | 5432 | ❌ IPv6-only unless you buy the IPv4 add-on. Your VPS likely has no IPv6. |
| **Session pooler** | **5432** | ✅ **Use this** for engine, worker, backend, migrations |
| Transaction pooler | 6543 | ❌ Breaks psycopg3 — see below |

**Why not the transaction pooler:** psycopg3 automatically promotes a statement
to a server-side prepared statement after 5 executions. PgBouncer in transaction
mode does not keep prepared statements across transactions, so your hot query
paths start failing intermittently once they warm up — a genuinely nasty
intermittent bug. `pgvector`'s `register_vector(conn)` also depends on stable
per-connection type registration.

If you ever *must* use the transaction pooler, you have to pass
`prepare_threshold=None` to every psycopg connection in `engine/saas.py`,
`rag-engine/.../store/db.py`, and `backend/app/db.py`. Not worth it. Use the
session pooler.

Append `?sslmode=require` to the URL.

### 1.4 Apply the schema

**Shell: Git Bash. Path: repo root.** `apply.sh` is a bash script and the
commands below are bash — PowerShell rejects `for f in ...; do` and mis-parses
`$CLOUD_DB`.

```bash
cd /c/Users/HP/Downloads/adcoherentlabs-project/adcoherentlabs-project
```

Use `apply.sh` with its `PSQL` override rather than a hand-rolled loop — it
orders the files, records each in `app.schema_migrations`, and therefore
**resumes cleanly** if one fails midway. A raw `psql -f` loop leaves that table
empty, so a later `apply.sh` run would try to re-apply all eleven.

```bash
export CLOUD_DB='postgresql://postgres.<ref>:<password>@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require'
```

Single-quote it so bash leaves `$` and `!` in the password alone. URL-encode the
password if it contains `@`, `/`, `#`, or `?`.

```bash
PSQL="docker exec -i supabase-db psql $CLOUD_DB" bash supabase/apply.sh
```

Routing through the `supabase-db` container avoids installing psql on Windows —
it ships psql 15 and has outbound internet.

Then the RAG schema (`apply.sh` only covers `migrations/`):

```bash
docker exec -i supabase-db psql "$CLOUD_DB" -v ON_ERROR_STOP=1 -1 < rag-engine/adcoherent_rag/store/schema.sql
```

Verify — expect **11** and the six `rag_*` tables:

```bash
docker exec -i supabase-db psql "$CLOUD_DB" -c "select count(*) from app.schema_migrations;" -c "\dt public.rag_*"
```

I grepped all 2,054 lines of migration for superuser-only DDL — there is none.
One `create schema app`, no `CREATE ROLE`, no `ALTER SYSTEM`. These replay clean
on managed Postgres.

**Expected non-fatal noise:** `0005` does `alter publication supabase_realtime
add table ...`. On Cloud the `postgres` role owns that publication so it should
succeed; if it errors, it's safe to skip — realtime is not on any critical path
(the frontend polls `/v1/runs/{id}/events`).

### 1.5 Move the RAG corpus

**Git Bash, repo root** — both the `>` and `<` below touch host files.

Do **not** use PowerShell for the dump. Redirecting a native command's output
with `>` in PowerShell 5.1 routes bytes through the string pipeline: console
encoding conversion, a **UTF-8 BOM**, and possible line-ending rewrites. On a
~150 MB dump that corrupts the file — the BOM alone makes psql fail on the
first statement, and the corpus is full of non-ASCII (`§`, curly quotes, em
dashes from FTC/CFPB source text). Git Bash `>` is a byte-level redirect.

Dump in dependency order:

```bash
docker exec supabase-db pg_dump -h 127.0.0.1 -U postgres -d postgres --data-only --no-owner --no-privileges -t public.rag_sources -t public.rag_regulation_versions -t public.rag_chunks -t public.rag_raw_snapshots -t public.rag_ingest_runs -t public.rag_ingest_events > rag_corpus.sql
```

Expect **~69 MB**. Confirm it wasn't truncated — the last line must read
`-- PostgreSQL database dump complete`:

```bash
tail -3 rag_corpus.sql
```

**Expected warning, safe to ignore:** pg_dump reports *circular foreign-key
constraints on rag_regulation_versions*. That's the self-reference
`superseded_by uuid references rag_regulation_versions(id)`. pg_dump warns from
the schema, not the data — and all 762 rows have `superseded_by` NULL, so the
constraint is never checked on load.

> This stops being cosmetic once you ingest regulation *updates* and
> `superseded_by` gets populated. The fix then is drop constraint → load →
> re-add. **Not** `--disable-triggers`: that needs superuser, and Cloud's
> `postgres` role isn't one.

Load it as one transaction so a mid-way failure rolls back cleanly:

```bash
docker exec -i supabase-db psql "$CLOUD_DB" -v ON_ERROR_STOP=1 -1 < rag_corpus.sql
```

Verify:

```bash
docker exec -i supabase-db psql "$CLOUD_DB" -c "select count(*) from public.rag_chunks;" -c "select count(*) from public.rag_chunks where embedding is null;"
```

Must be **11061** and **0**. A non-zero null count means the vector type didn't
resolve — go back to 1.2.

Now **create** the ANN index. It does not exist yet: `schema.sql:6` notes that
the embedding index is created by `db.init_db()`, not by the schema file — so
after §1.4 the cloud DB has the gin/btree indexes but no vector index, and
retrieval would fall back to a sequential scan. The live local index is HNSW:

```bash
docker exec -i supabase-db psql "$CLOUD_DB" -c "create index if not exists rag_chunks_embedding_idx on public.rag_chunks using hnsw (embedding vector_cosine_ops);" -c "analyze public.rag_chunks;"
```

Building after the load is also better than before it — one bulk build yields a
better-connected graph than 11,061 incremental inserts. Takes a minute or two on
free-tier compute; if it fails on memory, prepend
`set maintenance_work_mem = '128MB';` in the same session.

Confirm all six indexes are present:

```bash
docker exec -i supabase-db psql "$CLOUD_DB" -c "select indexname from pg_indexes where tablename='rag_chunks';"
```

Expect `rag_chunks_embedding_idx` (hnsw), `_pkey`, `_version_id_chunk_index_key`,
`_tsv_idx`, `_frameworks_idx`, `_version_idx`.

### 1.6 Re-seed pricing and entitlements

This is a **verify** step, not a re-seed. The migration files already carry the
current values (checked): `0004` seeds `qwen/qwen3.7-plus` @ 4000 and
`qwen/qwen3.7-max` @ 6000 matching `review/tiers.py`; `0008` sets
`credits_per_month`; `0011` seeds `plan_pricing`, `pack_pricing`,
`credit_costs`, `allowed_kinds`, `max_video_seconds`. The past drift (stale
`qwen` values after the device move) was written back into `0004`.

Prove it — diff all five pricing tables, local vs cloud:

```bash
for t in plan_entitlements plan_pricing pack_pricing credit_costs token_rates; do Q="select (to_jsonb(x.*) - 'updated_at' - 'created_at')::text from public.$t x order by 1"; docker exec -i supabase-db psql -h 127.0.0.1 -U postgres -d postgres -At -c "$Q" > "/tmp/$t.local"; docker exec -i supabase-db psql "$CLOUD_DB" -At -c "$Q" > "/tmp/$t.cloud"; if diff -q "/tmp/$t.local" "/tmp/$t.cloud" >/dev/null; then echo "OK    $t"; else echo "DRIFT $t"; diff "/tmp/$t.local" "/tmp/$t.cloud"; fi; done
```

Stripping `updated_at`/`created_at` matters — they differ per environment and
would report false drift on every row. Five `OK` lines = done.

Empty `plan_pricing` / `pack_pricing` means an empty pricing page: the frontend
renders prices exclusively from `GET /v1/plans`.

While you're here: **fix the framework scoping.** Free is `["FTC"]` and hobby is
`["FTC","GDPR"]`. GDPR is EU privacy on a US fintech product — hobby buyers are
paying for a framework that can't fire. Decide the real hobby framework set now,
before anyone pays.

### 1.7 Checkpoint — verify BEFORE touching auth

No `.env` edit needed. `engine/saas.py::_default_db_url()` reads
`SUPABASE_DB_URL` first, and `engine/_paths.py` loads root `.env` with
`override=False` — so an exported shell variable wins.

```bash
source CV-RULE_ENG-NLP/.venv/Scripts/activate
```

```bash
SUPABASE_DB_URL="$CLOUD_DB" python -m engine.cli saas-selftest
```

Inline keeps it scoped to the one command, so your shell can't be left pointed
at cloud by accident. The startup line prints the connected host — confirm it
reads `pooler.supabase.com`, not `127.0.0.1`.

All 32 checks must pass, including the RLS isolation red-line. This exercises
psycopg → pooler → RLS → credits → audit chain without involving GoTrue or
Clerk at all.

**One expected failure mode:** `saas_selftest.py:85` inserts a test user
straight into `auth.users`. On Cloud that schema is owned by
`supabase_auth_admin` and `postgres` may lack INSERT — a permission error, not
a logic error. That is exactly the code path Part 2 deletes (`0012` moves
identity to `public.app_users`).

- Fails **only** at user creation → note it, continue to Part 2, re-run this
  gate after `0012`.
- Fails **anywhere else** → a real migration problem. Stop and fix before Clerk.

**Do not proceed to Part 2 until this is green.** It isolates "did the database
move correctly" from "did the identity model change correctly." If you change
both at once and something breaks, you won't know which one did it.

---

## Part 2 — Clerk cutover

### 2.1 The design decision

Your schema has `user_id uuid not null references auth.users(id)` in four
tables, and RLS derives everything from `auth.uid()`, which casts the JWT `sub`
claim to `uuid`.

Clerk user IDs look like `user_2abc123XYZ` — **not** UUIDs. So `auth.uid()`
doesn't return null with a Clerk token, it *throws a cast error*.

There are two ways out:

**(A) Change every `user_id` to `text`.** Touches 4 tables, 4 FKs, the audit
hash chain (`audit_logs.actor`), and every index. Invasive, and the audit chain
is append-only with a trigger guarding it.

**(B) Keep `uuid` internally, map Clerk IDs at the edge.** ← **Do this.**

Add `public.app_users(id uuid primary key, external_id text unique)` and a
resolver function. Then:

- **Zero column type changes**
- **Zero index changes**
- **Audit hash chain untouched**
- FKs simply repoint from `auth.users` to `app_users`
- If you ever leave Clerk, only `external_id` and one function change

And here's why (B) is genuinely cheap in your codebase: I traced every
`auth.uid()` call site. Because almost all your policies delegate to three
helper functions, there are only **9 places total**:

| Site | File |
|---|---|
| `app.user_org_ids()` | `0002:16` |
| `app.is_org_member()` | `0002:21` |
| `app.has_org_role()` | `0002:26` |
| `app.create_org()` | `0008:492` (supersedes `0002:38`) |
| `memberships_delete` policy | `0002:103` |
| `submissions_reviewer_insert` policy | `0002:119` |
| storage `assets org reviewer insert` | `0005:37` |
| storage `assets org admin delete` | `0005:48` |
| org-member guards ×3 | `0008:141`, `0008:447`, `0011:135` |

Every other policy in the system is untouched.

### 2.2 Migration `0012_clerk_identity.sql`

```sql
-- 0012_clerk_identity.sql — Clerk replaces GoTrue as the identity provider.
-- Internal user identity stays uuid; Clerk's string id is mapped at the edge.

begin;

-- ---------------------------------------------------------------------------
-- The identity table. Synced from Clerk webhooks (user.created/updated/deleted).

create table if not exists public.app_users (
  id             uuid primary key default gen_random_uuid(),
  external_id    text unique not null,          -- Clerk: "user_2abc..."
  email          text not null,
  email_verified boolean not null default false,
  mfa_enabled    boolean not null default false,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists app_users_email_idx on public.app_users (lower(email));

alter table public.app_users enable row level security;
-- No policies: readable only via service_role / the backend's direct pool.

-- ---------------------------------------------------------------------------
-- Repoint the four FKs off auth.users.
-- Safe: there are no production rows (see Part 0).

alter table public.memberships drop constraint if exists memberships_user_id_fkey;
alter table public.memberships add constraint memberships_user_id_fkey
  foreign key (user_id) references public.app_users(id) on delete cascade;

alter table public.submissions drop constraint if exists submissions_created_by_fkey;
alter table public.submissions add constraint submissions_created_by_fkey
  foreign key (created_by) references public.app_users(id);

alter table public.findings drop constraint if exists findings_reviewed_by_fkey;
alter table public.findings add constraint findings_reviewed_by_fkey
  foreign key (reviewed_by) references public.app_users(id);

alter table public.api_keys drop constraint if exists api_keys_created_by_fkey;
alter table public.api_keys add constraint api_keys_created_by_fkey
  foreign key (created_by) references public.app_users(id);

-- ---------------------------------------------------------------------------
-- THE resolver. Everything that used auth.uid() now calls this.
-- auth.jwt()->>'sub' is text and is NOT cast to uuid, so Clerk ids are safe.

create or replace function app.current_user_id() returns uuid
language sql stable security definer set search_path = public, extensions as
$$ select id from public.app_users
   where external_id = nullif(auth.jwt() ->> 'sub', '') $$;

revoke all on function app.current_user_id() from public, anon;
grant execute on function app.current_user_id() to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Rewrite the three helpers (one line each).

create or replace function app.user_org_ids() returns setof uuid
language sql stable security definer set search_path = public, extensions as
$$ select org_id from public.memberships where user_id = app.current_user_id() $$;

create or replace function app.is_org_member(target_org uuid) returns boolean
language sql stable security definer set search_path = public, extensions as
$$ select exists (select 1 from public.memberships
                  where org_id = target_org and user_id = app.current_user_id()) $$;

create or replace function app.has_org_role(target_org uuid, roles text[]) returns boolean
language sql stable security definer set search_path = public, extensions as
$$ select exists (select 1 from public.memberships
                  where org_id = target_org and user_id = app.current_user_id()
                    and role = any(roles)) $$;

-- ---------------------------------------------------------------------------
-- app.create_org — forward-only replacement of the 0008 definition.

create or replace function app.create_org(org_name text) returns uuid
language plpgsql security definer set search_path = public, extensions as $$
declare new_org uuid; caller uuid;
begin
  caller := app.current_user_id();
  if caller is null then
    raise exception 'not authenticated';
  end if;
  insert into public.orgs (name) values (org_name) returning id into new_org;
  insert into public.memberships (org_id, user_id, role)
  values (new_org, caller, 'owner');
  insert into public.subscriptions (org_id, tier, status,
                                    current_period_start, current_period_end)
  values (new_org, 'free', 'active', date_trunc('month', now()),
          date_trunc('month', now()) + interval '1 month');
  perform app.ensure_cycle_grant(new_org);
  return new_org;
end $$;

revoke all on function app.create_org(text) from public, anon;
grant execute on function app.create_org(text) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- The two direct-auth.uid() policies.

drop policy if exists memberships_delete on public.memberships;
create policy memberships_delete on public.memberships for delete to authenticated
  using (user_id = app.current_user_id()
         or app.has_org_role(org_id, array['owner','admin']));

drop policy if exists submissions_reviewer_insert on public.submissions;
create policy submissions_reviewer_insert on public.submissions for insert to authenticated
  with check (created_by = app.current_user_id()
              and app.has_org_role(org_id, array['owner','admin','reviewer']));

-- ---------------------------------------------------------------------------
-- Storage policies (0005).

drop policy if exists "assets org reviewer insert" on storage.objects;
create policy "assets org reviewer insert" on storage.objects for insert to authenticated
  with check (
    bucket_id = 'assets'
    and exists (select 1 from public.memberships m
                where m.user_id = app.current_user_id()
                  and m.role in ('owner','admin','reviewer')
                  and m.org_id::text = (storage.foldername(name))[1])
  );

drop policy if exists "assets org admin delete" on storage.objects;
create policy "assets org admin delete" on storage.objects for delete to authenticated
  using (
    bucket_id = 'assets'
    and exists (select 1 from public.memberships m
                where m.user_id = app.current_user_id()
                  and m.role in ('owner','admin')
                  and m.org_id::text = (storage.foldername(name))[1])
  );

commit;
```

**Also patch the three org-member guards** at `0008:141`, `0008:447`,
`0011:135`. They read `if auth.uid() is not null and not
app.is_org_member(target_org)`. Change `auth.uid()` → `app.current_user_id()`
in each. These are inside larger function bodies, so re-issue those
`create or replace function` statements with the one-token change rather than
hand-editing the live DB.

> ⚠️ `apply.sh` skips migrations by **filename**. If you edit `0012` after a
> first run, re-apply it by hand — the SQL above is idempotent.

### 2.3 Configure Clerk

**Dashboard → Sessions → Customize session token.** Supabase's RLS requires the
`role` claim:

```json
{
  "role": "authenticated",
  "email": "{{user.primary_email_address}}",
  "email_verified": "{{user.email_verified}}"
}
```

Without `role: "authenticated"`, PostgREST treats the token as `anon` and every
frontend read returns empty with no error.

**Dashboard → Configure → Sessions:** set token lifetime (60s default is fine —
the Clerk SDK refreshes transparently).

**SSO (your reason for Pro):** Dashboard → Enterprise Connections → add a SAML
connection (Okta / Entra ID / Google Workspace) → verify the customer's domain
→ map `email` and `name` attributes.

> Verify in your Clerk billing page whether SAML connections are included in
> Pro or need the separate Enhanced Authentication add-on — this has changed
> over time and it's a hard blocker if you assume wrong. Check before you promise
> SSO to a customer.

**Do NOT enable Clerk Organizations.** You already have `orgs`, `memberships`,
roles, credits, tiers, and RLS built on them. Two org systems means two sources
of truth for entitlements. Clerk provides *identity only*.

### 2.4 Register Clerk with Supabase

Dashboard → Authentication → **Third-Party Auth** → add Clerk, paste your Clerk
domain (`https://<slug>.clerk.accounts.dev` in dev, your custom domain in prod).

This is available on the free tier — it is not the paid SAML SSO feature. It
tells Supabase's PostgREST and Storage to accept Clerk-signed JWTs so
`auth.jwt()` is populated for your policies.

### 2.5 Backend changes

**`backend/app/auth/jwt.py`** — add RS256/JWKS verification alongside the
existing HS256 path (keep HS256 for now; it's what your API-key tests and dev
token-injection trick use).

```python
# Clerk signs RS256 and publishes JWKS at <domain>/.well-known/jwks.json.
# Cache the client — PyJWKClient caches keys and handles kid rotation.
_jwks: pyjwt.PyJWKClient | None = None

def verify_clerk_jwt(token: str, jwks_url: str, issuer: str) -> JwtClaims:
    global _jwks
    if _jwks is None:
        _jwks = pyjwt.PyJWKClient(jwks_url, cache_keys=True)
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = pyjwt.decode(
            token, key, algorithms=["RS256"], issuer=issuer,
            options={"require": ["exp", "sub"], "verify_aud": False},
        )
    except pyjwt.ExpiredSignatureError:
        raise ApiError(401, "unauthenticated", "Token has expired.")
    except pyjwt.PyJWTError:
        raise ApiError(401, "unauthenticated", "Invalid token.")
    return JwtClaims(claims)
```

`verify_aud=False` because Clerk session tokens carry `azp` (authorized party)
rather than `aud`. **Check `azp` against your frontend origins explicitly** —
otherwise a token minted for any other Clerk app on the same instance is
accepted.

**MFA / the `aal2` step-up.** `JwtClaims.aal` currently reads GoTrue's `aal`
claim. Clerk's equivalent is `fva` — a two-element array
`[minsSinceFirstFactor, minsSinceSecondFactor]`, where `-1` means "not used".
Map it:

```python
@property
def aal(self) -> str:
    fva = self.get("fva")
    if isinstance(fva, list) and len(fva) > 1 and fva[1] is not None and fva[1] >= 0:
        return "aal2"
    return "aal1"
```

This preserves the step-up enforcement on api-keys/members/billing/admin routes
that `deps.py:72` already implements — nothing above the claims layer changes.

**`backend/app/deps.py:107-127`** — `_user_context()` queries `auth.users` and
`auth.mfa_factors`. Both will be permanently empty. Rewrite against
`app_users`, keyed by Clerk's `external_id`:

```python
user = await db.fetch_one(
    "select id::text, email, email_verified as confirmed, mfa_enabled as mfa_verified "
    "from public.app_users where external_id = %s", (external_id,))
```

Note the returned `id` is now the **internal uuid** — that is what
`memberships.user_id` joins on, so the membership query below it works
unchanged. Cache key becomes `authn:{external_id}`.

`AuthContext` needs to carry both: `user_id` (internal uuid, for DB writes) and
a new `external_id` (Clerk id, for JWT-claim injection).

**`backend/app/routes/orgs.py:38`** — this injects `request.jwt.claims` so
`auth.uid()` resolves inside `app.create_org`. It now has to inject the
**Clerk** id, because `app.current_user_id()` looks up `external_id`:

```python
await conn.execute("select set_config('request.jwt.claims', %s, true)",
                   (json.dumps({"sub": ctx.external_id, "role": "authenticated"}),))
```

Getting this wrong is silent — `app.current_user_id()` returns null and
`create_org` raises `not authenticated`.

**`backend/app/routes/orgs.py:73,92`** — `join auth.users u on u.id = m.user_id`
and `select id from auth.users where lower(email) = ...` both become
`public.app_users`. The email lookup at :92 is member-invite-by-email; it now
only finds users who have signed into Clerk at least once. Decide whether to
return "user must sign up first" or create a Clerk invitation via their API.

**`engine/saas.py:250-264`** — same `auth.users` → `app_users` swap. The
`NotProvisionedError(f"no auth.users row for {user!r}")` message needs updating
too.

**`engine/saas_selftest.py:85,121`** — inserts/deletes test users in
`auth.users`. Point at `app_users`. This gets *simpler*: you can drop all the
GoTrue token-column workarounds (`confirmation_token=''` etc.) that were needed
to avoid the "Database error querying schema" 500.

**New — `POST /v1/webhooks/clerk`.** Clerk is the source of truth for identity;
`app_users` is a read replica of it. Subscribe to `user.created`,
`user.updated`, `user.deleted`.

- Verify the **Svix signature** (`svix-id`, `svix-timestamp`, `svix-signature`
  headers) against your webhook signing secret. An unverified webhook that
  upserts users is a full account-takeover primitive.
- `user.created` / `user.updated` → upsert on `external_id`, syncing `email`,
  `email_verified`, `mfa_enabled` (`two_factor_enabled` in the payload).
- `user.deleted` → your FK is `on delete cascade` from memberships. Prefer a
  soft delete plus a retention job over an immediate hard delete, so you don't
  cascade away audit history.
- Route it **outside** `auth_context` — it's signature-authenticated, not
  bearer-authenticated. Also exclude it from `rate_limited`.

**Race to handle:** a brand-new user can hit `POST /v1/orgs` before the webhook
lands. Make `_user_context` fall back to upserting `app_users` directly from
the verified JWT claims (`sub`, `email`, `email_verified`) when the row is
missing. The webhook then becomes the correction path rather than the critical
path.

### 2.6 Frontend changes

Only 7 Supabase call sites exist, so this is small.

```bash
npm i @clerk/nextjs
```

- Wrap the app in `<ClerkProvider>`; add Clerk's middleware. **Note:** Next 16
  uses `proxy.ts`, not `middleware.ts` — check Clerk's App Router docs match.
- `src/components/providers.tsx:127,133` — `supabase.auth.getSession()` and
  `onAuthStateChange` become `useAuth()` / `useSession()` from Clerk.
- `src/app/(auth)/reset-password/page.tsx` — **delete it.** Clerk owns password
  reset. Same for your sign-in/sign-up pages → `<SignIn />` / `<SignUp />`.
- `src/lib/supabase.ts` — the client must now send the Clerk token, or the two
  `.from("memberships")` reads and `signedAssetUrl()` return empty:

```typescript
createClient(url, anon, {
  accessToken: async () => (await window.Clerk?.session?.getToken()) ?? null,
});
```

  Drop `persistSession`, `autoRefreshToken`, `detectSessionInUrl`, `flowType`,
  and `storageKey` — Clerk owns the session now. `@supabase/supabase-js`
  ^2.110.7 supports `accessToken`.

> The `storageKey: "adcoherent-auth"` dev trick (injecting a hand-minted HS256
> JWT into localStorage to test with GoTrue down) **stops working**. Clerk's
> test-mode users or a long-lived Clerk token via their testing tokens API are
> the replacement. Set this up before you need it at 2am.

- `src/components/providers.tsx:186` and `src/app/onboarding/page.tsx:62` —
  the `.from("memberships")` RLS reads keep working once `accessToken` is
  wired, because `app.current_user_id()` resolves the Clerk `sub`. The existing
  `GET /v1/orgs/me` fallback covers you if not.
- Keep the org-discovery `isStale()` race guard. Clerk's loading state settles
  differently from Supabase's; if anything, that guard matters more now.

### 2.7 Retire GoTrue

Once Clerk works end to end:

- Dashboard → Authentication → Providers → disable email/password signup so
  nobody can create a GoTrue account that has no `app_users` row.
- Leave `SUPABASE_JWT_SECRET` in the backend config — API keys and internal
  token minting still use the HS256 path.
- Do **not** drop `auth.users`. Supabase Storage and PostgREST have internal
  references to the `auth` schema.

---

## Part 3 — Point the application at the cloud

### 3.1 Environment

**DONE — a `SUPABASE_MODE` switch is now wired through the stack.** Set
`SUPABASE_MODE=cloud` in the root `.env` and:

- `backend/docker-entrypoint.sh` stops rewriting the data-plane URLs to
  `supabase-db` / `supabase-kong`, but **still** rewrites `REDIS_URL` and
  `CLAMAV_HOST` (those sidecars stay on the compose network in every mode).
  It hard-fails if a data-plane URL still points at a local host.
- `backend/app/config.py::require_boot_secrets()` refuses to boot on leftover
  placeholders or any `127.0.0.1` / `localhost` / `supabase-db` in the URLs —
  a half-edited `.env` fails at boot, not at first request.
- `scripts/sync_env.py` refuses to run in cloud mode (it writes *self-hosted*
  credentials and would clobber the cloud values). `--force-local` overrides.
- `backend/docker-compose.backend.yml` no longer joins the external
  `supabase_default` network; both the service list and the declaration carry
  a comment on restoring it for local mode.

Backups of the working self-hosted files: `.env.local-stack.bak` and
`frontend/.env.local.local-stack.bak`. Switching back = restore those (or just
flip `SUPABASE_MODE=local`) and re-add the network in compose.

Root `.env` changes:

```
DATABASE_URL / _API / _WORKER / _MIGRATIONS  → the session-pooler URL
SUPABASE_URL          → https://<ref>.supabase.co
SUPABASE_SERVICE_KEY  → cloud service_role key
SUPABASE_JWT_SECRET   → keep (API-key/HS256 path)
CLERK_JWKS_URL        → https://<domain>/.well-known/jwks.json
CLERK_ISSUER          → https://<domain>
CLERK_WEBHOOK_SECRET  → from Clerk dashboard
CLERK_AUTHORIZED_PARTIES → your frontend origins (azp check)
```

`frontend/.env.local`:

```
NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY        → cloud values
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
CLERK_SECRET_KEY
NEXT_PUBLIC_API_BASE_URL                     → your backend origin
```

> `backend/docker-entrypoint.sh` **rebuilds** `SUPABASE_URL`, `DATABASE_URL`,
> `REDIS_URL`, and `CLAMAV_HOST` from `POSTGRES_PASSWORD` + service names when
> `APP_IN_CONTAINER=1`. That logic assumes a local Supabase on the shared Docker
> network and will happily overwrite your cloud URLs. **Gate every Supabase/DB
> rebuild behind a `SUPABASE_MODE=cloud` check** before you deploy. Remember the
> entrypoint is baked via `COPY`, not mounted — rebuild the image after editing
> it, and verify with `tr '\0' '\n' < /proc/1/environ`, not `docker exec env`.

### 3.2 Compose

Remove the `supabase_default` external network from
`backend/docker-compose.backend.yml` — there is no local Supabase to join.
`redis` and `clamav` stay local to the box.

### 3.3 Storage

`backend/app/services/storage.py` builds URLs as
`{supabase_url}/storage/v1/object/assets/{path}` — that works against Cloud
unchanged.

But the free tier gives **1 GB storage and 5 GB egress**, and your hobby tier
accepts 60-second videos. You will blow through that. Migrating those four
functions to Cloudflare R2 (10 GB free, **zero egress fees**) is roughly a
day's work and removes your most likely surprise bill. Note that
`signedAssetUrl()` in the frontend also depends on Supabase Storage signed URLs,
so an R2 move needs a backend-issued presigned-URL endpoint to replace it.

---

## Part 4 — Verification gates

Run in order. Do not skip ahead on a red gate.

| # | Gate | Passes when |
|---|---|---|
| 1 | `saas-selftest` against cloud DB (GoTrue still in place) | 32/32, RLS isolation green |
| 2 | `rag_chunks` count + null-embedding count | 11061 / 0 |
| 3 | A real retrieval query returns FTC chunks | non-empty, sane similarity scores |
| 4 | Migration `0012` applied; `saas-selftest` re-run | 32/32 with `app_users` |
| 5 | Backend pytest | 46/46 (expect edits in the auth/user-context tests) |
| 6 | Clerk sign-up → `app_users` row appears | webhook fired and verified |
| 7 | `POST /v1/orgs` for a brand-new Clerk user | 201, membership + free credits granted |
| 8 | Frontend `.from("memberships")` read | returns the row (proves Third-Party Auth + `role` claim) |
| 9 | Full E2E: upload → worker → CV/NLP → retrieval → LLM → rule engine → report | matches the 2026-07-22 local run |
| 10 | Credit + token settlement | `consume.run` then `consume.tokens` in the ledger |
| 11 | RLS cross-tenant probe: user A reads org B | **empty result** |

Gate 11 is the one that must never be skipped. You changed the function every
tenant-isolation policy depends on.

---

## Known gotchas, collected

1. **Transaction pooler breaks psycopg3.** Session pooler, port 5432. (§1.3)
2. **`auth.uid()` throws on Clerk ids** — it casts to uuid. Never call it after
   `0012`. (§2.1)
3. **Missing `role: "authenticated"`** in the Clerk token → all PostgREST reads
   silently return empty. (§2.3)
4. **`docker-entrypoint.sh` overwrites cloud URLs** when `APP_IN_CONTAINER=1`.
   (§3.1)
5. **`sync_env.py` probes the local DB** and will clobber cloud credentials.
   (§3.1)
6. **`apply.sh` skips by filename** — edits to an applied migration need a
   manual re-apply. (§2.2)
7. **The localStorage JWT-injection dev trick dies** with Clerk. (§2.6)
8. **Supabase free tier has no backups.** Cron a nightly `pg_dump` to R2 from
   the VPS and *restore it once* to prove it works. Your entire product is
   64 MB — there is no excuse for losing it.
9. **Free projects pause after ~7 days of inactivity.** Real traffic prevents
   this; during the quiet build phase, a cron ping does.
10. **Verify Clerk's SAML availability on your plan** before promising SSO. (§2.3)

---

## Sequencing

| Stage | Work | Gates |
|---|---|---|
| Part 1 | Cloud project, schema, RAG corpus, seeds | 1–3 |
| Part 2 | Migration `0012`, backend auth, Clerk webhook, frontend | 4–8 |
| Part 3 | Env, compose, storage decision | — |
| Part 4 | Full E2E + isolation | 9–11 |

**Do Part 1 and Part 2 on separate days with a green gate between them.** They
are independent failures, and combining them means you can't tell which one
broke.

Keep the local stack running and untouched until gate 11 is green. It is your
rollback.
