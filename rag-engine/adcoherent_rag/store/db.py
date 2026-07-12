"""Database connection + schema initialization (psycopg 3 + pgvector)."""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .. import config

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_HNSW_INDEX_SQL = (
    "create index if not exists rag_chunks_embedding_idx "
    "on rag_chunks using hnsw (embedding vector_cosine_ops)"
)
_IVFFLAT_INDEX_SQL = (
    "create index if not exists rag_chunks_embedding_idx "
    "on rag_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100)"
)


def get_connection() -> psycopg.Connection:
    """Open a connection to the configured Postgres (Supabase).

    dict_row rows, autocommit OFF (callers control transactions), pgvector
    type adapter registered.
    """
    if not config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Put your Supabase direct connection "
            "string (port 5432) in rag-engine/.env — see .env.example."
        )
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row)
    try:
        from pgvector.psycopg import register_vector

        register_vector(conn)
    except psycopg.ProgrammingError:
        # vector extension not created yet — init_db will create it and
        # re-register the adapter on this connection.
        logger.warning(
            "pgvector extension not installed yet; run init-db before ingesting"
        )
        conn.rollback()
    return conn


def init_db(conn: psycopg.Connection) -> None:
    """Create the schema (idempotent) and the ANN index (HNSW, IVFFlat fallback)."""
    schema_sql = _SCHEMA_PATH.read_text()
    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()
    logger.info("schema applied from %s", _SCHEMA_PATH.name)

    # Now that the vector extension exists, make sure the adapter is registered
    # for this connection (no-op if it already is).
    from pgvector.psycopg import register_vector

    register_vector(conn)

    try:
        with conn.cursor() as cur:
            cur.execute(_HNSW_INDEX_SQL)
        conn.commit()
        logger.info("ANN index ready (hnsw)")
        return
    except psycopg.Error as e:
        conn.rollback()
        logger.warning("hnsw index unavailable (%s); trying ivfflat", e)

    try:
        with conn.cursor() as cur:
            cur.execute(_IVFFLAT_INDEX_SQL)
        conn.commit()
        logger.info("ANN index ready (ivfflat)")
    except psycopg.Error as e:
        conn.rollback()
        logger.warning(
            "no ANN index could be created (%s); vector search will "
            "sequential-scan — fine at small corpus sizes",
            e,
        )
