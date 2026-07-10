"""Segmentation: raw asset text -> schema.Segment-shaped dicts.

Three input modes, in priority order: OCR lines (from ``cv.ocr``),
HTML (structural tags carry role hints), plain text (keyword and
position heuristics). Output dicts match ``schema.Segment`` exactly.

Roles are limited to schema.SegmentRole: headline, body, disclosure,
fine_print, cta, legal, unknown. (There is no "subhead" in the schema;
secondary headings land in headline or body.)

Deterministic structurer, not a judge: role assignment is a layout
guess for downstream routing, never a compliance conclusion.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_DISCLOSURE_RE = re.compile(
    r"terms apply|rates? (?:from|as low as|may (?:change|vary))|"
    r"accurate as of|subject to (?:change|approval|credit)|"
    r"conditions apply|see terms|results (?:may|not) |"
    r"not a (?:commitment|guarantee)|apr(?:s)? (?:range|vary)|"
    r"for details|qualifications? (?:apply|required)",
    re.IGNORECASE,
)
_LEGAL_RE = re.compile(
    r"member fdic|fdic[- ]insured|\bfdic\b|equal housing|nmls|"
    r"\bsipc\b|all rights reserved|©|\(c\)\s*\d{4}|trademark",
    re.IGNORECASE,
)
_CTA_RE = re.compile(
    r"^(?:apply|learn more|get started|sign up|join|open (?:an? )?account|"
    r"shop|download|order|claim|start|enroll|check your rate|see (?:if|your)|"
    r"get the app|visit)\b|apply (?:now|today)\b",
    re.IGNORECASE,
)


def _keyword_role(text: str) -> str | None:
    """Role from wording alone, or None if wording is neutral."""
    if _LEGAL_RE.search(text):
        return "legal"
    if _DISCLOSURE_RE.search(text):
        return "disclosure"
    stripped = text.strip()
    if _CTA_RE.search(stripped) and len(stripped.split()) <= 6:
        return "cta"
    return None


def _segment(i: int, text: str, role: str, source: str,
             bbox: dict | None = None,
             ocr_confidence: float | None = None) -> dict:
    return {
        "segment_id": f"seg_{i}",
        "text": text,
        "role": role,
        "source": source,
        "bbox": bbox,
        "ocr_confidence": ocr_confidence,
    }


# ---------------------------------------------------------------- OCR

# Block-merge tunables. Raw OCR emits one line per visual text row, but
# labels (and downstream span matching) work in logical blocks — a
# headline wrapped over two rows, a paragraph, "Member" over "FDIC".
_MERGE_MAX_HEIGHT_RATIO = 1.8  # member line heights within 1.8x of each other
_MERGE_MAX_VGAP = 0.7          # stacked-row gap <= 0.7 * taller line height
_MERGE_MAX_HGAP = 1.0          # same-row gap <= 1.0 * taller line height
_ROW_OVERLAP = 0.5             # vertical overlap fraction that means "same row"
_MERGE_ROW_HGAP = 6.0          # band-consolidation gap <= 6 * line height


def _reading_order(members: list) -> list:
    """Sort block members into visual rows top-to-bottom, left-to-right."""
    rows: list[list] = []
    for m in sorted(members, key=lambda m: m[1][1]):
        _, (_, y, _, h), _ = m
        for row in rows:
            _, (_, ry, _, rh), _ = row[0]
            if min(y + h, ry + rh) - max(y, ry) >= _ROW_OVERLAP * min(h, rh):
                row.append(m)
                break
        else:
            rows.append([m])
    return [m for row in rows for m in sorted(row, key=lambda m: m[1][0])]


def _merge_ocr_lines(lines: list) -> list:
    """Group raw OCR lines into visually coherent blocks.

    A line joins a block when its text height is similar and it either
    continues one of the block's rows (strong vertical overlap, small
    horizontal gap) or stacks directly below the block (small vertical
    gap, horizontally aligned). Lines without real boxes stay singletons.

    lines: [(text, (x, y, w, h), conf)] with normalized boxes.
    Returns [(text, union_box, mean_conf, line_height)] in reading
    order. line_height is the mean member height — the union box grows
    with every stacked row, so it cannot drive text-size heuristics.
    """
    groups: list[dict] = []
    for text, (x, y, w, h), conf in sorted(lines, key=lambda t: (t[1][1], t[1][0])):
        target = None
        for g in groups:
            gh = g["line_h"]
            if h <= 0 or gh <= 0:
                continue
            if min(h, gh) / max(h, gh) < 1.0 / _MERGE_MAX_HEIGHT_RATIO:
                continue
            ref = max(h, gh)
            hgap = max(x - g["x1"], g["x0"] - (x + w))
            same_row = hgap <= _MERGE_MAX_HGAP * ref and any(
                min(y + h, my + mh) - max(y, my) >= _ROW_OVERLAP * min(h, mh)
                for _, (_, my, _, mh), _ in g["members"]
            )
            vgap = y - g["y1"]
            x_overlap = min(x + w, g["x1"]) - max(x, g["x0"])
            stacked = (
                -0.5 * ref <= vgap <= _MERGE_MAX_VGAP * ref
                and x_overlap >= 0.3 * min(w, g["x1"] - g["x0"])
            )
            if same_row or stacked:
                target = g
                break
        if target is None:
            groups.append({
                "members": [(text, (x, y, w, h), conf)],
                "x0": x, "y0": y, "x1": x + w, "y1": y + h, "line_h": h,
            })
        else:
            target["members"].append((text, (x, y, w, h), conf))
            target["x0"] = min(target["x0"], x)
            target["y0"] = min(target["y0"], y)
            target["x1"] = max(target["x1"], x + w)
            target["y1"] = max(target["y1"], y + h)
            target["line_h"] = (sum(mh for _, (_, _, _, mh), _ in target["members"])
                                / len(target["members"]))

    _consolidate_bands(groups)

    merged = []
    for g in groups:
        members = _reading_order(g["members"])
        confs = [c for _, _, c in members if c is not None]
        merged.append((
            " ".join(t for t, _, _ in members),
            (g["x0"], g["y0"], g["x1"] - g["x0"], g["y1"] - g["y0"]),
            sum(confs) / len(confs) if confs else None,
            g["line_h"],
        ))
    merged.sort(key=lambda b: (b[1][1], b[1][0]))
    return merged


def _consolidate_bands(groups: list[dict]) -> None:
    """Second pass: merge blocks that share a horizontal band.

    Table rows and multi-column rows read as one logical segment even
    though the column gaps exceed the same-row line limit ('U.S. Bank |
    7.20% | Weeks | None'). Two blocks merge when their union boxes
    overlap vertically by at least half the shorter block, their line
    heights are similar, and the horizontal gap stays within
    _MERGE_ROW_HGAP line heights. Runs to fixpoint, in place.
    """
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(groups):
            for j in range(len(groups) - 1, i, -1):
                b = groups[j]
                ha, hb = a["line_h"], b["line_h"]
                if ha <= 0 or hb <= 0:
                    continue
                if min(ha, hb) / max(ha, hb) < 1.0 / _MERGE_MAX_HEIGHT_RATIO:
                    continue
                v_overlap = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
                if v_overlap < 0.5 * min(a["y1"] - a["y0"], b["y1"] - b["y0"]):
                    continue
                hgap = max(b["x0"] - a["x1"], a["x0"] - b["x1"])
                if hgap > _MERGE_ROW_HGAP * max(ha, hb):
                    continue
                a["members"] += b["members"]
                a["x0"] = min(a["x0"], b["x0"])
                a["y0"] = min(a["y0"], b["y0"])
                a["x1"] = max(a["x1"], b["x1"])
                a["y1"] = max(a["y1"], b["y1"])
                a["line_h"] = (sum(h for _, (_, _, _, h), _ in a["members"])
                               / len(a["members"]))
                del groups[j]
                changed = True


def _from_ocr(ocr_lines: list) -> list[dict]:
    """Merge OCR lines into blocks, then one segment per block.

    Roles come from wording first, then layout: the tallest blocks in
    the upper half are the headline; distinctly small text is
    fine_print; the rest is body. Size heuristics use the block's
    member line height, never the (multi-row) union box height.
    """
    lines = []
    for line in ocr_lines:
        if isinstance(line, dict):
            text = line.get("text", "")
            box = tuple(line.get("box") or (0, 0, 0, 0))
            conf = line.get("confidence")
        else:
            text = getattr(line, "text", "")
            box = tuple(getattr(line, "box", (0, 0, 0, 0)))
            conf = getattr(line, "confidence", None)
        if text.strip():
            lines.append((text, box, conf))
    if not lines:
        return []

    blocks = _merge_ocr_lines(lines)
    heights = sorted(b[3] for b in blocks)
    max_h = heights[-1]
    median_h = heights[len(heights) // 2]

    segments = []
    for i, (text, (x, y, w, h), conf, line_h) in enumerate(blocks, start=1):
        role = _keyword_role(text)
        if role is None:
            if line_h >= 0.7 * max_h and y < 0.5:
                role = "headline"
            elif median_h > 0 and line_h < 0.5 * median_h:
                role = "fine_print"
            elif len(text.split()) >= 3:
                role = "body"
            else:
                role = "unknown"
        segments.append(_segment(
            i, text, role, "ocr",
            bbox={"x": x, "y": y, "width": w, "height": h},
            ocr_confidence=conf,
        ))
    return segments


# --------------------------------------------------------------- HTML

_TAG_ROLES = {
    "h1": "headline", "h2": "headline",
    "h3": "body", "h4": "body", "h5": "body", "h6": "body",
    "small": "fine_print", "footer": "fine_print",
    "button": "cta",
}
_BLOCK_TAGS = set(_TAG_ROLES) | {"p", "li", "div", "td", "a", "span"}


class _HtmlSegmenter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks: list[tuple[str, str]] = []  # (text, tag-role hint)
        self._stack: list[str] = []
        self._buf: list[str] = []
        self._skip = 0

    def _flush(self):
        text = " ".join("".join(self._buf).split())
        self._buf.clear()
        if not text:
            return
        role = "body"
        for tag in reversed(self._stack):
            if tag in _TAG_ROLES:
                role = _TAG_ROLES[tag]
                break
        self.chunks.append((text, role))

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in _BLOCK_TAGS and tag not in ("span", "a"):
            self._flush()
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if tag in _BLOCK_TAGS and tag not in ("span", "a"):
            self._flush()
        while self._stack and self._stack.pop() != tag:
            pass

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)


def _from_html(html: str) -> list[dict]:
    parser = _HtmlSegmenter()
    parser.feed(html)
    parser._flush()
    segments = []
    for i, (text, tag_role) in enumerate(parser.chunks, start=1):
        # Explicit wording beats tag structure — <small>Member FDIC</small>
        # is legal, not fine_print.
        role = _keyword_role(text) or tag_role
        segments.append(_segment(i, text, role, "html"))
    return segments


# --------------------------------------------------------------- text

def _from_text(text: str) -> list[dict]:
    chunks = [c.strip() for c in re.split(r"\n{2,}|\n", text) if c.strip()]
    segments = []
    for i, chunk in enumerate(chunks, start=1):
        role = _keyword_role(chunk)
        if role is None:
            if i == 1:
                role = "headline"
            elif i == len(chunks) and len(chunk.split()) > 8:
                # trailing wall of text is usually the fine print
                role = "fine_print"
            else:
                role = "body"
        segments.append(_segment(i, chunk, role, "text"))
    return segments


def segment_text(text: str = None, html: str = None,
                 ocr_lines: list = None) -> list[dict]:
    """Segment one asset's content into schema.Segment-shaped dicts.

    Priority: ocr_lines > html > text. Exactly one source is used per
    call; returns [] if none is given or the given one is empty.
    """
    if ocr_lines is not None:
        return _from_ocr(ocr_lines)
    if html is not None:
        return _from_html(html)
    if text is not None:
        return _from_text(text)
    return []


if __name__ == "__main__":
    import glob
    import json
    import os
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    import schema
    from cv.ocr import run_ocr

    gold_path = image_path = None
    for path in sorted(glob.glob(os.path.join(root, "data/gold/*.json"))):
        with open(path) as f:
            gold = json.load(f)
        candidate = os.path.join(root, "data/unlabeled", f"{gold['asset_id']}.jpg")
        if os.path.isfile(candidate):
            gold_path, image_path = path, candidate
            break
    if gold_path is None:
        sys.exit("no gold-labeled image found under data/unlabeled/")

    print(f"asset: {gold['asset_id']}  ({image_path})\n")
    ocr_lines, _ = run_ocr(image_path)  # free tier: no semantic signals
    segments = segment_text(ocr_lines=ocr_lines)
    for s in segments:
        schema.Segment.model_validate(s)  # prove schema shape

    print(f"predicted ({len(segments)} segments):")
    for s in segments:
        print(f"  {s['segment_id']:>6}  {s['role']:<11} {s['text']!r}")
    print(f"\ngold ({len(gold['segments'])} segments):")
    for s in gold["segments"]:
        print(f"  {s['segment_id']:>6}  {s['role']:<11} {s['text']!r}")
