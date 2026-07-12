"""PDF -> SectionUnits (PyMuPDF text extraction + citation-heading splitting).

Used for the ``generic_pdf`` family (direct PDF statute/reference documents).
CFR sources are parsed from eCFR XML instead; their govinfo PDFs are stored
as audit snapshots only and never pass through here.
"""

from __future__ import annotations

import logging
import re

from ..models import FetchResult, SectionUnit, SourceSpec
from .base import NormalizeError
from .html_generic import split_labeled_paragraphs

logger = logging.getLogger(__name__)

# Section headings at line start: "§ 255.0", "Sec. 40-12-101.", "SECTION 5."
_HEADING_RE = re.compile(
    r"^(?:§+\s*(?P<cfr>\d+[\w.\-]*)"
    r"|Sec(?:tion)?\.?\s+(?P<sec>\d[\w.\-:]*))"
    r"\.?\s",
    re.MULTILINE,
)

_PAGES_PER_FALLBACK_UNIT = 3
_MIN_BODY_CHARS = 40  # headings with less body than this are index-page noise


def _pdf_pages_text(content: bytes, *, source_id: str) -> list[str]:
    try:
        import fitz  # PyMuPDF — lazy heavy import
    except ImportError as e:  # pragma: no cover - env dependent
        raise NormalizeError(
            "PyMuPDF (fitz) is not installed; cannot normalize PDFs",
            source_id=source_id,
        ) from e
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            return [page.get_text("text") for page in doc]
    except Exception as e:
        raise NormalizeError(
            f"could not read PDF for {source_id}: {e}", source_id=source_id
        ) from e


def _slug(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z.\-:]+", "-", value).strip("-").lower()


class PdfNormalizer:
    """Splits PDF text into sections on citation-style headings."""

    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]:
        pages = _pdf_pages_text(fetched.content, source_id=spec.id)
        full_text = "\n".join(pages)
        if not full_text.strip():
            raise NormalizeError(
                f"PDF for {spec.id} contains no extractable text (scanned image?)",
                source_id=spec.id,
            )

        units = self._split_on_headings(full_text, spec)
        if units:
            logger.info(
                "normalized %d PDF section(s) for %s via headings", len(units), spec.id
            )
            return units

        units = self._page_window_fallback(pages, spec)
        if not units:
            raise NormalizeError(
                f"no usable text units in PDF for {spec.id}", source_id=spec.id
            )
        logger.info(
            "normalized %d PDF page-window unit(s) for %s (no heading structure)",
            len(units),
            spec.id,
        )
        return units

    # ------------------------------------------------------------------

    def _split_on_headings(self, text: str, spec: SourceSpec) -> list[SectionUnit]:
        matches = list(_HEADING_RE.finditer(text))
        if len(matches) < 2:  # one accidental match is not structure
            return []
        units: list[SectionUnit] = []
        seen: set[str] = set()
        for i, m in enumerate(matches):
            number = m.group("cfr") or m.group("sec") or ""
            number = number.strip().rstrip(".")
            if not number:
                continue
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.end():end].strip()
            if len(body) < _MIN_BODY_CHARS:
                continue
            key = f"{spec.id}/{_slug(number)}"
            if key in seen:
                continue
            seen.add(key)
            citation = f"§ {number}" if m.group("cfr") else f"Sec. {number}"
            paragraphs = split_labeled_paragraphs(body)
            if not paragraphs:
                continue
            units.append(
                SectionUnit(
                    source_id=spec.id,
                    section_key=key,
                    citation=f"{spec.citation or spec.name} — {citation}",
                    heading=None,
                    paragraphs=paragraphs,
                )
            )
        return units

    def _page_window_fallback(
        self, pages: list[str], spec: SourceSpec
    ) -> list[SectionUnit]:
        units: list[SectionUnit] = []
        for start in range(0, len(pages), _PAGES_PER_FALLBACK_UNIT):
            end = min(start + _PAGES_PER_FALLBACK_UNIT, len(pages))
            body = "\n".join(pages[start:end]).strip()
            if not body:
                continue
            paragraphs = split_labeled_paragraphs(body)
            if not paragraphs:
                continue
            units.append(
                SectionUnit(
                    source_id=spec.id,
                    section_key=f"{spec.id}/pages-{start + 1}-{end}",
                    citation=f"{spec.citation or spec.name} (pp. {start + 1}-{end})",
                    heading=None,
                    paragraphs=paragraphs,
                )
            )
        return units
