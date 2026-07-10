"""Mutation-testing harness for the rule engine.

For every (gold asset, mutation) pair: start from the known-passing
reference LLMOutput in data/llm_outputs/gold/, corrupt it in exactly one
way, run the engine, and assert the mapped check(s) caught it. Two
numbers matter:

- catch rate — must be 100%. A mutation the engine misses is a false
  negative, the exact thing this engine exists to prevent.
- cross-fires — checks failing that are neither the mutation's target
  nor a documented design companion. Each is a false-positive surface
  to investigate. Design companions (e.g. ALL-COV-001 and the
  per-framework COV-001 both firing when a framework is dropped from
  frameworks_evaluated) are declared per mutation and listed, but not
  counted as cross-fires.

Mutations touch only the LLMOutput, so only review-scope checks can
fire; asset-scope checks (the STR family) are exercised by the
synthetic fixture harness instead and asset_defects are ignored here.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rule_engine import run_checks
from rule_engine.lexicons import match_lexicon

GOLD_DIR = Path(__file__).resolve().parent.parent / "data" / "gold"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "llm_outputs" / "gold"

_SUBSTANTIATION_TYPES = {"performance", "comparative", "guarantee", "risk_free"}
_CREDIT = {"credit_card", "personal_loan", "mortgage", "auto_loan", "bnpl"}
_CLOSED_END = {"personal_loan", "mortgage", "auto_loan", "bnpl"}
_NUM_RE = re.compile(r"\$\d[\d,]*(?:\.\d+)?|\d+(?:\.\d+)?%")

#: Output-sensitive framework checks that no gold asset can exercise via
#: an LLMOutput mutation — their triggers are asset-gated and absent from
#: this corpus. All have synthetic-fixture coverage (framework check
#: fixtures built alongside the check modules).
NOT_EXERCISABLE = {
    "FTC5-COV-003": "no gold credit asset carries guaranteed-approval language",
    "REGZ-SEV-001": "requires a trigger-terms-without-APR asset; all TILA gold assets disclose APR",
    "REGDD-COV-002": "no gold deposit asset has rate/free/bonus deposit-terms triggers",
    "REGDD-SEV-001": "requires a free-claim + positive-fee contradiction in the asset",
    "FDIC328-SEV-001": "requires FDIC wording on an uninsurable product (investment/crypto/insurance)",
    "REGB-COV-001": "router never emits ECOA (taxonomy change request #3)",
    "REGB-COV-002": "no prohibited-basis wording in gold credit assets",
    "REGB-SEV-001": "no prohibited-basis wording in gold credit assets",
}

MUTATIONS: list = []


def mutation(name: str, intended: list[str], allowed: list[str] = []):
    """Register fn(asset, output) -> mutated output dict, or None if the
    mutation is structurally inapplicable to this asset."""
    def decorator(fn):
        MUTATIONS.append((name, tuple(intended), tuple(allowed), fn))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Core mutations (spec-mandated seven)
# ---------------------------------------------------------------------------

@mutation("drop_finding_for_claim", intended=["ALL-COV-002"],
          allowed=["FTC5-COV-002"])
def drop_finding_for_claim(asset, out):
    """Delete the first finding that addresses a claim, leaving the claim
    unaddressed. FTC5-COV-002 is a design companion when the claim is a
    substantiation-burden type (same duty, framework attribution)."""
    out = copy.deepcopy(out)
    for i, f in enumerate(out["findings"]):
        cid = f.get("claim_candidate_id")
        if cid and cid not in out["reviewed_clear"]:
            del out["findings"][i]
            return out
    return None


@mutation("cite_nonexistent_segment", intended=["ALL-GRD-001"])
def cite_nonexistent_segment(asset, out):
    """Append a segment id that does not exist to the first finding."""
    out = copy.deepcopy(out)
    if not out["findings"]:
        return None
    out["findings"][0]["cited_segment_ids"].append("seg_does_not_exist")
    return out


@mutation("misquote_evidence", intended=["ALL-GRD-004"])
def misquote_evidence(asset, out):
    """Replace the first quoted_evidence with text not in the asset
    (digit- and lexeme-free so only the verbatim check can fire)."""
    out = copy.deepcopy(out)
    for f in out["findings"]:
        if f.get("quoted_evidence"):
            f["quoted_evidence"] = ("This exact sentence appears nowhere "
                                    "in the creative.")
            return out
    return None


@mutation("change_quoted_number", intended=["ALL-GRD-007"],
          allowed=["ALL-GRD-004"])
def change_quoted_number(asset, out):
    """Alter one money/percent figure inside a quote. ALL-GRD-004 is an
    inherent companion: changing a digit inside a verbatim quote
    necessarily also breaks the verbatim match."""
    out = copy.deepcopy(out)
    values = [e["normalized_value"] for e in asset["entities"]
              if e["normalized_value"] is not None]
    for f in out["findings"]:
        quote = f.get("quoted_evidence") or ""
        m = _NUM_RE.search(quote)
        if not m:
            continue
        tok = m.group(0)
        num = float(tok.lstrip("$").replace(",", "").rstrip("%"))
        v = next(num + d for d in (1, 2, 3)
                 if all(abs(num + d - ev) > 0.005 for ev in values))
        if tok.startswith("$"):
            new = f"${v:,.2f}" if "." in tok else f"${v:,.0f}"
        else:
            decs = len(tok.rstrip("%").split(".")[1]) if "." in tok else 0
            new = f"{v:.{decs}f}%"
        f["quoted_evidence"] = quote.replace(tok, new, 1)
        return out
    return None


@mutation("drop_framework_from_evaluated", intended=["ALL-COV-001"],
          allowed=["FTC5-COV-001", "REGZ-COV-001", "REGDD-COV-001",
                   "REGB-COV-001", "ALL-CON-005"])
def drop_framework_from_evaluated(asset, out):
    """Remove the first evaluated framework. Companions by design: the
    dropped framework's own COV-001 (same duty, framework-attributed) and
    ALL-CON-005 for findings now orphaned under the dropped framework."""
    out = copy.deepcopy(out)
    if not out["frameworks_evaluated"]:
        return None
    out["frameworks_evaluated"] = out["frameworks_evaluated"][1:]
    return out


@mutation("contradict_disclosure_presence", intended=["ALL-CON-002"])
def contradict_disclosure_presence(asset, out):
    """Add an id cited by an adverse finding to reviewed_clear — the
    output simultaneously clears and indicts the same content."""
    out = copy.deepcopy(out)
    for f in out["findings"]:
        if f["verdict"] in ("violation", "potential_violation"):
            contested = f.get("claim_candidate_id") or (
                f["cited_segment_ids"][0] if f["cited_segment_ids"] else None)
            if contested:
                out["reviewed_clear"].append(contested)
                return out
    return None


@mutation("mark_guarantee_claim_compliant_without_reason",
          intended=["FTC5-SEV-001"])
def mark_guarantee_claim_compliant_without_reason(asset, out):
    """Wave off a guarantee/risk_free claim: affirm the violation but rate
    it low. (A literal wrongly-'compliant' verdict is a judgment error a
    deterministic engine cannot see; the mechanizable floor is an affirmed
    violation rated below the severity floor — FTC5-SEV-001.)"""
    out = copy.deepcopy(out)
    claim_types = {c["claim_id"]: c["claim_type"]
                   for c in asset["claim_candidates"]}
    for f in out["findings"]:
        if claim_types.get(f.get("claim_candidate_id")) in ("guarantee",
                                                            "risk_free"):
            f["verdict"] = "violation"
            f["severity"] = "low"
            return out
    return None


# ---------------------------------------------------------------------------
# Framework-specific mutations (one per output-sensitive check)
# ---------------------------------------------------------------------------

def _drop_framework(out, fw):
    if fw not in out["frameworks_evaluated"]:
        return None
    out = copy.deepcopy(out)
    out["frameworks_evaluated"] = [x for x in out["frameworks_evaluated"]
                                   if x != fw]
    return out


@mutation("drop_ftc_from_evaluated", intended=["FTC5-COV-001"],
          allowed=["ALL-COV-001", "ALL-CON-005"])
def drop_ftc_from_evaluated(asset, out):
    """Remove FTC specifically; ALL-COV-001/CON-005 are the generic
    companions of any framework drop."""
    return _drop_framework(out, "FTC")


@mutation("drop_tila_from_evaluated", intended=["REGZ-COV-001"],
          allowed=["ALL-COV-001", "ALL-CON-005"])
def drop_tila_from_evaluated(asset, out):
    if "TILA" not in asset["routing"]["frameworks"]:
        return None
    return _drop_framework(out, "TILA")


@mutation("drop_regdd_from_evaluated", intended=["REGDD-COV-001"],
          allowed=["ALL-COV-001", "ALL-CON-005"])
def drop_regdd_from_evaluated(asset, out):
    if "Reg_DD" not in asset["routing"]["frameworks"]:
        return None
    return _drop_framework(out, "Reg_DD")


@mutation("unaddress_substantiation_claim", intended=["FTC5-COV-002"],
          allowed=["ALL-COV-002"])
def unaddress_substantiation_claim(asset, out):
    """Strip coverage from the first substantiation-burden claim.
    ALL-COV-002 is the superset duty and fires alongside by design."""
    out = copy.deepcopy(out)
    for c in asset["claim_candidates"]:
        if c["claim_type"] not in _SUBSTANTIATION_TYPES:
            continue
        for f in out["findings"]:
            if f.get("claim_candidate_id") == c["claim_id"]:
                f["claim_candidate_id"] = None
                return out
        if c["claim_id"] in out["reviewed_clear"]:
            out["reviewed_clear"].remove(c["claim_id"])
            return out
    return None


def _regz_trigger_segs(asset):
    if asset["routing"]["product_type"] not in _CLOSED_END:
        return None
    amounts = [e for e in asset["entities"] if e["entity_type"] == "amount"]
    periods = [e for e in asset["entities"] if e["entity_type"] == "time_period"]
    lex = [s for s in asset["segments"]
           if match_lexicon("TILA_TRIGGER", s["text"])]
    if not ((amounts and periods) or lex):
        return None
    segs = {s["segment_id"] for s in lex}
    if amounts and periods:
        segs |= {e["segment_id"] for e in amounts + periods}
    return segs


@mutation("remove_tila_engagement", intended=["REGZ-COV-002"])
def remove_tila_engagement(asset, out):
    """One semantic corruption — the LLM ignored the trigger-term geometry
    entirely: drop all TILA findings (their claims move to reviewed_clear
    so claim coverage stays intact) and excise every trigger-bearing
    segment from citations and reviewed_clear."""
    segs = _regz_trigger_segs(asset)
    tila = [f for f in out["findings"] if f["framework"] == "TILA"]
    if not segs or not tila:
        return None
    out = copy.deepcopy(out)
    out["findings"] = [f for f in out["findings"] if f["framework"] != "TILA"]
    for f in tila:
        cid = f.get("claim_candidate_id")
        if cid and cid not in out["reviewed_clear"]:
            out["reviewed_clear"].append(cid)
    out["reviewed_clear"] = [i for i in out["reviewed_clear"] if i not in segs]
    for f in out["findings"]:
        f["cited_segment_ids"] = [i for i in f["cited_segment_ids"]
                                  if i not in segs]
    return out


@mutation("file_tila_finding_on_noncredit", intended=["REGZ-CON-001"])
def file_tila_finding_on_noncredit(asset, out):
    """Add a TILA finding (and TILA to frameworks_evaluated) on an asset
    with no credit product and no apr/rate entities."""
    if asset["routing"]["product_type"] in _CREDIT or any(
            e["entity_type"] in ("apr", "rate") for e in asset["entities"]):
        return None
    out = copy.deepcopy(out)
    out["findings"].append({
        "finding_id": "llmf_mut_tila", "framework": "TILA",
        "severity": "low", "verdict": "compliant",
        "cited_segment_ids": [asset["segments"][0]["segment_id"]],
        "cited_entity_ids": [], "quoted_evidence": None,
        "claim_candidate_id": None,
        "reasoning": "mutation: TILA finding filed on a non-credit asset"})
    if "TILA" not in out["frameworks_evaluated"]:
        out["frameworks_evaluated"].append("TILA")
    return out


@mutation("refile_fdic_under_regdd",
          intended=["REGDD-CON-001", "FDIC328-CON-001"])
def refile_fdic_under_regdd(asset, out):
    """Add a Reg_DD finding whose only evidence is insured-status wording.
    The two boundary guards are mirrors and must BOTH fire — this is the
    designed two-sided policing of the FDIC/Reg-DD conflation."""
    if "Reg_DD" not in out["frameworks_evaluated"]:
        return None
    seg = next((s for s in asset["segments"]
                if match_lexicon("FDIC", s["text"])
                and not match_lexicon("DEPOSIT_TERMS", s["text"])), None)
    if seg is None:
        return None
    out = copy.deepcopy(out)
    out["findings"].append({
        "finding_id": "llmf_mut_fdic", "framework": "Reg_DD",
        "severity": "low", "verdict": "compliant",
        "cited_segment_ids": [seg["segment_id"]],
        "cited_entity_ids": [], "quoted_evidence": seg["text"],
        "claim_candidate_id": None,
        "reasoning": "mutation: insured-status wording filed under Reg DD"})
    return out


@mutation("uncover_fdic_segment", intended=["FDIC328-COV-001"])
def uncover_fdic_segment(asset, out):
    """Remove an insured-status segment from reviewed_clear so nothing in
    the output covers it (applies only when reviewed_clear is its sole
    coverage)."""
    cited = {i for f in out["findings"] for i in f["cited_segment_ids"]}
    for s in asset["segments"]:
        if match_lexicon("FDIC", s["text"]) \
                and s["segment_id"] in out["reviewed_clear"] \
                and s["segment_id"] not in cited:
            out = copy.deepcopy(out)
            out["reviewed_clear"].remove(s["segment_id"])
            return out
    return None


@mutation("file_ecoa_finding_on_noncredit", intended=["REGB-CON-001"])
def file_ecoa_finding_on_noncredit(asset, out):
    """Add an ECOA finding (and ECOA to frameworks_evaluated) on an asset
    with no credit product and no apr/rate/fee entities."""
    if asset["routing"]["product_type"] in _CREDIT or any(
            e["entity_type"] in ("apr", "rate", "fee")
            for e in asset["entities"]):
        return None
    out = copy.deepcopy(out)
    out["findings"].append({
        "finding_id": "llmf_mut_ecoa", "framework": "ECOA",
        "severity": "low", "verdict": "compliant",
        "cited_segment_ids": [asset["segments"][0]["segment_id"]],
        "cited_entity_ids": [], "quoted_evidence": None,
        "claim_candidate_id": None,
        "reasoning": "mutation: ECOA finding filed on a non-credit asset"})
    if "ECOA" not in out["frameworks_evaluated"]:
        out["frameworks_evaluated"].append("ECOA")
    return out


# ---------------------------------------------------------------------------
# Matrix runner
# ---------------------------------------------------------------------------

def run_matrix():
    pairs = []
    for out_path in sorted(OUT_DIR.glob("*.json")):
        out = json.loads(out_path.read_text())
        asset = next(json.loads(p.read_text()) for p in GOLD_DIR.glob("*.json")
                     if json.loads(p.read_text())["asset_id"] == out["asset_id"])
        base = run_checks(asset, out, ruleset_version="taxonomy-v1.1")
        assert base.passed, (f"reference output for {out['asset_id']} no "
                             f"longer passes — fix that before mutating")
        pairs.append((asset, out))

    rows = []
    for name, intended, allowed, fn in MUTATIONS:
        for asset, out in pairs:
            mutated = fn(asset, out)
            if mutated is None:
                continue
            report = run_checks(asset, mutated,
                                ruleset_version="taxonomy-v1.1")
            failed = {r.check_id for r in report.failed_checks}
            caught = set(intended) <= failed
            companions = sorted(failed & set(allowed))
            cross = sorted(failed - set(intended) - set(allowed))
            rows.append({"mutation": name, "asset": asset["asset_id"],
                         "intended": list(intended), "caught": caught,
                         "companions": companions, "cross_fires": cross})
    return rows


def main() -> int:
    rows = run_matrix()

    print(f"{'mutation':44} {'asset':17} {'intended':30} "
          f"{'caught':6} cross-fires")
    print("-" * 118)
    for r in rows:
        cross = ", ".join(r["cross_fires"]) or "-"
        comp = f"  (design co-fires: {', '.join(r['companions'])})" \
            if r["companions"] else ""
        print(f"{r['mutation']:44} {r['asset']:17} "
              f"{'+'.join(r['intended']):30} "
              f"{'YES' if r['caught'] else 'MISS':6} {cross}{comp}")

    by_mutation: dict[str, dict] = {}
    for r in rows:
        agg = by_mutation.setdefault(r["mutation"], {
            "intended": "+".join(r["intended"]), "n": 0, "caught": 0,
            "cross": 0})
        agg["n"] += 1
        agg["caught"] += r["caught"]
        agg["cross"] += len(r["cross_fires"])

    print(f"\n{'mutation':44} {'intended check':30} {'caught?':10} "
          f"cross-fires")
    print("-" * 100)
    for name, agg in by_mutation.items():
        print(f"{name:44} {agg['intended']:30} "
              f"{agg['caught']}/{agg['n']:<8} {agg['cross']}")

    total = len(rows)
    caught = sum(r["caught"] for r in rows)
    cross_total = sum(len(r["cross_fires"]) for r in rows)
    print(f"\napplicable (asset, mutation) pairs: {total}")
    print(f"catch rate: {caught}/{total} "
          f"({100.0 * caught / total:.1f}%) — must be 100%")
    print(f"total cross-fires: {cross_total}")
    for r in rows:
        for c in r["cross_fires"]:
            print(f"  CROSS-FIRE to investigate: {c} "
                  f"(mutation={r['mutation']}, asset={r['asset']})")

    print("\nchecks not exercisable by LLMOutput mutation on the gold "
          "corpus (synthetic-fixture coverage only):")
    for cid, why in NOT_EXERCISABLE.items():
        print(f"  {cid}: {why}")

    return 0 if caught == total else 1


if __name__ == "__main__":
    sys.exit(main())
