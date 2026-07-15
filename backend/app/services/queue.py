"""Queue interface (§10) — narrow on purpose so a broker swap stays contained:
enqueue (same transaction as the charge), stats, DLQ admin.
"""

from __future__ import annotations

import psycopg

from .. import db


async def enqueue_tx(conn: psycopg.AsyncConnection, run_id: str) -> int:
    """MUST be called on the same connection/transaction that consumed the
    credits — charge and enqueue commit or roll back together (D3)."""
    cur = await conn.execute("select app.enqueue_run(%s) as job_id", (run_id,))
    return int((await cur.fetchone())["job_id"])


async def stats() -> dict:
    row = await db.fetch_one("select app.queue_stats() as s")
    return row["s"]


async def dlq_list(limit: int = 50) -> list[dict]:
    return await db.fetch_all(
        "select id, run_id::text, org_id::text, tier, attempts, last_error, "
        "       created_at "
        "from app.job_queue where status = 'dlq' order by id desc limit %s",
        (min(limit, 200),))


async def dlq_requeue(job_id: int) -> bool:
    row = await db.fetch_one("select app.requeue_dlq_job(%s) as ok", (job_id,))
    return bool(row and row["ok"])
