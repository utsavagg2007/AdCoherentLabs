"""Cross-validation harness for the deterministic NLP + routing layers.

Scores the real pipeline against a corpus in TEXT mode (segment texts fed
as newline-joined input), isolating NLP quality from OCR variance. Reuses
``eval.scorer`` with segment-id alignment and value-mode entity matching,
so the numbers credit correct extraction rather than id/span drift.

Run it on three corpora to watch for overfitting:
  * synthetic val   — held-out slice of the reproducible generator;
  * gold / silver   — the real hand-labeled corpora (held-out; never a
    training target).

Usage:
    python -m synth.evaluate                 # synth-val + gold + silver
    python -m synth.evaluate --n 400 --seed 7
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import scorer  # noqa: E402
from eval.run_eval import TARGETS, evaluate_targets  # noqa: E402


def _text_predict(asset: dict, tier: str = "free") -> dict:
    import pipeline
    text = "\n".join(s["text"] for s in asset["segments"])
    rep = pipeline.analyze_asset(
        asset["asset_id"], text=text,
        target_jurisdictions=asset.get("target_jurisdictions") or None,
    )
    return rep.model_dump(mode="json")


def score_text_corpus(corpus: list[dict]) -> dict:
    ent, seg, clm, cv = [], [], [], []
    g_routes, p_routes = [], []
    for gold in corpus:
        pred = _text_predict(gold)
        mapping = scorer.align_segment_ids(gold["segments"], pred.get("segments", []))
        pred = scorer.remap_segment_ids(pred, mapping)
        ent.append(scorer.entity_metrics(gold.get("entities", []),
                                         pred.get("entities", []), match_mode="value"))
        seg.append(scorer.segment_metrics(gold["segments"], pred.get("segments", [])))
        clm.append(scorer.claim_metrics(gold.get("claim_candidates", []),
                                        pred.get("claim_candidates", [])))
        g_routes.append(gold["routing"])
        p_routes.append(pred.get("routing") or {"product_type": "unknown",
                                                "frameworks": [], "signal": ""})

    etypes = sorted({t for r in ent for t in r if t != "overall"})
    entities = {t: scorer.merge_counts([r[t] for r in ent if t in r]) for t in etypes}
    entities["overall"] = scorer.merge_counts([r["overall"] for r in ent])

    roles = sorted({t for r in seg for t in r if t != "overall"})
    segments = {}
    for role in roles + ["overall"]:
        c = sum(r[role]["correct"] for r in seg if role in r)
        t = sum(r[role]["total"] for r in seg if role in r)
        segments[role] = {"accuracy": c / t if t else 0.0, "correct": c, "total": t}

    claims = scorer.merge_counts(clm)
    routing = scorer.routing_metrics(g_routes, p_routes)
    return {"entities": entities, "segments": segments,
            "claims": claims, "routing": routing, "n": len(corpus)}


def _fmt(x):
    return f"{x:.3f}" if isinstance(x, float) else str(x)


def print_summary(name: str, r: dict) -> None:
    e, s = r["entities"]["overall"], r["segments"]["overall"]
    c, rt = r["claims"], r["routing"]
    print(f"\n[{name}]  n={r['n']}")
    print(f"  entities   P={_fmt(e['precision'])} R={_fmt(e['recall'])} "
          f"F1={_fmt(e['f1'])}   (tp={e['tp']} fp={e['fp']} fn={e['fn']})")
    print(f"  segments   role_acc={_fmt(s['accuracy'])} "
          f"({s['correct']}/{s['total']})")
    print(f"  claims     P={_fmt(c['precision'])} R={_fmt(c['recall'])} "
          f"F1={_fmt(c['f1'])}")
    print(f"  routing    F1={_fmt(rt['overall']['f1'])} "
          f"product_acc={_fmt(rt['product_type_accuracy'])}")


#: OCR-noise robustness bar: entities F1 on the noised copy of synth-val
#: (workstream-1 bar; gated whenever --noise runs).
NOISY_ENTITIES_F1_BAR = 0.80


def print_bars(name: str, r: dict, noisy_f1: float | None = None) -> bool:
    """Print the hard V1 pass/fail bars for a synthetic suite and return
    whether all passed.

    These bars (entities F1 >= 0.90 clean / >= 0.80 noisy, claims recall
    >= 0.85, segments role_acc >= 0.85, routing F1 >= 0.90) are gated
    here — on the higher-volume synthetic corpus — not on the tiny
    held-out gold set, where run_eval prints them only as a directional
    reference. ``noisy_f1`` adds the noise bar when a --noise run
    measured it.
    """
    targets = evaluate_targets(r)
    if noisy_f1 is not None:
        targets.append({"component": "entities", "metric": "f1_noisy",
                        "bar": NOISY_ENTITIES_F1_BAR, "actual": noisy_f1,
                        "passed": noisy_f1 >= NOISY_ENTITIES_F1_BAR})
    print(f"\n  V1 bars [{name}]:")
    for t in targets:
        status = "PASS ✓" if t["passed"] else "FAIL ✗"
        print(f"    {t['component']}.{t['metric']:<9} "
              f"{t['actual']:.3f} >= {t['bar']:.2f}   {status}")
    n_pass = sum(t["passed"] for t in targets)
    print(f"  {n_pass}/{len(targets)} bars met")
    return n_pass == len(targets)


def per_entity_table(r: dict) -> None:
    print("  entity types:", end=" ")
    for t in sorted(k for k in r["entities"] if k != "overall"):
        m = r["entities"][t]
        print(f"{t}={_fmt(m['f1'])}", end="  ")
    print()


def _load_dir(path: str) -> list[dict]:
    return [json.load(open(p)) for p in sorted(glob.glob(os.path.join(path, "*.json")))]


# ---------------------------------------------------------------------------
# Phrasing-family gap analysis: bucket entity recall by the generator's
# per-entity phrasing_family tag, so we can rank exactly which (entity_type,
# phrasing_family) pairs the current deterministic patterns miss.
# ---------------------------------------------------------------------------

import math  # noqa: E402
from collections import defaultdict  # noqa: E402


def _predict_pairs(corpus: list[dict]) -> list[tuple[dict, dict]]:
    """(gold, segment-aligned prediction) for every asset, once."""
    pairs = []
    for gold in corpus:
        pred = _text_predict(gold)
        m = scorer.align_segment_ids(gold["segments"], pred.get("segments", []))
        pred = scorer.remap_segment_ids(pred, m)
        pairs.append((gold, pred))
    return pairs


def _value_match(g: dict, p: dict) -> bool:
    """Value-mode entity match, mirroring eval.scorer.entity_metrics."""
    if g.get("entity_type") != p.get("entity_type"):
        return False
    gv, pv = g.get("normalized_value"), p.get("normalized_value")
    if gv is None and pv is None:
        return g.get("segment_id") == p.get("segment_id") and (
            (g.get("raw_text") or "").strip().lower()
            == (p.get("raw_text") or "").strip().lower())
    if gv is None or pv is None:
        return False
    return math.isclose(float(gv), float(pv), rel_tol=1e-6, abs_tol=1e-9)


def family_recall(pairs: list[tuple[dict, dict]]) -> dict:
    """Per-(entity_type, phrasing_family) recall via greedy value matching.

    Returns ``{(etype, family): {tp, fn, recall}}`` counted over gold
    entities — a gold entity is a tp if some value-matching prediction
    survives, else fn.
    """
    agg: dict = defaultdict(lambda: {"tp": 0, "fn": 0})
    for gold, pred in pairs:
        preds = list(pred.get("entities", []))
        used = [False] * len(preds)
        for g in gold.get("entities", []):
            key = (g.get("entity_type"), g.get("phrasing_family", "?"))
            matched = False
            for i, p in enumerate(preds):
                if not used[i] and _value_match(g, p):
                    used[i] = True
                    matched = True
                    break
            agg[key]["tp" if matched else "fn"] += 1
    for k, c in agg.items():
        tot = c["tp"] + c["fn"]
        c["recall"] = c["tp"] / tot if tot else 0.0
    return agg


def false_positive_rate(pairs: list[tuple[dict, dict]]) -> dict:
    """False positives on negative assets (gold has zero entities)."""
    neg_assets = neg_fp = 0
    for gold, pred in pairs:
        if gold.get("negative") or not gold.get("entities"):
            neg_assets += 1
            neg_fp += len(pred.get("entities", []))
    return {"neg_assets": neg_assets, "fp": neg_fp,
            "fp_per_asset": neg_fp / neg_assets if neg_assets else 0.0}


def print_per_type(name: str, r: dict) -> None:
    print(f"\n  [{name}] per-entity-type P / R / F1")
    print(f"    {'type':<16}{'P':>7}{'R':>7}{'F1':>7}{'tp':>6}{'fp':>6}{'fn':>6}")
    for t in sorted(k for k in r["entities"] if k != "overall"):
        m = r["entities"][t]
        print(f"    {t:<16}{m['precision']:>7.3f}{m['recall']:>7.3f}"
              f"{m['f1']:>7.3f}{m['tp']:>6}{m['fp']:>6}{m['fn']:>6}")
    m = r["entities"]["overall"]
    print(f"    {'OVERALL':<16}{m['precision']:>7.3f}{m['recall']:>7.3f}"
          f"{m['f1']:>7.3f}{m['tp']:>6}{m['fp']:>6}{m['fn']:>6}")


def print_clean_vs_noisy(clean: dict, noisy: dict) -> None:
    print("\n=== ENTITY P/R/F1: CLEAN vs OCR-NOISY (synth-val) ===")
    print(f"  {'type':<16}{'F1_clean':>10}{'F1_noisy':>10}{'ΔF1':>8}"
          f"{'R_clean':>9}{'R_noisy':>9}")
    types = sorted((set(clean["entities"]) | set(noisy["entities"])) - {"overall"})
    for t in types + ["overall"]:
        c = clean["entities"].get(t, {"f1": 0, "recall": 0})
        n = noisy["entities"].get(t, {"f1": 0, "recall": 0})
        tag = "OVERALL" if t == "overall" else t
        print(f"  {tag:<16}{c['f1']:>10.3f}{n['f1']:>10.3f}"
              f"{n['f1'] - c['f1']:>+8.3f}{c['recall']:>9.3f}{n['recall']:>9.3f}")


def print_family_gaps(label: str, fam: dict, top: int = 15,
                      min_support: int = 5) -> None:
    print(f"\n=== WORST (entity_type, phrasing_family) GAPS — {label} ===")
    print(f"  (ranked by recall asc; support = gold count >= {min_support})")
    print(f"    {'entity_type':<20}{'phrasing_family':<22}{'recall':>8}"
          f"{'tp':>6}{'fn':>6}{'support':>9}")
    ranked = [(k, c) for k, c in fam.items() if (c["tp"] + c["fn"]) >= min_support]
    ranked.sort(key=lambda kc: (kc[1]["recall"], -(kc[1]["tp"] + kc[1]["fn"])))
    for (et, family), c in ranked[:top]:
        sup = c["tp"] + c["fn"]
        print(f"    {et:<20}{family:<22}{c['recall']:>8.3f}{c['tp']:>6}"
              f"{c['fn']:>6}{sup:>9}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--val-frac", type=float, default=0.25)
    ap.add_argument("--synth-dir", default=None,
                    help="score a dumped synth split dir instead of generating")
    ap.add_argument("--gold-dir", default="data/gold")
    ap.add_argument("--silver-dir", default="data/silver")
    ap.add_argument("--entities", action="store_true", help="print per-type F1")
    ap.add_argument("--noise", action="store_true",
                    help="also score an OCR-noised copy of synth-val (clean vs noisy)")
    ap.add_argument("--family-gaps", action="store_true",
                    help="rank the worst (entity_type, phrasing_family) recall gaps")
    args = ap.parse_args()

    if args.synth_dir:
        val = _load_dir(args.synth_dir)
    else:
        from synth.generator import generate_corpus
        corpus = generate_corpus(args.n, args.seed)
        n_val = int(round(args.n * args.val_frac))
        val = corpus[:n_val]

    results = {}
    results["synth-val"] = score_text_corpus(val)
    if os.path.isdir(args.gold_dir):
        results["gold"] = score_text_corpus(_load_dir(args.gold_dir))
    if os.path.isdir(args.silver_dir):
        results["silver"] = score_text_corpus(_load_dir(args.silver_dir))

    for name, r in results.items():
        print_summary(name, r)
        if args.entities:
            per_entity_table(r)

    # --- Expanded-distribution baseline reporting (synth-val) ---
    if args.entities or args.noise or args.family_gaps:
        print_per_type("synth-val (clean)", results["synth-val"])

    val_pairs = None
    if args.family_gaps:
        val_pairs = _predict_pairs(val)
        fpr = false_positive_rate(val_pairs)
        print(f"\n  false positives on {fpr['neg_assets']} negative assets: "
              f"{fpr['fp']} entities ({fpr['fp_per_asset']:.3f}/asset)")
        # min_support=3: the extractor is deterministic, so even a few
        # examples of a family are a conclusive hit/miss signal.
        print_family_gaps("synth-val CLEAN", family_recall(val_pairs),
                          min_support=3)

    noisy_f1 = None
    if args.noise:
        import random as _random
        from synth.generator import augment_ocr_noise
        rng = _random.Random(args.seed + 1)
        noisy_val = [augment_ocr_noise(a, rng) for a in val]
        noisy_res = score_text_corpus(noisy_val)
        noisy_f1 = noisy_res["entities"]["overall"]["f1"]
        print_clean_vs_noisy(results["synth-val"], noisy_res)
        if args.family_gaps:
            print_family_gaps("synth-val NOISY",
                              family_recall(_predict_pairs(noisy_val)),
                              min_support=3)

    # Hard pass/fail bars gate ONLY the synthetic suite, where volume
    # supports them. gold/silver stay directional (summary only) — they
    # are held-out references, never a tuning/gating target. --noise
    # additionally gates the noisy entities-F1 bar (used by CI).
    synth_passed = print_bars("synth-val", results["synth-val"],
                              noisy_f1=noisy_f1)
    return 0 if synth_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
