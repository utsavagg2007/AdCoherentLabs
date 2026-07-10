"""Eval runner: score analyze_asset() outputs against gold labels.

Usage:
    python -m eval.run_eval [--gold-dir data/gold] [--csv-out eval/results]

Loads every gold label from data/gold/*.json (falling back to
eval/sample_gold.json when the directory is missing or empty), runs
analyze_asset() on each asset, scores every component with eval.scorer,
prints a table report with V1 target bars, and writes a CSV row set for
tracking metrics over time.
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

# V1 quality bars. metric_path resolves into the aggregated results dict.
TARGETS = [
    {"component": "entities", "metric": "recall", "bar": 0.90},
    {"component": "entities", "metric": "precision", "bar": 0.95},
    {"component": "claims", "metric": "recall", "bar": 0.85},
    {"component": "routing", "metric": "f1", "bar": 0.80},
    {"component": "segments", "metric": "accuracy", "bar": 0.80},
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
    ent_results, seg_results, claim_results, cv_results = [], [], [], []
    gold_routes, pred_routes = [], []
    counts = {k: {"gold": 0, "pred": 0} for k in ("entities", "segments", "claims", "cv", "routing")}

    for gold in corpus:
        pred = analyze_asset(gold, tier=tier)
        ent_results.append(scorer.entity_metrics(gold["entities"], pred.get("entities", [])))
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

    # Entities: micro-aggregate overall + per-type across assets.
    entity_types = sorted({t for r in ent_results for t in r if t != "overall"})
    entities = {t: scorer.merge_counts([r[t] for r in ent_results if t in r]) for t in entity_types}
    entities["overall"] = scorer.merge_counts([r["overall"] for r in ent_results])

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

    return {
        "entities": entities,
        "segments": segments,
        "claims": claims,
        "routing": routing,
        "cv": cv,
        "counts": counts,
        "n_assets": len(corpus),
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
    """Flatten aggregated results into report rows."""
    rows = []
    counts = results["counts"]

    def row(component, detail, metric, value, gold_count, pred_count, precision=None, recall=None, f1=None):
        rows.append({
            "component": component, "detail": detail, "metric": metric, "value": value,
            "gold_count": gold_count, "pred_count": pred_count,
            "precision": precision, "recall": recall, "f1": f1,
        })

    ent = results["entities"]
    for etype in sorted(k for k in ent if k != "overall"):
        m = ent[etype]
        row("entities", etype, "f1", m["f1"], m["tp"] + m["fn"], m["tp"] + m["fp"],
            m["precision"], m["recall"], m["f1"])
    m = ent["overall"]
    row("entities", "overall", "f1", m["f1"], counts["entities"]["gold"], counts["entities"]["pred"],
        m["precision"], m["recall"], m["f1"])

    seg = results["segments"]
    for role in sorted(k for k in seg if k != "overall"):
        m = seg[role]
        row("segments", role, "accuracy", m["accuracy"], m["total"], m["total"])
    m = seg["overall"]
    row("segments", "overall", "accuracy", m["accuracy"], counts["segments"]["gold"], counts["segments"]["pred"])

    c = results["claims"]
    row("claims", "overall", "recall", c["recall"], counts["claims"]["gold"], counts["claims"]["pred"],
        c["precision"], c["recall"], c["f1"])
    row("claims", "overall", "exact_span_rate", c["exact_span_rate"], counts["claims"]["gold"],
        counts["claims"]["pred"])

    rt = results["routing"]
    for fw in sorted(k for k in rt if k not in ("overall", "product_type_accuracy")):
        m = rt[fw]
        row("routing", fw, "f1", m["f1"], m["tp"] + m["fn"], m["tp"] + m["fp"],
            m["precision"], m["recall"], m["f1"])
    m = rt["overall"]
    row("routing", "overall", "f1", m["f1"], counts["routing"]["gold"], counts["routing"]["pred"],
        m["precision"], m["recall"], m["f1"])
    row("routing", "product_type", "accuracy", rt["product_type_accuracy"],
        results["n_assets"], results["n_assets"])

    cv = results["cv"]
    for mtype in sorted(k for k in cv if k != "overall"):
        m = cv[mtype]
        row("cv", mtype, "mae", m["mae"], m["matched"] + m["gold_only"], m["matched"] + m["pred_only"])
    m = cv["overall"]
    row("cv", "overall", "mae", m["mae"], counts["cv"]["gold"], counts["cv"]["pred"])

    return rows


def evaluate_targets(results: dict) -> list[dict]:
    lookup = {
        ("entities", "recall"): results["entities"]["overall"]["recall"],
        ("entities", "precision"): results["entities"]["overall"]["precision"],
        ("claims", "recall"): results["claims"]["recall"],
        ("routing", "f1"): results["routing"]["overall"]["f1"],
        ("segments", "accuracy"): results["segments"]["overall"]["accuracy"],
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


def print_report(results: dict, rows: list[dict], targets: list[dict]) -> None:
    print(f"\n=== AdCoherentLabs Eval Report — {results['n_assets']} asset(s) ===")

    print_table(
        ["Component", "Detail", "Metric", "Gold", "Pred", "Precision", "Recall", "F1"],
        [
            [
                r["component"], r["detail"],
                f"{r['metric']}={_fmt(r['value'])}",
                _fmt(r["gold_count"]), _fmt(r["pred_count"]),
                _fmt(r["precision"]), _fmt(r["recall"]), _fmt(r["f1"]),
            ]
            for r in rows
        ],
        "Component metrics",
    )

    bar_rows = []
    for t in targets:
        filled = round(min(t["actual"], 1.0) * 20)
        bar = "█" * filled + "░" * (20 - filled)
        status = "PASS ✓" if t["passed"] else "FAIL ✗"
        bar_rows.append([
            f"{t['component']}.{t['metric']}", f">= {t['bar']:.2f}",
            f"{t['actual']:.3f}", bar, status,
        ])
    print_table(["Target", "Bar", "Actual", "", "Status"], bar_rows, "V1 target bars")

    n_pass = sum(t["passed"] for t in targets)
    verdict = "ALL BARS PASS" if n_pass == len(targets) else f"{len(targets) - n_pass} BAR(S) FAILING"
    print(f"\nOverall: {n_pass}/{len(targets)} bars met — {verdict}")


def export_csv(rows: list[dict], targets: list[dict], out_dir: str, timestamp: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"eval_{timestamp}.csv")
    target_lookup = {(t["component"], t["metric"]): t for t in targets}
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "timestamp", "component", "detail", "metric", "value",
            "gold_count", "pred_count", "precision", "recall", "f1", "target_bar", "passed",
        ])
        for r in rows:
            t = target_lookup.get((r["component"], r["metric"])) if r["detail"] == "overall" else None
            w.writerow([
                timestamp, r["component"], r["detail"], r["metric"],
                _fmt(r["value"], 6), r["gold_count"], r["pred_count"],
                _fmt(r["precision"], 6), _fmt(r["recall"], 6), _fmt(r["f1"], 6),
                t["bar"] if t else "", t["passed"] if t else "",
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
    csv_path = export_csv(rows, targets, args.csv_out, timestamp)
    print(f"CSV report written to {csv_path}")

    return 0 if all(t["passed"] for t in targets) else 1


if __name__ == "__main__":
    sys.exit(main())
