"""Normalizer contract: raw fetched bytes -> canonical SectionUnits."""

from __future__ import annotations

from typing import Protocol

from ..models import FetchResult, SectionUnit, SourceSpec


class NormalizeError(RuntimeError):
    """Raised when fetched content cannot be parsed into section units."""

    def __init__(self, message: str, *, source_id: str | None = None):
        super().__init__(message)
        self.source_id = source_id


class Normalizer(Protocol):
    def normalize(self, fetched: FetchResult, spec: SourceSpec) -> list[SectionUnit]:
        """Parse one FetchResult into canonical section units.

        Must raise NormalizeError (not bare exceptions) on failure."""
        ...
