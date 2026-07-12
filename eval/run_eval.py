"""Eval runner: score analyze_asset() outputs against gold labels.

Usage:
    python -m eval.run_eval [--gold-dir data/gold] [--csv-out eval/results]

Loads every gold label from data/gold/*.json (falling back to
eval/sample_gold.json when the directory is missing or empty), runs
analyze_asset() on each asset, scores every component with eval.scorer,
prints a two-section report, and writes a CSV row set for tracking
metrics over time.

The report is split so the headline numbers reflect extraction quality
rather than id/offset bookkeeping:

  * EXTRACTION QUALITY — value-mode entities (right type + right
    normalized value anywhere in the asset), alignment-tolerant segment
    and claim scoring, and routing. These are the headline metrics.
  * ALIGNMENT DIAGNOSTICS — span-strict entity matching (exact
    segment_id + char span, a probe of id/offset alignment, NOT
    extraction quality) and cv_findings counts.

Gold is a tiny held-out corpus (n=6): metrics print as a directional
reference with NO pass/fail bars. Hard V1 pass/fail bars are enforced
only on the higher-volume synthetic suites (synth/evaluate.py). Every
number is OCR-backend-specific (PaddleOCR vs pytesseract produce
different transcriptions), so the active backend is recorded in the
report header and CSV and numbers are not comparable across backends.
"""

from __future__ import annotations

import argparse
import copy
import csv
import glob
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import scorer  # noqa: E402

try:
    from schema import AssetRepresentation
except ImportError:  # pydantic not installed — score raw dicts instead
    AssetRepresentation = None

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GOLD_DIR = os.path.join(os.path.dirname(EVAL_DIR), "data", "gold")
SAMPLE_GOLD = os.path.join(EVAL_DIR, "sample_gold.json")

# V1 quality bars (the EXPANDED 1.3 target set). These are hard
# pass/fail bars ONLY on the synthetic suites, where volume supports
# them (see synth/evaluate.py). On the tiny gold corpus they are printed
# as a directional reference with no pass/fail column — never as a gate.
TARGETS = [
    {"component": "entities", "metric": "f1", "bar": 0.90},
    {"component": "claims", "metric": "recall", "bar": 0.85},
    {"component": "segments", "metric": "accuracy", "bar": 0.85},
    {"component": "routing", "metric": "f1", "bar": 0.90},
]


# ---------------------------------------------------------------------------
# System under test
# ---------------------------------------------------------------------------

DEFAULT_UNLABELED_DIR = os.path.join(os.path.dirname(EVAL_DIR), "data", "unlabeled")

_IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def _resolve_media(asset_id: str, unlabeled_dir: str) -> list[str] | None:
    """Image path(s) for an asset: single file, carousel folder, or None."""
    for ext in _IMAGE_EXTS:
        single = os.path.join(unlabeled_dir, f"{asset_id}{ext}")
        if os.path.isfile(single):
            return [single]
    folder = os.path.join(unlabeled_dir, asset_id)
    if os.path.isdir(folder):
        cards = sorted(
            p for p in glob.glob(os.path.join(folder, "*"))
            if p.lower().endswith(_IMAGE_EXTS)
        )
        if cards:
            return cards
    return None


def analyze_asset(gold_asset: dict, tier: str = "free",
                  unlabeled_dir: str = DEFAULT_UNLABELED_DIR) -> dict:
    """Run the real CV+NLP pipeline on the asset's source media.

    Media resolution: data/unlabeled/<asset_id>.jpg (single image) or
    data/unlabeled/<asset_id>/ (carousel: every card image, sorted).
    Assets with no media file (text-only samples) are re-analyzed from
    their label's segment text instead.
    """
    import pipeline

    asset_id = gold_asset["asset_id"]
    media = _resolve_media(asset_id, unlabeled_dir)
    if media:
        rep = pipeline.analyze_asset(asset_id, image_path=media, tier=tier)
    else:
        rep = pipeline.analyze_asset(
            asset_id, tier=tier,
            text="\n".join(s["text"] for s in gold_asset["segments"]),
        )
    return rep.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Gold loading
# ---------------------------------------------------------------------------

