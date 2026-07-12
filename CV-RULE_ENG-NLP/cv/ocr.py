"""Tiered OCR provider for the CV layer.

Two tiers behind one dispatcher:

  * free (default) — local OCR: PaddleOCR (preferred) or pytesseract
    (fallback), no API cost. ``run_ocr_local``.
  * paid — Google Cloud Vision: better OCR accuracy plus semantic
    signals (labels, logos, web entities) useful for ad-regtech
    classification. ``run_ocr_google_vision``. Falls back to the free
    tier on any failure (missing credentials, quota, network).

``run_ocr(image_path, tier=...)`` returns ``(lines, semantic_signals,
backend)`` where lines are ``OcrLine``, semantic_signals are
``schema.SemanticSignal``-shaped dicts (always [] on the free tier),
and backend names the engine that served this call.
Boxes are normalized to [0, 1] with origin top-left so they can feed
``schema.BoundingBox`` directly. This layer only transcribes and
reports service signals — segmentation into roles and any compliance
interpretation happen downstream.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

# PaddleX phones home to pick a model mirror unless told not to; models
# are cached under ~/.paddlex after first download.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

_log = logging.getLogger("cv.ocr")

# Local backend preference order, first available wins. PaddleOCR is
# preferred because of measured fidelity on REAL ad screenshots, where
# the two backends differ sharply; on clean rendered banners both are
# near-perfect, so the real-screenshot numbers are the deciding floor.
BACKEND_PREFERENCE = ("paddle", "tesseract")

# Measured floors per backend — synth.backend_eval (clean renders,
# n=20 seed=7) + synth.ocr_eval --source gold (real screenshots, n=5),
# PaddleOCR 3.x PP-OCRv6 / tesseract 5.3.4, 2026-07-12. Downstream
# extraction cannot recover text OCR destroyed, so no accuracy claim
# for OCR-sourced assets may exceed the active backend's floor.
MEASURED_FLOORS = {
    "paddle": {"clean_render_cer": 0.001, "entity_survival": 0.98,
               "real_word_recall": 0.994, "real_char_sim": 0.67},
    "tesseract": {"clean_render_cer": 0.000, "entity_survival": 1.00,
                  "real_word_recall": 0.613, "real_char_sim": 0.415},
}


@dataclass(frozen=True)
class OcrLine:
    text: str
    box: tuple[float, float, float, float]  # (x, y, w, h) normalized 0-1
    confidence: float  # 0-1


_engine = None  # ("paddle", pipeline) | ("tesseract", pytesseract module)


def _init_paddle():
    from paddleocr import PaddleOCR

    # PaddleOCR 3.x replaced use_gpu=False with device="cpu".
    # enable_mkldnn=False works around a paddlepaddle-3.3 oneDNN bug
    # (NotImplementedError in ConvertPirAttribute2RuntimeAttribute).
    pipeline = PaddleOCR(
        device="cpu",
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    # Warm-up on a blank image: init can succeed while inference is
    # broken (missing paddlepaddle engine, oneDNN issues), and we want
    # to fall back to tesseract in that case rather than at first use.
    import numpy as np

    pipeline.predict(np.full((32, 32, 3), 255, dtype=np.uint8))
    return pipeline


def _init_tesseract():
    import pytesseract

    pytesseract.get_tesseract_version()  # raises if binary missing
    return pytesseract


_INIT = {"paddle": _init_paddle, "tesseract": _init_tesseract}


def _get_engine():
    global _engine
    if _engine is None:
        errors = []
        for name in BACKEND_PREFERENCE:
            try:
                _engine = (name, _INIT[name]())
                break
            except Exception as exc:  # noqa: BLE001 — fall to next backend
                errors.append(f"{name}: {exc}")
        if _engine is None:
            raise RuntimeError(
                "No OCR backend available ("
                + "; ".join(errors)
                + "). Install paddleocr+paddlepaddle or "
                "pytesseract+tesseract-ocr."
            )
        name = _engine[0]
        floor = MEASURED_FLOORS[name]
        _log.warning(
            "OCR backend: %s%s — measured floor: real-screenshot "
            "word_recall %.3f / char_sim %.2f, clean-render CER %.3f, "
            "entity survival %.2f (synth.backend_eval + synth.ocr_eval, "
            "2026-07-12). OCR-sourced accuracy cannot exceed this floor.",
            name,
            f" (fallback; {'; '.join(errors)})" if errors else "",
            floor["real_word_recall"], floor["real_char_sim"],
            floor["clean_render_cer"], floor["entity_survival"],
        )
    return _engine


def active_backend() -> str | None:
    """Name of the local OCR backend currently initialized this process
    (``"paddle"`` or ``"tesseract"``), or ``None`` if no local OCR has run
    yet. Callers use this to record which engine produced a set of
    numbers — OCR output (and therefore every downstream metric) is not
    comparable across backends.
    """
    return _engine[0] if _engine else None




def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def _norm_box(x0: float, y0: float, x1: float, y1: float, w: int, h: int
              ) -> tuple[float, float, float, float]:
    nx, ny = _clamp01(x0 / w), _clamp01(y0 / h)
    return (nx, ny, _clamp01(x1 / w) - nx, _clamp01(y1 / h) - ny)


def _paddle_lines(pipeline, img) -> list[OcrLine]:
    ih, iw = img.shape[:2]
    lines: list[OcrLine] = []
    for res in pipeline.predict(img):
        for text, score, poly in zip(
            res["rec_texts"], res["rec_scores"], res["rec_polys"]
        ):
            if not text.strip():
                continue
            xs = [float(p[0]) for p in poly]
            ys = [float(p[1]) for p in poly]
            lines.append(OcrLine(
                text=text,
                box=_norm_box(min(xs), min(ys), max(xs), max(ys), iw, ih),
                confidence=float(score),
            ))
    return lines


def _tesseract_lines(pytesseract, img) -> list[OcrLine]:
    ih, iw = img.shape[:2]
    data = pytesseract.image_to_data(
        img, output_type=pytesseract.Output.DICT
    )
    # image_to_data is word-level; regroup into lines so both backends
    # return comparable units.
    grouped: dict[tuple, list[int]] = {}
    for i, word in enumerate(data["text"]):
        if not word.strip() or float(data["conf"][i]) < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped.setdefault(key, []).append(i)
    lines: list[OcrLine] = []
    for idxs in grouped.values():
        x0 = min(data["left"][i] for i in idxs)
        y0 = min(data["top"][i] for i in idxs)
        x1 = max(data["left"][i] + data["width"][i] for i in idxs)
        y1 = max(data["top"][i] + data["height"][i] for i in idxs)
        confs = [float(data["conf"][i]) for i in idxs]
        lines.append(OcrLine(
            text=" ".join(data["text"][i] for i in idxs),
            box=_norm_box(x0, y0, x1, y1, iw, ih),
            confidence=sum(confs) / len(confs) / 100.0,
        ))
    return lines


def run_ocr_local(image_path: str, max_dim: int | None = None) -> list[OcrLine]:
    """Free tier: OCR an image file into text lines with normalized boxes.

    Returns [] for a missing file, an unreadable/corrupt image, or an
    image containing no detectable text — never raises for bad input.

    ``max_dim`` (opt-in) downscales the longest side to this many pixels
    before OCR. Measured on real gold screenshots: capping to ~1300–1600px
    retained 0.994 word recall while cutting CPU OCR time — a latency lever
    for oversized creatives. Default None keeps full-resolution behavior.
    Boxes stay normalized, so downstream geometry is unaffected.
    """
    import cv2

    if not os.path.isfile(image_path):
        return []
    img = cv2.imread(image_path)
    if img is None or img.size == 0:
        return []
    if max_dim and max(img.shape[:2]) > max_dim:
        s = max_dim / max(img.shape[:2])
        img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)),
                         interpolation=cv2.INTER_AREA)
    kind, engine = _get_engine()
    try:
        if kind == "paddle":
            return _paddle_lines(engine, img)
        return _tesseract_lines(engine, img)
    except Exception as exc:
        print(f"[cv.ocr] OCR failed on {image_path}: {exc}", file=sys.stderr)
        return []


# ------------------------------------------- Google Vision (paid tier)

_GCP_CREDS_VAR = "GOOGLE_APPLICATION_CREDENTIALS"
_VISION_SOURCE = "google_vision"


def vision_import_error() -> str | None:
    """None if the google-cloud-vision package imports, else the reason.

    The single source of truth for "is the Vision SDK available" — the
    same import ``run_ocr_google_vision`` performs; config.py reuses
    this instead of duplicating the probe.
    """
    try:
        from google.cloud import vision  # noqa: F401
        return None
    except Exception as exc:  # noqa: BLE001 — report any import failure
        return f"{type(exc).__name__}: {exc}"


def _signal(signal_type: str, value: str, score: float) -> dict:
    """schema.SemanticSignal-shaped dict; web-entity scores can exceed
    1.0, so clamp into the schema's [0, 1] confidence bound."""
    return {
        "signal_type": signal_type,
        "value": value,
        "confidence": _clamp01(float(score)),
        "source": _VISION_SOURCE,
    }


