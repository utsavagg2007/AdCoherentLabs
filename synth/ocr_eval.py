"""OCR fidelity + segmentation + preprocessing ablation, with a device
benchmark.

Serves the CV-accuracy and NLP-segmentation objectives with real layout:

  * renders held-out synthetic assets (or uses real gold images),
  * OCRs each under several preprocessing variants,
  * scores OCR text fidelity (word recall + char similarity) and
    segmentation role accuracy against ground truth,
  * times each backend/device so GPU vs CPU is decided by data, not
    assumption.

Usage:
    python -m synth.ocr_eval --source synth --n 20
    python -m synth.ocr_eval --source gold
"""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --------------------------------------------------------------- preprocessing

def _to_bgr(gray):
    import cv2
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def pp_raw(img):
    return img


def pp_gray(img):
    import cv2
    return _to_bgr(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))


def pp_upscale(img, factor=2.0):
    import cv2
    return cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)


def pp_otsu(img):
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return _to_bgr(b)


def pp_upscale_otsu(img):
    return pp_otsu(pp_upscale(img, 2.0))


def pp_denoise_adaptive(img):
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.fastNlMeansDenoising(g, h=10)
    b = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY, 31, 15)
    return _to_bgr(b)


VARIANTS = {
    "raw": pp_raw,
    "upscale2x": pp_upscale,
    "otsu": pp_otsu,
    "upscale+otsu": pp_upscale_otsu,
    "denoise+adaptive": pp_denoise_adaptive,
}


# ------------------------------------------------------------------- OCR bridge

def _ocr_array(img):
    """OCR a BGR array via cv.ocr's active engine. Returns list[OcrLine]."""
    from cv import ocr
    kind, engine = ocr._get_engine()
    if kind == "paddle":
        return ocr._paddle_lines(engine, img)
    return ocr._tesseract_lines(engine, img)


# --------------------------------------------------------------------- metrics

def _norm(t):
    return " ".join((t or "").split()).lower()


def fidelity(gt_text: str, ocr_lines) -> tuple[float, float]:
    """(word_recall, char_similarity) of OCR output against ground truth."""
    ocr_text = _norm(" ".join(l.text for l in ocr_lines))
    gt = _norm(gt_text)
    gt_words = gt.split()
    ocr_words = set(ocr_text.split())
    recall = (sum(w in ocr_words for w in gt_words) / len(gt_words)) if gt_words else 0.0
    sim = difflib.SequenceMatcher(None, gt, ocr_text).ratio()
    return recall, sim


def seg_role_accuracy(gt_segments, ocr_lines) -> tuple[int, int, int, int]:
    """(role_correct, matched, gt_total, pred_total) via text alignment."""
    from nlp.normalize import segment_text
    lines = [{"text": l.text, "box": l.box, "confidence": l.confidence}
             for l in ocr_lines]
    pred = segment_text(ocr_lines=lines)
    pred_by = {}
    for p in pred:
        pred_by.setdefault(_norm(p["text"]), []).append(p)
    correct = matched = 0
    for g in gt_segments:
        cands = pred_by.get(_norm(g["text"]))
        if cands:
            matched += 1
            p = cands.pop(0)
            if p["role"] == g["role"]:
                correct += 1
    return correct, matched, len(gt_segments), len(pred)


# ------------------------------------------------------------------- data prep

def _synth_items(n, seed):
    from synth.generator import generate_corpus
    from synth.render import render_asset
    val = generate_corpus(400, seed)[:n]
    items = []
    for a in val:
        img, gt = render_asset(a)
        import numpy as np
        bgr = np.array(img)[:, :, ::-1].copy()  # RGB->BGR
        items.append((a["asset_id"], bgr, gt,
                      " ".join(s["text"] for s in a["segments"])))
    return items


def _gold_items():
    import cv2
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    items = []
    for gp in sorted(glob.glob(os.path.join(root, "data/gold/*.json"))):
        g = json.load(open(gp))
        aid = g["asset_id"]
        for ext in (".jpg", ".jpeg", ".png"):
            p = os.path.join(root, "data/unlabeled", f"{aid}{ext}")
            if os.path.isfile(p):
                img = cv2.imread(p)
                if img is not None:
                    items.append((aid, img, g["segments"],
                                  " ".join(s["text"] for s in g["segments"])))
                break
    return items


# ------------------------------------------------------------------------ main

def _cap(img, maxdim):
    """Downscale so the longest side <= maxdim (latency control on large
    real screenshots); no-op for smaller images."""
    if maxdim <= 0:
        return img
    import cv2
    h, w = img.shape[:2]
    if max(h, w) <= maxdim:
        return img
    s = maxdim / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


def run(items, variants, maxdim=1600):
    rows = []
    for vname in variants:
        pp = VARIANTS[vname]
        wr = cs = 0.0
        rc = rm = gt_tot = pred_tot = 0
        t0 = time.time()
        for aid, img, gt_segs, gt_text in items:
            lines = _ocr_array(pp(_cap(img, maxdim)))
            r, s = fidelity(gt_text, lines)
            wr += r
            cs += s
            c, m, gtt, pt = seg_role_accuracy(gt_segs, lines)
            rc += c
            rm += m
            gt_tot += gtt
            pred_tot += pt
        n = len(items)
        rows.append({
            "variant": vname,
            "word_recall": wr / n, "char_sim": cs / n,
            "role_acc": rc / rm if rm else 0.0,
            "seg_matched": rm / gt_tot if gt_tot else 0.0,
            "over_seg": pred_tot / gt_tot if gt_tot else 0.0,
            "sec_per_asset": (time.time() - t0) / n,
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("synth", "gold"), default="synth")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--maxdim", type=int, default=1600,
                    help="downscale longest image side to this before OCR (0=off)")
    args = ap.parse_args()

    items = _synth_items(args.n, args.seed) if args.source == "synth" else _gold_items()
    variants = [v for v in args.variants.split(",") if v in VARIANTS]
    print(f"source={args.source}  assets={len(items)}  "
          f"backend={__import__('cv.ocr', fromlist=['_get_engine'])._get_engine()[0]}")
    rows = run(items, variants, maxdim=args.maxdim)

    hdr = f"{'variant':<18}{'word_recall':>12}{'char_sim':>10}{'role_acc':>10}{'seg_match':>11}{'over_seg':>9}{'s/asset':>9}"
    print(hdr)
    print("-" * len(hdr))
    for r in sorted(rows, key=lambda x: -x["word_recall"]):
        print(f"{r['variant']:<18}{r['word_recall']:>12.3f}{r['char_sim']:>10.3f}"
              f"{r['role_acc']:>10.3f}{r['seg_matched']:>11.3f}{r['over_seg']:>9.2f}"
              f"{r['sec_per_asset']:>9.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
