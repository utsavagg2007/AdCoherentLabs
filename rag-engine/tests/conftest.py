"""Test bootstrap: fake embeddings, no network, no DB, no torch."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["EMBEDDING_FAKE"] = "1"  # must be set before the package imports

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from adcoherent_rag.models import FetchResult, SourceSpec  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def make_spec():
    def _make(**overrides) -> SourceSpec:
        defaults = dict(
            id="test-source",
            tier=1,
            category="federal_regulation",
            jurisdiction="US",
            authority="FTC",
            citation="16 CFR Part 255",
            name="Test Source",
            url="https://example.gov/doc",
            format="html",
            ingestion="html_scrape",
            topics=("testing",),
        )
        defaults.update(overrides)
        return SourceSpec(**defaults)

    return _make


@pytest.fixture
def make_fetch_result():
    def _make(content: bytes, **overrides) -> FetchResult:
        defaults = dict(
            source_id="test-source",
            requested_url="https://example.gov/doc",
            resolved_url="https://example.gov/doc",
            content=content,
            content_type="text/html",
            http_status=200,
            fetched_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            meta={"kind": "generic_html"},
        )
        defaults.update(overrides)
        return FetchResult(**defaults)

    return _make
