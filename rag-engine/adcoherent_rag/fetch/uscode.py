"""Fetcher for U.S. Code sections on uscode.house.gov (OLRC "prelim" pages).

The manifest URL carries a granuleid of the form
``granuleid:USC-prelim-title{T}-section{S}``. A single source may cover
several sections (e.g. "12 U.S.C. §§ 5531, 5536"); the extra sections are
parsed out of the citation and fetched by substituting the section number in
the granuleid URL. One FetchResult is returned per section.

uscode.house.gov aggressively throttles/blocks some networks, so each
section falls back to the govinfo USCODE annual-edition HTML via the link
service (``/link/uscode/{title}/{section}?link-type=html&year=mostrecent``)
— same official text, one edition older than OLRC prelim at worst. The
fallback result carries ``meta["uscode_source"] = "govinfo-annual"``.
"""

from __future__ import annotations

import logging
import re
import time

from ..models import FetchResult, SourceSpec
from . import http
from .base import FetchError

logger = logging.getLogger(__name__)

# granuleid:USC-prelim-title15-section45 -> title=15, section=45
_GRANULE_RE = re.compile(
    r"granuleid:USC-prelim-title(?P<title>\d+)-section(?P<section>[0-9A-Za-z\-]+)",
    re.IGNORECASE,
)

# Parenthetical asides in citations ("(Dodd-Frank §§ 1031, 1036)") must not
# contribute section numbers.
_PAREN_RE = re.compile(r"\([^)]*\)")

# "12 U.S.C. §§ 5531, 5536" / "15 U.S.C. § 45" / "... §§ 5531 and 5536"
_USC_LIST_RE = re.compile(
    r"U\.?\s*S\.?\s*C\.?\s*§*\s*"
    r"(?P<body>\d[0-9A-Za-z\-]*(?:\s*(?:,\s*(?:and\s+)?|\band\b\s*|&\s*)\d[0-9A-Za-z\-]*)*)",
    re.IGNORECASE,
)
_SECTION_TOKEN_RE = re.compile(r"^\d[0-9A-Za-z\-]*$")

# Politeness delay between successive requests to uscode.house.gov.
_REQUEST_DELAY_SECONDS = 0.5


def _sections_from_citation(citation: str | None) -> list[str]:
    """Section numbers listed in a U.S.C. citation, in document order."""
    if not citation:
        return []
    cleaned = _PAREN_RE.sub(" ", citation)
    m = _USC_LIST_RE.search(cleaned)
    if not m:
        return []
    sections: list[str] = []
    for token in re.split(r",|\band\b|&", m.group("body")):
        token = token.strip()
        if token and _SECTION_TOKEN_RE.match(token) and token not in sections:
            sections.append(token)
    return sections


class UscodeHtmlFetcher:
    """Fetches every U.S.C. section a source resolves to, one result each."""

    def fetch(self, spec: SourceSpec) -> list[FetchResult]:
        try:
            return self._fetch(spec)
        except FetchError:
            raise
        except Exception as e:  # never let bare exceptions escape a fetcher
            raise FetchError(
                f"uscode fetch failed for {spec.id}: {e}", source_id=spec.id, url=spec.url
            ) from e

    def _fetch(self, spec: SourceSpec) -> list[FetchResult]:
        m = _GRANULE_RE.search(spec.url)
        if not m:
            raise FetchError(
                f"cannot parse USC granuleid from url: {spec.url!r}",
                source_id=spec.id,
                url=spec.url,
            )
        title = int(m.group("title"))
        primary_section = m.group("section")

        sections = [primary_section]
        for extra in _sections_from_citation(spec.citation):
            if extra not in sections:
                sections.append(extra)
        logger.info(
            "fetching %d U.S.C. section(s) for %s: title %d, sections %s",
            len(sections), spec.id, title, ", ".join(sections),
        )

        results: list[FetchResult] = []
        for i, section in enumerate(sections):
            # Substitute the section number inside the granuleid, keeping the
            # rest of the URL (query params etc.) intact.
            url = spec.url[: m.start("section")] + section + spec.url[m.end("section"):]
            if i > 0:
                time.sleep(_REQUEST_DELAY_SECONDS)
            try:
                result = http.fetch_url(
                    spec.id,
                    url,
                    kind="uscode_html",
                    extra_meta={"usc_title": title, "usc_section": section},
                )
            except FetchError as primary_err:
                result = self._fetch_govinfo_fallback(
                    spec, title=title, section=section, primary_err=primary_err
                )
                if result is None:
                    if section == primary_section:
                        raise  # the manifest's own URL failing is fatal
                    logger.warning(
                        "skipping extra U.S.C. section %s for %s (fetch failed: %s)",
                        section, spec.id, url,
                    )
                    continue
            results.append(result)

        if not results:
            raise FetchError(
                f"no U.S.C. sections could be fetched for {spec.id}",
                source_id=spec.id,
                url=spec.url,
            )
        return results

    def _fetch_govinfo_fallback(
        self,
        spec: SourceSpec,
        *,
        title: int,
        section: str,
        primary_err: FetchError,
    ) -> FetchResult | None:
        """Official govinfo USCODE annual-edition HTML via the link service."""
        url = (
            f"https://www.govinfo.gov/link/uscode/{title}/{section}"
            "?link-type=html&year=mostrecent"
        )
        logger.warning(
            "uscode.house.gov failed for %s §%s (%s); trying govinfo annual edition",
            spec.id, section, primary_err,
        )
        try:
            result = http.fetch_url(
                spec.id,
                url,
                kind="uscode_html",
                extra_meta={
                    "usc_title": title,
                    "usc_section": section,
                    "uscode_source": "govinfo-annual",
                },
            )
        except FetchError as e:
            logger.warning("govinfo uscode fallback also failed for §%s: %s", section, e)
            return None
        if not result.content.strip():
            return None
        return result
