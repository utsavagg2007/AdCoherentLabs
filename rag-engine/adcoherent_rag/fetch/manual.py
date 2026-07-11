"""Manual snapshot "fetcher": local files for sources with no scrape path.

Sources in ``manifest.MANUAL_STUB_SOURCES`` (JS-only viewers, Lexis/Westlaw-
hosted codes) cannot be scraped over plain HTTP. Instead, save the official
text by hand — browser "Save Page As" HTML, or print-to-PDF — into::

    data/manual/<source-id>/<any-name>.html|.pdf|.txt

and re-run ``ingest``. The pipeline picks the files up automatically (the
source is only skipped when its manual directory is empty or missing).

Conventions:

- One file per document; several files per source are fine (each becomes
  its own section-key namespace, so files never collide).
- KEEP THE SAME FILENAME when updating a document with a newer copy —
  section keys embed the file stem, so a renamed file would create new
  sections instead of superseding the old ones.
- ``fetched_at`` is the file's mtime, so effective_start reflects when the
  snapshot was taken, and unchanged files are deduped by content hash.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..models import FetchResult, SourceSpec
from .base import FetchError

logger = logging.getLogger(__name__)

_KIND_BY_EXT = {
    ".html": "manual_html",
    ".htm": "manual_html",
    ".txt": "manual_html",   # plain text runs through the HTML normalizer
    ".pdf": "manual_pdf",
}

_CONTENT_TYPE_BY_KIND = {
    "manual_html": "text/html",
    "manual_pdf": "application/pdf",
}


def manual_dir_for(spec: SourceSpec) -> Path:
    return config.MANUAL_SNAPSHOT_DIR / spec.id


def manual_files_for(spec: SourceSpec) -> list[Path]:
    """Usable snapshot files for a source, sorted by name ([] when none)."""
    directory = manual_dir_for(spec)
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in _KIND_BY_EXT
    )


class ManualFetcher:
    """Reads manual snapshot files and wraps them as FetchResults."""

    def fetch(self, spec: SourceSpec) -> list[FetchResult]:
        files = manual_files_for(spec)
        if not files:
            raise FetchError(
                f"no manual snapshot files for {spec.id} in {manual_dir_for(spec)} "
                "(expected .html/.pdf/.txt)",
                source_id=spec.id,
            )
        results: list[FetchResult] = []
        for path in files:
            try:
                content = path.read_bytes()
            except OSError as e:
                raise FetchError(
                    f"cannot read manual snapshot {path}: {e}", source_id=spec.id
                ) from e
            if not content.strip():
                logger.warning("manual snapshot %s is empty; skipping", path)
                continue
            kind = _KIND_BY_EXT[path.suffix.lower()]
            results.append(
                FetchResult(
                    source_id=spec.id,
                    requested_url=path.as_uri(),
                    resolved_url=path.as_uri(),
                    content=content,
                    content_type=_CONTENT_TYPE_BY_KIND[kind],
                    http_status=0,  # not an HTTP fetch
                    fetched_at=datetime.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc
                    ),
                    meta={"kind": kind, "manual_file": path.name},
                )
            )
        if not results:
            raise FetchError(
                f"all manual snapshot files for {spec.id} were empty",
                source_id=spec.id,
            )
        logger.info(
            "using %d manual snapshot file(s) for %s: %s",
            len(results), spec.id,
            ", ".join(str(r.meta["manual_file"]) for r in results),
        )
        return results
