"""Runtime configuration: .env-backed settings for the pipeline.

Loads ``.env`` from the repo root at import time (a safe no-op when the
file is absent) and exposes cached :func:`get_settings`. Configuration
problems NEVER raise: the pipeline must always be able to start and run
on the free OCR tier, so a paid-tier misconfiguration produces one
clear startup warning naming exactly what is missing, then degrades.

Usage:
    from config import get_settings
    tier = get_settings().ocr_tier
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()  # reads .env if present; no-op otherwise

_log = logging.getLogger("config")

_VALID_TIERS = ("free", "paid")


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings (build via :func:`get_settings`)."""

    ocr_tier: str
    google_credentials_path: str | None

    @property
    def google_vision_enabled(self) -> bool:
        """True only when the paid tier could actually serve: credentials
        are configured AND the Vision SDK imports. Uses cv.ocr's own
        detection logic (same env var, same import) — never duplicated.
        """
        return not self._vision_problems()

    def _vision_problems(self) -> list[str]:
        """Everything standing between this config and a Vision call."""
        from cv.ocr import vision_import_error

        problems = []
        if not self.google_credentials_path:
            problems.append(
                "GOOGLE_APPLICATION_CREDENTIALS is not set (point it at a "
                "service-account JSON key file)")
        elif not os.path.isfile(self.google_credentials_path):
            problems.append(
                f"credentials file is unreadable: "
                f"{self.google_credentials_path!r} does not exist or is "
                "not a file")
        import_err = vision_import_error()
        if import_err is not None:
            problems.append(
                "google-cloud-vision package is not installed "
                f"({import_err}); pip install google-cloud-vision")
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once; validate and warn (never raise)."""
    tier = (os.environ.get("OCR_TIER") or "free").strip().lower()
    if tier not in _VALID_TIERS:
        _log.warning(
            "OCR_TIER=%r is not one of %s; running on the free tier",
            tier, _VALID_TIERS)
        tier = "free"

    settings = Settings(
        ocr_tier=tier,
        google_credentials_path=os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS") or None,
    )

    # Paid tier requested but not servable: one clear warning naming each
    # missing piece; the pipeline still starts and every OCR call falls
    # back to the free tier (cv.ocr.run_ocr degrades per call).
    if settings.ocr_tier == "paid" and not settings.google_vision_enabled:
        _log.warning(
            "OCR_TIER=paid but Google Vision is not available — %s. "
            "Continuing on the free tier fallback (local OCR).",
            "; ".join(settings._vision_problems()))
    return settings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    s = get_settings()
    print(f"ocr_tier={s.ocr_tier!r}")
    print(f"google_credentials_path={s.google_credentials_path!r}")
    print(f"google_vision_enabled={s.google_vision_enabled}")
