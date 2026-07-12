"""Role-recovery confusion matrix over rendered synthetic banners.

Renders synthetic assets with role-realistic layout (synth.render), runs
the real OCR -> merge -> role pipeline (cv.ocr + nlp.normalize), aligns
predicted segments back to ground truth by text similarity, and prints a
gt-role x predicted-role confusion matrix. This isolates exactly which
role-assignment rules in ``nlp.normalize`` fail on which layouts.

Alignment: each gt segment is matched to the predicted segment with the
highest normalized-text similarity (containment counts as 1.0, so a gt
line swallowed by an over-merged block still aligns to that block, and
the block's single role is charged against every member gt role — merge
errors surface as role confusion, which is the honest accounting).
Unmatched gt segments land in the ``(missing)`` column.

Usage:
    python -m synth.role_eval --n 24 --seed 7
"""

from __future__ import annotations

import argparse
import difflib
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROLES = ["headline", "body", "cta", "disclosure", "legal", "fine_print",
          "unknown"]
_MISS = "(missing)"


def _norm(t: str) -> str:
    return " ".join((t or "").split()).lower()


def _match_score(gt: str, pred: str) -> float:
    if not gt or not pred:
        return 0.0
    if gt in pred or pred in gt:
        return 1.0
    return difflib.SequenceMatcher(None, gt, pred).ratio()


def confusion(items) -> tuple[Counter, list]:
    """items: iterable of (gt_segments, pred_segments) per asset.
    Returns (Counter[(gt_role, pred_role)], [misassignment examples])."""
    cm: Counter = Counter()
    examples = []
    for gt_segs, pred_segs in items:
        preds = [(_norm(p["text"]), p["role"]) for p in pred_segs]
        for g in gt_segs:
            gt_text = _norm(g["text"])
            best, best_s = None, 0.0
            for ptext, prole in preds:
                s = _match_score(gt_text, ptext)
                if s > best_s:
                    best, best_s = prole, s
            if best is None or best_s < 0.3:
                cm[(g["role"], _MISS)] += 1
            else:
                cm[(g["role"], best)] += 1
                if best != g["role"]:
                    examples.append((g["role"], best, g["text"]))
    return cm, examples


def print_matrix(cm: Counter) -> None:
    pred_cols = _ROLES + [_MISS]
    print(f"\n{'gt \\ pred':<12}" + "".join(f"{c[:9]:>10}" for c in pred_cols)
          + f"{'acc':>8}")
    total_correct = total = 0
    for r in _ROLES:
        row = [cm.get((r, c), 0) for c in pred_cols]
        n = sum(row)
        if n == 0:
            continue
        correct = cm.get((r, r), 0)
        total_correct += correct
        total += n
        print(f"{r:<12}" + "".join(f"{v:>10}" for v in row)
              + f"{correct / n:>8.3f}")
    print(f"{'OVERALL':<12}" + " " * (10 * len(pred_cols))
          + f"{total_correct / total if total else 0.0:>8.3f}"
          + f"   ({total_correct}/{total})")


def top_confusions(cm: Counter, k: int = 6) -> list:
    pairs = [((g, p), n) for (g, p), n in cm.items() if g != p]
    pairs.sort(key=lambda x: -x[1])
    return pairs[:k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--maxdim", type=int, default=1600)
    ap.add_argument("--examples", type=int, default=8,
                    help="misassignment examples to print")
    args = ap.parse_args()

    import numpy as np

    from nlp.normalize import segment_text
    from synth.generator import generate_corpus
    from synth.ocr_eval import _cap, _ocr_array
    from synth.render import render_asset

    corpus = generate_corpus(args.n, args.seed)
    items = []
    for a in corpus:
        img, gt = render_asset(a)
        bgr = np.array(img)[:, :, ::-1].copy()
        lines = _ocr_array(_cap(bgr, args.maxdim))
        pred = segment_text(ocr_lines=[
            {"text": l.text, "box": l.box, "confidence": l.confidence}
            for l in lines])
        items.append((gt, pred))

    cm, examples = confusion(items)
    print(f"role confusion over {len(items)} rendered assets "
          f"(seed={args.seed})")
    print_matrix(cm)

    print("\ntop confusions (gt -> pred):")
    for (g, p), n in top_confusions(cm):
        print(f"  {g:<12} -> {p:<12} {n}")

    if args.examples:
        print("\nmisassignment examples:")
        for g, p, text in examples[:args.examples]:
            print(f"  [{g} -> {p}] {text[:90]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
