"""Sponsorship/ad-marker detection over OCR output.

Scans OCR line text for FTC-relevant disclosure markers ("#ad",
"paid partnership", "sponsored") and emits one CVFinding-shaped dict
per line — ``measurement: "marker_presence"``, ``value`` 1.0 if the
line carries a marker, 0.0 if not. Presence is a fact; whether the
placement satisfies 16 CFR 255 is the rule engine's call.
"""

from __future__ import annotations

import re

# Word-bounded so substrings never trigger: "advantage" is not "#ad",
# "unsponsored" is not "sponsored". (?<![#\w]) also rejects "##ad".
_MARKER_PATTERNS = [
    re.compile(r"(?<![#\w])#ad(?!\w)", re.IGNORECASE),
    re.compile(r"\bpaid\s+partnership\b", re.IGNORECASE),
    re.compile(r"\bsponsored\b", re.IGNORECASE),
]

_METHOD = "regex_marker_v1"

# Footnote markers: a leading asterisk/dagger flags text as a footnote
# whose referent must carry a matching disclosure. Gold labels this as
# marker_presence via an "asterisk_footnote_detector"; detecting it here
# lets the pipeline emit comparable findings (e.g. "*72% Savings...").
_FOOTNOTE_RE = re.compile(r"^\s*[*†‡]\S")
_FOOTNOTE_METHOD = "asterisk_footnote_detector"


def has_footnote_marker(text: str) -> bool:
    return bool(_FOOTNOTE_RE.match(text or ""))


def _line_text(line) -> str:
    if isinstance(line, str):
        return line
    if isinstance(line, dict):
        return line.get("text", "")
    return getattr(line, "text", "")


def has_marker(text: str) -> bool:
    return any(p.search(text) for p in _MARKER_PATTERNS)


def detect_markers(ocr_lines: list) -> list[dict]:
    """One ``schema.CVFinding``-shaped dict per OCR line checked.

    Accepts ``cv.ocr.OcrLine`` objects, dicts with a ``text`` key, or
    bare strings. ``segment_id`` is None: OCR lines precede
    segmentation, so there is no segment to reference yet.
    """
    findings = []
    for i, line in enumerate(ocr_lines, start=1):
        findings.append({
            "finding_id": f"cvf_marker_{i}",
            "measurement": "marker_presence",
            "value": 1.0 if has_marker(_line_text(line)) else 0.0,
            "segment_id": None,
            "related_segment_id": None,
            "method": _METHOD,
        })
    return findings


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import schema
    from cv.ocr import OcrLine

    def show(name, lines):
        print(f"{name}:")
        for line, f in zip(lines, detect_markers(lines)):
            schema.CVFinding.model_validate(f)  # prove schema shape
            verdict = "PRESENT" if f["value"] == 1.0 else "absent "
            print(f"  {verdict}  {f['value']:.1f}  {line.text!r}")
        print()

    show("with marker", [
        OcrLine("Earn 4.50% APY today", (0.1, 0.1, 0.8, 0.1), 0.99),
        OcrLine("#ad Paid Partnership with FinCo", (0.1, 0.9, 0.5, 0.05), 0.97),
    ])
    show("without marker", [
        OcrLine("Lowest rates in America", (0.1, 0.1, 0.8, 0.1), 0.99),
        OcrLine("Apply now", (0.4, 0.8, 0.2, 0.08), 0.98),
    ])
    show("ambiguous (must NOT trigger)", [
        OcrLine("Take advantage of our #advantage rewards", (0.1, 0.2, 0.8, 0.1), 0.96),
        OcrLine("Unsponsored opinions from real members", (0.1, 0.4, 0.8, 0.1), 0.95),
        OcrLine("Sponsored", (0.8, 0.02, 0.15, 0.04), 0.99),
    ])
