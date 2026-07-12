"""Ingest orchestration: manifest -> fetch -> snapshot -> normalize ->
versioned upsert -> chunk -> embed -> store.

Per-source error isolation: each source runs inside its own transaction
(savepoint); a failing source is rolled back, recorded as an error event,
and never poisons the rest of the run. Snapshots are recorded in the same
transaction *after* successful normalization, so a failed source is fully
retried on the next run (the unchanged-hash short-circuit can't hide it).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from typing import Any

from . import config
from .chunk.chunker import chunk_section
from .embed.embedder import get_embedder
from .fetch import http
from .fetch.base import FetchError, Fetcher
from .fetch.ecfr import EcfrFetcher
from .fetch.finra import FinraFetcher
from .fetch.govinfo import PdfFetcher
from .fetch.states import StateFetcher
from .fetch.uscode import UscodeHtmlFetcher
from .manifest import (
    all_ingest_sources,
    default_ingest_sources,
    frameworks_for,
    get_source,
    load_manifest,
    manifest_version,
    source_family,
)
from .models import FetchResult, SectionUnit, SourceSpec
from .normalize.base import NormalizeError, Normalizer
from .normalize.ecfr_xml import EcfrXmlNormalizer
from .normalize.html_generic import (
    FinraHtmlNormalizer,
    GenericHtmlNormalizer,
    UscodeHtmlNormalizer,
)
from .normalize.pdf import PdfNormalizer
from .normalize.statute_html import StateHtmlNormalizer
from .store import repository
from .store.db import get_connection

logger = logging.getLogger(__name__)

_EXT_BY_KIND = {
    "ecfr_xml": ".xml",
    "audit_pdf": ".pdf",
    "generic_pdf": ".pdf",
    "state_pdf": ".pdf",
    "manual_pdf": ".pdf",
}


class _GenericHtmlFetcher:
    """Trivial fetcher for the generic_html family."""

    def fetch(self, spec: SourceSpec) -> list[FetchResult]:
        return [http.fetch_url(spec.id, spec.url, kind="generic_html")]


HANDLERS: dict[str, tuple[Fetcher, Normalizer]] = {
    "cfr": (EcfrFetcher(), EcfrXmlNormalizer()),
    "uscode_html": (UscodeHtmlFetcher(), UscodeHtmlNormalizer()),
    "finra_html": (FinraFetcher(), FinraHtmlNormalizer()),
    "state_html": (StateFetcher(), StateHtmlNormalizer()),
    "generic_pdf": (PdfFetcher(), PdfNormalizer()),
    "generic_html": (_GenericHtmlFetcher(), GenericHtmlNormalizer()),
}


def sync_sources(conn=None) -> int:
    """Upsert every manifest entry into rag_sources. Returns the count."""
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        specs = load_manifest()
        repository.upsert_sources(conn, specs, manifest_version())
        conn.commit()
        return len(specs)
    finally:
        if own_conn:
            conn.close()


def ingest_sources(
    source_ids: list[str] | None = None,
    *,
    all_sources: bool = False,
    force: bool = False,
    dry_run: bool = False,
    conn=None,
) -> dict:
    """Ingest the given sources (default: tier-1 federal + priority states;
    ``all_sources`` selects the entire manifest, references included).

    dry_run: fetch + normalize + chunk only — no DB writes, no snapshots,
    no embeddings. Returns the aggregate stats dict either way.
    """
    specs = load_manifest()
    if source_ids:
        selected = [get_source(sid, specs) for sid in source_ids]
    elif all_sources:
        selected = all_ingest_sources(specs)
    else:
        selected = default_ingest_sources(specs)

    own_conn = conn is None and not dry_run
    run_id: str | None = None
    embedder = None if dry_run else get_embedder()

    if not dry_run:
        conn = conn or get_connection()
        repository.upsert_sources(conn, specs, manifest_version())
        conn.commit()
        run_id = repository.start_ingest_run(conn)
        conn.commit()

    stats: dict[str, Any] = {
        "run_id": run_id,
        "dry_run": dry_run,
        "selected": len(selected),
        "stored": 0,
        "unchanged": 0,
        "skipped": 0,
        "errors": 0,
        "sections": 0,
        "new_versions": 0,
        "chunks": 0,
        "per_source": {},
    }

    try:
        for spec in selected:
            outcome = _ingest_one(
                spec,
                conn=conn,
                run_id=run_id,
                embedder=embedder,
                force=force,
                dry_run=dry_run,
            )
            stats["per_source"][spec.id] = outcome
            status = outcome["status"]
            stats[
                "stored" if status == "stored" else
                "unchanged" if status == "unchanged" else
                "skipped" if status == "skipped" else "errors"
            ] += 1
            stats["sections"] += outcome.get("sections", 0)
            stats["new_versions"] += outcome.get("new_versions", 0)
            stats["chunks"] += outcome.get("chunks", 0)
    finally:
        if not dry_run and conn is not None and run_id is not None:
            summary = {k: v for k, v in stats.items() if k != "per_source"}
            repository.finish_ingest_run(conn, run_id, summary)
            conn.commit()
        if own_conn and conn is not None:
            conn.close()

    logger.info(
        "ingest complete: %d stored, %d unchanged, %d skipped, %d errors "
        "(%d sections, %d new versions, %d chunks)",
        stats["stored"], stats["unchanged"], stats["skipped"], stats["errors"],
        stats["sections"], stats["new_versions"], stats["chunks"],
    )
    return stats


# ---------------------------------------------------------------------------
# Per-source ingest


def _ingest_one(
    spec: SourceSpec,
    *,
    conn,
    run_id: str | None,
    embedder,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    family = source_family(spec)
    logger.info("ingesting %s (family=%s)", spec.id, family)

    if family == "manual_stub":
        from .fetch.manual import ManualFetcher, manual_dir_for, manual_files_for
        from .manifest import MANUAL_STUB_SOURCES
        from .normalize.manual import ManualSnapshotNormalizer

        if manual_files_for(spec):
            handler = (ManualFetcher(), ManualSnapshotNormalizer())
        else:
            detail = {
                "reason": MANUAL_STUB_SOURCES.get(
                    spec.id,
                    "source requires manual resolution before it can be scraped",
                )
                + f" — save the official text into {manual_dir_for(spec)} "
                "(.html/.pdf/.txt) and re-run ingest",
                "url": spec.url,
            }
            if not dry_run:
                repository.log_ingest_event(conn, run_id, spec.id, "skipped", detail)
                conn.commit()
            logger.warning("skipping %s: %s", spec.id, detail["reason"])
            return {"status": "skipped", **detail}
    else:
        handler = HANDLERS.get(family)
    if handler is None:
        detail = {"reason": f"no handler for family {family!r}"}
        if not dry_run:
            repository.log_ingest_event(conn, run_id, spec.id, "skipped", detail)
            conn.commit()
        return {"status": "skipped", **detail}
    fetcher, normalizer = handler

    def _attempt(f: Fetcher, n: Normalizer) -> dict[str, Any]:
        if dry_run:
            return _process_source(
                spec, f, n, conn=None, embedder=None, force=force, dry_run=True,
            )
        with conn.transaction():  # savepoint: source failure rolls back
            return _process_source(
                spec, f, n, conn=conn, embedder=embedder, force=force, dry_run=False,
            )

    try:
        try:
            counters = _attempt(fetcher, normalizer)
        except (FetchError, NormalizeError) as live_err:
            # Manual snapshot fallback: when the live fetch fails (geo/WAF
            # blocks, site redesigns) and hand-saved files exist under
            # data/manual/<source-id>/, ingest those instead of erroring.
            from .fetch.manual import ManualFetcher, manual_files_for
            from .normalize.manual import ManualSnapshotNormalizer

            if not manual_files_for(spec):
                raise
            logger.warning(
                "live fetch/normalize failed for %s (%s); falling back to "
                "manual snapshot files",
                spec.id, live_err,
            )
            counters = _attempt(ManualFetcher(), ManualSnapshotNormalizer())
            counters["manual_fallback"] = True
    except (FetchError, NormalizeError) as e:
        logger.error("source %s failed: %s", spec.id, e)
        if not dry_run:
            repository.log_ingest_event(
                conn, run_id, spec.id, "error",
                {"error": str(e), "type": type(e).__name__},
            )
            conn.commit()
        return {"status": "error", "error": str(e)}
    except Exception as e:  # defensive: keep the run alive
        logger.exception("unexpected failure ingesting %s", spec.id)
        if not dry_run:
            repository.log_ingest_event(
                conn, run_id, spec.id, "error",
                {"error": str(e), "type": type(e).__name__},
            )
            conn.commit()
        return {"status": "error", "error": str(e)}

    status = "stored" if counters["fetched_pages"] else "unchanged"
    if counters["fetched_pages"] and not counters["sections"]:
        status = "error"  # fetched but nothing normalized — surface loudly
        counters["error"] = "fetched pages produced no section units"
    if not dry_run:
        repository.log_ingest_event(conn, run_id, spec.id, status, counters)
        conn.commit()
    logger.info(
        "%s: %s (%d pages, %d sections, %d new versions, %d chunks)",
        spec.id, status, counters["fetched_pages"], counters["sections"],
        counters["new_versions"], counters["chunks"],
    )
    return {"status": status, **counters}


def _process_source(
    spec: SourceSpec,
    fetcher: Fetcher,
    normalizer: Normalizer,
    *,
    conn,
    embedder,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    counters: dict[str, Any] = {
        "fetched_pages": 0,
        "unchanged_pages": 0,
        "sections": 0,
        "new_versions": 0,
        "chunks": 0,
    }
    frameworks = frameworks_for(spec)
    results = fetcher.fetch(spec)

    for fetched in results:
        sha = hashlib.sha256(fetched.content).hexdigest()
        kind = str(fetched.meta.get("kind", "unknown"))

        if (
            not force
            and not dry_run
            and repository.snapshot_exists(conn, spec.id, kind, sha)
        ):
            counters["unchanged_pages"] += 1
            logger.debug("unchanged content for %s (%s); skipping", spec.id, kind)
            continue

        units = normalizer.normalize(fetched, spec)
        counters["fetched_pages"] += 1
        counters["sections"] += len(units)

        if dry_run:
            for unit in units:
                counters["chunks"] += len(chunk_section(unit, spec, frameworks))
            continue

        storage_path = _write_raw(spec, fetched, sha, kind)
        snapshot_id = repository.record_snapshot(conn, fetched, storage_path, sha)

        amend_dates: dict[str, str] = dict(fetched.meta.get("section_amend_dates") or {})
        for unit in units:
            effective_start = _effective_start(unit, amend_dates, fetched)
            text_sha = hashlib.sha256(unit.text.encode("utf-8")).hexdigest()
            version_id, is_new = repository.upsert_section_version(
                conn, unit, snapshot_id, effective_start, text_sha
            )
            if not (is_new or force):
                continue
            chunks = chunk_section(unit, spec, frameworks)
            if not chunks:
                continue
            embeddings = embedder.encode([c.embedding_input for c in chunks])
            repository.replace_chunks(
                conn, version_id, spec, chunks, embeddings,
                embedding_model=embedder.model_name,
                embedding_dim=embedder.dim,
            )
            counters["new_versions"] += 1
            counters["chunks"] += len(chunks)

    # CFR sources: also snapshot the official govinfo annual-edition PDF as
    # the auditable counterpart of the eCFR XML (never normalized; non-fatal).
    if not dry_run and source_family(spec) == "cfr" and counters["fetched_pages"]:
        _snapshot_audit_pdf(spec, conn)

    return counters


def _effective_start(
    unit: SectionUnit, amend_dates: dict[str, str], fetched: FetchResult
) -> date:
    """eCFR per-section amendment date when known, else the fetch date."""
    section_number = unit.section_key.rsplit("/", 1)[-1]
    amended = amend_dates.get(section_number)
    if amended:
        try:
            return date.fromisoformat(amended)
        except ValueError:
            logger.debug("bad amendment date %r for %s", amended, unit.section_key)
    fetched_at = fetched.fetched_at
    if isinstance(fetched_at, datetime):
        return fetched_at.date()
    return date.today()


def _write_raw(spec: SourceSpec, fetched: FetchResult, sha: str, kind: str) -> str:
    ext = _EXT_BY_KIND.get(kind, ".html")
    directory = config.RAW_STORAGE_DIR / spec.id
    directory.mkdir(parents=True, exist_ok=True)
    ts = fetched.fetched_at.strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{ts}_{kind}_{sha[:10]}{ext}"
    path.write_bytes(fetched.content)
    return str(path)


def _snapshot_audit_pdf(spec: SourceSpec, conn) -> None:
    try:
        audit = PdfFetcher().fetch_audit_copy(spec)
        sha = hashlib.sha256(audit.content).hexdigest()
        if repository.snapshot_exists(conn, spec.id, "audit_pdf", sha):
            logger.debug("audit PDF for %s unchanged; not re-storing", spec.id)
            return
        storage_path = _write_raw(spec, audit, sha, "audit_pdf")
        repository.record_snapshot(conn, audit, storage_path, sha)
        logger.info("stored audit PDF snapshot for %s", spec.id)
    except Exception as e:  # snapshot-only, never fails the source
        logger.warning("audit PDF snapshot failed for %s: %s", spec.id, e)
