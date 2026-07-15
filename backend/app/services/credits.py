"""Credit operations — thin wrappers; the SQL functions do the work (§8).

Everything money-moving happens inside app.* security-definer functions under
a SELECT ... FOR UPDATE row lock, so these wrappers add no logic of their own.
The submissions route calls consume() INSIDE its charge+enqueue transaction.
"""

from __future__ import annotations

from typing import Any

import psycopg

from .. import db


async def cost_quote(org_id: str, kind: str, cards: int = 1) -> int:
    row = await db.fetch_one("select app.credit_cost(%s, %s, %s) as c",
                             (org_id, kind, cards))
    return int(row["c"])


async def balance(org_id: str) -> dict:
    row = await db.fetch_one("select app.credit_balance(%s) as b", (org_id,))
    return row["b"]


async def ledger_page(org_id: str, before_id: int | None, limit: int) -> list[dict]:
    return await db.fetch_all(
        "select id, delta, bucket, reason, run_id::text, stripe_ref, "
        "       balance_after, created_at "
        "from public.credit_ledger where org_id = %s "
        "and (%s::bigint is null or id < %s) "
        "order by id desc limit %s",
        (org_id, before_id, before_id, min(limit, 200)))


# -- inside-transaction primitives (used by the submissions route) -----------

async def ensure_cycle_grant_tx(conn: psycopg.AsyncConnection, org_id: str) -> None:
    await conn.execute("select app.ensure_cycle_grant(%s)", (org_id,))


async def cost_tx(conn: psycopg.AsyncConnection, org_id: str,
                  kind: str, cards: int) -> int:
    cur = await conn.execute("select app.credit_cost(%s, %s, %s) as c",
                             (org_id, kind, cards))
    return int((await cur.fetchone())["c"])


async def consume_tx(conn: psycopg.AsyncConnection, org_id: str,
                     run_id: str, cost: int) -> dict[str, Any]:
    cur = await conn.execute("select app.consume_credits(%s, %s, %s) as d",
                             (org_id, run_id, cost))
    return (await cur.fetchone())["d"]
