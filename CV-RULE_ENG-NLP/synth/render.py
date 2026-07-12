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


# Role-realistic layout order: headline banner on top, body copy in the
# middle, the CTA as a button, and a bottom compliance block (disclosure,
# then legal, then fine_print) clustered tightly the way real ads set
# their mouse type.
_BOTTOM_ROLES = ("disclosure", "legal", "fine_print")

# CTA button palette: dark fill + white text (still high-contrast for OCR).
_BUTTON_FILLS = [(25, 55, 160), (10, 110, 60), (150, 30, 30), (40, 40, 40)]


def _layout_order(segments: list[dict]) -> list[dict]:
    """Reorder segments into visual order: headline, body/other, cta,
    then the bottom compliance cluster. Stable within each group."""
    heads = [s for s in segments if s["role"] == "headline"]
    ctas = [s for s in segments if s["role"] == "cta"]
    bottoms = [s for s in segments if s["role"] in _BOTTOM_ROLES]
    bottoms.sort(key=lambda s: _BOTTOM_ROLES.index(s["role"]))
    mids = [s for s in segments
            if s["role"] not in ("headline", "cta") + _BOTTOM_ROLES]
    return heads + mids + ctas + bottoms


def render_asset(asset: dict, width: int = 1000, seed: int | None = None):
    """Render one asset. Returns (PIL.Image, [gt segment dicts with bbox]).

    Role-realistic layout: the headline is set large at the top (randomly
    centered), body copy follows left-aligned, the CTA renders as a
    button (rounded filled rect, white bold text), and disclosure/legal/
    fine_print form a tightly-clustered small-type block at the bottom,
    separated from the marketing copy by a wide gap.

    Ground-truth segments carry normalized [0,1] bboxes so they can be
    scored against pipeline output exactly like OCR segments.
    """
    rng = random.Random(seed if seed is not None else hash(asset["asset_id"]) & 0xFFFF)
    margin = 40
    pad = 22
    cluster_pad = 6           # tight gap inside the bottom compliance block
    bottom_gap = 3 * pad      # wide gap isolating the bottom block
    btn_pad_x, btn_pad_y = 26, 14
    tmp = Image.new("RGB", (width, 10), "white")
    d = ImageDraw.Draw(tmp)

    center_headline = rng.random() < 0.5
    center_cta = rng.random() < 0.5
    button_fill = rng.choice(_BUTTON_FILLS)

    laid = []  # (seg, role, x, y, w, h, lines, font, line_h, style)
    y = margin
    prev_role = None
    for seg in _layout_order(asset["segments"]):
        role = seg["role"]
        bold, size = _ROLE_STYLE.get(role, (False, 26))
        size = max(11, size + rng.randint(-2, 2))  # mild jitter, still ordered
        font = ImageFont.truetype(_font_path(bold), size)
        max_w = width - 2 * margin - (2 * btn_pad_x if role == "cta" else 0)
        lines = _wrap(d, seg["text"], font, max_w)
        line_h = font.getbbox("Ag")[3] + 6
        block_h = line_h * len(lines)
        block_w = max((d.textlength(ln, font=font) for ln in lines), default=0)

        # Vertical rhythm: first bottom-block segment gets the wide gap,
        # segments inside the bottom block cluster tightly.
        if prev_role is not None:
            in_bottom = role in _BOTTOM_ROLES
            was_bottom = prev_role in _BOTTOM_ROLES
            if in_bottom and not was_bottom:
                y += bottom_gap - pad
            elif in_bottom and was_bottom:
                y += cluster_pad - pad
        # CTA button needs room for its padding.
        if role == "cta":
            y += btn_pad_y

        centered = (role == "headline" and center_headline) or \
                   (role == "cta" and center_cta)
        x = (width - block_w) / 2 if centered else margin
        laid.append((seg, role, x, y, block_w, block_h, lines, font, line_h))
        y += block_h + pad + (btn_pad_y if role == "cta" else 0)
        prev_role = role

    height = y + margin
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    gt = []
    for seg, role, x, yy, bw, bh, lines, font, line_h in laid:
        fill = "black"
        if role == "cta":
            # Button chrome behind the text; gt bbox stays on the text.
            draw.rounded_rectangle(
                [x - btn_pad_x, yy - btn_pad_y,
                 x + bw + btn_pad_x, yy + bh + btn_pad_y],
                radius=12, fill=button_fill,
            )
            fill = "white"
        cy = yy
        for ln in lines:
            lx = x + (bw - draw.textlength(ln, font=font)) / 2 if role == "cta" \
                else x
            draw.text((lx, cy), ln, fill=fill, font=font)
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
