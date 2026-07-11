"""Repository layer: all SQL against the rag_* tables.

Every function takes `conn` first and never commits — transaction boundaries
belong to the caller (the pipeline commits per source; the CLI commits per
command).

The versioned-upsert core (`upsert_section_version`) implements the
never-update-in-place rule: a changed section closes the current row
(effective_end + superseded_by) and inserts a new effective-dated row.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import psycopg

try:  # pgvector >= 0.3
    from pgvector import Vector
except ImportError:  # pragma: no cover - older pgvector
    from pgvector.utils import Vector  # type: ignore[no-redef]

from ..manifest import frameworks_for
from ..models import Chunk, FetchResult, SourceSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sources


def upsert_sources(
    conn: psycopg.Connection, specs: list[SourceSpec], manifest_ver: str
) -> None:
    sql = """
        insert into rag_sources (
            id, tier, category, jurisdiction, authority, citation, name, url,
            format, ingestion, url_status, update_cadence, topics, frameworks,
            notes, manifest_version
        ) values (
            %(id)s, %(tier)s, %(category)s, %(jurisdiction)s, %(authority)s,
            %(citation)s, %(name)s, %(url)s, %(format)s, %(ingestion)s,
            %(url_status)s, %(update_cadence)s, %(topics)s, %(frameworks)s,
            %(notes)s, %(manifest_version)s
        )
        on conflict (id) do update set
            tier = excluded.tier,
            category = excluded.category,
            jurisdiction = excluded.jurisdiction,
            authority = excluded.authority,
            citation = excluded.citation,
            name = excluded.name,
            url = excluded.url,
            format = excluded.format,
            ingestion = excluded.ingestion,
            url_status = excluded.url_status,
            update_cadence = excluded.update_cadence,
            topics = excluded.topics,
            frameworks = excluded.frameworks,
            notes = excluded.notes,
            manifest_version = excluded.manifest_version,
            updated_at = now()
    """
    with conn.cursor() as cur:
        for spec in specs:
            cur.execute(
                sql,
                {
                    "id": spec.id,
                    "tier": spec.tier,
                    "category": spec.category,
                    "jurisdiction": spec.jurisdiction,
                    "authority": spec.authority,
                    "citation": spec.citation,
                    "name": spec.name,
                    "url": spec.url,
                    "format": spec.format,
                    "ingestion": spec.ingestion,
                    "url_status": spec.url_status,
                    "update_cadence": spec.update_cadence,
                    "topics": json.dumps(list(spec.topics)),
                    "frameworks": frameworks_for(spec),
                    "notes": spec.notes,
                    "manifest_version": manifest_ver,
                },
            )
    logger.info("synced %d manifest sources into rag_sources", len(specs))


# ---------------------------------------------------------------------------
# Raw snapshots


def latest_snapshot_sha(
    conn: psycopg.Connection, source_id: str, kind: str
) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            select content_sha256 from rag_raw_snapshots
            where source_id = %s and kind = %s
            order by fetched_at desc limit 1
            """,
            (source_id, kind),
        )
        row = cur.fetchone()
    return row["content_sha256"] if row else None


def snapshot_exists(
    conn: psycopg.Connection, source_id: str, kind: str, sha256: str
) -> bool:
    """Whether these exact bytes were snapshotted before (multi-page safe)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select 1 from rag_raw_snapshots
            where source_id = %s and kind = %s and content_sha256 = %s
            limit 1
            """,
            (source_id, kind, sha256),
        )
        return cur.fetchone() is not None


def record_snapshot(
    conn: psycopg.Connection, fetched: FetchResult, storage_path: str, sha256: str
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into rag_raw_snapshots (
                source_id, kind, requested_url, resolved_url, http_status,
                content_type, content_sha256, content_bytes, storage_path,
                fetched_at, meta
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                fetched.source_id,
                str(fetched.meta.get("kind", "unknown")),
                fetched.requested_url,
                fetched.resolved_url,
                fetched.http_status,
                fetched.content_type,
                sha256,
                len(fetched.content),
                storage_path,
                fetched.fetched_at,
                json.dumps(_json_safe(fetched.meta)),
            ),
        )
        return str(cur.fetchone()["id"])


def _json_safe(meta: dict[str, Any]) -> dict[str, Any]:
    """Meta dicts are JSON-serializable by convention; coerce defensively."""
    try:
        json.dumps(meta)
        return meta
    except (TypeError, ValueError):
        return {k: str(v) for k, v in meta.items()}


# ---------------------------------------------------------------------------
# Versioned regulation storage


