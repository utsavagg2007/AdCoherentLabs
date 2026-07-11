"""eCFR fetcher: point-in-time full XML plus per-section amendment dates.

Uses the eCFR versioner API (https://www.ecfr.gov/developers/documentation):

1. ``titles.json`` resolves the latest point-in-time date for the CFR title.
2. ``full/{date}/title-{T}.xml?part={P}`` returns the authoritative XML
   (section-scoped when the manifest citation names a single section).
3. ``versions/title-{T}.json`` provides per-section ``amendment_date``s used
   by the pipeline as ``effective_start`` for versioned storage.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from ..manifest import parse_cfr_citation
from ..models import FetchResult, SourceSpec
from . import http
from .base import FetchError

logger = logging.getLogger(__name__)

_API_BASE = "https://www.ecfr.gov/api/versioner/v1"
_TITLES_URL = f"{_API_BASE}/titles.json"

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_JSON_HEADERS = {"Accept": "application/json"}
_XML_HEADERS = {"Accept": "application/xml"}


class EcfrFetcher:
    """Fetches one CFR part (or single section) as point-in-time eCFR XML."""

    def fetch(self, spec: SourceSpec) -> list[FetchResult]:
        try:
            return self._fetch(spec)
        except FetchError:
            raise
        except Exception as exc:  # contract: never let bare exceptions escape
            raise FetchError(
                f"unexpected error fetching eCFR source {spec.id}: {exc}",
                source_id=spec.id,
                url=spec.url,
            ) from exc

    # ------------------------------------------------------------------
    # internals

    def _fetch(self, spec: SourceSpec) -> list[FetchResult]:
        if not spec.citation:
            raise FetchError(
                f"source {spec.id} has no CFR citation to resolve", source_id=spec.id
            )
        try:
            title, part, section = parse_cfr_citation(spec.citation)
        except ValueError as exc:
            raise FetchError(
                f"cannot parse CFR citation for {spec.id}: {exc}", source_id=spec.id
            ) from exc

        date = self._resolve_point_in_time(title, source_id=spec.id)
        result = self._fetch_full_xml(
            spec, title=title, part=part, section=section, date=date
        )
        amend_dates = self._fetch_section_amend_dates(
            title=title, part=part, date=date, source_id=spec.id
        )
        result.meta["section_amend_dates"] = amend_dates
        logger.info(
            "fetched eCFR XML for %s (title %s part %s, as of %s, %d bytes, "
            "%d section amendment dates)",
            spec.id,
            title,
            part,
            date,
            len(result.content),
            len(amend_dates),
        )
        return [result]

    def _resolve_point_in_time(self, title: int, *, source_id: str) -> str:
        """Latest ``up_to_date_as_of`` for the title; today's date as fallback."""
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            resp = http.get(_TITLES_URL, headers=_JSON_HEADERS, source_id=source_id)
            payload = json.loads(resp.content)
            for entry in payload.get("titles", []):
                if not isinstance(entry, dict):
                    continue
                try:
                    number = int(entry.get("number", -1))
                except (TypeError, ValueError):
                    continue
                if number != title:
                    continue
                as_of = entry.get("up_to_date_as_of") or ""
                if isinstance(as_of, str) and _ISO_DATE_RE.fullmatch(as_of):
                    return as_of
                break
            logger.warning(
                "eCFR titles.json has no usable up_to_date_as_of for title %s; "
                "falling back to today (%s)",
                title,
                today,
            )
        except FetchError as exc:
            logger.warning(
                "could not fetch eCFR titles.json (%s); falling back to today (%s)",
                exc,
                today,
            )
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "malformed eCFR titles.json (%s); falling back to today (%s)",
                exc,
                today,
            )
        return today

    def _fetch_full_xml(
        self,
        spec: SourceSpec,
        *,
        title: int,
        part: int,
        section: str | None,
        date: str,
    ) -> FetchResult:
        part_url = f"{_API_BASE}/full/{date}/title-{title}.xml?part={part}"
        extra_meta: dict[str, Any] = {
            "ecfr_date": date,
            "cfr_title": title,
            "cfr_part": part,
        }

        if section:
            # The API expects the full section identifier (part.section),
            # e.g. section=1030.8 or section=275.206(4)-1 (URL-encoded).
            section_id = f"{part}.{section}"
            scoped_url = f"{part_url}&section={quote(section_id, safe='')}"
            try:
                result = http.fetch_url(
                    spec.id,
                    scoped_url,
                    kind="ecfr_xml",
                    extra_meta=extra_meta,
                    headers=_XML_HEADERS,
                )
                if result.content.strip():
                    return result
                logger.warning(
                    "empty section-scoped eCFR response for %s (%s); "
                    "falling back to whole part %s",
                    spec.id,
                    section_id,
                    part,
                )
            except FetchError as exc:
                logger.warning(
                    "section-scoped eCFR request failed for %s (%s); "
                    "falling back to whole part %s",
                    spec.id,
                    exc,
                    part,
                )

        result = http.fetch_url(
            spec.id,
            part_url,
            kind="ecfr_xml",
            extra_meta=extra_meta,
            headers=_XML_HEADERS,
        )
        if not result.content.strip():
            raise FetchError(
                f"empty eCFR XML response for title {title} part {part}",
                source_id=spec.id,
                url=part_url,
            )
        return result

    def _fetch_section_amend_dates(
        self, *, title: int, part: int, date: str, source_id: str
    ) -> dict[str, str]:
        """Map section identifier ("1030.8") -> latest amendment date.

        Non-fatal: any failure logs a warning and returns {} — the pipeline
        then falls back to the fetch date for effective_start.
        """
        # The versions feed is paginated when unfiltered; the part= filter
        # keeps the response complete and small (verified against the API).
        url = f"{_API_BASE}/versions/title-{title}.json?part={part}"
        try:
            resp = http.get(url, headers=_JSON_HEADERS, source_id=source_id)
            payload = json.loads(resp.content)
            versions = payload.get("content_versions") or []
            meta = payload.get("meta") or {}
            try:
                result_count = int(meta.get("result_count", len(versions)))
            except (TypeError, ValueError):
                result_count = len(versions)
            if result_count > len(versions):
                logger.warning(
                    "eCFR versions feed for title %s part %s is truncated "
                    "(%d of %d entries); missing sections fall back to the "
                    "fetch date for effective_start",
                    title, part, len(versions), result_count,
                )
            part_str = str(part)
            latest: dict[str, str] = {}
            for entry in versions:
                if not isinstance(entry, dict):
                    continue
                identifier = str(entry.get("identifier") or "").strip()
                entry_part = str(entry.get("part") or "").strip()
                if entry_part != part_str and not identifier.startswith(f"{part_str}."):
                    continue
                amend = entry.get("amendment_date")
                if (
                    not identifier
                    or not isinstance(amend, str)
                    or not _ISO_DATE_RE.fullmatch(amend)
                ):
                    continue
                # ISO dates compare correctly as strings; keep the latest.
                if identifier not in latest or amend > latest[identifier]:
                    latest[identifier] = amend
            return latest
        except FetchError as exc:
            logger.warning(
                "eCFR versions feed unavailable for title %s part %s (%s); "
                "continuing without section amendment dates",
                title,
                part,
                exc,
            )
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "malformed eCFR versions feed for title %s part %s (%s); "
                "continuing without section amendment dates",
                title,
                part,
                exc,
            )
        return {}
