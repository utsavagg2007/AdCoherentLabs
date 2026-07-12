"""Pure-math CV measurements for compliance evidence.

These feed ``schema.CVFinding`` values: numbers only, never judgments.
Whether 4.2:1 contrast on a disclosure is acceptable is the rule
engine's call, not this module's.

No ML and no file I/O — every function is deterministic arithmetic over
its arguments. ``estimate_region_contrast`` additionally samples an
image array that is *passed in* (the caller does any file reading), so
this module still never touches the filesystem or the network.
"""

from __future__ import annotations

import math


def _channel(c8: float) -> float:
    """Linearize one 8-bit sRGB channel per WCAG 2.x."""
    c = c8 / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple) -> float:
    """WCAG 2.x relative luminance of an (R, G, B) color in 0-255."""
    r, g, b = (_channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb_fg: tuple, rgb_bg: tuple) -> float:
    """WCAG 2.x contrast ratio between two 0-255 RGB colors.

    Symmetric in its arguments; always in [1.0, 21.0], matching the
    ``schema.CVFinding`` bounds for ``contrast_ratio``.
    """
    l1 = relative_luminance(rgb_fg)
    l2 = relative_luminance(rgb_bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def estimate_region_contrast(image, bbox: tuple) -> float | None:
    """Best-effort WCAG contrast of a text region against its background.

    ``image`` is an OpenCV BGR array; ``bbox`` is (x, y, w, h) normalized
    to [0, 1]. The region is split into two luminance clusters by Otsu's
    threshold (text strokes vs. background); the mean color of each
    cluster is taken as one side of the pair. ``contrast_ratio`` is
    symmetric, so which cluster is "foreground" does not matter.

    Returns None (not an exception) when the region is too small or
    single-colored to estimate — callers simply emit no finding then.
    Approximate by nature (anti-aliasing, gradients, imagery behind
    text), so it is evidence for the rule engine, not a verdict.
    """
    import cv2
    import numpy as np

    h_img, w_img = image.shape[:2]
    x, y, w, h = bbox
    x0, y0 = int(round(x * w_img)), int(round(y * h_img))
    x1, y1 = int(round((x + w) * w_img)), int(round((y + h) * h_img))
    x0, x1 = max(0, min(x0, w_img - 1)), max(0, min(x1, w_img))
    y0, y1 = max(0, min(y0, h_img - 1)), max(0, min(y1, h_img))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    thresh, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    pixels = crop.reshape(-1, 3)
    mask = gray.reshape(-1) <= thresh
    dark, light = pixels[mask], pixels[~mask]
    if len(dark) == 0 or len(light) == 0:
        return None
    db, lb = dark.mean(axis=0), light.mean(axis=0)  # BGR
    fg = (float(db[2]), float(db[1]), float(db[0]))  # -> RGB
    bg = (float(lb[2]), float(lb[1]), float(lb[0]))
    return contrast_ratio(fg, bg)


def text_height_pct(box_height_px: float, image_height_px: float) -> float:
    """Text height as a percentage of image height, in [0, 100]."""
    if image_height_px <= 0:
        raise ValueError("image_height_px must be positive")
    return 100.0 * box_height_px / image_height_px


def proximity(box_a: tuple, box_b: tuple) -> float:
    """Euclidean distance between the centers of two boxes.

    Boxes are (x, y, w, h) in normalized [0, 1] coordinates (the same
    shape ``cv.ocr.OcrLine.box`` and ``schema.BoundingBox`` use), so the
    result is already normalized: 0.0 for coincident centers, up to
    sqrt(2) for opposite image corners.
    """
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    return math.hypot((ax + aw / 2) - (bx + bw / 2),
                      (ay + ah / 2) - (by + bh / 2))


if __name__ == "__main__":
    # 1. Black on white: (1.0+0.05)/(0.0+0.05) = 21.0 exactly.
    print(f"contrast_ratio(black, white) = "
          f"{contrast_ratio((0, 0, 0), (255, 255, 255)):.2f}  (expect 21.00)")

    # 2. 24px text in a 1200px image: 100*24/1200 = 2.0.
    print(f"text_height_pct(24, 1200)    = "
          f"{text_height_pct(24, 1200):.2f}  (expect 2.00)")

    # 3a. Same position and size -> centers coincide -> 0.0.
    box = (0.1, 0.2, 0.3, 0.1)
    print(f"proximity(box, box)          = "
          f"{proximity(box, box):.2f}  (expect 0.00)")
    # 3b. Centers at (0.25, 0.25) and (0.25, 0.65): |dy| = 0.4.
    a = (0.2, 0.2, 0.1, 0.1)
    b = (0.2, 0.6, 0.1, 0.1)
    print(f"proximity(a, b)              = "
          f"{proximity(a, b):.2f}  (expect 0.40)")
