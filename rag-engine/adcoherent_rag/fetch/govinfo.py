"""PDF fetchers (govinfo annual-edition CFR PDFs and other direct PDF links).

``PdfFetcher.fetch`` handles the ``generic_pdf`` family: ``spec.url`` is
either a direct PDF link or a govinfo link-service URL
(``https://www.govinfo.gov/link/cfr/16/255?link-type=pdf&year=mostrecent``)
that redirects to the current annual-edition PDF.

``PdfFetcher.fetch_audit_copy`` performs the same download tagged
``audit_pdf`` so the pipeline can store the official govinfo PDF snapshot
alongside the eCFR XML for CFR sources; the govinfo package id (e.g.
``CFR-2025-title16-vol1``) is recorded when the final URL exposes it.
"""

from __future__ import annotations

import logging
import re

from ..models import FetchResult, SourceSpec
from .base import FetchError
from .http import fetch_url

logger = logging.getLogger(__name__)

# govinfo content URLs look like
# https://www.govinfo.gov/content/pkg/CFR-2025-title16-vol1/pdf/CFR-2025-title16-vol1-part255.pdf
_GOVINFO_PKG_RE = re.compile(r"pkg/(CFR-\d{4}-title\d+-vol\d+)")

# The PDF spec allows the %PDF header to appear within the first 1024 bytes.
_PDF_MAGIC_WINDOW = 1024

_PDF_ACCEPT_HEADERS = {"Accept": "application/pdf,*/*;q=0.8"}


def _extract_govinfo_package_id(resolved_url: str | None) -> str | None:
    """Pull the govinfo package id out of a resolved content URL (None-safe)."""
    if not resolved_url:
        return None
    match = _GOVINFO_PKG_RE.search(resolved_url)
    return match.group(1) if match else None


def _looks_like_pdf(result: FetchResult) -> bool:
    if b"%PDF" in result.content[:_PDF_MAGIC_WINDOW]:
        return True
    return "pdf" in (result.content_type or "").lower()


class PdfFetcher:
    """Downloads PDF sources, following redirects to the final document."""

    def fetch(self, spec: SourceSpec) -> list[FetchResult]:
        """Download ``spec.url`` as a ``generic_pdf`` FetchResult."""
        return [self._download(spec, kind="generic_pdf")]

    def fetch_audit_copy(self, spec: SourceSpec) -> FetchResult:
        """Download ``spec.url`` as an ``audit_pdf`` snapshot.

        Adds ``meta["govinfo_package_id"]`` (``CFR-YYYY-titleT-volV`` or None)
        parsed from the redirect-resolved URL. Used by the pipeline to store
        the official annual-edition PDF alongside eCFR XML for CFR sources —
        snapshot only, never normalized.
        """
        result = self._download(spec, kind="audit_pdf")
        package_id = _extract_govinfo_package_id(result.resolved_url)
        result.meta["govinfo_package_id"] = package_id
        if package_id:
            logger.info(
                "audit copy for %s resolved to govinfo package %s", spec.id, package_id
            )
        else:
            logger.debug(
                "audit copy for %s: no govinfo package id in resolved url %s",
                spec.id,
                result.resolved_url,
            )
        return result

    # ------------------------------------------------------------------
    # internals

    def _download(self, spec: SourceSpec, *, kind: str) -> FetchResult:
        try:
            result = fetch_url(
                spec.id, spec.url, kind=kind, headers=_PDF_ACCEPT_HEADERS
            )
        except FetchError:
            raise
        except Exception as e:  # never let bare exceptions escape a fetcher
            raise FetchError(
                f"unexpected error downloading PDF {spec.url}: {e}",
                source_id=spec.id,
                url=spec.url,
            ) from e

        if not result.content:
            raise FetchError(
                f"empty response body for PDF {spec.url}",
                source_id=spec.id,
                url=result.resolved_url or spec.url,
            )
        if not _looks_like_pdf(result):
            sniff = result.content[:16]
            raise FetchError(
                f"response for {spec.url} does not look like a PDF "
                f"(content-type={result.content_type!r}, first bytes={sniff!r})",
                source_id=spec.id,
                url=result.resolved_url or spec.url,
            )

        logger.info(
            "fetched %s: %d bytes (kind=%s) from %s",
            spec.id,
            len(result.content),
            kind,
            result.resolved_url,
        )
        return result
