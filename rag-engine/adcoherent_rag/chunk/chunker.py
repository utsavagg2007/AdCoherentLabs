"""Section -> Chunk conversion.

Chunks are cut along regulatory structure, not arbitrary character offsets:
paragraphs are grouped by their TOP-LEVEL subsection label ("(a)", "(b)", ...)
so each chunk is roughly one legally-citable subsection. Oversized groups are
windowed on sentence boundaries with a small overlap so the embedding model
(which truncates long inputs) never silently drops text.
"""

from __future__ import annotations

import logging
import re

from .. import config
from ..models import Chunk, Paragraph, SectionUnit, SourceSpec

logger = logging.getLogger(__name__)

# A top-level subsection designator: "(a)", "(b)", ... (also "(aa)" spillover).
# Nested designators like "(a)(1)" or "(1)" do NOT match and therefore stay
# inside the current group.
_TOP_LEVEL_LABEL_RE = re.compile(r"^\([a-z]+\)$")

# Sentence boundaries: whitespace after terminal punctuation, or hard newlines
# (paragraph breaks inside a group are natural split points too).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


# ---------------------------------------------------------------------------
# Public API


def chunk_section(unit: SectionUnit, spec: SourceSpec, frameworks: list[str]) -> list[Chunk]:
    """Turn one SectionUnit into retrieval chunks.

    - Paragraphs are grouped by top-level subsection label; prose before the
      first labeled paragraph forms its own unlabeled group.
    - Groups within ``config.CHUNK_MAX_CHARS`` become a single chunk; larger
      groups are windowed to ~``config.CHUNK_TARGET_CHARS`` on sentence
      boundaries with ``config.CHUNK_OVERLAP_CHARS`` of overlap.
    - Returns [] for sections with no usable text.
    """
    groups = _group_paragraphs(unit.paragraphs)
    if not groups:
        logger.debug("section %s has no text; skipping", unit.section_key)
        return []

    chunks: list[Chunk] = []
    chunk_index = 0
    for label, text in groups:
        header = _context_header(unit, label)
        for window in _windows_for_group(text):
            window = window.strip()
            if not window:
                continue
            chunks.append(
                Chunk(
                    section_key=unit.section_key,
                    citation=unit.citation,
                    chunk_index=chunk_index,
                    subsection_label=label,
                    context_header=header,
                    text=window,
                    metadata={
                        "source_id": spec.id,
                        "jurisdiction": spec.jurisdiction,
                        "authority": spec.authority,
                        "frameworks": list(frameworks),
                        "topics": list(spec.topics),
                        "citation": unit.citation,
                        "section_key": unit.section_key,
                    },
                )
            )
            chunk_index += 1

    if not chunks:
        logger.debug("section %s produced no non-empty chunks", unit.section_key)
    return chunks


# ---------------------------------------------------------------------------
# Grouping


def _group_paragraphs(paragraphs: list[Paragraph]) -> list[tuple[str | None, str]]:
    """Group paragraphs by top-level subsection label.

    Returns (label, text) pairs in document order; empty groups are dropped.
    """
    groups: list[tuple[str | None, str]] = []
    current_label: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_lines
        text = "\n".join(current_lines).strip()
        if text:
            groups.append((current_label, text))
        current_lines = []

    for p in paragraphs:
        label = p.label.strip() if p.label else None
        if label and _TOP_LEVEL_LABEL_RE.match(label):
            _flush()  # close the previous group (no-op before the first one)
            current_label = label
        body = p.text.strip()
        if body:  # a bare designator with no text contributes nothing
            current_lines.append(f"{label} {body}" if label else body)
    _flush()

    return groups


def _context_header(unit: SectionUnit, label: str | None) -> str:
    header = unit.citation
    if unit.heading:
        header = f"{header} — {unit.heading}"
    if label:
        header = f"{header} — {label}"
    return header


# ---------------------------------------------------------------------------
# Windowing


def _windows_for_group(text: str) -> list[str]:
    """One window when the group fits; sentence-boundary windows otherwise."""
    if len(text) <= config.CHUNK_MAX_CHARS:
        return [text]
    return _split_windows(
        _sentences(text),
        target=config.CHUNK_TARGET_CHARS,
        overlap=config.CHUNK_OVERLAP_CHARS,
    )


def _sentences(text: str) -> list[str]:
    """Split text into sentence-ish units, hard-splitting any monster runs."""
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p and p.strip()]
    out: list[str] = []
    for part in parts:
        if len(part) > config.CHUNK_TARGET_CHARS:
            out.extend(_hard_split(part, config.CHUNK_TARGET_CHARS))
        else:
            out.append(part)
    return out


def _hard_split(sentence: str, limit: int) -> list[str]:
    """Split an over-long sentence at word boundaries (character-level as a
    last resort for single tokens longer than the limit)."""
    pieces: list[str] = []
    current = ""
    for word in sentence.split():
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)

    out: list[str] = []
    for piece in pieces:
        while len(piece) > limit:
            out.append(piece[:limit])
            piece = piece[limit:]
        if piece:
            out.append(piece)
    return out


def _split_windows(sentences: list[str], *, target: int, overlap: int) -> list[str]:
    """Pack sentences into ~target-char windows with ~overlap-char overlap.

    Every window contains at least one *new* sentence, so overlap seeding can
    never produce a window that merely repeats the previous one. Window size
    stays within target + overlap (< CHUNK_MAX_CHARS with the shipped config).
    """
    windows: list[str] = []
    current: list[str] = []
    new_in_window = 0

    for sentence in sentences:
        if new_in_window > 0 and len(" ".join([*current, sentence])) > target:
            windows.append(" ".join(current))
            current = _overlap_tail(current, overlap)
            new_in_window = 0
        current.append(sentence)
        new_in_window += 1

    if new_in_window > 0 and current:
        windows.append(" ".join(current))
    return windows


def _overlap_tail(window_sentences: list[str], overlap: int) -> list[str]:
    """Trailing sentences of a window totalling <= overlap chars.

    When no whole sentence fits the budget, fall back to a word-aligned
    character tail of the last sentence so consecutive windows still share
    context.
    """
    tail: list[str] = []
    length = 0
    for sentence in reversed(window_sentences):
        extra = len(sentence) + (1 if tail else 0)
        if length + extra > overlap:
            break
        tail.insert(0, sentence)
        length += extra

    if not tail and window_sentences:
        cut = window_sentences[-1][-overlap:]
        space = cut.find(" ")
        if 0 <= space < len(cut) - 1:
            cut = cut[space + 1 :]
        cut = cut.strip()
        if cut:
            tail = [cut]
    return tail