def get_current_version(
    conn: psycopg.Connection, source_id: str, section_key: str
) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            select * from rag_regulation_versions
            where source_id = %s and section_key = %s and effective_end is null
            order by effective_start desc limit 1
            """,
            (source_id, section_key),
        )
        return cur.fetchone()


def upsert_section_version(
    conn: psycopg.Connection,
    unit,
    snapshot_id: str | None,
    effective_start: date,
    text_sha256: str,
) -> tuple[str, bool]:
    """Versioned upsert of one section. Returns (version_id, is_new).

    - unchanged text -> (existing id, False)
    - changed text  -> close current row, insert new one -> (new id, True)
    - same-day re-ingest with different text -> update that day's row in
      place (documented exception to append-only; a correction, not history)
    """
    current = get_current_version(conn, unit.source_id, unit.section_key)
    if current and current["text_sha256"] == text_sha256:
        return str(current["id"]), False

    with conn.cursor() as cur:
        if current and current["effective_start"] == effective_start:
            # Same-day correction: replace this row's text rather than
            # creating a zero-length predecessor version.
            cur.execute(
                """
                update rag_regulation_versions
                set citation = %s, heading = %s, text_content = %s,
                    text_sha256 = %s, snapshot_id = %s
                where id = %s
                returning id
                """,
                (
                    unit.citation,
                    unit.heading,
                    unit.text,
                    text_sha256,
                    snapshot_id,
                    current["id"],
                ),
            )
            return str(cur.fetchone()["id"]), True

        cur.execute(
            """
            insert into rag_regulation_versions (
                source_id, section_key, citation, heading, text_content,
                text_sha256, effective_start, snapshot_id
            ) values (%s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                unit.source_id,
                unit.section_key,
                unit.citation,
                unit.heading,
                unit.text,
                text_sha256,
                effective_start,
                snapshot_id,
            ),
        )
        new_id = str(cur.fetchone()["id"])

        if current:
            cur.execute(
                """
                update rag_regulation_versions
                set effective_end = %s, superseded_by = %s
                where id = %s
                """,
                (effective_start, new_id, current["id"]),
            )
            logger.info(
                "superseded %s (%s): %s -> %s",
                unit.section_key,
                unit.source_id,
                current["id"],
                new_id,
            )
    return new_id, True


# ---------------------------------------------------------------------------
# Chunks


def replace_chunks(
    conn: psycopg.Connection,
    version_id: str,
    spec: SourceSpec,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    embedding_model: str,
    embedding_dim: int,
) -> int:
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"chunks/embeddings length mismatch: {len(chunks)} != {len(embeddings)}"
        )
    frameworks = frameworks_for(spec)
    with conn.cursor() as cur:
        cur.execute("delete from rag_chunks where version_id = %s", (version_id,))
        cur.executemany(
            """
            insert into rag_chunks (
                version_id, source_id, jurisdiction, frameworks, chunk_index,
                subsection_label, context_header, text, embedding,
                embedding_model, embedding_dim, metadata
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    version_id,
                    spec.id,
                    spec.jurisdiction,
                    frameworks,
                    chunk.chunk_index,
                    chunk.subsection_label,
                    chunk.context_header,
                    chunk.text,
                    Vector(embedding),
                    embedding_model,
                    embedding_dim,
                    json.dumps(_json_safe(chunk.metadata)),
                )
                for chunk, embedding in zip(chunks, embeddings)
            ],
        )
    return len(chunks)


# ---------------------------------------------------------------------------
# Ingest runs / events


def start_ingest_run(conn: psycopg.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute("insert into rag_ingest_runs default values returning id")
        return str(cur.fetchone()["id"])


def finish_ingest_run(conn: psycopg.Connection, run_id: str, stats: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update rag_ingest_runs set finished_at = now(), stats = %s where id = %s",
            (json.dumps(_json_safe(stats)), run_id),
        )


def log_ingest_event(
    conn: psycopg.Connection,
    run_id: str,
    source_id: str | None,
    status: str,
    detail: dict,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into rag_ingest_events (run_id, source_id, status, detail)
            values (%s, %s, %s, %s)
            """,
            (run_id, source_id, status, json.dumps(_json_safe(detail))),
        )


# ---------------------------------------------------------------------------
# Stats


def corpus_stats(conn: psycopg.Connection) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            select s.id as source_id, s.jurisdiction,
                   count(distinct v.id) as versions,
                   count(distinct v.id) filter (where v.effective_end is null)
                       as current_versions,
                   count(c.id) as chunks
            from rag_sources s
            left join rag_regulation_versions v on v.source_id = s.id
            left join rag_chunks c on c.version_id = v.id
            group by s.id, s.jurisdiction
            having count(v.id) > 0
            order by s.id
            """
        )
        per_source = cur.fetchall()
        cur.execute(
            """
            select count(*) as total_chunks,
                   count(distinct embedding_model) as embedding_models,
                   array_agg(distinct embedding_model) as models
            from rag_chunks
            """
        )
        totals = cur.fetchone()
        cur.execute(
            """
            select id, started_at, finished_at, stats
            from rag_ingest_runs order by started_at desc limit 1
            """
        )
        last_run = cur.fetchone()
    return {
        "per_source": per_source,
        "total_chunks": totals["total_chunks"] if totals else 0,
        "embedding_models": (totals or {}).get("models"),
        "last_run": last_run,
    }
