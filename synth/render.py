"""Render synthetic assets to images with ground-truth layout.

Turns a text-mode synthetic asset (from ``synth.generator``) into a PNG
that looks like an ad: role-driven font sizes and vertical stacking, plus
the exact per-segment bounding boxes. This is the instrument for the two
layout-dependent objectives that text mode cannot measure —

  * OCR text fidelity (CV accuracy), and
  * segmentation boundary + role recovery (NLP segmentation),

evaluated on held-out synthetic images and cross-checked on the real
gold/silver corpora. Deterministic given the asset + seed.
"""

from __future__ import annotations

import glob
import random

from PIL import Image, ImageDraw, ImageFont

_FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def _font_path(bold: bool) -> str:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    hits = glob.glob(f"{_FONT_DIR}/{name}") or glob.glob(
        f"/usr/share/fonts/**/{name}", recursive=True)
    return hits[0]


# (bold, point size) per role — mirrors how ads actually weight text:
# big bold headline at the top, tiny disclosure/fine print at the bottom.
_ROLE_STYLE = {
    "headline": (True, 52),
    "cta": (True, 34),
    "body": (False, 30),
    "unknown": (False, 26),
    "disclosure": (False, 20),
    "legal": (False, 18),
    "fine_print": (False, 15),
}


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def render_asset(asset: dict, width: int = 1000, seed: int | None = None):
    """Render one asset. Returns (PIL.Image, [gt segment dicts with bbox]).

    Ground-truth segments carry normalized [0,1] bboxes so they can be
    scored against pipeline output exactly like OCR segments.
    """
    rng = random.Random(seed if seed is not None else hash(asset["asset_id"]) & 0xFFFF)
    margin = 40
    pad = 22
    tmp = Image.new("RGB", (width, 10), "white")
    d = ImageDraw.Draw(tmp)

    laid = []  # (text, role, x, y, w, h, lines, font)
    y = margin
    for seg in asset["segments"]:
        role = seg["role"]
        bold, size = _ROLE_STYLE.get(role, (False, 26))
        size = max(11, size + rng.randint(-2, 2))  # mild jitter, still ordered
        font = ImageFont.truetype(_font_path(bold), size)
        lines = _wrap(d, seg["text"], font, width - 2 * margin)
        line_h = font.getbbox("Ag")[3] + 6
        block_h = line_h * len(lines)
        block_w = max((d.textlength(ln, font=font) for ln in lines), default=0)
        laid.append((seg, role, margin, y, block_w, block_h, lines, font, line_h))
        y += block_h + pad

    height = y + margin
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    gt = []
    for seg, role, x, yy, bw, bh, lines, font, line_h in laid:
        cy = yy
        for ln in lines:
            draw.text((x, cy), ln, fill="black", font=font)
            cy += line_h
        gt.append({
            "segment_id": seg["segment_id"], "text": seg["text"], "role": role,
            "source": "ocr", "ocr_confidence": None,
            "bbox": {"x": x / width, "y": yy / height,
                     "width": bw / width, "height": bh / height},
        })
    return img, gt


def render_corpus_to(assets, out_dir, width=1000):
    """Render assets to <out_dir>/<asset_id>.png; return {asset_id: gt}."""
    import json
    import os
    os.makedirs(out_dir, exist_ok=True)
    gts = {}
    for a in assets:
        img, gt = render_asset(a, width=width)
        img.save(os.path.join(out_dir, f"{a['asset_id']}.png"))
        gts[a["asset_id"]] = gt
    with open(os.path.join(out_dir, "_ground_truth.json"), "w") as f:
        json.dump(gts, f)
    return gts


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from synth.generator import generate_corpus
    a = generate_corpus(3, seed=7)[0]
    img, gt = render_asset(a)
    out = os.path.join(os.path.dirname(__file__), "_sample_render.png")
    img.save(out)
    print(f"rendered {a['asset_id']} ({img.size}) -> {out}")
    for g in gt:
        print(f"  {g['segment_id']:8} {g['role']:11} bbox={ {k: round(v,3) for k,v in g['bbox'].items()} }")
