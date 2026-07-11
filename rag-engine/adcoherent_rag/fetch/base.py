"""Fetcher contract: a fetcher turns a SourceSpec into raw FetchResults."""

from __future__ import annotations

from typing import Protocol

from ..models import FetchResult, SourceSpec


class FetchError(RuntimeError):
    """Raised when a source cannot be fetched. The pipeline records it as an
    error event for that source and continues with the rest."""

    def __init__(self, message: str, *, source_id: str | None = None, url: str | None = None):
        super().__init__(message)
        self.source_id = source_id
        self.url = url


class Fetcher(Protocol):
    def fetch(self, spec: SourceSpec) -> list[FetchResult]:
        """Fetch every document this source resolves to.

        Must raise FetchError (not bare exceptions) on failure. May return
        several results, e.g. one per statute section page."""
        ...
