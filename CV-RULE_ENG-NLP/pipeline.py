"""End-to-end asset analysis: raw asset -> schema.AssetRepresentation.

Wires the deterministic layers together:

    image  -> cv.ocr.run_ocr -> nlp.normalize.segment_text(ocr_lines=)
              + cv.measure / cv.markers for cv_findings
    text   -> nlp.normalize.segment_text(text=)
    html   -> nlp.normalize.segment_text(html=)
    then   -> nlp.entities.extract_entities
           -> nlp.claims.detect_claims
           -> nlp.routing.route
           -> AssetRepresentation (validated, provenance-stamped)

Structurer, not judge: the output is candidates and measurements for
the rule engine, never a compliance verdict.
"""

from __future__ import annotations

import schema
from cv.markers import has_footnote_marker, has_marker
from cv.measure import estimate_region_contrast, proximity
from cv.ocr import run_ocr
from nlp.claims import detect_claims
from nlp.entities import extract_entities
from nlp.normalize import segment_text
from nlp.routing import SEMANTIC_FALLBACK_MARKER, route
from version import make_provenance

_DISCLOSURE_ROLES = {"disclosure", "fine_print", "legal"}


def _bbox_tuple(seg: dict):
    b = seg.get("bbox")
    return (b["x"], b["y"], b["width"], b["height"]) if b else None


def _read_image(path: str):
    """Load a BGR image array, or None if it can't be read (never raises)."""
    try:
        import cv2

        return cv2.imread(path)
    except Exception:  # noqa: BLE001 — contrast is best-effort, degrade quietly
        return None


def _cv_findings(segments: list[dict], claims: list[dict],
                 seg_images: dict | None = None) -> list[dict]:
    """Visual measurements over OCR-built segments. Numbers only."""
    findings: list[dict] = []
    seg_images = seg_images or {}

    # Marker presence is reported only where a marker actually occurs —
    # sponsorship wording (#ad / sponsored / paid partnership) or a
    # leading asterisk/dagger footnote. Emitting one finding per segment
    # (present or not) floods the metric with absence rows the gold labels
    # never carry.
    for seg in segments:
        text = seg["text"]
        if has_marker(text):
            method = "regex_marker_v1"
        elif has_footnote_marker(text):
            method = "asterisk_footnote_detector"
        else:
            continue
        findings.append({
            "finding_id": f"cvf_marker_{seg['segment_id']}",
            "measurement": "marker_presence",
            "value": 1.0,
            "segment_id": seg["segment_id"],
            "related_segment_id": None,
            "method": method,
        })

    # Rendered text height (bbox is normalized, so height% = h * 100).
    for seg in segments:
        box = _bbox_tuple(seg)
        if box:
            findings.append({
                "finding_id": f"cvf_height_{seg['segment_id']}",
                "measurement": "text_height_percent",
                "value": box[3] * 100.0,
                "segment_id": seg["segment_id"],
                "related_segment_id": None,
                "method": "ocr_bbox_height",
            })

    # Text/background contrast, estimated from the rendered pixels behind
    # each segment's box. Best-effort (see estimate_region_contrast) and
    # only when the source image is available; emits nothing otherwise.
    for seg in segments:
        img = seg_images.get(seg["segment_id"])
        box = _bbox_tuple(seg)
        if img is None or not box:
            continue
        ratio = estimate_region_contrast(img, box)
        if ratio is not None:
            findings.append({
                "finding_id": f"cvf_contrast_{seg['segment_id']}",
                "measurement": "contrast_ratio",
                "value": ratio,
                "segment_id": seg["segment_id"],
                "related_segment_id": None,
                "method": "wcag2_otsu_estimate",
            })

    # Claim-to-disclosure distance for every (claim seg, disclosure seg)
    # pair that has boxes. The rule engine decides what "too far" means.
    claim_seg_ids = {c["segment_id"] for c in claims}
    by_id = {s["segment_id"]: s for s in segments}
    disclosures = [s for s in segments if s["role"] in _DISCLOSURE_ROLES]
    n = 0
    for claim_id in sorted(claim_seg_ids):
        claim_box = _bbox_tuple(by_id[claim_id])
        if not claim_box:
            continue
        for disc in disclosures:
            disc_box = _bbox_tuple(disc)
            if not disc_box or disc["segment_id"] == claim_id:
                continue
            n += 1
            findings.append({
                "finding_id": f"cvf_prox_{n}",
                "measurement": "disclosure_proximity",
                "value": proximity(claim_box, disc_box),
                "segment_id": claim_id,
                "related_segment_id": disc["segment_id"],
                "method": "bbox_center_euclidean",
            })
    return findings