def run_ocr_google_vision(image_path: str) -> tuple[list[OcrLine], list[dict]]:
    """Paid tier: OCR + semantic signals via Google Cloud Vision.

    One annotate call requesting document text, labels, logos, and web
    entities. Returns (lines, semantic_signals); lines are paragraph-
    level (Vision's closest analog to the local backends' text lines),
    signals are ``schema.SemanticSignal``-shaped dicts.

    Raises RuntimeError if the GOOGLE_APPLICATION_CREDENTIALS env var
    is unset (service-account JSON path) or the API returns an error —
    callers relying on graceful degradation should go through
    ``run_ocr(tier="paid")``, which falls back to the free tier.
    """
    if not os.environ.get(_GCP_CREDS_VAR):
        raise RuntimeError(
            f"{_GCP_CREDS_VAR} is not set. Point it at a service-account "
            "JSON key file to use the paid Google Vision tier."
        )
    from google.cloud import vision

    with open(image_path, "rb") as f:
        content = f.read()
    client = vision.ImageAnnotatorClient()
    feature = vision.Feature.Type
    response = client.annotate_image({
        "image": vision.Image(content=content),
        "features": [
            {"type_": feature.DOCUMENT_TEXT_DETECTION},
            {"type_": feature.LABEL_DETECTION},
            {"type_": feature.LOGO_DETECTION},
            {"type_": feature.WEB_DETECTION},
        ],
    })
    if response.error.message:
        raise RuntimeError(f"Vision API error: {response.error.message}")

    lines: list[OcrLine] = []
    for page in response.full_text_annotation.pages:
        pw, ph = page.width or 1, page.height or 1
        for block in page.blocks:
            for para in block.paragraphs:
                text = " ".join(
                    "".join(s.text for s in w.symbols) for w in para.words
                ).strip()
                if not text:
                    continue
                xs = [v.x for v in para.bounding_box.vertices]
                ys = [v.y for v in para.bounding_box.vertices]
                lines.append(OcrLine(
                    text=text,
                    box=_norm_box(min(xs), min(ys), max(xs), max(ys), pw, ph),
                    confidence=_clamp01(float(para.confidence)),
                ))

    signals: list[dict] = []
    for ann in response.label_annotations:
        signals.append(_signal("label", ann.description, ann.score))
    for ann in response.logo_annotations:
        signals.append(_signal("logo", ann.description, ann.score))
    for ent in response.web_detection.web_entities:
        if ent.description:
            signals.append(_signal("web_entity", ent.description, ent.score))
    return lines, signals


