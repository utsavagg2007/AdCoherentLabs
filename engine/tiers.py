"""Product-tier plumbing for the connected engine.

The five product tiers (pricing plans) drive two independent choices:

  * which LLM reviews the ad (Layer 3) — defined once in
    ``adcoherent_rag.review.tiers.TIERS`` and re-exported here;
  * which OCR backend normalizes image ads (Layer 1) — the CV layer's
    own tier knob ("free" = local PaddleOCR-preferred, "paid" = Google
    Vision with local fallback).

Per the current product decision, EVERY product tier runs the local
PaddleOCR path for now (the OCR will be swapped after production).
Flipping a tier to a paid/cloud OCR later is a one-line change in
``OCR_TIER_BY_PRODUCT_TIER`` — nothing else in the engine moves.
"""

from __future__ import annotations

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

from adcoherent_rag.review.tiers import TIERS, TierConfig, get_tier

PRODUCT_TIERS: tuple[str, ...] = ("free", "hobby", "pro", "design", "enterprise")

# Layer-1 OCR routing. "free" = local OCR (PaddleOCR preferred, per
# cv.ocr.BACKEND_PREFERENCE); "paid" = Google Vision (falls back to
# local on any failure). PaddleOCR everywhere for now, by design.
OCR_TIER_BY_PRODUCT_TIER: dict[str, str] = {
    "free": "free",
    "hobby": "free",
    "pro": "free",
    "design": "free",
    "enterprise": "free",
}


def normalize_tier(name: str) -> str:
    """Validate and canonicalize a product-tier name."""
    tier = (name or "").strip().lower()
    if tier not in PRODUCT_TIERS:
        raise ValueError(
            f"unknown product tier {name!r}; expected one of {list(PRODUCT_TIERS)}"
        )
    return tier


def ocr_tier_for(product_tier: str) -> str:
    """Layer-1 OCR tier for a product tier (PaddleOCR everywhere for now)."""
    return OCR_TIER_BY_PRODUCT_TIER[normalize_tier(product_tier)]


__all__ = [
    "PRODUCT_TIERS",
    "OCR_TIER_BY_PRODUCT_TIER",
    "TIERS",
    "TierConfig",
    "get_tier",
    "normalize_tier",
    "ocr_tier_for",
]
