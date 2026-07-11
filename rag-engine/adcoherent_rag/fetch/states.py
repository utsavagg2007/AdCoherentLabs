"""State statute fetchers — every state jurisdiction with a scrapeable source.

Dispatch is per SOURCE ID (two sources can share a jurisdiction, e.g.
``us-ca-udap`` vs ``us-ca-dfpi-ccfpl``). Most states are declarative
:class:`StateStrategy` entries; the original priority states keep bespoke
functions where the site needs probing/fallback logic. States with NO
plain-HTTP official source (SPA/Lexis/Westlaw-only viewers) are not here —
they live in ``manifest.MANUAL_STUB_SOURCES`` with per-source reasons.

Every returned FetchResult carries::

    meta = {"kind": "state_html" | "state_pdf",
            "section_hint": "<section number>",      (single-section pages)
            "citation_hint": "<human citation>",
            "split": "<CHAPTER_SPLITS key>"}          (chapter pages/PDFs)

Strategy modes:

- ``sections``       — one URL per statute section (individually guarded;
                        only a state whose EVERY page fails raises FetchError)
- ``chapter_html``   — page(s) holding a whole chapter/act; the normalizer
                        splits them via ``CHAPTER_SPLITS[split]``
- ``chapter_pdf``    — same, but an official PDF (kind ``state_pdf``)
- ``linked_sections``— fetch a listing page, follow links whose text matches
                        ``link_text_re``, each linked page is one section

A source may list several strategies; they are tried in order until one
yields results. Chapter strategies verify their section markers at fetch
time so SPA shells / index pages fall through to the next strategy instead
of failing later in the normalizer.

Live-probe status (2026-07-05, from the dev machine): AZ, DC, DE, HI, IA,
KS, KY, ME, MD, MN, MT, ND, SC, SD, VA, WA, WY + CA/TX/FL/IL/MA + CA-CCFPL
verified working. CO, CT, MI, MO, NC, NE, NH, NV, OH, OR, PA, RI, UT, VT,
WI, WV keep their best-known official URLs but the hosts geo/WAF-block this
network (403 or connect timeout) — they error cleanly here and are expected
to work from US-based infrastructure.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin

from ..models import FetchResult, SourceSpec
from .base import FetchError
from .http import fetch_url

logger = logging.getLogger(__name__)

# Delay between successive requests to the same host (politeness).
_POLITENESS_DELAY_SECONDS = 0.5

# State legislature sites occasionally reject bare programmatic clients;
# browser-like Accept headers (on top of the configured User-Agent) keep the
# request honest but unremarkable.
_BROWSER_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_PDF_HEADERS: dict[str, str] = {"Accept": "application/pdf,*/*;q=0.8"}

# (url, section_hint, citation_hint)
_SectionTarget = tuple[str, str, str]


@dataclass(frozen=True)
class StateStrategy:
    """One declarative way to fetch a state statute source."""

    mode: str                                   # sections | chapter_html | chapter_pdf | linked_sections
    pages: tuple[_SectionTarget, ...] = ()      # sections mode
    url: str | None = None                      # chapter modes / listing page
    urls: tuple[str, ...] = ()                  # chapter_html: extra pages (same split)
    split: str | None = None                    # chapter modes -> CHAPTER_SPLITS key
    hint: str = ""                              # chapter modes: section_hint
    citation: str = ""                          # chapter modes: citation_hint
    link_text_re: str | None = None             # linked_sections: visible-text regex
    link_citation: str = ""                     # linked_sections: citation prefix
    link_hint_template: str = "{m}"             # linked_sections: capture -> section hint
    max_links: int = 12
    mirror: str | None = None                   # set when the text is an unofficial mirror
    extra_meta: dict = field(default_factory=dict)


def _visible_text(content: bytes) -> str:
    """Best-effort visible text of an HTML payload (for content sniffing)."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)
    except Exception:  # pragma: no cover - sniffing must never raise
        return content.decode("utf-8", errors="replace")


# Statute sites typeset section numbers with en/em/figure dashes and NBSPs
# (mgaleg renders "13–301" for § 13-301); normalize before containment checks.
_DASHES_RE = re.compile(r"[‐‑‒–—−]")


def _match_normalize(s: str) -> str:
    return _DASHES_RE.sub("-", s).replace(" ", " ")


def _section_pdf_text(content: bytes) -> str:
    """Extracted text of a per-section PDF, "" when PyMuPDF is unavailable
    (the containment guard is then skipped; the normalizer still parses)."""
    try:
        import fitz  # PyMuPDF — lazy heavy import

        with fitz.open(stream=content, filetype="pdf") as doc:
            return "\n".join(page.get_text("text") for page in doc)
    except ImportError:  # pragma: no cover - env dependent
        return ""
    except Exception:
        return ""


