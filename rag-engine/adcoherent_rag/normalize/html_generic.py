"""HTML normalizers + shared text-extraction helpers.

`extract_main_text` / `split_labeled_paragraphs` / `extract_leading_label`
are shared by the state-statute normalizer (statute_html.py) and the eCFR
XML normalizer, so their behavior is a contract: keep them conservative.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..models import FetchResult, Paragraph, SectionUnit, SourceSpec
from .base import NormalizeError

logger = logging.getLogger(__name__)

# Tags that never contain statute text.
_CHROME_TAGS = (
    "script", "style", "noscript", "nav", "header", "footer",
    "aside", "form", "iframe", "button", "svg",
)

# Leading subsection designator chain: "(a)", "(a)(1)", "(1)", "(i)" ...
_LABEL_CHAIN_RE = re.compile(r"^\s*((?:\(\s*[0-9a-zA-Z]{1,4}\s*\))+)\s*")
_LABEL_GROUP_RE = re.compile(r"\(\s*([0-9a-zA-Z]{1,4})\s*\)")

# Multi-character lowercase romanettes ("ii", "iv", ...); a bare "(i)" is
# treated as a letter since it is ambiguous.
_ROMAN_RE = re.compile(r"^[ivxl]{2,}$")

_BLANK_RUN_RE = re.compile(r"\n{3,}")


# ---------------------------------------------------------------------------
# Shared helpers


def extract_leading_label(text: str) -> tuple[str | None, str, int]:
    """Split "(a)(1) Foo bar" into ("(a)(1)", "Foo bar", indent_level).

    indent_level heuristic: letters=0, digits=1, romanettes=2 (based on the
    first designator in the chain), best effort — 0 when unsure.
    """
    m = _LABEL_CHAIN_RE.match(text)
    if not m:
        return None, text.strip(), 0
    chain = re.sub(r"\s+", "", m.group(1))
    rest = text[m.end():].strip()
    groups = _LABEL_GROUP_RE.findall(chain)
    indent = 0
    if groups:
        first = groups[0].lower()
        if first.isdigit():
            indent = 1
        elif _ROMAN_RE.match(first):
            indent = 2
    # Deeper chains are at least as nested as their length implies.
    indent = max(indent, len(groups) - 1)
    return chain, rest, min(indent, 3)


def split_labeled_paragraphs(text: str) -> list[Paragraph]:
    """Turn plain text into Paragraphs, detecting leading designators.

    Lines are treated as paragraph candidates; blank lines separate them.
    A line that *starts* a new designator opens a new paragraph even without
    a preceding blank line (common in statute HTML flattened to text).
    """
    paragraphs: list[Paragraph] = []
    buffer: list[str] = []
    buffer_label: str | None = None
    buffer_indent = 0

    def _flush() -> None:
        nonlocal buffer, buffer_label, buffer_indent
        body = " ".join(buffer).strip()
        if body:
            paragraphs.append(Paragraph(label=buffer_label, text=body, indent_level=buffer_indent))
        buffer, buffer_label, buffer_indent = [], None, 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            _flush()
            continue
        label, rest, indent = extract_leading_label(line)
        if label:
            _flush()
            buffer_label, buffer_indent = label, indent
            if rest:
                buffer.append(rest)
        else:
            buffer.append(line)
    _flush()
    return paragraphs


def extract_main_text(html: str) -> str:
    """Best-effort visible main-content text of an HTML page.

    Drops chrome tags, prefers <main>/<article>/content-ish containers, and
    falls back to the whole body. Returns newline-separated text with blank
    runs collapsed.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_CHROME_TAGS):
        tag.decompose()

    candidates = [
        soup.find("main"),
        soup.find("article"),
        soup.find(attrs={"role": "main"}),
        soup.find(id=re.compile(r"(main[-_]?content|content[-_]?main|codeLawSection)", re.I)),
        soup.find("div", class_=re.compile(r"(main[-_]?content|page[-_]?content|body[-_]?content)", re.I)),
    ]
    node = next((c for c in candidates if c is not None), None) or soup.body or soup

    text = node.get_text("\n", strip=True)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()


def _page_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            return t
    if soup.title and soup.title.string:
        return soup.title.string.strip() or None
    return None


def _decode(fetched: FetchResult) -> str:
    return fetched.content.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Normalizers


