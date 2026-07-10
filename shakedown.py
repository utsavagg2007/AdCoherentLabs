"""Shakedown: full pipeline + rule-engine plumbing on fresh media.

For every image (or carousel folder) in data/shakedown/: run
pipeline.analyze_asset (tier=free), build a naive "perfect echo"
LLMOutput — one compliant finding per claim candidate with real cited
ids and verbatim quotes — and push the pair through the orchestrator.
No scoring, no labels: the output is shakedown_report.md, a
human-readable eyeball report with a failures & anomalies section on
top. The echo is NOT a real LLM; a review-scope check failing against
its own echo means a plumbing/contract bug and is reported loudly.
Asset-scope defects are pipeline signal, not failures, and are listed
per asset.
"""

from __future__ import annotations

import os

# Pin OCR thread counts BEFORE paddle loads: with SHAKEDOWN_WORKERS
# processes running in parallel, each gets cores/workers threads instead
# of every worker oversubscribing the whole machine.
_WORKERS = max(1, int(os.environ.get("SHAKEDOWN_WORKERS", "3")))
_THREADS = str(max(1, (os.cpu_count() or 4) // _WORKERS))
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, _THREADS)

import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path
from statistics import median

from pipeline import analyze_asset
from rule_engine import RULESET_VERSION, ruleset_hash
from rule_engine.checks_universal import _MONEY_RE, _PERCENT_RE, NUM_TOL
from rule_engine.orchestrator import evaluate_with_retry

SHAKEDOWN_DIR = Path("data/shakedown")
REPORT_PATH = Path("shakedown_report.md")
IMG_EXTS = {".jpg", ".jpeg", ".png"}
LATENCY_OUTLIER_FACTOR = 3.0  # x median, with a 5 s floor


def discover_assets():
    """(asset_id, [image paths], kind) per entry; plus skipped names."""
    assets, skipped = [], []
    for p in sorted(SHAKEDOWN_DIR.iterdir()):
        if p.is_dir():
            cards = sorted(f for f in p.iterdir()
                           if f.suffix.lower() in IMG_EXTS)
            if cards:
                assets.append((p.name, cards,
                               f"carousel ({len(cards)} cards)"))
            else:
                skipped.append(p.name)
        elif p.suffix.lower() in IMG_EXTS:
            assets.append((p.stem, [p], "single image"))
        else:
            skipped.append(p.name)
    return assets, skipped


def build_echo(rep) -> tuple[dict, list[str]]:
    """Perfect-echo LLMOutput for an AssetRepresentation.

    One compliant finding per claim candidate, cited ids taken straight
    from the claim, quote = the claim's exact char span. Quotes whose
    money/percent figures match no extracted entity (within NUM_TOL) are
    omitted — such a figure is an extraction gap, and quoting it would
    make ALL-GRD-007 fire and masquerade as a plumbing bug. Those claim
    ids are returned as `unquotable` for the anomalies section.
    reviewed_clear lists every segment so lexicon-coverage checks (FDIC
    wording etc.) see a review that examined everything.
    """
    fws = [f.value for f in rep.routing.frameworks]
    finding_fw = "FTC" if "FTC" in fws else fws[0]
    seg_text = {s.segment_id: s.text for s in rep.segments}
    values = [e.normalized_value for e in rep.entities
              if e.normalized_value is not None]
    findings, unquotable = [], []
    for i, c in enumerate(rep.claim_candidates, 1):
        quote = seg_text[c.segment_id][c.char_span.start:c.char_span.end]
        tokens = ([float(t.lstrip("$ ").replace(",", ""))
                   for t in _MONEY_RE.findall(quote)]
                  + [float(t.rstrip("% "))
                     for t in _PERCENT_RE.findall(quote)])
        quotable = all(any(abs(t - v) <= NUM_TOL for v in values)
                       for t in tokens)
        if not quotable:
            unquotable.append(c.claim_id)
        findings.append({
            "finding_id": f"echo_{i:03d}",
            "framework": finding_fw,
            "severity": "low",
            "verdict": "compliant",
            "cited_segment_ids": [c.segment_id],
            "cited_entity_ids": list(c.entity_ids),
            "quoted_evidence": quote if quotable else None,
            "claim_candidate_id": c.claim_id,
            "reasoning": f"shakedown echo of {c.claim_type.value} claim "
                         f"{c.claim_id}; not a real review",
        })
    return {
        "asset_id": rep.asset_id,
        "findings": findings,
        "reviewed_clear": [s.segment_id for s in rep.segments],
        "frameworks_evaluated": fws,
        "llm_meta": {"model": "shakedown-echo", "prompt_version": "echo-v0"},
    }, unquotable


def classify_crash(tb: str) -> str:
    if "segments" in tb and ("too_short" in tb or "at least 1" in tb
                             or "min_length" in tb):
        return "zero-OCR (no text found, empty segments fail the schema)"
    return "crash"


def process_asset(spec: tuple) -> dict:
    """Worker: analyze one asset + run the engine echo. Returns a plain
    picklable row dict. Runs in a pool process; the OCR model is lazily
    initialized once per worker."""
    idx, asset_id, paths, kind = spec
    row = {"idx": idx, "asset_id": asset_id, "kind": kind,
           "thumb": paths[0], "crash": None}

    t0 = time.perf_counter()
    try:
        rep = analyze_asset(
            asset_id,
            image_path=paths[0] if len(paths) == 1 else paths,
            tier="free")
    except Exception:
        row["latency"] = time.perf_counter() - t0
        tb = traceback.format_exc()
        row["crash"] = {"kind": classify_crash(tb), "traceback": tb}
        return row
    row["latency"] = time.perf_counter() - t0

    row["segments"] = len(rep.segments)
    row["entities"] = Counter(e.entity_type.value for e in rep.entities)
    row["claims"] = len(rep.claim_candidates)
    row["cv"] = len(rep.cv_findings)
    row["product"] = rep.routing.product_type.value
    row["frameworks"] = [f.value for f in rep.routing.frameworks]
    row["signal"] = rep.routing.signal
    sem_claims = [c.claim_id for c in rep.claim_candidates
                  if str(c.pattern_id or "").startswith("sem_")]
    row["fallback"] = {
        "embedding_model_version": rep.provenance.embedding_model_version,
        "routing_fallback": "semantic-similarity fallback"
                            in rep.routing.signal,
        "semantic_claims": sem_claims,
    }
    row["first_segments"] = [(s.segment_id, s.role.value, s.text)
                             for s in rep.segments[:3]]

    echo, unquotable = build_echo(rep)
    row["unquotable"] = unquotable
    try:
        t1 = time.perf_counter()
        res = evaluate_with_retry(rep, lambda a, prior: echo,
                                  max_rounds=2)
        row["engine_ms"] = (time.perf_counter() - t1) * 1000
        row["engine_status"] = res.status
        row["engine_rounds"] = res.rounds
        row["engine_failed"] = [
            {"check_id": f.check_id, "message": f.message}
            for f in res.final_report.failed_checks]
        row["asset_defects"] = [
            {"check_id": f.check_id, "severity": f.severity,
             "message": f.message}
            for f in res.final_report.asset_defects]
    except Exception:
        row["engine_status"] = "ENGINE CRASH"
        row["engine_crash_tb"] = traceback.format_exc()
    return row


def main() -> int:
    assets, skipped = discover_assets()
    print(f"shakedown: {len(assets)} assets in {SHAKEDOWN_DIR}/ "
          f"({len(skipped)} non-image entries skipped) | "
          f"{_WORKERS} workers x {_THREADS} OCR threads", flush=True)

    specs = [(i, asset_id, [str(p) for p in paths], kind)
             for i, (asset_id, paths, kind) in enumerate(assets)]
    t_run = time.perf_counter()
    rows = []
    if _WORKERS == 1:
        results = map(process_asset, specs)
    else:
        pool = Pool(processes=_WORKERS)
        results = pool.imap_unordered(process_asset, specs)
    for n, row in enumerate(results, 1):
        rows.append(row)
        if row["crash"]:
            status = f"CRASH after {row['latency']:.1f}s"
        else:
            ok = (row["engine_status"] == "passed"
                  and row.get("engine_rounds") == 1)
            status = (f"{row['latency']:.1f}s, {row['segments']} segs, "
                      f"{row['claims']} claims, engine "
                      f"{'OK' if ok else row['engine_status'].upper()}")
        print(f"[{n}/{len(specs)} done] {row['asset_id']} "
              f"({row['kind']}): {status}", flush=True)
    if _WORKERS > 1:
        pool.close()
        pool.join()
    rows.sort(key=lambda r: r["idx"])

    write_report(rows, skipped)
    print(f"\ntotal wall time: {time.perf_counter() - t_run:.0f}s | "
          f"report written to {REPORT_PATH}", flush=True)
    return 0


def _anomalies(rows, skipped):
    out = []
    analyzed = [r for r in rows if not r["crash"]]
    med = median(r["latency"] for r in analyzed) if analyzed else 0.0
    for name in skipped:
        out.append(f"**SKIPPED** `{name}`: unsupported media "
                   f"(not an image or image folder)")
    for r in rows:
        if r["crash"]:
            tail = r["crash"]["traceback"].strip().splitlines()[-1]
            out.append(f"**{r['crash']['kind'].upper()}** `{r['asset_id']}`: "
                       f"`{tail}` — full traceback in stdout log; "
                       f"reproduce with `analyze_asset('{r['asset_id']}', "
                       f"image_path=..., tier='free')`")
            continue
        if r["segments"] == 0:
            out.append(f"**ZERO SEGMENTS** `{r['asset_id']}`: OCR produced "
                       f"no usable text")
        if not r["frameworks"]:
            out.append(f"**EMPTY ROUTING** `{r['asset_id']}`: no frameworks "
                       f"assigned — router bug")
        if r["engine_status"] != "passed" or r.get("engine_rounds") != 1:
            detail = (r.get("engine_crash_tb", "").strip().splitlines()[-1:]
                      or [", ".join(f"{f['check_id']} ({f['message']})"
                                    for f in r.get("engine_failed", []))])
            out.append(f"**ENGINE** `{r['asset_id']}`: echo output did not "
                       f"pass round 1 (status={r['engine_status']}) — this "
                       f"is a plumbing/contract bug: {detail[0]}")
        if med and r["latency"] > max(LATENCY_OUTLIER_FACTOR * med, 5.0):
            out.append(f"**LATENCY** `{r['asset_id']}`: {r['latency']:.1f}s "
                       f"vs median {med:.1f}s")
        if r.get("unquotable"):
            out.append(f"**EXTRACTION GAP** `{r['asset_id']}`: claims "
                       f"{r['unquotable']} contain money/percent figures "
                       f"matching no extracted entity — echo left those "
                       f"quotes empty; check nlp/entities.py recall on this "
                       f"asset's text")
    return out


def write_report(rows, skipped):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Shakedown report",
        "",
        f"run: {now} | tier: free (local OCR) | ruleset: {RULESET_VERSION} "
        f"@ `{ruleset_hash()}` | assets: {len(rows)}",
        "",
        "No scoring, no labels. Engine ran against a synthetic 'perfect "
        "echo' of each asset's own structure — engine failures here mean "
        "plumbing bugs, not compliance verdicts. Asset defects are "
        "deterministic statements about the ads themselves.",
        "",
        "## Failures & anomalies",
        "",
    ]
    anomalies = _anomalies(rows, skipped)
    if anomalies:
        lines += [f"- {a}" for a in anomalies]
    else:
        lines.append("- none — all assets analyzed, all echoes passed "
                     "round 1, no outliers.")

    lines += ["", "## Summary", "",
              "| asset | media | latency (s) | segs | entities | claims | "
              "cv | product | frameworks | fallback | engine |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["crash"]:
            lines.append(f"| {r['asset_id']} | {r['kind']} | "
                         f"{r['latency']:.1f} | — | — | — | — | — | — | — | "
                         f"{r['crash']['kind'].upper()} |")
            continue
        fb = "yes" if (r["fallback"]["routing_fallback"]
                       or r["fallback"]["semantic_claims"]) else "no"
        eng = ("passed r1" if r["engine_status"] == "passed"
               and r["engine_rounds"] == 1 else r["engine_status"])
        lines.append(
            f"| {r['asset_id']} | {r['kind']} | {r['latency']:.1f} | "
            f"{r['segments']} | {sum(r['entities'].values())} | "
            f"{r['claims']} | {r['cv']} | {r['product']} | "
            f"{', '.join(r['frameworks'])} | {fb} | {eng} |")

    lines += ["", "## Per-asset detail", ""]
    for r in rows:
        lines += [f"### {r['asset_id']}", "",
                  f"![{r['asset_id']}]({r['thumb']})", "",
                  f"- media: {r['kind']} | latency: {r['latency']:.1f}s"]
        if r["crash"]:
            tb_tail = "\n".join(
                r["crash"]["traceback"].strip().splitlines()[-6:])
            lines += [f"- **{r['crash']['kind'].upper()}**:",
                      "", "```", tb_tail, "```", ""]
            continue
        ents = ", ".join(f"{k}: {v}" for k, v in
                         sorted(r["entities"].items())) or "none"
        lines += [
            f"- segments: {r['segments']} | claims: {r['claims']} | "
            f"cv findings: {r['cv']}",
            f"- entities: {ents}",
            f"- routing: **{r['product']}** -> "
            f"{', '.join(r['frameworks'])}",
            f"- routing signal: {r['signal'][:200]}",
            f"- semantic fallback: routing="
            f"{r['fallback']['routing_fallback']}, "
            f"sem claims={r['fallback']['semantic_claims'] or 'none'}, "
            f"embedding={r['fallback']['embedding_model_version'] or '—'}",
        ]
        eng = ("passed round 1"
               if r["engine_status"] == "passed" and r["engine_rounds"] == 1
               else f"**{r['engine_status']}**")
        defects = ", ".join(f"{d['check_id']} [{d['severity']}]"
                            for d in r.get("asset_defects", [])) or "none"
        lines += [f"- engine: {eng} ({r.get('engine_ms', 0):.0f} ms) | "
                  f"asset defects: {defects}"]
        if r.get("unquotable"):
            lines.append(f"- unquotable claims (extraction gaps): "
                         f"{r['unquotable']}")
        lines += ["", "| segment | role | text (first 3, OCR eyeball) |",
                  "|---|---|---|"]
        for sid, role, text in r["first_segments"]:
            safe = text[:90].replace("|", "\\|")
            lines.append(f"| {sid} | {role} | {safe} |")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines))


if __name__ == "__main__":
    import sys
    sys.exit(main())