def _fetch_sections(
    spec: SourceSpec,
    targets: list[_SectionTarget],
    *,
    mirror: str | None = None,
) -> list[FetchResult]:
    """Fetch a list of section pages, tolerating per-section failures.

    A page whose visible text does not even contain its own section number
    is dropped (soft-404 / viewer-shell guard). Raises FetchError only when
    *every* target fails.
    """
    results: list[FetchResult] = []
    failures: list[str] = []
    for i, (url, section_hint, citation_hint) in enumerate(targets):
        if i:
            time.sleep(_POLITENESS_DELAY_SECONDS)
        meta = {"section_hint": section_hint, "citation_hint": citation_hint}
        if mirror:
            meta["mirror"] = mirror
        try:
            result = fetch_url(
                spec.id, url, kind="state_html",
                extra_meta=meta, headers=_BROWSER_HEADERS,
            )
            is_pdf = (
                b"%PDF" in result.content[:1024]
                or "pdf" in (result.content_type or "").lower()
            )
            if is_pdf:
                # Some states serve each section as a PDF (KY statute.aspx,
                # NC per-section PDFs). Retag so the normalizer extracts via
                # PyMuPDF instead of treating the bytes as HTML.
                result.meta["kind"] = "state_pdf"
                page_text = _match_normalize(_section_pdf_text(result.content))
            else:
                page_text = _match_normalize(_visible_text(result.content))
            token = re.sub(r"^[a-z]+-", "", section_hint)  # "fin-90003" -> "90003"
            if token and page_text and _match_normalize(token) not in page_text:
                raise FetchError(
                    f"page does not mention §{token} (viewer shell or soft 404?)",
                    source_id=spec.id,
                    url=url,
                )
            results.append(result)
        except FetchError as e:
            failures.append(f"{citation_hint} ({url}): {e}")
            logger.warning(
                "section fetch failed for %s — %s (%s): %s",
                spec.id, citation_hint, url, e,
            )
        except Exception as e:  # defensive: never leak bare exceptions
            failures.append(f"{citation_hint} ({url}): {e}")
            logger.warning(
                "unexpected error fetching %s — %s (%s): %s",
                spec.id, citation_hint, url, e,
            )
    if not results:
        raise FetchError(
            f"all {len(targets)} section fetches failed for {spec.id}: "
            + "; ".join(failures),
            source_id=spec.id,
        )
    if failures:
        logger.warning(
            "partial fetch for %s: %d/%d section pages failed (%s)",
            spec.id, len(failures), len(targets), "; ".join(failures),
        )
    return results


def _check_chapter_markers(
    spec: SourceSpec, strategy: StateStrategy, text: str, url: str
) -> None:
    """Chapter strategies must actually contain their section markers.

    Catches SPA shells / index-only pages at fetch time so the next strategy
    gets tried, instead of failing later in the normalizer.
    """
    from ..normalize.statute_html import CHAPTER_SPLITS

    config = CHAPTER_SPLITS.get(strategy.split or "")
    if config is None:
        raise FetchError(
            f"strategy for {spec.id} names unknown split {strategy.split!r}",
            source_id=spec.id,
            url=url,
        )
    if not config.marker.search(text):
        raise FetchError(
            f"page at {url} has no {strategy.split!r} section markers "
            "(SPA shell or index-only page?)",
            source_id=spec.id,
            url=url,
        )


def _fetch_chapter_html(spec: SourceSpec, strategy: StateStrategy) -> list[FetchResult]:
    assert strategy.split and (strategy.url or strategy.urls)
    from ..normalize.html_generic import extract_main_text

    urls = tuple(u for u in ((strategy.url,) if strategy.url else ()) + strategy.urls if u)
    meta = {
        "section_hint": strategy.hint,
        "citation_hint": strategy.citation,
        "split": strategy.split,
        **strategy.extra_meta,
    }
    if strategy.mirror:
        meta["mirror"] = strategy.mirror

    results: list[FetchResult] = []
    failures: list[str] = []
    for i, url in enumerate(urls):
        if i:
            time.sleep(_POLITENESS_DELAY_SECONDS)
        try:
            result = fetch_url(
                spec.id, url, kind="state_html",
                extra_meta=dict(meta), headers=_BROWSER_HEADERS,
            )
            _check_chapter_markers(
                spec, strategy,
                extract_main_text(result.content.decode("utf-8", errors="replace")),
                url,
            )
            results.append(result)
        except FetchError as e:
            failures.append(str(e))
            logger.warning("chapter page failed for %s (%s): %s", spec.id, url, e)
    if not results:
        raise FetchError(
            f"all {len(urls)} chapter pages failed for {spec.id}: "
            + " | ".join(failures),
            source_id=spec.id,
            url=urls[0],
        )
    return results


def _fetch_chapter_pdf(spec: SourceSpec, strategy: StateStrategy) -> list[FetchResult]:
    assert strategy.url and strategy.split
    meta = {
        "section_hint": strategy.hint,
        "citation_hint": strategy.citation,
        "split": strategy.split,
        **strategy.extra_meta,
    }
    result = fetch_url(
        spec.id, strategy.url, kind="state_pdf",
        extra_meta=meta, headers=_PDF_HEADERS,
    )
    if b"%PDF" not in result.content[:1024] and "pdf" not in result.content_type.lower():
        raise FetchError(
            f"expected a PDF from {strategy.url} "
            f"(content-type={result.content_type!r})",
            source_id=spec.id,
            url=strategy.url,
        )
    # Verify the PDF text actually contains the expected section markers so
    # a wrong document falls through to the next strategy. Skipped when
    # PyMuPDF is unavailable (the normalizer would surface it instead).
    try:
        import fitz  # PyMuPDF — lazy heavy import

        with fitz.open(stream=result.content, filetype="pdf") as doc:
            text = "\n".join(page.get_text("text") for page in doc)
        _check_chapter_markers(spec, strategy, text, strategy.url)
    except ImportError:  # pragma: no cover - env dependent
        logger.debug("PyMuPDF unavailable; skipping PDF marker pre-check")
    except FetchError:
        raise
    except Exception as e:
        raise FetchError(
            f"could not read PDF from {strategy.url}: {e}",
            source_id=spec.id,
            url=strategy.url,
        ) from e
    return [result]


