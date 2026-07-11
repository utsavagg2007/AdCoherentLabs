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


def per_entity_table(r: dict) -> None:
    print("  entity types:", end=" ")
    for t in sorted(k for k in r["entities"] if k != "overall"):
        m = r["entities"][t]
        print(f"{t}={_fmt(m['f1'])}", end="  ")
    print()


def _load_dir(path: str) -> list[dict]:
    return [json.load(open(p)) for p in sorted(glob.glob(os.path.join(path, "*.json")))]


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
