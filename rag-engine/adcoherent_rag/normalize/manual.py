"""Normalizer for manual snapshot files (fetch/manual.py).

Dispatches per file kind — ``manual_html`` through the generic HTML
normalizer, ``manual_pdf`` through the PDF normalizer — then namespaces
every section key with the snapshot file's stem so multiple files for one
source can never collide (the generic HTML normalizer alone would key every
file to plain ``spec.id``).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..models import FetchResult, SectionUnit, SourceSpec
from .base import NormalizeError
from .html_generic import GenericHtmlNormalizer
from .pdf import PdfNormalizer

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^0-9a-zA-Z.\-]+")


def _stem_slug(filename: str) -> str:
    stem = Path(filename).stem
    return _SLUG_RE.sub("-", stem).strip("-").lower() or "file"


class ManualSnapshotNormalizer:
    """manual_html -> GenericHtmlNormalizer, manual_pdf -> PdfNormalizer,
    with file-stem-namespaced section keys."""

    def __init__(self) -> None:
        self._html = GenericHtmlNormalizer()
        self._pdf = PdfNormalizer()

    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]:
        kind = str(fetched.meta.get("kind", ""))
        if kind == "manual_pdf":
            units = self._pdf.normalize(fetched, spec)
        elif kind == "manual_html":
            units = self._html.normalize(fetched, spec)
        else:
            raise NormalizeError(
                f"unexpected manual snapshot kind {kind!r} for {spec.id}",
                source_id=spec.id,
            )

        stem = _stem_slug(str(fetched.meta.get("manual_file", "file")))
        for unit in units:
            suffix = unit.section_key
            if suffix.startswith(spec.id):
                suffix = suffix[len(spec.id):].lstrip("/")
            unit.section_key = (
                f"{spec.id}/{stem}/{suffix}" if suffix else f"{spec.id}/{stem}"
            )
        logger.info(
            "normalized %d unit(s) from manual snapshot %s for %s",
            len(units), fetched.meta.get("manual_file"), spec.id,
        )
        return units