def _fetch_linked_sections(spec: SourceSpec, strategy: StateStrategy) -> list[FetchResult]:
    """Fetch a listing page and follow section links matched by visible text."""
    assert strategy.url and strategy.link_text_re
    from bs4 import BeautifulSoup

    listing = fetch_url(
        spec.id, strategy.url, kind="state_html",
        extra_meta={"section_hint": "listing", "citation_hint": strategy.citation},
        headers=_BROWSER_HEADERS,
    )
    pattern = re.compile(strategy.link_text_re)
    soup = BeautifulSoup(listing.content, "html.parser")
    targets: list[_SectionTarget] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a"):
        text = anchor.get_text(" ", strip=True)
        href = anchor.get("href")
        if not href or not text:
            continue
        m = pattern.search(text)
        if not m:
            continue
        captured = (m.group(1) if m.groups() else m.group(0)).strip()
        section = strategy.link_hint_template.format(m=captured)
        url = urljoin(listing.resolved_url, href)
        if section in seen or url in seen:
            continue
        seen.add(section)
        seen.add(url)
        targets.append(
            (url, section, f"{strategy.link_citation or spec.citation or spec.name} § {section}")
        )
        if len(targets) >= strategy.max_links:
            break
    if not targets:
        raise FetchError(
            f"no section links matching {strategy.link_text_re!r} on {strategy.url}",
            source_id=spec.id,
            url=strategy.url,
        )
    time.sleep(_POLITENESS_DELAY_SECONDS)
    return _fetch_sections(spec, targets, mirror=strategy.mirror)


def _run_strategy(spec: SourceSpec, strategy: StateStrategy) -> list[FetchResult]:
    if strategy.mode == "sections":
        return _fetch_sections(spec, list(strategy.pages), mirror=strategy.mirror)
    if strategy.mode == "chapter_html":
        return _fetch_chapter_html(spec, strategy)
    if strategy.mode == "chapter_pdf":
        return _fetch_chapter_pdf(spec, strategy)
    if strategy.mode == "linked_sections":
        return _fetch_linked_sections(spec, strategy)
    raise FetchError(
        f"unknown state strategy mode {strategy.mode!r} for {spec.id}",
        source_id=spec.id,
    )


# ---------------------------------------------------------------------------
# Bespoke fetchers (priority states with probing / fallback logic)


def _fetch_texas(spec: SourceSpec) -> list[FetchResult]:
    """Texas DTPA — Bus. & Com. Code ch. 17 as one static HTML chapter file.

    statutes.capitol.texas.gov is now an Angular SPA that serves the same JS
    shell for every path; the actual statute files live on the SPA's file
    server (its ``FileServerPath``): https://tcss.legis.texas.gov/resources.
    The normalizer splits the chapter on ``Sec. 17.41.``-style headings.
    """
    return _fetch_chapter_html(
        spec,
        StateStrategy(
            mode="chapter_html",
            url="https://tcss.legis.texas.gov/resources/BC/htm/BC.17.htm",
            split="tx-bc-17",
            hint="17",
            citation="Tex. Bus. & Com. Code ch. 17",
        ),
    )


_CA_SECTION_URL = (
    "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"
    "?lawCode={code}&sectionNum={num}"
)
_CA_BPC_SECTIONS = ("17200", "17500", "17501", "17502", "17505", "17505.5", "17508", "17509")


def _fetch_california(spec: SourceSpec) -> list[FetchResult]:
    """California UCL / FAL (Bus. & Prof. Code) + CLRA § 1770 (Civ. Code)."""
    targets: list[_SectionTarget] = [
        (
            _CA_SECTION_URL.format(code="BPC", num=num),
            num,
            f"Cal. Bus. & Prof. Code § {num}",
        )
        for num in _CA_BPC_SECTIONS
    ]
    targets.append(
        (_CA_SECTION_URL.format(code="CIV", num="1770"), "1770", "Cal. Civ. Code § 1770")
    )
    return _fetch_sections(spec, targets)


_NY_SECTIONS = ("349", "350", "350-A", "350-D")


def _fetch_new_york(spec: SourceSpec) -> list[FetchResult]:
    """New York GBL art. 22-A — nysenate.gov per-section pages.

    §§ 350-A / 350-D may 404 depending on site codification; those are simply
    skipped by the per-section guard in _fetch_sections.
    """
    targets: list[_SectionTarget] = [
        (
            f"https://www.nysenate.gov/legislation/laws/GBS/{num}",
            num.lower(),
            f"N.Y. Gen. Bus. Law § {num.lower()}",
        )
        for num in _NY_SECTIONS
    ]
    return _fetch_sections(spec, targets)


_FL_SECTION_URL = (
    "http://www.leg.state.fl.us/statutes/index.cfm"
    "?App_mode=Display_Statute&URL=0500-0599/0501/Sections/0501.{num}.html"
)
_FL_SECTIONS = ("201", "202", "203", "204", "2041", "2075", "2077", "211", "212", "213")


def _fetch_florida(spec: SourceSpec) -> list[FetchResult]:
    """Florida FDUTPA — Online Sunshine per-section pages (404s skipped)."""
    targets: list[_SectionTarget] = [
        (_FL_SECTION_URL.format(num=num), f"501.{num}", f"Fla. Stat. § 501.{num}")
        for num in _FL_SECTIONS
    ]
    return _fetch_sections(spec, targets)


