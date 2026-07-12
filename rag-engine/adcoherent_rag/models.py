"""Core datatypes shared across the RAG pipeline.

These are the frozen contracts between modules — fetchers produce
FetchResults, normalizers produce SectionUnits, the chunker produces Chunks,
and retrieval returns RetrievalResults. Do not change field names without
updating every consumer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class SourceSpec:
    """One entry from adcoherent_regulatory_sources.json."""

    id: str
    tier: int
    category: str          # federal_regulation | federal_statute | sro_rule | state_udap | state_finreg | secondary_reference
    jurisdiction: str      # "US", "US-CA", "US-ALL-STATES", ...
    authority: str | None
    citation: str | None
    name: str
    url: str
    format: str            # "pdf" | "html"
    ingestion: str         # "pdf_download" | "html_scrape"
    url_status: str | None = None
    update_cadence: str | None = None
    topics: tuple[str, ...] = ()
    notes: str | None = None


@dataclass
class FetchResult:
    """Raw bytes fetched for a source (one source may yield several)."""

    source_id: str
    requested_url: str
    resolved_url: str
    content: bytes
    content_type: str
    http_status: int
    fetched_at: datetime
    # Free-form, JSON-serializable fetch metadata. Conventions:
    #   {"kind": "ecfr_xml" | "audit_pdf" | "uscode_html" | "finra_html"
    #            | "state_html" | "generic_pdf" | "generic_html"}
    #   {"govinfo_package_id": "CFR-2025-title16-vol1"}
    #   {"section_hint": "17500", "citation_hint": "Cal. Bus. & Prof. Code § 17500"}
    #   {"section_amend_dates": {"1030.8": "2024-01-01", ...}}   (eCFR versions feed)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Paragraph:
    """One block of text inside a section.

    `label` is the subsection designator as printed in the source ("(a)",
    "(a)(1)", "1.", None for unlabeled prose). `indent_level` 0 = top level.
    """

    label: str | None
    text: str
    indent_level: int = 0


@dataclass
class SectionUnit:
    """Canonical unit of regulation text: one section (e.g. 12 CFR § 1030.8).

    section_key is a stable slug used for versioning identity, e.g.:
      "cfr/12/1030.8"      (12 CFR § 1030.8)
      "usc/15/45"          (15 U.S.C. § 45)
      "finra/2210"         (FINRA Rule 2210)
      "us-tx/bc/17.46"     (Tex. Bus. & Com. Code § 17.46)
    """

    source_id: str
    section_key: str
    citation: str          # human citation, e.g. "12 CFR § 1030.8"
    heading: str | None
    paragraphs: list[Paragraph]

    @property
    def text(self) -> str:
        parts = []
        for p in self.paragraphs:
            prefix = f"{p.label} " if p.label else ""
            joined = f"{prefix}{p.text}".strip()
            if joined:
                parts.append(joined)
        return "\n".join(parts).strip()


@dataclass
class Chunk:
    """One retrieval chunk (roughly one subsection)."""

    section_key: str
    citation: str
    chunk_index: int
    subsection_label: str | None   # e.g. "(a)" when the chunk covers one subsection
    context_header: str            # "«citation» — «heading»[ — «label»]"
    text: str                      # verbatim regulation text (retrieval payload)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def embedding_input(self) -> str:
        """Text actually embedded: header gives the model citation context."""
        return f"{self.context_header}\n{self.text}"


@dataclass
class RetrievalResult:
    chunk_id: str
    version_id: str
    source_id: str
    citation: str
    heading: str | None
    subsection_label: str | None
    context_header: str
    text: str
    score: float                   # RRF-fused score
    vector_rank: int | None
    lexical_rank: int | None
    effective_start: date
    effective_end: date | None
    metadata: dict[str, Any]
