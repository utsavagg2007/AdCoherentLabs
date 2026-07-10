"""Component-level scoring for AssetRepresentation outputs.

Every function compares a gold (hand-labeled) component list against a
predicted one and returns plain dicts of metrics. All functions accept
either Pydantic model instances from ``schema`` or already-dumped dicts —
inputs are normalized up front, so the scorer has no hard dependency on
the model classes at call time.

Matching is one-to-one and greedy: each gold item consumes at most one
prediction and vice versa, so a single prediction can never satisfy two
gold items (which would inflate recall).

Raw ``tp``/``fp``/``fn`` counts are included in every result so that
per-asset results can be summed across a corpus and re-derived with
:func:`prf` — never average per-asset F1 scores directly.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Optional

# Relative tolerance for "value match" mode on normalized numbers.
VALUE_REL_TOL = 1e-6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_dict(obj: Any) -> dict:
    """Accept a Pydantic model or a plain dict; return a plain dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"expected dict or Pydantic model, got {type(obj).__name__}")


def _as_dicts(items: Optional[Iterable[Any]]) -> list[dict]:
    return [_as_dict(i) for i in (items or [])]


def _enum_str(value: Any) -> str:
    """Normalize enum members / raw strings to the wire string."""
    return getattr(value, "value", value)


def _span(item: dict) -> tuple[int, int]:
    cs = item.get("char_span") or {}
    cs = _as_dict(cs)
    return int(cs.get("start", 0)), int(cs.get("end", 0))


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def prf(tp: int, fp: int, fn: int) -> dict:
    """Precision/recall/F1 from raw counts (0.0 where undefined)."""
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def _greedy_match(gold: list[dict], pred: list[dict], is_match) -> tuple[int, int, int]:
    """One-to-one greedy matching; returns (tp, fp, fn)."""
    used = [False] * len(pred)
    tp = 0
    for g in gold:
        for i, p in enumerate(pred):
            if not used[i] and is_match(g, p):
                used[i] = True
                tp += 1
                break
    return tp, len(pred) - tp, len(gold) - tp


def merge_counts(results: Iterable[dict]) -> dict:
    """Sum ``tp``/``fp``/``fn`` across per-asset results and recompute P/R/F1.

    Each input is a flat dict with tp/fp/fn keys (e.g. one type-bucket of
    an entity_metrics result). Use this to aggregate a corpus correctly.
    """
    tp = fp = fn = 0
    for r in results:
        tp += r.get("tp", 0)
        fp += r.get("fp", 0)
        fn += r.get("fn", 0)
    return prf(tp, fp, fn)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


def entity_metrics(
    gold_entities: Iterable[Any],
    pred_entities: Iterable[Any],
    match_mode: str = "span",
) -> dict:
    """Per-entity-type precision/recall/F1.

    match_mode:
      - ``"span"``  — same entity_type, same segment_id, exact char span.
      - ``"value"`` — same entity_type and normalized_value equal within
        relative tolerance (span-agnostic; credits extraction that found
        the right number in a slightly different span). Entities whose
        normalized_value is None match on (type, segment_id, raw_text).

    Returns ``{entity_type: {precision, recall, f1, tp, fp, fn}}`` plus an
    ``"overall"`` micro-averaged bucket.
    """
    if match_mode not in ("span", "value"):
        raise ValueError(f"unknown match_mode: {match_mode!r}")

    gold = _as_dicts(gold_entities)
    pred = _as_dicts(pred_entities)

    def span_match(g: dict, p: dict) -> bool:
        return (
            _enum_str(g.get("entity_type")) == _enum_str(p.get("entity_type"))
            and g.get("segment_id") == p.get("segment_id")
            and _span(g) == _span(p)
        )

    def value_match(g: dict, p: dict) -> bool:
        if _enum_str(g.get("entity_type")) != _enum_str(p.get("entity_type")):
            return False
        gv, pv = g.get("normalized_value"), p.get("normalized_value")
        if gv is None and pv is None:
            return g.get("segment_id") == p.get("segment_id") and (
                (g.get("raw_text") or "").strip().lower()
                == (p.get("raw_text") or "").strip().lower()
            )
        if gv is None or pv is None:
            return False
        return math.isclose(float(gv), float(pv), rel_tol=VALUE_REL_TOL, abs_tol=1e-9)

    is_match = span_match if match_mode == "span" else value_match

    by_type_gold: dict[str, list[dict]] = defaultdict(list)
    by_type_pred: dict[str, list[dict]] = defaultdict(list)
    for g in gold:
        by_type_gold[_enum_str(g.get("entity_type"))].append(g)
    for p in pred:
        by_type_pred[_enum_str(p.get("entity_type"))].append(p)

    out: dict[str, dict] = {}
    total_tp = total_fp = total_fn = 0
    for etype in sorted(set(by_type_gold) | set(by_type_pred)):
        tp, fp, fn = _greedy_match(by_type_gold[etype], by_type_pred[etype], is_match)
        out[etype] = prf(tp, fp, fn)
        total_tp += tp
        total_fp += fp
        total_fn += fn
    out["overall"] = prf(total_tp, total_fp, total_fn)
    return out


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