# ilga.gov was redesigned (2025/2026): the old ilcs3.asp/ilcs2.asp URLs now
# return empty shell pages (HTTP 200!), and ActIDs were renumbered — the
# Consumer Fraud Act is ActID=2356 on the new site (was 1219).
# Verified live 2026-07-07: the Articles page carries the full act text with
# "(815 ILCS 505/N)" markers.
_IL_ACT_URL = "https://www.ilga.gov/Legislation/ILCS/Articles?ActID=2356&ChapterID=67"
_IL_LISTING_URL = "https://www.ilga.gov/Legislation/ILCS/Acts?ChapterID=67"
_IL_MARKER_RE = re.compile(r"815\s+ILCS\s+505/")
_IL_META = {"section_hint": "815-505", "citation_hint": "815 ILCS 505", "split": "il-815-505"}


def _fetch_illinois(spec: SourceSpec) -> list[FetchResult]:
    """Illinois Consumer Fraud Act (815 ILCS 505) — one full-act page.

    The direct ActID URL is verified to actually contain the act's section
    markers (ilga.gov serves empty HTTP-200 shells for stale URLs); on
    failure, falls back to the chapter-815 act listing and follows the first
    link whose text contains "Consumer Fraud".
    """
    try:
        result = fetch_url(
            spec.id, _IL_ACT_URL, kind="state_html",
            extra_meta=dict(_IL_META), headers=_BROWSER_HEADERS,
        )
        if _IL_MARKER_RE.search(_visible_text(result.content)):
            return [result]
        logger.warning(
            "IL act page %s has no 815 ILCS 505 markers (stale/renumbered "
            "ActID?); falling back to act listing %s",
            _IL_ACT_URL, _IL_LISTING_URL,
        )
    except FetchError as e:
        logger.warning(
            "IL act page %s failed (%s); falling back to act listing %s",
            _IL_ACT_URL, e, _IL_LISTING_URL,
        )

    time.sleep(_POLITENESS_DELAY_SECONDS)
    listing = fetch_url(
        spec.id, _IL_LISTING_URL, kind="state_html",
        extra_meta={"section_hint": "chapter-67", "citation_hint": "815 ILCS ch. 67 listing"},
        headers=_BROWSER_HEADERS,
    )
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(listing.content, "html.parser")
        act_href: str | None = None
        for anchor in soup.find_all("a"):
            text = anchor.get_text(" ", strip=True)
            href = anchor.get("href")
            if href and "consumer fraud" in text.lower():
                act_href = urljoin(listing.resolved_url, href)
                break
    except Exception as e:
        raise FetchError(
            f"could not parse IL act listing for the Consumer Fraud Act link: {e}",
            source_id=spec.id,
            url=_IL_LISTING_URL,
        ) from e
    if not act_href:
        raise FetchError(
            "no 'Consumer Fraud' link found on the IL act listing",
            source_id=spec.id,
            url=_IL_LISTING_URL,
        )
    time.sleep(_POLITENESS_DELAY_SECONDS)
    return [
        fetch_url(
            spec.id, act_href, kind="state_html",
            extra_meta=dict(_IL_META), headers=_BROWSER_HEADERS,
        )
    ]


_MA_SECTIONS = ("1", "2", "3", "4", "9", "11")


def _fetch_massachusetts(spec: SourceSpec) -> list[FetchResult]:
    """Massachusetts ch. 93A — malegislature.gov per-section pages."""
    targets: list[_SectionTarget] = [
        (
            f"https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXV/Chapter93A/Section{num}",
            num,
            f"Mass. Gen. Laws ch. 93A, § {num}",
        )
        for num in _MA_SECTIONS
    ]
    return _fetch_sections(spec, targets)


_CUSTOM_FETCHERS: dict[str, Callable[[SourceSpec], list[FetchResult]]] = {
    "us-ca-udap": _fetch_california,
    "us-ny-udap": _fetch_new_york,
    "us-tx-udap": _fetch_texas,
    "us-fl-udap": _fetch_florida,
    "us-il-udap": _fetch_illinois,
    "us-ma-udap": _fetch_massachusetts,
}


# ---------------------------------------------------------------------------
# Declarative registry. Verified = live-probed OK from the dev machine on
# 2026-07-05. Blocked-here = host geo/WAF-blocks this network; official URL
# kept for US-based runs.

def _s(url: str, hint: str, citation: str) -> _SectionTarget:
    return (url, hint, citation)


