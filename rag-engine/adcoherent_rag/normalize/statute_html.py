"""State statute HTML/PDF -> SectionUnits.

Three shapes arrive from fetch/states.py:

- single-section pages (CA leginfo, NY nysenate, FL Online Sunshine,
  MA malegislature, and most registry states): one SectionUnit per
  FetchResult, identified by the fetcher's ``section_hint`` /
  ``citation_hint`` meta;
- whole-chapter/act HTML pages (TX ``BC.17.htm``, IL ILCS listing, NV NRS
  chapter, CT/SC/NH/OR/DE/WV/PA ...): split on section-heading markers into
  many SectionUnits, driven by the ``split`` config named in the fetch meta;
- whole-chapter/title PDFs (``kind == "state_pdf"``: WY, IA, CO, ND ...):
  text is extracted with PyMuPDF, then split exactly like chapter HTML.

Chapter splitting is declarative: a ``ChapterSplitConfig`` gives the section
marker regex (one capture group = the section number) plus key/citation
templates. Marker false positives (tables of contents, amendment variants,
cross-reference anchor lines) are handled by keeping, per section number,
the candidate with the longest body.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..models import FetchResult, SectionUnit, SourceSpec
from .base import NormalizeError
from .html_generic import extract_main_text, split_labeled_paragraphs

logger = logging.getLogger(__name__)

# Texas-style ALL-CAPS heading right after the marker:
# "Sec. 17.41.  SHORT TITLE.  This subchapter ..."
_CAPS_HEADING_RE = re.compile(r"^\s*([A-Z][A-Z0-9 ,;:'()\-&/§\.]{2,120}?)\.\s")

_MIN_BODY_CHARS = 40  # marker hits with less body are index/TOC noise


@dataclass(frozen=True)
class ChapterSplitConfig:
    """How to split one chapter/act/title text blob into sections.

    ``marker`` must have exactly one capture group: the section number as it
    should appear in ``key_template``/``citation_template`` (``{num}``).
    ``caps_heading`` extracts a Texas-style ALL-CAPS heading from the body.
    ``flow`` collapses all whitespace to single spaces before matching (for
    pages whose markup breaks marker lines apart); flow markers must not
    rely on ``^`` anchors.
    ``stop`` truncates the input at its first match BEFORE splitting — used
    when the fetched document continues past the wanted chapter (full-title
    PDFs: the next chapter's first section heading), so the last section's
    body cannot swallow the rest of the title.
    """

    marker: re.Pattern[str]
    key_template: str
    citation_template: str
    caps_heading: bool = False
    flow: bool = False
    min_body_chars: int = _MIN_BODY_CHARS
    stop: re.Pattern[str] | None = None


# Registry of chapter-split strategies, referenced by fetch meta ``split``.
CHAPTER_SPLITS: dict[str, ChapterSplitConfig] = {
    # --- existing chapter states -----------------------------------------
    "tx-bc-17": ChapterSplitConfig(
        marker=re.compile(r"Sec\.\s*(17\.\d+[A-Za-z\-]*)\.", re.MULTILINE),
        key_template="us-tx/bc/{num}",
        citation_template="Tex. Bus. & Com. Code § {num}",
        caps_heading=True,
    ),
    "il-815-505": ChapterSplitConfig(
        marker=re.compile(r"\(815\s+ILCS\s+505/([0-9a-zA-Z.\-]+)\)"),
        key_template="us-il/815-505/{num}",
        citation_template="815 ILCS 505/{num}",
    ),
    "il-sec-fallback": ChapterSplitConfig(
        marker=re.compile(r"^Sec\.\s*([0-9a-zA-Z.\-]+)\.", re.MULTILINE),
        key_template="us-il/815-505/{num}",
        citation_template="815 ILCS 505/{num}",
    ),
    # --- new chapter-HTML states ------------------------------------------
    "ct-42-110": ChapterSplitConfig(
        marker=re.compile(r"^\s*Sec\.\s*(42-110[a-z]{0,2})\.", re.MULTILINE),
        key_template="us-ct/gs/{num}",
        citation_template="Conn. Gen. Stat. § {num}",
    ),
    "nv-nrs-598": ChapterSplitConfig(
        marker=re.compile(r"^\s*NRS\s*(598\.\d{3,4})\s{2,}", re.MULTILINE),
        key_template="us-nv/nrs/{num}",
        citation_template="Nev. Rev. Stat. § {num}",
    ),
    "sc-39-5": ChapterSplitConfig(
        marker=re.compile(r"^\s*SECTION\s+(39-5-\d+)\.", re.MULTILINE),
        key_template="us-sc/code/{num}",
        citation_template="S.C. Code § {num}",
    ),
    "nh-358-a": ChapterSplitConfig(
        marker=re.compile(r"^\s*(358-A:\d+(?:-[a-z])?)\s", re.MULTILINE),
        key_template="us-nh/rsa/{num}",
        citation_template="N.H. Rev. Stat. § {num}",
    ),
    "or-646": ChapterSplitConfig(
        marker=re.compile(r"^\s*(646\.\d{3})\s", re.MULTILINE),
        key_template="us-or/ors/{num}",
        citation_template="ORS § {num}",
    ),
    "de-6-25": ChapterSplitConfig(
        marker=re.compile(r"^\s*§\s*(25[0-9]{2}[A-Za-z]?)\.?\s", re.MULTILINE),
        key_template="us-de/6/{num}",
        citation_template="6 Del. C. § {num}",
    ),
    "wv-46a-6": ChapterSplitConfig(
        marker=re.compile(r"^\s*§\s*(46A-6-\d+)\.?\s", re.MULTILINE),
        key_template="us-wv/code/{num}",
        citation_template="W. Va. Code § {num}",
    ),
    "pa-utpcpl": ChapterSplitConfig(
        marker=re.compile(r"^\s*Section\s+(\d+(?:\.\d+)?(?:-[A-Z])?)\.", re.MULTILINE),
        key_template="us-pa/73ps/201-{num}",
        citation_template="73 P.S. § 201-{num}",
    ),
    "nd-51-15": ChapterSplitConfig(
        marker=re.compile(r"^\s*(51-15-\d+(?:\.\d+)?)\.\s", re.MULTILINE),
        key_template="us-nd/cc/{num}",
        citation_template="N.D. Cent. Code § {num}",
    ),
    "ak-45-50": ChapterSplitConfig(
        marker=re.compile(r"^\s*Sec\.\s*(45\.50\.\d+)\.", re.MULTILINE),
        key_template="us-ak/stat/{num}",
        citation_template="Alaska Stat. § {num}",
    ),
    # --- chapter/title PDFs -------------------------------------------------
    "wy-40-12": ChapterSplitConfig(
        marker=re.compile(r"^\s*(40-12-\d+)\.\s", re.MULTILINE),
        key_template="us-wy/stat/{num}",
        citation_template="Wyo. Stat. § {num}",
        # title40.pdf continues into ch. 13+; stop at the next chapter head
        stop=re.compile(r"^\s*40-13-\d+\.\s", re.MULTILINE),
    ),
    "ia-714": ChapterSplitConfig(
        marker=re.compile(r"^\s*(714[H]?\.\d+[A-Z]?)\s", re.MULTILINE),
        key_template="us-ia/code/{num}",
        citation_template="Iowa Code § {num}",
    ),
    "co-6-1": ChapterSplitConfig(
        marker=re.compile(r"^\s*(6-1-\d+(?:\.\d+)?)\.\s", re.MULTILINE),
        key_template="us-co/crs/{num}",
        citation_template="Colo. Rev. Stat. § {num}",
        # the CRS title-6 PDF continues into article 2+; stop at its head
        stop=re.compile(r"^\s*6-2-\d+(?:\.\d+)?\.\s", re.MULTILINE),
    ),
    "mi-445-9": ChapterSplitConfig(
        marker=re.compile(r"^\s*(445\.9\d{2}[a-z]?)\s", re.MULTILINE),
        key_template="us-mi/mcl/{num}",
        citation_template="Mich. Comp. Laws § {num}",
    ),
    "wa-19-86": ChapterSplitConfig(
        marker=re.compile(r"^\s*(19\.86\.\d{3})\s", re.MULTILINE),
        key_template="us-wa/rcw/{num}",
        citation_template="RCW {num}",
    ),
    # NYDFS BitLicense regulation (23 NYCRR Part 200). The source is a manual
    # stub today (text lives only on the bot-protected Westlaw NYCRR viewer);
    # this config is ready for the manual/licensed snapshot when it lands.
    "ny-23nycrr-200": ChapterSplitConfig(
        marker=re.compile(r"^\s*(?:§|Section)\s*(200\.\d+)\s", re.MULTILINE),
        key_template="us-ny/23nycrr/{num}",
        citation_template="23 NYCRR § {num}",
    ),
}


def _pdf_text(content: bytes, *, source_id: str) -> str:
    try:
        import fitz  # PyMuPDF — lazy heavy import
    except ImportError as e:  # pragma: no cover - env dependent
        raise NormalizeError(
            "PyMuPDF (fitz) is not installed; cannot normalize state PDFs",
            source_id=source_id,
        ) from e
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            return "\n".join(page.get_text("text") for page in doc)
    except Exception as e:
        raise NormalizeError(
            f"could not read state PDF for {source_id}: {e}", source_id=source_id
        ) from e


def _unit_from_text(
    spec: SourceSpec,
    *,
    section_key: str,
    citation: str,
    heading: str | None,
    text: str,
) -> SectionUnit | None:
    paragraphs = split_labeled_paragraphs(text)
    if not paragraphs:
        return None
    return SectionUnit(
        source_id=spec.id,
        section_key=section_key,
        citation=citation,
        heading=heading,
        paragraphs=paragraphs,
    )


def split_chapter(
    spec: SourceSpec, text: str, config: ChapterSplitConfig
) -> list[SectionUnit]:
    """Split chapter/act/title text into per-section units.

    All marker hits are collected as candidates; per section number the
    candidate with the longest body wins (drops TOC entries and truncated
    cross-reference fragments), and units come out in document order.
    """
    if config.flow:
        text = re.sub(r"\s+", " ", text)
    if config.stop:
        stop_match = config.stop.search(text)
        if stop_match:
            text = text[: stop_match.start()]
    matches = list(config.marker.finditer(text))
    candidates: dict[str, tuple[int, str]] = {}  # num -> (position, body)
    for i, m in enumerate(matches):
        num = m.group(1).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if len(body) < config.min_body_chars:
            continue
        if num not in candidates or len(body) > len(candidates[num][1]):
            candidates[num] = (m.start(), body)

    units: list[SectionUnit] = []
    for num, (_pos, body) in sorted(candidates.items(), key=lambda kv: kv[1][0]):
        heading = None
        if config.caps_heading:
            hm = _CAPS_HEADING_RE.match(body)
            if hm:
                heading = hm.group(1).strip().title()
                body = body[hm.end():].strip()
        unit = _unit_from_text(
            spec,
            section_key=config.key_template.format(num=num),
            citation=config.citation_template.format(num=num),
            heading=heading,
            text=body,
        )
        if unit:
            units.append(unit)
    return units


class StateHtmlNormalizer:
    """Normalizer for the state_html / state_pdf family."""

    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]:
        try:
            return self._normalize(fetched, spec)
        except NormalizeError:
            raise
        except Exception as e:
            raise NormalizeError(
                f"state normalization failed for {spec.id}: {e}", source_id=spec.id
            ) from e

    def _normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]:
        kind = str(fetched.meta.get("kind") or "state_html")
        if kind == "state_pdf":
            text = _pdf_text(fetched.content, source_id=spec.id)
        else:
            html = fetched.content.decode("utf-8", errors="replace")
            text = extract_main_text(html)
        if not text.strip():
            raise NormalizeError(
                f"no visible text on state page {fetched.resolved_url}",
                source_id=spec.id,
            )

        split_key = str(fetched.meta.get("split") or "").strip()
        if not split_key:
            # Back-compat: TX/IL chapter pages predate the split meta.
            if spec.jurisdiction == "US-TX":
                split_key = "tx-bc-17"
            elif spec.jurisdiction == "US-IL":
                split_key = "il-815-505" if CHAPTER_SPLITS["il-815-505"].marker.search(text) \
                    else "il-sec-fallback"

        if split_key:
            config = CHAPTER_SPLITS.get(split_key)
            if config is None:
                raise NormalizeError(
                    f"unknown chapter split config {split_key!r} for {spec.id}",
                    source_id=spec.id,
                )
            # IL: prefer the ILCS marker but fall back to bare "Sec. n." pages.
            if split_key == "il-815-505" and not config.marker.search(text):
                config = CHAPTER_SPLITS["il-sec-fallback"]
            units = split_chapter(spec, text, config)
            if not units:
                raise NormalizeError(
                    f"no {split_key!r} section markers found for {spec.id} "
                    f"({fetched.resolved_url})",
                    source_id=spec.id,
                )
            logger.info(
                "normalized %d section(s) for %s via %s", len(units), spec.id, split_key
            )
            return units

        # Single-section pages (CA, NY, FL, MA, and registry states with
        # per-section targets).
        section_hint = str(fetched.meta.get("section_hint") or "").strip()
        citation_hint = str(fetched.meta.get("citation_hint") or "").strip()
        if not section_hint:
            raise NormalizeError(
                f"state FetchResult for {spec.id} missing section_hint meta",
                source_id=spec.id,
            )
        key_hint = re.sub(r"[^0-9a-zA-Z.\-:]+", "-", section_hint.lower())
        unit = _unit_from_text(
            spec,
            section_key=f"{spec.jurisdiction.lower()}/{key_hint}",
            citation=citation_hint or f"{spec.citation or spec.name} § {section_hint}",
            heading=None,
            text=text,
        )
        if unit is None:
            raise NormalizeError(
                f"no paragraphs extracted for {spec.id} § {section_hint}",
                source_id=spec.id,
            )
        return [unit]