def segment_metrics(gold_segments: Iterable[Any], pred_segments: Iterable[Any]) -> dict:
    """Role-classification accuracy per role.

    Segments are aligned by normalized text (whitespace-collapsed,
    case-insensitive); a gold segment with no text-matched prediction
    counts as incorrect for its role, so over-merging or dropping
    segments is penalized, not ignored.

    Returns ``{role: {accuracy, correct, total}}`` plus ``"overall"``.
    """
    gold = _as_dicts(gold_segments)
    pred = _as_dicts(pred_segments)

    def norm(text: str) -> str:
        return " ".join((text or "").split()).lower()

    pred_by_text: dict[str, list[dict]] = defaultdict(list)
    for p in pred:
        pred_by_text[norm(p.get("text", ""))].append(p)

    per_role: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})
    for g in gold:
        role = _enum_str(g.get("role", "unknown"))
        per_role[role]["total"] += 1
        candidates = pred_by_text.get(norm(g.get("text", "")), [])
        if candidates:
            p = candidates.pop(0)  # one-to-one: consume the match
            if _enum_str(p.get("role")) == role:
                per_role[role]["correct"] += 1

    out: dict[str, dict] = {}
    total_correct = total = 0
    for role, c in sorted(per_role.items()):
        acc = c["correct"] / c["total"] if c["total"] else 0.0
        out[role] = {"accuracy": acc, "correct": c["correct"], "total": c["total"]}
        total_correct += c["correct"]
        total += c["total"]
    out["overall"] = {
        "accuracy": total_correct / total if total else 0.0,
        "correct": total_correct,
        "total": total,
    }
    return out


# ---------------------------------------------------------------------------
# Claim candidates
# ---------------------------------------------------------------------------