# ----------------------------------------------------------- dispatcher

def run_ocr(image_path: str, tier: str = "free"
            ) -> tuple[list[OcrLine], list[dict], str | None]:
    """OCR an image at the requested tier.

    tier="paid"  -> Google Vision; on any failure (missing credentials,
                    quota, network) logs a warning and falls back to
                    local OCR with no semantic signals.
    tier="free"  -> local OCR (PaddleOCR/pytesseract), no API cost.

    Returns (lines, semantic_signals, backend): semantic_signals is []
    whenever the local path served the request, and ``backend`` names
    the engine that actually transcribed THIS call ("google_vision",
    "paddle", "tesseract", or None when nothing was read). Returned per
    call — never stashed in shared state — so concurrent callers each
    get their own truthful provenance value.
    """
    if tier not in ("free", "paid"):
        raise ValueError(f"unknown OCR tier {tier!r}; expected 'free' or 'paid'")
    if tier == "paid":
        try:
            lines, signals = run_ocr_google_vision(image_path)
            return lines, signals, _VISION_SOURCE
        except Exception as exc:
            print(
                f"[cv.ocr] paid tier failed ({exc}); falling back to local OCR",
                file=sys.stderr,
            )
    lines = run_ocr_local(image_path)
    # run_ocr_local returns [] without engine init for unreadable media;
    # only name a backend when one actually transcribed something.
    return lines, [], _engine[0] if _engine else None


if __name__ == "__main__":
    import glob
    import json

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Gold labels don't store a path; asset_id is the image's filename
    # stem under data/unlabeled/.
    image_path = None
    for gold_path in sorted(glob.glob(os.path.join(root, "data/gold/*.json"))):
        with open(gold_path) as f:
            asset_id = json.load(f)["asset_id"]
        candidate = os.path.join(root, "data/unlabeled", f"{asset_id}.jpg")
        if os.path.isfile(candidate):
            image_path = candidate
            break
    if image_path is None:
        sys.exit("no gold-labeled image found under data/unlabeled/")

    print(f"image: {image_path}\n")
    print("-- tier=free (local OCR) --")
    lines, signals, backend = run_ocr(image_path, tier="free")
    for line in lines:
        print(line)
    assert signals == [], "free tier must return no semantic signals"

    if os.environ.get(_GCP_CREDS_VAR):
        print("\n-- tier=paid (Google Vision) --")
        lines, signals, backend = run_ocr(image_path, tier="paid")
        for line in lines:
            print(line)
        print(f"semantic signals ({len(signals)}):")
        for s in signals:
            print(f"  {s['signal_type']:<11} {s['confidence']:.2f}  {s['value']!r}")
    else:
        print(f"\nskipping paid tier test — no credentials set ({_GCP_CREDS_VAR})")
