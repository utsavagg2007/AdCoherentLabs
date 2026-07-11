"""eCFR versioner-API XML -> canonical SectionUnits.

eCFR XML nests DIV1 (title) > DIV3 (chapter) > DIV5 (part) > DIV6 (subpart)
> DIV8 (section). Section-scoped responses have a DIV8 at (or near) the root.
Each DIV8 with TYPE="SECTION" becomes one SectionUnit; DIV9 appendices are
included best-effort. Authority/source/editorial notes are skipped.
"""

from __future__ import annotations

import logging
import re

from lxml import etree

from ..models import FetchResult, Paragraph, SectionUnit, SourceSpec
from .base import NormalizeError
from .html_generic import extract_leading_label

logger = logging.getLogger(__name__)

# Elements whose text is not regulation body text.
_SKIP_TAGS = {"CITA", "AUTH", "SOURCE", "EDNOTE", "NOTE", "PRTPAGE"}

# Body paragraph elements inside a DIV8/DIV9.
_PARA_TAGS = {"P", "FP", "FP-1", "FP-2", "HD"}

_WS_RE = re.compile(r"\s+")


def _element_text(el: etree._Element) -> str:
    """Flattened visible text of an element (inline markup collapsed)."""
    return _WS_RE.sub(" ", " ".join(el.itertext())).strip()


def _paragraphs_of(div: etree._Element) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for el in div.iter():
        tag = str(el.tag) if isinstance(el.tag, str) else ""
        if tag not in _PARA_TAGS:
            continue
        # skip paragraphs living inside notes/authority blocks
        skip = False
        parent = el.getparent()
        while parent is not None:
            if str(parent.tag) in _SKIP_TAGS:
                skip = True
                break
            parent = parent.getparent()
        if skip:
            continue
        text = _element_text(el)
        if not text:
            continue
        if tag == "HD":
            paragraphs.append(Paragraph(label=None, text=text, indent_level=0))
            continue
        label, rest, indent = extract_leading_label(text)
        paragraphs.append(Paragraph(label=label, text=rest or text, indent_level=indent))
    return paragraphs


def _heading_of(div: etree._Element, number: str) -> str | None:
    head = div.find("HEAD")
    if head is None:
        return None
    text = _element_text(head)
    # "§ 1030.8   Advertising." -> "Advertising."
    text = re.sub(rf"^§+\s*{re.escape(number)}\s*", "", text).strip()
    return text or None


class EcfrXmlNormalizer:
    """Parses eCFR full-XML into one SectionUnit per CFR section."""

    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]:
        title = fetched.meta.get("cfr_title")
        part = fetched.meta.get("cfr_part")
        if title is None:
            raise NormalizeError(
                "eCFR FetchResult missing cfr_title meta", source_id=spec.id
            )
        try:
            root = etree.fromstring(fetched.content)
        except etree.XMLSyntaxError as e:
            raise NormalizeError(
                f"invalid eCFR XML for {spec.id}: {e}", source_id=spec.id
            ) from e

        units: list[SectionUnit] = []
        seen_keys: set[str] = set()

        # iter() includes the root itself, which covers section-scoped
        # responses whose root element is the DIV8.
        for div8 in root.iter("DIV8"):
            if (div8.get("TYPE") or "").upper() != "SECTION":
                continue
            number = (div8.get("N") or "").strip().lstrip("§ ").strip()
            if not number:
                continue
            paragraphs = _paragraphs_of(div8)
            if not paragraphs:
                logger.debug("eCFR section %s has no body text; skipping", number)
                continue
            key = f"cfr/{title}/{number}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            units.append(
                SectionUnit(
                    source_id=spec.id,
                    section_key=key,
                    citation=f"{title} CFR § {number}",
                    heading=_heading_of(div8, number),
                    paragraphs=paragraphs,
                )
            )

        # Appendices (best effort).
        for div9 in root.iter("DIV9"):
            if (div9.get("TYPE") or "").upper() != "APPENDIX":
                continue
            try:
                raw_label = (div9.get("N") or "appendix").strip()
                slug = re.sub(r"[^0-9a-zA-Z]+", "-", raw_label).strip("-").lower() or "appendix"
                paragraphs = _paragraphs_of(div9)
                if not paragraphs:
                    continue
                key = f"cfr/{title}/{part}/appendix-{slug}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                head = div9.find("HEAD")
                heading = _element_text(head) if head is not None else raw_label
                units.append(
                    SectionUnit(
                        source_id=spec.id,
                        section_key=key,
                        citation=heading or f"{title} CFR Part {part} {raw_label}",
                        heading=heading,
                        paragraphs=paragraphs,
                    )
                )
            except Exception:  # appendices are non-essential
                logger.warning(
                    "skipping malformed appendix in %s", spec.id, exc_info=True
                )

        if not units:
            raise NormalizeError(
                f"no CFR sections found in eCFR XML for {spec.id} "
                f"(title {title}, part {part})",
                source_id=spec.id,
            )
        logger.info("normalized %d eCFR section(s) for %s", len(units), spec.id)
        return units