class UscodeHtmlNormalizer:
    """uscode.house.gov OLRC 'prelim' pages -> one SectionUnit per page."""

    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]:
        try:
            title = fetched.meta.get("usc_title")
            section = fetched.meta.get("usc_section")
            if title is None or section is None:
                raise NormalizeError(
                    "uscode FetchResult missing usc_title/usc_section meta",
                    source_id=spec.id,
                )
            html = _decode(fetched)
            soup = BeautifulSoup(html, "html.parser")

            heading = None
            head_el = soup.find(class_=re.compile(r"section-head", re.I))
            if head_el:
                heading = head_el.get_text(" ", strip=True)
                # "§45. Unfair methods of competition..." -> drop the number
                heading = re.sub(rf"^§+\s*{re.escape(str(section))}\.?\s*", "", heading).strip() or None

            paragraphs: list[Paragraph] = []
            body_els = soup.find_all(class_=re.compile(r"statutory-body|subsection-head", re.I))
            for el in body_els:
                text = el.get_text(" ", strip=True)
                if not text:
                    continue
                label, rest, indent = extract_leading_label(text)
                # class suffix carries nesting: statutory-body-1em, -2em, ...
                m = re.search(r"-(\d)em", " ".join(el.get("class", [])))
                if m:
                    indent = max(indent, int(m.group(1)))
                paragraphs.append(Paragraph(label=label, text=rest or text, indent_level=indent))

            if not paragraphs:
                logger.info(
                    "no statutory-body markup for %s §%s; falling back to generic extraction",
                    spec.id, section,
                )
                paragraphs = split_labeled_paragraphs(extract_main_text(html))
            if not paragraphs:
                raise NormalizeError(
                    f"no text extracted from uscode page for §{section}", source_id=spec.id
                )

            return [
                SectionUnit(
                    source_id=spec.id,
                    section_key=f"usc/{title}/{section}",
                    citation=f"{title} U.S.C. § {section}",
                    heading=heading,
                    paragraphs=paragraphs,
                )
            ]
        except NormalizeError:
            raise
        except Exception as e:
            raise NormalizeError(
                f"uscode normalization failed for {spec.id}: {e}", source_id=spec.id
            ) from e


class FinraHtmlNormalizer:
    """finra.org rulebook page -> one SectionUnit for the rule."""

    _CRUFT_PATTERNS = re.compile(
        r"^(Skip to|Breadcrumb|Home\b|Rules & Guidance|Rulebooks|FINRA Rules|"
        r"Selected Notices?|Versions|Cross References?|Amended by|Adopted by|"
        r"©|Sign in|Search|Feedback|Print)",
        re.I,
    )

    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]:
        try:
            rule_number = str(fetched.meta.get("rule_number") or "unknown")
            html = _decode(fetched)
            text = extract_main_text(html)
            lines = [
                ln for ln in text.splitlines()
                if ln.strip() and not self._CRUFT_PATTERNS.match(ln.strip())
            ]
            paragraphs = split_labeled_paragraphs("\n".join(lines))
            if not paragraphs:
                raise NormalizeError(
                    f"no rule text extracted from FINRA page for rule {rule_number}",
                    source_id=spec.id,
                )
            heading = _page_title(html)
            return [
                SectionUnit(
                    source_id=spec.id,
                    section_key=f"finra/{rule_number}",
                    citation=f"FINRA Rule {rule_number}",
                    heading=heading,
                    paragraphs=paragraphs,
                )
            ]
        except NormalizeError:
            raise
        except Exception as e:
            raise NormalizeError(
                f"FINRA normalization failed for {spec.id}: {e}", source_id=spec.id
            ) from e


class GenericHtmlNormalizer:
    """Fallback: whole page -> one SectionUnit."""

    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]:
        try:
            html = _decode(fetched)
            paragraphs = split_labeled_paragraphs(extract_main_text(html))
            if not paragraphs:
                raise NormalizeError(
                    f"no text extracted from {fetched.resolved_url}", source_id=spec.id
                )
            return [
                SectionUnit(
                    source_id=spec.id,
                    section_key=spec.id,
                    citation=spec.citation or spec.name,
                    heading=_page_title(html) or spec.name,
                    paragraphs=paragraphs,
                )
            ]
        except NormalizeError:
            raise
        except Exception as e:
            raise NormalizeError(
                f"generic HTML normalization failed for {spec.id}: {e}", source_id=spec.id
            ) from e