STATE_STRATEGIES: dict[str, tuple[StateStrategy, ...]] = {
    # --- Arizona — static per-section pages (verified) ---------------------
    "us-az-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://www.azleg.gov/ars/44/01521.htm", "44-1521", "Ariz. Rev. Stat. § 44-1521"),
                _s("https://www.azleg.gov/ars/44/01522.htm", "44-1522", "Ariz. Rev. Stat. § 44-1522"),
                _s("https://www.azleg.gov/ars/44/01528.htm", "44-1528", "Ariz. Rev. Stat. § 44-1528"),
                _s("https://www.azleg.gov/ars/44/01531.htm", "44-1531", "Ariz. Rev. Stat. § 44-1531"),
            ),
        ),
    ),
    # --- Colorado — official CRS title 6 PDF (blocked-here: 403) ------------
    "us-co-udap": (
        StateStrategy(
            mode="chapter_pdf",
            url="https://leg.colorado.gov/sites/default/files/images/olls/crs2024-title-06.pdf",
            split="co-6-1",
            hint="6-1",
            citation="Colo. Rev. Stat. tit. 6, art. 1",
        ),
    ),
    # --- Connecticut — whole-chapter static page (blocked-here: timeout) ----
    "us-ct-udap": (
        StateStrategy(
            mode="chapter_html",
            url="https://www.cga.ct.gov/current/pub/chap_735a.htm",
            split="ct-42-110",
            hint="42-110",
            citation="Conn. Gen. Stat. ch. 735a",
        ),
    ),
    # --- Delaware — subchapter pages I-III of ch. 25 (verified) -------------
    "us-de-udap": (
        StateStrategy(
            mode="chapter_html",
            url="https://delcode.delaware.gov/title6/c025/sc01/index.html",
            urls=(
                "https://delcode.delaware.gov/title6/c025/sc02/index.html",
                "https://delcode.delaware.gov/title6/c025/sc03/index.html",
            ),
            split="de-6-25",
            hint="6-25",
            citation="6 Del. C. ch. 25",
        ),
    ),
    # --- District of Columbia — per-section pages (verified) ----------------
    "us-dc-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://code.dccouncil.gov/us/dc/council/code/sections/28-3901",
                   "28-3901", "D.C. Code § 28-3901"),
                _s("https://code.dccouncil.gov/us/dc/council/code/sections/28-3904",
                   "28-3904", "D.C. Code § 28-3904"),
                _s("https://code.dccouncil.gov/us/dc/council/code/sections/28-3905",
                   "28-3905", "D.C. Code § 28-3905"),
                _s("https://code.dccouncil.gov/us/dc/council/code/sections/28-3909",
                   "28-3909", "D.C. Code § 28-3909"),
            ),
        ),
    ),
    # --- Hawaii — static HRS per-section pages (verified) --------------------
    "us-hi-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://www.capitol.hawaii.gov/hrscurrent/Vol11_Ch0476-0490/HRS0480/HRS_0480-0002.htm",
                   "480-2", "Haw. Rev. Stat. § 480-2"),
                _s("https://www.capitol.hawaii.gov/hrscurrent/Vol11_Ch0476-0490/HRS0481A/HRS_0481A-0003.htm",
                   "481A-3", "Haw. Rev. Stat. § 481A-3"),
                _s("https://www.capitol.hawaii.gov/hrscurrent/Vol11_Ch0476-0490/HRS0481A/HRS_0481A-0004.htm",
                   "481A-4", "Haw. Rev. Stat. § 481A-4"),
            ),
        ),
    ),
    # --- Idaho — per-section pages (blocked-here: timeout) -------------------
    "us-id-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://legislature.idaho.gov/statutesrules/idstat/Title48/T48CH6/SECT48-601/",
                   "48-601", "Idaho Code § 48-601"),
                _s("https://legislature.idaho.gov/statutesrules/idstat/Title48/T48CH6/SECT48-602/",
                   "48-602", "Idaho Code § 48-602"),
                _s("https://legislature.idaho.gov/statutesrules/idstat/Title48/T48CH6/SECT48-603/",
                   "48-603", "Idaho Code § 48-603"),
                _s("https://legislature.idaho.gov/statutesrules/idstat/Title48/T48CH6/SECT48-608/",
                   "48-608", "Idaho Code § 48-608"),
            ),
        ),
    ),
    # --- Iowa — official per-chapter PDFs (verified) --------------------------
    "us-ia-udap": (
        StateStrategy(
            mode="chapter_pdf",
            url="https://www.legis.iowa.gov/docs/code/714.pdf",
            split="ia-714",
            hint="714",
            citation="Iowa Code ch. 714",
        ),
        StateStrategy(
            mode="chapter_pdf",
            url="https://www.legis.iowa.gov/docs/code/714H.pdf",
            split="ia-714",
            hint="714H",
            citation="Iowa Code ch. 714H",
        ),
    ),
    # --- Kansas — ksrevisor per-section pages (verified) ----------------------
    "us-ks-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://www.ksrevisor.gov/statutes/chapters/ch50/050_006_0023.html",
                   "50-623", "Kan. Stat. § 50-623"),
                _s("https://www.ksrevisor.gov/statutes/chapters/ch50/050_006_0024.html",
                   "50-624", "Kan. Stat. § 50-624"),
                _s("https://www.ksrevisor.gov/statutes/chapters/ch50/050_006_0026.html",
                   "50-626", "Kan. Stat. § 50-626"),
                _s("https://www.ksrevisor.gov/statutes/chapters/ch50/050_006_0027.html",
                   "50-627", "Kan. Stat. § 50-627"),
                _s("https://www.ksrevisor.gov/statutes/chapters/ch50/050_006_0036.html",
                   "50-636", "Kan. Stat. § 50-636"),
            ),
        ),
    ),
    # --- Kentucky — KRS ch. 367 listing -> section links (verified) ----------
    # Anchor texts on the chapter page are ".110  Definitions..." (no "367").
    "us-ky-udap": (
        StateStrategy(
            mode="linked_sections",
            url="https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=39092",
            link_text_re=r"^\.(110|170|220)\b",
            link_citation="KRS",
            link_hint_template="367.{m}",
            max_links=6,
        ),
    ),
    # --- Maine — static per-section pages (verified) ---------------------------
    "us-me-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://legislature.maine.gov/statutes/5/title5sec205-A.html",
                   "205-A", "5 M.R.S. § 205-A"),
                _s("https://legislature.maine.gov/statutes/5/title5sec206.html",
                   "206", "5 M.R.S. § 206"),
                _s("https://legislature.maine.gov/statutes/5/title5sec207.html",
                   "207", "5 M.R.S. § 207"),
                _s("https://legislature.maine.gov/statutes/5/title5sec213.html",
                   "213", "5 M.R.S. § 213"),
            ),
        ),
    ),
    # --- Maryland — mgaleg StatuteText endpoint (verified) ----------------------
    "us-md-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gcl&section=13-101&enactments=false",
                   "13-101", "Md. Code, Com. Law § 13-101"),
                _s("https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gcl&section=13-301&enactments=false",
                   "13-301", "Md. Code, Com. Law § 13-301"),
                _s("https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gcl&section=13-303&enactments=false",
                   "13-303", "Md. Code, Com. Law § 13-303"),
            ),
        ),
    ),
    # --- Michigan — MCL pages + act PDF (blocked-here: timeout) -----------------
    "us-mi-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-445-902",
                   "445.902", "Mich. Comp. Laws § 445.902"),
                _s("https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-445-903",
                   "445.903", "Mich. Comp. Laws § 445.903"),
                _s("https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-445-911",
                   "445.911", "Mich. Comp. Laws § 445.911"),
            ),
        ),
        StateStrategy(
            mode="chapter_pdf",
            url="https://www.legislature.mi.gov/documents/mcl/pdf/mcl-Act-331-of-1976.pdf",
            split="mi-445-9",
            hint="445.901",
            citation="Mich. Comp. Laws ch. 445 (Act 331 of 1976)",
        ),
    ),
    # --- Minnesota — revisor per-section pages (verified) ------------------------
    "us-mn-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://www.revisor.mn.gov/statutes/cite/325F.67",
                   "325F.67", "Minn. Stat. § 325F.67"),
                _s("https://www.revisor.mn.gov/statutes/cite/325F.68",
                   "325F.68", "Minn. Stat. § 325F.68"),
                _s("https://www.revisor.mn.gov/statutes/cite/325F.69",
                   "325F.69", "Minn. Stat. § 325F.69"),
                _s("https://www.revisor.mn.gov/statutes/cite/325D.44",
                   "325D.44", "Minn. Stat. § 325D.44"),
            ),
        ),
    ),
    # --- Missouri — revisor per-section endpoint (blocked-here: timeout) ---------
    "us-mo-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://revisor.mo.gov/main/OneSection.aspx?section=407.010",
                   "407.010", "Mo. Rev. Stat. § 407.010"),
                _s("https://revisor.mo.gov/main/OneSection.aspx?section=407.020",
                   "407.020", "Mo. Rev. Stat. § 407.020"),
                _s("https://revisor.mo.gov/main/OneSection.aspx?section=407.025",
                   "407.025", "Mo. Rev. Stat. § 407.025"),
            ),
        ),
    ),
    # --- Montana — static deep-path per-section pages (verified) ------------------
    "us-mt-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://leg.mt.gov/bills/mca/title_0300/chapter_0140/part_0010/section_0020/0300-0140-0010-0020.html",
                   "30-14-102", "Mont. Code Ann. § 30-14-102"),
                _s("https://leg.mt.gov/bills/mca/title_0300/chapter_0140/part_0010/section_0030/0300-0140-0010-0030.html",
                   "30-14-103", "Mont. Code Ann. § 30-14-103"),
                _s("https://leg.mt.gov/bills/mca/title_0300/chapter_0140/part_0010/section_0330/0300-0140-0010-0330.html",
                   "30-14-133", "Mont. Code Ann. § 30-14-133"),
            ),
        ),
    ),
    # --- Nebraska — statutes.php per-section (blocked-here: timeout) ---------------
    "us-ne-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://nebraskalegislature.gov/laws/statutes.php?statute=59-1601",
                   "59-1601", "Neb. Rev. Stat. § 59-1601"),
                _s("https://nebraskalegislature.gov/laws/statutes.php?statute=59-1602",
                   "59-1602", "Neb. Rev. Stat. § 59-1602"),
                _s("https://nebraskalegislature.gov/laws/statutes.php?statute=87-302",
                   "87-302", "Neb. Rev. Stat. § 87-302"),
            ),
        ),
    ),
    # --- Nevada — official chapter page (blocked-here: 403) -------------------------
    "us-nv-udap": (
        StateStrategy(
            mode="chapter_html",
            url="https://www.leg.state.nv.us/NRS/NRS-598.html",
            split="nv-nrs-598",
            hint="598",
            citation="Nev. Rev. Stat. ch. 598",
        ),
    ),
    # --- New Hampshire — merged whole-chapter page (blocked-here: 403) --------------
    "us-nh-udap": (
        StateStrategy(
            mode="chapter_html",
            url="https://www.gencourt.state.nh.us/rsa/html/XXXI/358-A/358-A-mrg.htm",
            split="nh-358-a",
            hint="358-A",
            citation="N.H. Rev. Stat. ch. 358-A",
        ),
    ),
    # --- North Carolina — official per-section HTML (blocked-here: 403) -------------
    "us-nc-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_75/GS_75-1.html",
                   "75-1", "N.C. Gen. Stat. § 75-1"),
                _s("https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_75/GS_75-1.1.html",
                   "75-1.1", "N.C. Gen. Stat. § 75-1.1"),
                _s("https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_75/GS_75-16.html",
                   "75-16", "N.C. Gen. Stat. § 75-16"),
            ),
        ),
    ),
    # --- North Dakota — official chapter PDF (verified) ------------------------------
    "us-nd-udap": (
        StateStrategy(
            mode="chapter_pdf",
            url="https://ndlegis.gov/cencode/t51c15.pdf",
            split="nd-51-15",
            hint="51-15",
            citation="N.D. Cent. Code ch. 51-15",
        ),
    ),
    # --- Ohio — codes.ohio.gov per-section (blocked-here: timeout) --------------------
    "us-oh-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://codes.ohio.gov/ohio-revised-code/section-1345.01",
                   "1345.01", "Ohio Rev. Code § 1345.01"),
                _s("https://codes.ohio.gov/ohio-revised-code/section-1345.02",
                   "1345.02", "Ohio Rev. Code § 1345.02"),
                _s("https://codes.ohio.gov/ohio-revised-code/section-1345.03",
                   "1345.03", "Ohio Rev. Code § 1345.03"),
                _s("https://codes.ohio.gov/ohio-revised-code/section-1345.09",
                   "1345.09", "Ohio Rev. Code § 1345.09"),
            ),
        ),
    ),
    # --- Oregon — whole-chapter static page (blocked-here: timeout) -------------------
    "us-or-udap": (
        StateStrategy(
            mode="chapter_html",
            url="https://www.oregonlegislature.gov/bills_laws/ors/ors646.html",
            split="or-646",
            hint="646",
            citation="ORS ch. 646",
        ),
    ),
    # --- Pennsylvania — unconsolidated statutes viewer (blocked-here: timeout) --------
    "us-pa-udap": (
        StateStrategy(
            mode="chapter_html",
            url="https://www.legis.state.pa.us/cfdocs/legis/LI/uconsCheck.cfm?txtType=HTM&yr=1968&sessInd=0&smthLwInd=0&act=387",
            split="pa-utpcpl",
            hint="201",
            citation="73 P.S. §§ 201-1 — 201-9.3",
        ),
        StateStrategy(
            mode="chapter_html",
            url="https://www.legis.state.pa.us/cfdocs/legis/LI/uconsCheck.cfm?txtType=HTM&yr=1968&sessInd=0&smthLwInd=0&act=0387.",
            split="pa-utpcpl",
            hint="201",
            citation="73 P.S. §§ 201-1 — 201-9.3",
        ),
    ),
    # --- Rhode Island — static per-section pages (blocked-here: timeout) --------------
    "us-ri-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("http://webserver.rilegislature.gov/Statutes/TITLE6/6-13.1/6-13.1-1.htm",
                   "6-13.1-1", "R.I. Gen. Laws § 6-13.1-1"),
                _s("http://webserver.rilegislature.gov/Statutes/TITLE6/6-13.1/6-13.1-2.htm",
                   "6-13.1-2", "R.I. Gen. Laws § 6-13.1-2"),
                _s("http://webserver.rilegislature.gov/Statutes/TITLE6/6-13.1/6-13.1-12.htm",
                   "6-13.1-12", "R.I. Gen. Laws § 6-13.1-12"),
            ),
        ),
    ),
    # --- South Carolina — whole-chapter page (verified) --------------------------------
    "us-sc-udap": (
        StateStrategy(
            mode="chapter_html",
            url="https://www.scstatehouse.gov/code/t39c005.php",
            split="sc-39-5",
            hint="39-5",
            citation="S.C. Code ch. 39-5",
        ),
    ),
    # --- South Dakota — sdlegislature.gov statute API (verified) ------------------------
    "us-sd-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://sdlegislature.gov/api/Statutes/37-24-1.html",
                   "37-24-1", "S.D. Codified Laws § 37-24-1"),
                _s("https://sdlegislature.gov/api/Statutes/37-24-6.html",
                   "37-24-6", "S.D. Codified Laws § 37-24-6"),
                _s("https://sdlegislature.gov/api/Statutes/37-24-31.html",
                   "37-24-31", "S.D. Codified Laws § 37-24-31"),
            ),
        ),
    ),
    # --- Utah — xcode per-section pages (blocked-here: timeout) -------------------------
    "us-ut-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://le.utah.gov/xcode/Title13/Chapter11/13-11-S4.html",
                   "13-11-4", "Utah Code § 13-11-4"),
                _s("https://le.utah.gov/xcode/Title13/Chapter11/13-11-S5.html",
                   "13-11-5", "Utah Code § 13-11-5"),
                _s("https://le.utah.gov/xcode/Title13/Chapter11A/13-11a-S3.html",
                   "13-11a-3", "Utah Code § 13-11a-3"),
                _s("https://le.utah.gov/xcode/Title13/Chapter11A/13-11a-S4.html",
                   "13-11a-4", "Utah Code § 13-11a-4"),
            ),
        ),
    ),
    # --- Vermont — per-section pages (blocked-here: timeout) ----------------------------
    "us-vt-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://legislature.vermont.gov/statutes/section/09/063/02451",
                   "2451", "9 V.S.A. § 2451"),
                _s("https://legislature.vermont.gov/statutes/section/09/063/02453",
                   "2453", "9 V.S.A. § 2453"),
                _s("https://legislature.vermont.gov/statutes/section/09/063/02457",
                   "2457", "9 V.S.A. § 2457"),
                _s("https://legislature.vermont.gov/statutes/section/09/063/02461",
                   "2461", "9 V.S.A. § 2461"),
            ),
        ),
    ),
    # --- Virginia — per-section pages (verified) -----------------------------------------
    "us-va-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://law.lis.virginia.gov/vacode/59.1-196/",
                   "59.1-196", "Va. Code § 59.1-196"),
                _s("https://law.lis.virginia.gov/vacode/59.1-198/",
                   "59.1-198", "Va. Code § 59.1-198"),
                _s("https://law.lis.virginia.gov/vacode/59.1-200/",
                   "59.1-200", "Va. Code § 59.1-200"),
                _s("https://law.lis.virginia.gov/vacode/59.1-204/",
                   "59.1-204", "Va. Code § 59.1-204"),
            ),
        ),
    ),
    # --- Washington — official chapter PDF rendition (verified) --------------------------
    "us-wa-udap": (
        StateStrategy(
            mode="chapter_pdf",
            url="https://app.leg.wa.gov/RCW/default.aspx?cite=19.86&pdf=true",
            split="wa-19-86",
            hint="19.86",
            citation="RCW ch. 19.86",
        ),
        StateStrategy(
            mode="chapter_pdf",
            url="https://app.leg.wa.gov/RCW/default.aspx?cite=19.86.020&pdf=true",
            split="wa-19-86",
            hint="19.86.020",
            citation="RCW 19.86.020",
        ),
    ),
    # --- West Virginia — article page, else per-section (blocked-here: 403) ---------------
    "us-wv-udap": (
        StateStrategy(
            mode="chapter_html",
            url="https://code.wvlegislature.gov/46A-6/",
            split="wv-46a-6",
            hint="46A-6",
            citation="W. Va. Code art. 46A-6",
        ),
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://code.wvlegislature.gov/46A-6-102/",
                   "46A-6-102", "W. Va. Code § 46A-6-102"),
                _s("https://code.wvlegislature.gov/46A-6-104/",
                   "46A-6-104", "W. Va. Code § 46A-6-104"),
            ),
        ),
    ),
    # --- Wisconsin — docs.legis per-section pages (blocked-here: timeout) ------------------
    "us-wi-udap": (
        StateStrategy(
            mode="sections",
            pages=(
                _s("https://docs.legis.wisconsin.gov/statutes/statutes/100/18",
                   "100.18", "Wis. Stat. § 100.18"),
                _s("https://docs.legis.wisconsin.gov/statutes/statutes/100/195",
                   "100.195", "Wis. Stat. § 100.195"),
                _s("https://docs.legis.wisconsin.gov/statutes/statutes/100/20",
                   "100.20", "Wis. Stat. § 100.20"),
            ),
        ),
    ),
    # --- Wyoming — full-title official PDF (verified) --------------------------------------
    "us-wy-udap": (
        StateStrategy(
            mode="chapter_pdf",
            url="https://wyoleg.gov/statutes/compress/title40.pdf",
            split="wy-40-12",
            hint="40-12",
            citation="Wyo. Stat. tit. 40, ch. 12",
        ),
    ),
    # --- California DFPI CCFPL (state UDAAP) — Fin. Code div. 24 via leginfo (verified) ----
    "us-ca-dfpi-ccfpl": (
        StateStrategy(
            mode="sections",
            pages=(
                _s(_CA_SECTION_URL.format(code="FIN", num="90001"),
                   "fin-90001", "Cal. Fin. Code § 90001"),
                _s(_CA_SECTION_URL.format(code="FIN", num="90002"),
                   "fin-90002", "Cal. Fin. Code § 90002"),
                _s(_CA_SECTION_URL.format(code="FIN", num="90003"),
                   "fin-90003", "Cal. Fin. Code § 90003"),
                _s(_CA_SECTION_URL.format(code="FIN", num="90005"),
                   "fin-90005", "Cal. Fin. Code § 90005"),
                _s(_CA_SECTION_URL.format(code="FIN", num="90009"),
                   "fin-90009", "Cal. Fin. Code § 90009"),
            ),
        ),
    ),
}


