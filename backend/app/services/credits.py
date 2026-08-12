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
    """DEPRECATED (0012): flat charge at enqueue. Superseded by reserve_tx —
    kept one release for rollback."""
    cur = await conn.execute("select app.consume_credits(%s, %s, %s) as d",
                             (org_id, run_id, cost))
    return (await cur.fetchone())["d"]


# -- metered credits (0012) --------------------------------------------------

async def forecast_tx(conn: psycopg.AsyncConnection, org_id: str,
                      kind: str, cards: int) -> int:
    """Credits to escrow ABOVE the floor — p95 of comparable recent runs."""
    cur = await conn.execute("select app.credit_forecast(%s, %s, %s) as f",
                             (org_id, kind, cards))
    return int((await cur.fetchone())["f"])


async def reserve_tx(conn: psycopg.AsyncConnection, org_id: str, run_id: str,
                     floor_credits: int, forecast: int) -> dict[str, Any]:
    """Escrow floor + forecast for this run. Same allowed/needed/balance
    contract as consume_tx, so the 402 path is unchanged."""
    cur = await conn.execute("select app.reserve_credits(%s, %s, %s, %s) as d",
                             (org_id, run_id, floor_credits, forecast))
    return (await cur.fetchone())["d"]


async def hold_for_run(org_id: str, run_id: str) -> dict | None:
    """Live escrow state for a run — what the run detail endpoint shows while
    the engine is still working."""
    return await db.fetch_one(
        "select reserved, floor_credits, metered, charged, status, settled_at "
        "from public.credit_holds where run_id = %s and org_id = %s",
        (run_id, org_id))


async def effort_breakdown(org_id: str, run_id: str) -> list[dict]:
    """Line items behind a metered charge — the answer to 'why 47 credits?'."""
    return await db.fetch_all(
        "select unit, sum(quantity) as quantity, max(rate) as rate, "
        "       sum(credits) as credits, count(*) as events "
        "from public.effort_events where run_id = %s and org_id = %s "
        "group by unit order by sum(credits) desc",
        (run_id, org_id))
