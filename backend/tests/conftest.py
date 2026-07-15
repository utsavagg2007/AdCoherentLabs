"""Shared fixtures: throwaway tenants against the LIVE local stack, minted
JWTs (stack secret), an ASGI test client with the DB pool opened.

Every suite needing the stack is guarded — unreachable DB skips, never fails.
Throwaway orgs/users are deleted afterwards; audit rows remain by design.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
for p in (str(_REPO), str(_BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

import httpx  # noqa: E402
import jwt as pyjwt  # noqa: E402
import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.config import settings  # noqa: E402

DB_URL = settings.supabase_db_url or settings.database_url_api


def _connect() -> psycopg.Connection:
    return psycopg.connect(DB_URL, row_factory=dict_row, autocommit=True)


@pytest.fixture(scope="session")
def stack():
    """Skip the whole suite when the local Supabase stack is down."""
    try:
        with psycopg.connect(DB_URL, connect_timeout=3):
            pass
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local Supabase stack unreachable: {exc}")
    return DB_URL


def mint_jwt(user_id: str, email: str, *, secret: str | None = None,
             aud: str = "authenticated", expired: bool = False,
             iss: str | None = None, aal: str = "aal1") -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "email": email, "aud": aud,
         "iss": iss if iss is not None else (settings.supabase_jwt_issuer
                                             or "http://localhost:8000/auth/v1"),
         "aal": aal, "amr": [{"method": "password", "timestamp": now}],
         "iat": now - 7200 if expired else now,
         "exp": now - 3600 if expired else now + 3600,
         "role": "authenticated"},
        secret or settings.supabase_jwt_secret, algorithm="HS256")


def _mk_user(cur, email: str, confirmed: bool = True) -> str:
    cur.execute(
        "insert into auth.users (instance_id, id, aud, role, email, "
        "  email_confirmed_at, created_at, updated_at) "
        "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
        "  'authenticated', 'authenticated', %s, "
        "  case when %s then now() end, now(), now()) returning id::text",
        (email, confirmed))
    return cur.fetchone()["id"]


@pytest.fixture()
def tenant(stack):
    """Throwaway org with the full role ladder + a second org for cross-tenant
    checks. Funded with 50 subscription credits (no cycle grant — tests own
    the balance)."""
    tag = uuid.uuid4().hex[:8]
    ids: dict = {"tag": tag, "users": {}}
    with _connect() as conn, conn.cursor() as cur:
        for role in ("owner", "admin", "reviewer", "viewer"):
            ids["users"][role] = _mk_user(cur, f"{role}-{tag}@bt.local")
        ids["users"]["unconfirmed"] = _mk_user(
            cur, f"unconfirmed-{tag}@bt.local", confirmed=False)
        ids["users"]["outsider"] = _mk_user(cur, f"outsider-{tag}@bt.local")

        cur.execute("insert into public.orgs (name) values (%s) returning id::text",
                    (f"bt-{tag}",))
        ids["org"] = cur.fetchone()["id"]
        cur.execute("insert into public.orgs (name) values (%s) returning id::text",
                    (f"bt-other-{tag}",))
        ids["other_org"] = cur.fetchone()["id"]

        for role in ("owner", "admin", "reviewer", "viewer"):
            cur.execute("insert into public.memberships (org_id, user_id, role) "
                        "values (%s, %s, %s)", (ids["org"], ids["users"][role], role))
        cur.execute("insert into public.memberships (org_id, user_id, role) "
                    "values (%s, %s, 'reviewer')",
                    (ids["org"], ids["users"]["unconfirmed"]))
        cur.execute("insert into public.memberships (org_id, user_id, role) "
                    "values (%s, %s, 'owner')",
                    (ids["other_org"], ids["users"]["outsider"]))
        for org in (ids["org"], ids["other_org"]):
            cur.execute(
                "insert into public.subscriptions (org_id, tier, status, "
                "  current_period_start, current_period_end) "
                "values (%s, 'free', 'active', date_trunc('month', now()), "
                "  date_trunc('month', now()) + interval '1 month')", (org,))
        cur.execute("select app.adjust_credits_manual(%s, 50, 'subscription', "
                    "%s, 'test funding')", (ids["org"], ids["users"]["owner"]))
    yield ids
    with _connect() as conn, conn.cursor() as cur:
        for org in (ids["org"], ids["other_org"]):
            cur.execute("delete from public.orgs where id = %s", (org,))
        for uid in ids["users"].values():
            cur.execute("delete from auth.users where id = %s", (uid,))


def set_tier(org_id: str, tier: str) -> None:
    with _connect() as conn:
        conn.execute("update public.subscriptions set tier = %s where org_id = %s",
                     (tier, org_id))


def q_one(sql: str, params=()) -> dict | None:
    with _connect() as conn:
        return conn.execute(sql, params).fetchone()


def q_all(sql: str, params=()) -> list[dict]:
    with _connect() as conn:
        return conn.execute(sql, params).fetchall()


@pytest.fixture()
async def client(stack):
    """httpx client over the ASGI app with the DB pool opened (the ASGI
    transport does not run lifespan)."""
    from app import db, redis_client
    from app.main import app

    await redis_client.close()   # drop any client bound to a previous test loop
    await db.open_pool()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as c:
        yield c
    await db.close_pool()
    await redis_client.close()


@pytest.fixture()
async def dbpool(stack):
    """Just the async pool, for service-level tests."""
    from app import db, redis_client

    await redis_client.close()   # drop any client bound to a previous test loop
    await db.open_pool()
    yield db
    await db.close_pool()
    await redis_client.close()


def auth(token: str, org: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if org:
        h["X-Org-Id"] = org
    return h
