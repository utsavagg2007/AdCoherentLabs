"""Fetcher for FINRA rulebook pages (finra.org/rules-guidance/rulebooks).

There is no canonical government PDF for FINRA rules; the rulebook page is
authoritative per the manifest. The page is fetched with browser-like headers
because finra.org occasionally rejects bare programmatic clients.
"""

from __future__ import annotations

import logging
import re

from ..models import FetchResult, SourceSpec
from . import http
from .base import FetchError

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# .../rulebooks/finra-rules/2210 -> "2210"
_RULE_NUMBER_RE = re.compile(r"/finra-rules/(\d+[a-z]?)/?$", re.IGNORECASE)


class FinraFetcher:
    """Fetches one FINRA rulebook page as HTML."""

    def fetch(self, spec: SourceSpec) -> list[FetchResult]:
        m = _RULE_NUMBER_RE.search(spec.url)
        rule_number = m.group(1) if m else "unknown"
        try:
            result = http.fetch_url(
                spec.id,
                spec.url,
                kind="finra_html",
                extra_meta={"rule_number": rule_number},
                headers=_BROWSER_HEADERS,
            )
        except FetchError as e:
            raise FetchError(
                f"FINRA rulebook page rejected the request ({e}); the page may "
                "require a browser session — consider a manual snapshot",
                source_id=spec.id,
                url=spec.url,
            ) from e
        except Exception as e:  # never let bare exceptions escape a fetcher
            raise FetchError(
                f"unexpected error fetching FINRA rule page: {e}",
                source_id=spec.id,
                url=spec.url,
            ) from e

        if len(result.content) < 2000:
            raise FetchError(
                f"FINRA rule page response suspiciously small "
                f"({len(result.content)} bytes) — likely a block page",
                source_id=spec.id,
                url=spec.url,
            )
        logger.info(
            "fetched FINRA rule %s (%d bytes)", rule_number, len(result.content)
        )
        return [result]
