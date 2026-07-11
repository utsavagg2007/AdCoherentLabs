"""Hybrid retrieval: pgvector ANN + Postgres full-text, fused with RRF.

One SQL statement:

  filtered  — chunks joined to their regulation version, restricted to the
              effective-date window (currently-effective by default, or an
              ``as_of`` date for audit replay) plus optional framework /
              jurisdiction / source filters;
  vec       — top candidates by cosine distance;
  lex       — top candidates by websearch_to_tsquery + ts_rank_cd;
  fused     — full outer join, score = Σ 1/(RRF_K + rank).
"""

from __future__ import annotations

import json
import logging
from datetime import date

import psycopg

try:  # pgvector >= 0.3
    from pgvector import Vector
except ImportError:  # pragma: no cover - older pgvector
    from pgvector.utils import Vector  # type: ignore[no-redef]

from .. import config
from ..embed.embedder import BaseEmbedder
from ..models import RetrievalResult

logger = logging.getLogger(__name__)

_SQL = """
with filtered as (
    select c.id, c.version_id, c.source_id, c.subsection_label,
           c.context_header, c.text, c.embedding, c.tsv, c.metadata,
           v.citation, v.heading, v.effective_start, v.effective_end
    from rag_chunks c
    join rag_regulation_versions v on v.id = c.version_id
    where c.embedding is not null
      and (
            (%(as_of)s::date is null and v.effective_end is null)
         or (%(as_of)s::date is not null
             and v.effective_start <= %(as_of)s::date
             and (v.effective_end is null or v.effective_end > %(as_of)s::date))
      )
      and (%(frameworks)s::text[] is null or c.frameworks && %(frameworks)s::text[])
      and (%(jurisdictions)s::text[] is null or c.jurisdiction = any(%(jurisdictions)s::text[]))
      and (%(source_ids)s::text[] is null or c.source_id = any(%(source_ids)s::text[]))
),
vec as (
    select id, row_number() over (order by embedding <=> %(qvec)s) as rank
    from filtered
    order by embedding <=> %(qvec)s
    limit %(candidates)s
),
lex as (
    select id,
           row_number() over (
               order by ts_rank_cd(tsv, websearch_to_tsquery('english', %(query)s)) desc
           ) as rank
    from filtered
    where tsv @@ websearch_to_tsquery('english', %(query)s)
    order by rank
    limit %(candidates)s
)
select f.id, f.version_id, f.source_id, f.citation, f.heading,
       f.subsection_label, f.context_header, f.text, f.metadata,
       f.effective_start, f.effective_end,
       vec.rank as vector_rank, lex.rank as lexical_rank,
       coalesce(1.0 / (%(rrf_k)s + vec.rank), 0)
         + coalesce(1.0 / (%(rrf_k)s + lex.rank), 0) as score
from vec
full outer join lex using (id)
join filtered f using (id)
order by score desc
limit %(k)s
"""


def retrieve(
    conn: psycopg.Connection,
    embedder: BaseEmbedder,
    query: str,
    *,
    k: int = 8,
    frameworks: list[str] | None = None,
    jurisdictions: list[str] | None = None,
    source_ids: list[str] | None = None,
    as_of: date | None = None,
    candidates: int = config.RETRIEVAL_CANDIDATES,
) -> list[RetrievalResult]:
    """Hybrid RRF retrieval over the currently-effective corpus.

    ``as_of`` switches to audit-replay mode: only versions effective on that
    date are searched (the ad's run date, per the versioned-storage design).
    """
    query = query.strip()
    if not query:
        return []
    qvec = Vector(embedder.encode([query])[0])

    params = {
        "query": query,
        "qvec": qvec,
        "k": k,
        "candidates": max(candidates, k),
        "rrf_k": config.RRF_K,
        "as_of": as_of,
        "frameworks": frameworks or None,
        "jurisdictions": jurisdictions or None,
        "source_ids": source_ids or None,
    }
    with conn.cursor() as cur:
        cur.execute(_SQL, params)
        rows = cur.fetchall()

    results = []
    for row in rows:
        metadata = row["metadata"]
        if isinstance(metadata, str):  # jsonb normally arrives parsed
            metadata = json.loads(metadata)
        results.append(
            RetrievalResult(
                chunk_id=str(row["id"]),
                version_id=str(row["version_id"]),
                source_id=row["source_id"],
                citation=row["citation"],
                heading=row["heading"],
                subsection_label=row["subsection_label"],
                context_header=row["context_header"],
                text=row["text"],
                score=float(row["score"]),
                vector_rank=row["vector_rank"],
                lexical_rank=row["lexical_rank"],
                effective_start=row["effective_start"],
                effective_end=row["effective_end"],
                metadata=metadata or {},
            )
        )
    logger.info(
        "retrieve(%r, k=%d, frameworks=%s, jurisdictions=%s, as_of=%s) -> %d results",
        query[:80],
        k,
        frameworks,
        jurisdictions,
        as_of,
        len(results),
    )
    return results