# Jurisdictions with at least one fetch path (custom or registry). States
# whose only source is a MANUAL_STUB (AL, AK, AR, GA, IN, LA, MS, NM, OK,
# TN, NJ) are deliberately absent.
IMPLEMENTED_JURISDICTIONS: set[str] = {
    "US-CA", "US-NY", "US-TX", "US-FL", "US-IL", "US-MA",
} | {
    "US-" + source_id.split("-")[1].upper()
    for source_id in STATE_STRATEGIES
}


class StateFetcher:
    """Fetcher for state_html sources; dispatches on spec.id."""

    def fetch(self, spec: SourceSpec) -> list[FetchResult]:
        logger.info("fetching state source %s (%s)", spec.id, spec.jurisdiction)
        try:
            results = self._dispatch(spec)
        except FetchError:
            raise
        except Exception as e:  # defensive: contract is FetchError only
            raise FetchError(
                f"state fetch failed for {spec.id}: {e}",
                source_id=spec.id,
                url=spec.url,
            ) from e
        logger.info("fetched %d page(s) for %s", len(results), spec.id)
        return results

    def _dispatch(self, spec: SourceSpec) -> list[FetchResult]:
        custom = _CUSTOM_FETCHERS.get(spec.id)
        if custom is not None:
            return custom(spec)

        strategies = STATE_STRATEGIES.get(spec.id)
        if not strategies:
            raise FetchError(
                f"no scraper implemented yet for {spec.id} ({spec.jurisdiction})",
                source_id=spec.id,
                url=spec.url,
            )

        failures: list[str] = []
        for i, strategy in enumerate(strategies):
            if i:
                time.sleep(_POLITENESS_DELAY_SECONDS)
            try:
                results = _run_strategy(spec, strategy)
                if results:
                    if i:
                        logger.info(
                            "%s: strategy %d/%d (%s) succeeded after earlier failures",
                            spec.id, i + 1, len(strategies), strategy.mode,
                        )
                    return results
            except FetchError as e:
                failures.append(f"[{strategy.mode}] {e}")
                logger.warning(
                    "strategy %d/%d (%s) failed for %s: %s",
                    i + 1, len(strategies), strategy.mode, spec.id, e,
                )
        raise FetchError(
            f"all {len(strategies)} strategies failed for {spec.id}: "
            + " | ".join(failures),
            source_id=spec.id,
            url=spec.url,
        )