def analyze_asset(asset_id: str, *, image_path: str | list[str] = None,
                  text: str = None, html: str = None,
                  tier: str | None = None,
                  target_jurisdictions: list[str] | None = None
                  ) -> schema.AssetRepresentation:
    """Analyze one asset from exactly one source (image > text > html).

    ``image_path`` may be a single path or a list of paths (carousel
    ads: one image per card). Each card is OCR'd and segmented in its
    own coordinate space — cards overlap in normalized coordinates, so
    a shared space would let the block-merge pass stitch lines across
    cards. Carousel segment ids encode the card: seg_c<card>_<n>.

    ``tier`` selects the OCR provider for image assets: "free" (local,
    no credentials needed) or "paid" (Google Vision, adds
    semantic_signals; falls back to local on any failure). ``None``
    (default) resolves to ``config.get_settings().ocr_tier`` — the
    OCR_TIER environment/.env setting, "free" when unconfigured — so
    callers can still override per call. Non-image assets never perform
    OCR, so tier has no effect on them.

    ``target_jurisdictions`` is user-supplied targeting ("US" or
    "US-XX" state codes) passed through verbatim — where an ad runs
    cannot be extracted from the creative. None/empty means
    unspecified, and state-law checks downstream will not run.
    """
    if tier is None:
        from config import get_settings
        tier = get_settings().ocr_tier

    cv_findings: list[dict] = []
    semantic_signals: list[dict] = []
    seg_images: dict = {}
    ocr_backend: str | None = None
    if image_path is not None:
        paths = [image_path] if isinstance(image_path, str) else list(image_path)
        segments = []
        for card, p in enumerate(paths, start=1):
            lines, signals, card_backend = run_ocr(p, tier=tier)
            semantic_signals += signals
            # Name the engine that transcribed this asset — OCR accuracy
            # floors differ by backend (cv.ocr.MEASURED_FLOORS), so the
            # provenance must say which one produced these segments. The
            # value comes from THIS call's return, never shared state, so
            # concurrent analyze_asset calls cannot cross-contaminate.
            ocr_backend = card_backend or ocr_backend
            card_segments = segment_text(ocr_lines=lines)
            if len(paths) > 1:
                for seg in card_segments:
                    seg["segment_id"] = f"seg_c{card}_{seg['segment_id'][4:]}"
            card_img = _read_image(p)
            if card_img is not None:
                for seg in card_segments:
                    seg_images[seg["segment_id"]] = card_img
            segments += card_segments
        source = "ocr"
    else:
        segments = segment_text(text=text, html=html)
        source = "html" if html is not None else "text"

    # Graceful degradation: a blank/unreadable image (or empty text/html)
    # yields no segments, but AssetRepresentation requires at least one
    # (it is the addressing base for every other list). Emit a single
    # empty placeholder so the asset validates and flows through as
    # "nothing extracted" instead of raising a ValidationError.
    if not segments:
        segments = [{
            "segment_id": "seg_1", "text": "", "role": "unknown",
            "source": source, "bbox": None, "ocr_confidence": None,
        }]

    entities = extract_entities(segments)
    claims = detect_claims(segments, entities)
    routing = route(segments, entities,
                    target_jurisdictions=target_jurisdictions,
                    semantic_signals=semantic_signals)
    if image_path is not None:
        cv_findings = _cv_findings(segments, claims, seg_images)

    # Provenance must name the embedding model whenever a semantic
    # fallback (routing or claims) contributed to this output.
    embedding_version = None
    if SEMANTIC_FALLBACK_MARKER in routing["signal"] or any(
        str(c.get("pattern_id") or "").startswith("sem_") for c in claims
    ):
        from nlp.embeddings import get_embedding_model_version

        embedding_version = get_embedding_model_version()

    return schema.AssetRepresentation.model_validate({
        "asset_id": asset_id,
        "segments": segments,
        "entities": entities,
        "claim_candidates": claims,
        "cv_findings": cv_findings,
        "semantic_signals": semantic_signals,
        "routing": routing,
        "target_jurisdictions": target_jurisdictions or [],
        "provenance": make_provenance(embedding_model_version=embedding_version,
                                      ocr_backend=ocr_backend),
    })


if __name__ == "__main__":
    rep = analyze_asset("test", text="Get 5.99% APR, guaranteed approval!")
    print(rep.model_dump_json(indent=2))