GOLD_DEFAULTS = {
    "entities": [],
    "claim_candidates": [],
    "cv_findings": [],
    "provenance": {
        "cv_version": "gold",
        "nlp_version": "gold",
        "ruleset_hash": "gold",
        "timestamp": "2026-01-01T00:00:00Z",
    },
}


def load_gold(path: str) -> dict | None:
    """Load one gold label, filling reasonable defaults for missing fields.

    Returns None (and warns) for files that are unreadable or lack the
    truly required fields, so one bad label never aborts the run.
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  [warn] skipping {path}: {e}", file=sys.stderr)
        return None

    if not isinstance(raw, dict) or not raw.get("segments") or not raw.get("routing"):
        print(f"  [warn] skipping {path}: missing required 'segments' or 'routing'", file=sys.stderr)
        return None

    raw.setdefault("asset_id", os.path.splitext(os.path.basename(path))[0])
    for key, default in GOLD_DEFAULTS.items():
        raw.setdefault(key, copy.deepcopy(default))

    if AssetRepresentation is not None:
        try:
            return AssetRepresentation.model_validate(raw).model_dump(mode="json")
        except Exception as e:  # noqa: BLE001 — score leniently, but surface the issue
            print(f"  [warn] {path} fails schema validation ({e}); scoring raw dict", file=sys.stderr)
    return raw


def load_gold_corpus(gold_dir: str) -> list[dict]:
    paths = sorted(glob.glob(os.path.join(gold_dir, "*.json")))
    if not paths:
        print(f"No gold labels in {gold_dir}; falling back to {SAMPLE_GOLD}")
        paths = [SAMPLE_GOLD]
    corpus = [g for g in (load_gold(p) for p in paths) if g is not None]
    if not corpus:
        print("No usable gold labels found.", file=sys.stderr)
        sys.exit(1)
    return corpus


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_corpus(corpus: list[dict], tier: str = "free") -> dict:
    """Run analyze_asset over the corpus and aggregate metrics correctly:
    sum raw counts across assets, then derive P/R/F1 once."""
    ent_results, ent_span_results = [], []
    seg_results, claim_results, cv_results = [], [], []
    gold_routes, pred_routes = [], []
    counts = {k: {"gold": 0, "pred": 0} for k in ("entities", "segments", "claims", "cv", "routing")}

    for gold in corpus:
        pred_raw = analyze_asset(gold, tier=tier)
        # Align predicted segments to gold by text/bbox overlap and remap
        # ids, so entity/claim/CV scoring credits correct extraction on
        # re-segmented OCR output instead of penalizing id drift.
        mapping = scorer.align_segment_ids(gold["segments"], pred_raw.get("segments", []))
        pred = scorer.remap_segment_ids(pred_raw, mapping)
        # HEADLINE — entities in value mode: same type + normalized value
        # (span-agnostic), the mode built for OCR assets whose char spans
        # never line up with gold.
        ent_results.append(
            scorer.entity_metrics(gold["entities"], pred.get("entities", []),
                                  match_mode="value"))
        # DIAGNOSTIC — span-strict on the RAW (pre-remap) prediction:
        # exact segment_id + char span. This deliberately measures
        # id/offset alignment drift, not extraction quality, so it stays
        # out of the headline.
        ent_span_results.append(
            scorer.entity_metrics(gold["entities"], pred_raw.get("entities", []),
                                  match_mode="span"))
        seg_results.append(scorer.segment_metrics(gold["segments"], pred.get("segments", [])))
        claim_results.append(
            scorer.claim_metrics(gold["claim_candidates"], pred.get("claim_candidates", []))
        )
        cv_results.append(scorer.cv_metrics(gold["cv_findings"], pred.get("cv_findings", [])))
        gold_routes.append(gold["routing"])
        pred_routes.append(pred.get("routing") or {"product_type": "unknown", "frameworks": [], "signal": ""})

        counts["entities"]["gold"] += len(gold["entities"])
        counts["entities"]["pred"] += len(pred.get("entities", []))
        counts["segments"]["gold"] += len(gold["segments"])
        counts["segments"]["pred"] += len(pred.get("segments", []))
        counts["claims"]["gold"] += len(gold["claim_candidates"])
        counts["claims"]["pred"] += len(pred.get("claim_candidates", []))
        counts["cv"]["gold"] += len(gold["cv_findings"])
        counts["cv"]["pred"] += len(pred.get("cv_findings", []))
        counts["routing"]["gold"] += len(gold["routing"].get("frameworks", []))
        counts["routing"]["pred"] += len((pred.get("routing") or {}).get("frameworks", []))

    # Entities: micro-aggregate overall + per-type across assets, for both
    # the headline (value-mode) and the diagnostic (span-strict) results.
    def _agg_entities(results: list[dict]) -> dict:
        etypes = sorted({t for r in results for t in r if t != "overall"})
        agg = {t: scorer.merge_counts([r[t] for r in results if t in r]) for t in etypes}
        agg["overall"] = scorer.merge_counts([r["overall"] for r in results])
        return agg

    entities = _agg_entities(ent_results)
    entities_span = _agg_entities(ent_span_results)

    # Segments: sum correct/total per role.
    roles = sorted({t for r in seg_results for t in r if t != "overall"})
    segments = {}
    for role in roles + ["overall"]:
        correct = sum(r[role]["correct"] for r in seg_results if role in r)
        total = sum(r[role]["total"] for r in seg_results if role in r)
        segments[role] = {
            "accuracy": correct / total if total else 0.0,
            "correct": correct,
            "total": total,
        }

    claims = scorer.merge_counts(claim_results)
    matched_claims = claims["tp"]
    exact = sum(r["exact_span_rate"] * r["tp"] for r in claim_results)
    claims["exact_span_rate"] = exact / matched_claims if matched_claims else 0.0

    routing = scorer.routing_metrics(gold_routes, pred_routes)

    # CV: recompute MAE from per-asset sums.
    cv_types = sorted({t for r in cv_results for t in r if t != "overall"})
    cv = {}
    for mtype in cv_types + ["overall"]:
        rs = [r[mtype] for r in cv_results if mtype in r]
        matched = sum(r["matched"] for r in rs)
        err_sum = sum((r["mae"] or 0.0) * r["matched"] for r in rs)
        cv[mtype] = {
            "mae": err_sum / matched if matched else None,
            "matched": matched,
            "gold_only": sum(r["gold_only"] for r in rs),
            "pred_only": sum(r["pred_only"] for r in rs),
        }

    # Record which OCR backend produced these numbers. It is initialized
    # lazily on the first image OCR, so read it after the corpus has run;
    # None means no local OCR fired (text-only corpus / paid tier served).
    # Aliased so the import does not shadow the local ``cv`` metrics dict.
    import cv.ocr as cv_ocr

    return {
        "entities": entities,
        "entities_span": entities_span,
        "segments": segments,
        "claims": claims,
        "routing": routing,
        "cv": cv,
        "counts": counts,
        "n_assets": len(corpus),
        "tier": tier,
        "ocr_backend": cv_ocr.active_backend(),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt(v, digits=3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def build_rows(results: dict) -> list[dict]:
    """Flatten aggregated results into report rows, each tagged with a
    ``section``: ``"extraction"`` (headline extraction-quality metrics) or
    ``"diagnostic"`` (span-strict alignment probe + cv_findings counts)."""
    rows = []
    counts = results["counts"]

    def row(section, component, detail, metric, value, gold_count, pred_count,
            precision=None, recall=None, f1=None):
        rows.append({
            "section": section,
            "component": component, "detail": detail, "metric": metric, "value": value,
            "gold_count": gold_count, "pred_count": pred_count,
            "precision": precision, "recall": recall, "f1": f1,
        })

    # ---- EXTRACTION QUALITY (headline) ----
    ent = results["entities"]
    for etype in sorted(k for k in ent if k != "overall"):
        m = ent[etype]
        row("extraction", "entities", etype, "f1", m["f1"], m["tp"] + m["fn"], m["tp"] + m["fp"],
            m["precision"], m["recall"], m["f1"])
    m = ent["overall"]
    row("extraction", "entities", "overall", "f1", m["f1"],
        counts["entities"]["gold"], counts["entities"]["pred"],
        m["precision"], m["recall"], m["f1"])

    seg = results["segments"]
    for role in sorted(k for k in seg if k != "overall"):
        m = seg[role]
        row("extraction", "segments", role, "accuracy", m["accuracy"], m["total"], m["total"])
    m = seg["overall"]
    row("extraction", "segments", "overall", "accuracy", m["accuracy"],
        counts["segments"]["gold"], counts["segments"]["pred"])

    c = results["claims"]
    row("extraction", "claims", "overall", "recall", c["recall"],
        counts["claims"]["gold"], counts["claims"]["pred"], c["precision"], c["recall"], c["f1"])
    row("extraction", "claims", "overall", "exact_span_rate", c["exact_span_rate"],
        counts["claims"]["gold"], counts["claims"]["pred"])

    rt = results["routing"]
    for fw in sorted(k for k in rt if k not in ("overall", "product_type_accuracy")):
        m = rt[fw]
        row("extraction", "routing", fw, "f1", m["f1"], m["tp"] + m["fn"], m["tp"] + m["fp"],
            m["precision"], m["recall"], m["f1"])
    m = rt["overall"]
    row("extraction", "routing", "overall", "f1", m["f1"],
        counts["routing"]["gold"], counts["routing"]["pred"], m["precision"], m["recall"], m["f1"])
    row("extraction", "routing", "product_type", "accuracy", rt["product_type_accuracy"],
        results["n_assets"], results["n_assets"])

    # ---- ALIGNMENT DIAGNOSTICS ----
    # Span-strict entities: same numbers, but matched on exact segment_id +
    # char span. Labeled so nobody mistakes this for extraction quality.
    ent_span = results["entities_span"]
    for etype in sorted(k for k in ent_span if k != "overall"):
        m = ent_span[etype]
        row("diagnostic", "entities (span-strict)", etype, "f1", m["f1"],
            m["tp"] + m["fn"], m["tp"] + m["fp"], m["precision"], m["recall"], m["f1"])
    m = ent_span["overall"]
    row("diagnostic", "entities (span-strict)", "overall", "f1", m["f1"],
        counts["entities"]["gold"], counts["entities"]["pred"], m["precision"], m["recall"], m["f1"])

    cv = results["cv"]
    for mtype in sorted(k for k in cv if k != "overall"):
        m = cv[mtype]
        row("diagnostic", "cv_findings", mtype, "mae", m["mae"],
            m["matched"] + m["gold_only"], m["matched"] + m["pred_only"])
    m = cv["overall"]
    row("diagnostic", "cv_findings", "overall", "mae", m["mae"],
        counts["cv"]["gold"], counts["cv"]["pred"])

    return rows


def evaluate_targets(results: dict) -> list[dict]:
    """Resolve each V1 target's actual value (headline metrics only).

    ``passed`` is computed for callers that gate on it (the synthetic
    suites); the gold report shows these as a directional reference and
    ignores the pass/fail flag.
    """
    lookup = {
        ("entities", "f1"): results["entities"]["overall"]["f1"],
        ("claims", "recall"): results["claims"]["recall"],
        ("segments", "accuracy"): results["segments"]["overall"]["accuracy"],
        ("routing", "f1"): results["routing"]["overall"]["f1"],
    }
    out = []
    for t in TARGETS:
        actual = lookup[(t["component"], t["metric"])]
        out.append({**t, "actual": actual, "passed": actual >= t["bar"]})
    return out


def print_table(headers: list[str], rows: list[list[str]], title: str) -> None:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    sep = "─"
    print(f"\n{title}")
    print("┌" + "┬".join(sep * (w + 2) for w in widths) + "┐")
    print("│ " + " │ ".join(h.ljust(w) for h, w in zip(headers, widths)) + " │")
    print("├" + "┼".join(sep * (w + 2) for w in widths) + "┤")
    for r in rows:
        print("│ " + " │ ".join(c.ljust(w) for c, w in zip(r, widths)) + " │")
    print("└" + "┴".join(sep * (w + 2) for w in widths) + "┘")


def _backend_label(results: dict) -> str:
    """Human label for the OCR backend that produced these numbers."""
    backend = results.get("ocr_backend")
    if backend == "paddle":
        return "PaddleOCR (paddle)"
    if backend == "tesseract":
        return "pytesseract (tesseract)"
    return "none (no local OCR ran)"


def _section_table(rows: list[dict], section: str, title: str) -> None:
    section_rows = [r for r in rows if r["section"] == section]
    print_table(
        ["Component", "Detail", "Metric", "Gold", "Pred", "Precision", "Recall", "F1"],
        [
            [
                r["component"], r["detail"],
                f"{r['metric']}={_fmt(r['value'])}",
                _fmt(r["gold_count"]), _fmt(r["pred_count"]),
                _fmt(r["precision"]), _fmt(r["recall"]), _fmt(r["f1"]),
            ]
            for r in section_rows
        ],
        title,
    )


def print_report(results: dict, rows: list[dict], targets: list[dict]) -> None:
    n = results["n_assets"]
    print(f"\n=== AdCoherentLabs Eval Report — {n} asset(s) ===")
    print(f"OCR backend: {_backend_label(results)}   |   tier: {results.get('tier', 'free')}")
    print("Numbers are backend-specific — not comparable across OCR backends.")

    _section_table(
        rows, "extraction",
        "EXTRACTION QUALITY  (headline: value-mode entities, alignment-tolerant "
        "segments/claims, routing)",
    )
    _section_table(
        rows, "diagnostic",
        "ALIGNMENT DIAGNOSTICS  (span-strict = id/offset alignment probe, NOT "
        "extraction quality; cv_findings counts)",
    )

    # Gold is a tiny held-out corpus: show the V1 headline metrics as a
    # directional reference against the bars, with NO pass/fail column.
    # The hard bars are gated only on the synthetic suites.
    ref_rows = []
    for t in targets:
        filled = round(min(t["actual"], 1.0) * 20)
        bar = "█" * filled + "░" * (20 - filled)
        ref_rows.append([
            f"{t['component']}.{t['metric']}", f"{t['actual']:.3f}",
            bar, f"(V1 bar >= {t['bar']:.2f})",
        ])
    print_table(
        ["Metric", "Actual", "", "Reference"], ref_rows,
        f"HELD-OUT REFERENCE (n={n} — directional only; no pass/fail on gold)",
    )
    print("\nHard V1 pass/fail bars are enforced on the synthetic suites "
          "(synth/evaluate.py), where volume supports them.")


def export_csv(rows: list[dict], targets: list[dict], results: dict,
               out_dir: str, timestamp: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"eval_{timestamp}.csv")
    # Bars attach only to the headline (extraction) overall rows, and even
    # then as a directional reference — gold carries no pass/fail verdict.
    target_lookup = {(t["component"], t["metric"]): t for t in targets}
    backend = results.get("ocr_backend") or "none"
    tier = results.get("tier", "free")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "timestamp", "ocr_backend", "tier", "section", "component", "detail",
            "metric", "value", "gold_count", "pred_count", "precision", "recall",
            "f1", "reference_bar",
        ])
        for r in rows:
            t = (target_lookup.get((r["component"], r["metric"]))
                 if r["section"] == "extraction" and r["detail"] == "overall" else None)
            w.writerow([
                timestamp, backend, tier, r["section"], r["component"], r["detail"],
                r["metric"], _fmt(r["value"], 6), r["gold_count"], r["pred_count"],
                _fmt(r["precision"], 6), _fmt(r["recall"], 6), _fmt(r["f1"], 6),
                t["bar"] if t else "",
            ])
    return path


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Score analyze_asset() against gold labels.")
    ap.add_argument("--gold-dir", default=DEFAULT_GOLD_DIR)
    ap.add_argument("--csv-out", default=os.path.join(EVAL_DIR, "results"))
    ap.add_argument("--tier", default="free", choices=("free", "paid"),
                    help="OCR tier: free = local (no API cost), paid = Google Vision")
    args = ap.parse_args()

    corpus = load_gold_corpus(args.gold_dir)
    results = score_corpus(corpus, tier=args.tier)
    rows = build_rows(results)
    targets = evaluate_targets(results)
    print_report(results, rows, targets)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = export_csv(rows, targets, results, args.csv_out, timestamp)
    print(f"CSV report written to {csv_path}")

    # Gold is a held-out directional reference, not a gate: a successful
    # run exits 0 regardless of the bars. Hard pass/fail gating lives in
    # the synthetic suites (synth/evaluate.py).
    return 0


if __name__ == "__main__":
    sys.exit(main())
