"""Pure-math CV measurements for compliance evidence.

These feed ``schema.CVFinding`` values: numbers only, never judgments.
Whether 4.2:1 contrast on a disclosure is acceptable is the rule
engine's call, not this module's.

No ML, no I/O, no external calls — every function is deterministic
arithmetic over its arguments.
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