def claim_metrics(gold_claims: Iterable[Any], pred_claims: Iterable[Any]) -> dict:
    """Claim-candidate recall and precision.

    Matching is deliberately lenient (high-recall bias, mirroring the
    layer's job of never missing a claim): a prediction matches a gold
    claim if it has the same claim_type, the same segment, and *any*
    char-span overlap. Exact-span agreement is reported separately as
    ``exact_span_rate`` for diagnostics.

    Returns ``{recall, precision, f1, exact_span_rate, tp, fp, fn}``.
    """
    gold = _as_dicts(gold_claims)
    pred = _as_dicts(pred_claims)

    def overlap_match(g: dict, p: dict) -> bool:
        return (
            _enum_str(g.get("claim_type")) == _enum_str(p.get("claim_type"))
            and g.get("segment_id") == p.get("segment_id")
            and _spans_overlap(_span(g), _span(p))
        )

    def exact_match(g: dict, p: dict) -> bool:
        return overlap_match(g, p) and _span(g) == _span(p)

    tp, fp, fn = _greedy_match(gold, pred, overlap_match)
    exact_tp, _, _ = _greedy_match(gold, pred, exact_match)

    result = prf(tp, fp, fn)
    result["exact_span_rate"] = exact_tp / tp if tp else 0.0
    return result


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def routing_metrics(gold_routing: Any, pred_routing: Any) -> dict:
    """Per-framework precision/recall/F1 over routing decisions.

    Accepts a single RoutingLabel pair or two parallel lists (one label
    per asset). For each asset, each framework in the gold set is a
    positive; frameworks predicted but not gold are false positives.
    product_type agreement is reported as ``product_type_accuracy``.

    Returns ``{framework: {precision, recall, f1, tp, fp, fn}}`` plus
    ``"overall"`` (micro) and ``"product_type_accuracy"``.
    """
    gold_list = gold_routing if isinstance(gold_routing, (list, tuple)) else [gold_routing]
    pred_list = pred_routing if isinstance(pred_routing, (list, tuple)) else [pred_routing]
    if len(gold_list) != len(pred_list):
        raise ValueError(
            f"gold ({len(gold_list)}) and pred ({len(pred_list)}) routing lists differ in length"
        )

    counts: dict[str, dict] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    pt_correct = 0
    for g_raw, p_raw in zip(gold_list, pred_list):
        g, p = _as_dict(g_raw), _as_dict(p_raw)
        g_fw = {_enum_str(f) for f in g.get("frameworks", [])}
        p_fw = {_enum_str(f) for f in p.get("frameworks", [])}
        for fw in g_fw & p_fw:
            counts[fw]["tp"] += 1
        for fw in p_fw - g_fw:
            counts[fw]["fp"] += 1
        for fw in g_fw - p_fw:
            counts[fw]["fn"] += 1
        if _enum_str(g.get("product_type")) == _enum_str(p.get("product_type")):
            pt_correct += 1

    out: dict[str, Any] = {}
    total_tp = total_fp = total_fn = 0
    for fw, c in sorted(counts.items()):
        out[fw] = prf(c["tp"], c["fp"], c["fn"])
        total_tp += c["tp"]
        total_fp += c["fp"]
        total_fn += c["fn"]
    out["overall"] = prf(total_tp, total_fp, total_fn)
    out["product_type_accuracy"] = pt_correct / len(gold_list) if gold_list else 0.0
    return out


# ---------------------------------------------------------------------------
# CV findings
# ---------------------------------------------------------------------------


def cv_metrics(gold_findings: Iterable[Any], pred_findings: Iterable[Any]) -> dict:
    """Mean absolute error of CV measurements, per measurement type.

    Findings are paired by (measurement, segment_id, related_segment_id);
    MAE is computed over paired values only. Unpaired gold findings
    (measurement missing from prediction) and unpaired predictions are
    counted so silent coverage gaps are visible.

    Returns ``{measurement: {mae, matched, gold_only, pred_only}}`` plus
    ``"overall"`` (MAE across all paired findings).
    """
    gold = _as_dicts(gold_findings)
    pred = _as_dicts(pred_findings)

    def key(f: dict) -> tuple:
        return (
            _enum_str(f.get("measurement")),
            f.get("segment_id"),
            f.get("related_segment_id"),
        )

    pred_pool: dict[tuple, list[dict]] = defaultdict(list)
    for p in pred:
        pred_pool[key(p)].append(p)

    per_type: dict[str, dict] = defaultdict(
        lambda: {"errors": [], "gold_only": 0, "pred_only": 0}
    )
    for g in gold:
        mtype = _enum_str(g.get("measurement"))
        pool = pred_pool.get(key(g))
        if pool:
            p = pool.pop(0)
            per_type[mtype]["errors"].append(abs(float(g.get("value", 0.0)) - float(p.get("value", 0.0))))
        else:
            per_type[mtype]["gold_only"] += 1
    for k, leftover in pred_pool.items():
        if leftover:
            per_type[k[0]]["pred_only"] += len(leftover)

    out: dict[str, dict] = {}
    all_errors: list[float] = []
    for mtype, c in sorted(per_type.items()):
        errs = c["errors"]
        all_errors.extend(errs)
        out[mtype] = {
            "mae": sum(errs) / len(errs) if errs else None,
            "matched": len(errs),
            "gold_only": c["gold_only"],
            "pred_only": c["pred_only"],
        }
    out["overall"] = {
        "mae": sum(all_errors) / len(all_errors) if all_errors else None,
        "matched": len(all_errors),
        "gold_only": sum(c["gold_only"] for c in per_type.values()),
        "pred_only": sum(c["pred_only"] for c in per_type.values()),
    }
    return out
