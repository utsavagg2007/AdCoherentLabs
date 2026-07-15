"""Async Postgres access for the API (psycopg3 pool).

The pool connects as the privileged role, which BYPASSES RLS — the module
docstring rule from engine/saas.py applies verbatim: every statement written
against this pool must scope org_id explicitly. The red-line RLS test plus
code review guard the discipline (§3 trust boundaries).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings

_pool: AsyncConnectionPool | None = None


async def open_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            settings.db_url_api(),
            min_size=1, max_size=10, open=False,
            kwargs={"row_factory": dict_row,
                    "application_name": "adcoherent-api"},
        )
        await _pool.open(wait=True, timeout=30)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("DB pool not open - app startup did not run")
    return _pool


@asynccontextmanager
async def transaction() -> AsyncIterator[psycopg.AsyncConnection]:
    """One connection, one transaction — commit on clean exit, rollback on
    exception. THE primitive behind charge+enqueue atomicity (D3)."""
    async with pool().connection() as conn:
        async with conn.transaction():
            yield conn


async def fetch_one(sql: str, params: Any = ()) -> dict | None:
    async with pool().connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchone()


async def fetch_all(sql: str, params: Any = ()) -> list[dict]:
    async with pool().connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


async def execute(sql: str, params: Any = ()) -> None:
    async with pool().connection() as conn:
        await conn.execute(sql, params)


async def ping() -> bool:
    try:
        row = await fetch_one("select 1 as ok")
        return bool(row and row["ok"] == 1)
    except Exception:
        return False
