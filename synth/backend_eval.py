"""OCR backend fidelity: CER/WER by text-size band + entity survival.

Renders role-realistic synthetic banners (synth.render), OCRs each with
one or more backends (PaddleOCR / pytesseract), assigns OCR lines back
to ground-truth segments by bbox overlap, and reports:

  * CER / WER per (backend, text-size band) — bands come from the
    renderer's role styles: large ~52px headline, medium 26-34px
    body/cta, small 18-20px disclosure/legal, tiny ~15px fine print;
  * entity survival rate — does an entity's exact surface string
    ("5.99% APR") come through OCR intact in its segment?

These numbers are the *measured floor* that cv.ocr warnings and README
accuracy claims must respect: downstream extraction cannot recover what
OCR destroyed. Deterministic given (n, seed, backend).

Usage:
    python -m synth.backend_eval --n 20 --seed 7 --backends paddle,tesseract
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Text-size bands by rendered role (see synth.render._ROLE_STYLE).
_BANDS = [
    ("large ~52px (headline)", {"headline"}),
    ("medium 26-34px (body/cta)", {"body", "cta", "unknown"}),
    ("small 18-20px (disclosure/legal)", {"disclosure", "legal"}),
    ("tiny ~15px (fine_print)", {"fine_print"}),
]


def _band(role: str) -> str:
    for name, roles in _BANDS:
        if role in roles:
            return name
    return _BANDS[1][0]


def _norm(t: str) -> str:
    return " ".join((t or "").split())


def _lev(a: str, b: str) -> int:
    """Levenshtein edit distance (iterative DP, O(len(a)*len(b)))."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _overlap(line_box, seg_bbox) -> float:
    lx, ly, lw, lh = line_box
    sx, sy = seg_bbox["x"], seg_bbox["y"]
    sw, sh = seg_bbox["width"], seg_bbox["height"]
    ix = max(0.0, min(lx + lw, sx + sw) - max(lx, sx))
    iy = max(0.0, min(ly + lh, sy + sh) - max(ly, sy))
    la = lw * lh
    return (ix * iy) / la if la > 0 else 0.0


def _force_backend(name: str) -> None:
    """Pin cv.ocr's engine to one backend for a measurement pass."""
    from cv import ocr
    if name == "paddle":
        ocr._engine = ("paddle", ocr._init_paddle())
    elif name == "tesseract":
        ocr._engine = ("tesseract", ocr._init_tesseract())
    else:
        raise ValueError(f"unknown backend {name!r}")


def measure(corpus, backend: str, maxdim: int = 1600) -> dict:
    """Run one backend over rendered corpus; return aggregated stats."""
    import numpy as np

    from synth.ocr_eval import _cap, _ocr_array
    from synth.render import render_asset

    _force_backend(backend)

    stats = defaultdict(lambda: {"edits": 0, "chars": 0,
                                 "werr": 0, "words": 0, "segs": 0})
    ent_total = ent_ok = 0
    num_total = num_ok = 0

    for asset in corpus:
        img, gt = render_asset(asset)
        bgr = np.array(img)[:, :, ::-1].copy()
        lines = _ocr_array(_cap(bgr, maxdim))

        # Assign each OCR line to the gt segment with max overlap.
        seg_lines = defaultdict(list)
        for ln in lines:
            best, best_o = None, 0.0
            for g in gt:
                o = _overlap(ln.box, g["bbox"])
                if o > best_o:
                    best, best_o = g["segment_id"], o
            if best is not None and best_o >= 0.2:
                seg_lines[best].append(ln)

        seg_ocr = {}
        for g in gt:
            members = sorted(seg_lines.get(g["segment_id"], []),
                             key=lambda l: (l.box[1], l.box[0]))
            ocr_text = _norm(" ".join(l.text for l in members))
            seg_ocr[g["segment_id"]] = ocr_text
            gt_text = _norm(g["text"])
            band = _band(g["role"])
            s = stats[band]
            s["edits"] += _lev(gt_text, ocr_text)
            s["chars"] += len(gt_text)
            s["werr"] += _lev_words(gt_text.split(), ocr_text.split())
            s["words"] += len(gt_text.split())
            s["segs"] += 1

        for e in asset.get("entities", []):
            hay = seg_ocr.get(e["segment_id"], "").lower()
            needle = _norm(e["raw_text"]).lower()
            ent_total += 1
            hit = needle in hay
            ent_ok += hit
            if any(c.isdigit() for c in needle):
                num_total += 1
                num_ok += hit

    return {"bands": dict(stats),
            "entity_survival": (ent_ok, ent_total),
            "numeric_survival": (num_ok, num_total)}


def _lev_words(a: list, b: list) -> int:
    """Word-level edit distance (same DP over token sequences)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i]
        for j, wb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (wa != wb)))
        prev = cur
    return prev[-1]


def print_report(results: dict) -> None:
    print(f"\n{'backend':<11}{'text-size band':<34}{'CER':>7}{'WER':>7}"
          f"{'chars':>8}{'segs':>6}")
    print("-" * 73)
    for backend, r in results.items():
        for name, _roles in _BANDS:
            s = r["bands"].get(name)
            if not s or s["chars"] == 0:
                continue
            cer = s["edits"] / s["chars"]
            wer = s["werr"] / s["words"] if s["words"] else 0.0
            print(f"{backend:<11}{name:<34}{cer:>7.3f}{wer:>7.3f}"
                  f"{s['chars']:>8}{s['segs']:>6}")
        edits = sum(s["edits"] for s in r["bands"].values())
        chars = sum(s["chars"] for s in r["bands"].values())
        werr = sum(s["werr"] for s in r["bands"].values())
        words = sum(s["words"] for s in r["bands"].values())
        print(f"{backend:<11}{'OVERALL':<34}{edits / chars:>7.3f}"
              f"{werr / words:>7.3f}{chars:>8}")
        eo, et = r["entity_survival"]
        no, nt = r["numeric_survival"]
        print(f"{'':<11}entity survival: {eo}/{et} = {eo / et:.3f}   "
              f"numeric-entity survival: {no}/{nt} = {no / nt:.3f}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--maxdim", type=int, default=1600)
    ap.add_argument("--backends", default="paddle,tesseract")
    args = ap.parse_args()

    from synth.generator import generate_corpus
    corpus = generate_corpus(args.n, args.seed)

    results = {}
    for backend in [b.strip() for b in args.backends.split(",") if b.strip()]:
        try:
            results[backend] = measure(corpus, backend, args.maxdim)
        except Exception as exc:  # noqa: BLE001 — report and continue
            print(f"[backend_eval] {backend} unavailable: {exc}",
                  file=sys.stderr)
    if not results:
        print("no backend produced results", file=sys.stderr)
        return 1
    print(f"rendered assets: {len(corpus)} (seed={args.seed}, "
          f"maxdim={args.maxdim})")
    print_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
