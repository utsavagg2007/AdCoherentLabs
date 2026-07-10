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

MUTATIONS: list = []

#: Mutation names added in the full-coverage extension (every check in
#: the registry now has >= 1 mutation); used for the new-only summary.
NEW_MUTATION_NAMES: set[str] = set()


def mutation(name: str, intended: list[str], allowed: list[str] = [],
             base: str | None = None, new: bool = False):
    """Register a mutation.

    fn(asset, output) may return: a mutated output dict (output-only
    corruption), an (asset, output) tuple (asset-side corruption — the
    route for STR checks), or None (inapplicable to this base).

    ``base=None`` runs the mutation against every gold reference pair;
    ``base="fx_<name>"`` runs it once against that fixture base pair.
    Intended checks are asserted in the bucket their registered scope
    dictates: review-scope in failed_checks, asset-scope in
    asset_defects.
    """
    def decorator(fn):
        MUTATIONS.append((name, tuple(intended), tuple(allowed), fn, base))
        if new:
            NEW_MUTATION_NAMES.add(name)
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


@mutation("clear_nonexistent_id", intended=["ALL-GRD-005"])
def clear_nonexistent_id(asset, out):
    """Add an id to reviewed_clear that exists nowhere in the asset —
    the LLM claims to have reviewed something that doesn't exist."""
    out = copy.deepcopy(out)
    out["reviewed_clear"].append("clm_does_not_exist")
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
# Fixture base pairs — minimal (asset, output) pairs that pass baseline,
# for checks whose triggers don't exist in the gold corpus. Mutations
# against these corrupt asset and/or output.
# ---------------------------------------------------------------------------

def _seg(i, text, role="body", bbox=None):
    d = {"segment_id": f"seg_{i}", "text": text, "role": role,
         "source": "text"}
    if bbox:
        d["bbox"] = {"x": bbox[0], "y": bbox[1],
                     "width": bbox[2], "height": bbox[3]}
    return d


def _ent(i, etype, raw, segd, value=None):
    start = segd["text"].index(raw)
    return {"entity_id": f"ent_{i}", "entity_type": etype, "raw_text": raw,
            "normalized_value": value, "segment_id": segd["segment_id"],
            "char_span": {"start": start, "end": start + len(raw)}}


def _clm(i, ctype, segd, text, ents=()):
    start = segd["text"].index(text)
    return {"claim_id": f"clm_{i}", "claim_type": ctype, "text": text,
            "segment_id": segd["segment_id"],
            "char_span": {"start": start, "end": start + len(text)},
            "entity_ids": list(ents), "pattern_id": "fx"}


def _cvf(fid, meas, val, sid, rel=None):
    return {"finding_id": fid, "measurement": meas, "value": val,
            "segment_id": sid, "related_segment_id": rel, "method": "fx"}


def _asset(segs, product, fws, ents=(), clms=(), cv=(), juris=(),
           aid="fx"):
    return {"asset_id": aid, "segments": list(segs), "entities": list(ents),
            "claim_candidates": list(clms), "cv_findings": list(cv),
            "routing": {"product_type": product, "frameworks": list(fws),
                        "signal": "fixture"},
            "target_jurisdictions": list(juris),
            "provenance": {"cv_version": "fx", "nlp_version": "fx",
                           "ruleset_hash": "fx",
                           "timestamp": "2026-07-10T00:00:00Z"}}


def _fnd(fid, fw, verdict, sev, segs=(), ents=(), quote=None, claim=None,
         reasoning="fixture review"):
    return {"finding_id": fid, "framework": fw, "severity": sev,
            "verdict": verdict, "cited_segment_ids": list(segs),
            "cited_entity_ids": list(ents), "quoted_evidence": quote,
            "claim_candidate_id": claim, "reasoning": reasoning}


def _out(findings=(), clear=(), ev=(), aid="fx"):
    return {"asset_id": aid, "findings": list(findings),
            "reviewed_clear": list(clear),
            "frameworks_evaluated": list(ev),
            "llm_meta": {"model": "fx", "prompt_version": "fx-v0"}}


def _fx_credit():
    s1 = _seg(1, "Only $199 per month for 36 months", "headline",
              (0.1, 0.1, 0.8, 0.06))
    s2 = _seg(2, "17.5% APR. Terms and conditions apply.", "fine_print",
              (0.1, 0.9, 0.5, 0.02))
    a = _asset([s1, s2], "personal_loan", ["FTC", "TILA", "CFPB", "ECOA"],
               ents=[_ent(1, "amount", "$199", s1, 199.0),
                     _ent(2, "time_period", "36 months", s1, 1095.75),
                     _ent(3, "apr", "17.5% APR", s2, 17.5)],
               clms=[_clm(1, "pricing", s1, "Only $199 per month",
                          ["ent_1"])],
               cv=[_cvf("cvf_h1", "text_height_percent", 6.0, "seg_1"),
                   _cvf("cvf_h2", "text_height_percent", 2.0, "seg_2"),
                   _cvf("cvf_p1", "disclosure_proximity", 0.30,
                        "seg_1", "seg_2")])
    o = _out(findings=[
        _fnd("f1", "FTC", "compliant", "low", ["seg_1"], ["ent_1"],
             quote="Only $199 per month", claim="clm_1"),
        _fnd("f2", "TILA", "compliant", "low", ["seg_2"], ["ent_3"],
             quote="17.5% APR")],
        ev=["FTC", "TILA", "CFPB", "ECOA"])
    return a, o


def _fx_openend():
    s1 = _seg(1, "Annual fee $95 on the Platinum credit card")
    s2 = _seg(2, "19.9% APR applies after the intro period.", "fine_print")
    a = _asset([s1, s2], "credit_card", ["FTC", "TILA", "CFPB", "ECOA"],
               ents=[_ent(1, "fee", "$95", s1, 95.0),
                     _ent(2, "apr", "19.9% APR", s2, 19.9)])
    o = _out(findings=[_fnd("f1", "TILA", "compliant", "low",
                            ["seg_1", "seg_2"], ["ent_1", "ent_2"],
                            quote="19.9% APR")],
             clear=["seg_1"], ev=["FTC", "TILA", "CFPB", "ECOA"])
    return a, o


def _fx_deposit():
    s1 = _seg(1, "Earn 4.50% APY on your savings account", "headline")
    s2 = _seg(2, "Member FDIC. Terms and conditions apply.", "legal")
    a = _asset([s1, s2], "deposit_account",
               ["FTC", "Reg_DD", "CFPB", "FDIC"],
               ents=[_ent(1, "rate", "4.50%", s1, 4.5)])
    o = _out(findings=[_fnd("f1", "Reg_DD", "compliant", "low",
                            ["seg_1"], ["ent_1"],
                            quote="Earn 4.50% APY on your savings account")],
             clear=["seg_2"], ev=["FTC", "Reg_DD", "CFPB", "FDIC"])
    return a, o


def _fx_crypto():
    s1 = _seg(1, "Trade Bitcoin with confidence on our platform")
    a = _asset([s1], "crypto", ["FTC", "SEC", "FINRA"])
    o = _out(clear=["seg_1"], ev=["FTC", "SEC", "FINRA"])
    return a, o


def _fx_state():
    s1 = _seg(1, "Personal loans from 5.99% APR — season's lowest price",
              "headline")
    s2 = _seg(2, "Rates for qualified borrowers. Terms and conditions "
                 "apply.", "disclosure")
    a = _asset([s1, s2], "personal_loan",
               ["FTC", "TILA", "CFPB", "ECOA", "STATE_UDAP"],
               ents=[_ent(1, "apr", "5.99% APR", s1, 5.99)],
               clms=[_clm(1, "pricing", s1,
                          "Personal loans from 5.99% APR", ["ent_1"])],
               juris=["US-CA", "US-UT"])
    o = _out(findings=[
        _fnd("f_fed", "FTC", "compliant", "low", ["seg_1", "seg_2"],
             ["ent_1"], quote="Personal loans from 5.99% APR",
             claim="clm_1"),
        _fnd("f_state", "STATE_UDAP", "compliant", "low", ["seg_1"],
             reasoning="Reviewed under US-CA (Cal. Bus. & Prof. Code "
                       "§ 17500) and US-UT (§ 13-11a): claim qualified.")],
        clear=["seg_2"],
        ev=["FTC", "TILA", "CFPB", "ECOA", "STATE_UDAP"])
    return a, o


FIXTURE_BASES = {"fx_credit": _fx_credit, "fx_openend": _fx_openend,
                 "fx_deposit": _fx_deposit, "fx_crypto": _fx_crypto,
                 "fx_state": _fx_state}


# ---------------------------------------------------------------------------
# Full-coverage mutations: one per previously-unmutated check
# ---------------------------------------------------------------------------

# ---- universal (gold-based, output-side) ----------------------------------

@mutation("cite_nonexistent_entity", intended=["ALL-GRD-002"], new=True)
def cite_nonexistent_entity(asset, out):
    """Cite an entity id that does not exist in the asset."""
    out = copy.deepcopy(out)
    if not out["findings"]:
        return None
    out["findings"][0]["cited_entity_ids"].append("ent_does_not_exist")
    return out


@mutation("reference_nonexistent_claim", intended=["ALL-GRD-003"], new=True)
def reference_nonexistent_claim(asset, out):
    """Point a finding with no claim reference at a claim that does not
    exist (choosing a null one avoids un-addressing a real claim)."""
    out = copy.deepcopy(out)
    for f in out["findings"]:
        if f.get("claim_candidate_id") is None:
            f["claim_candidate_id"] = "clm_does_not_exist"
            return out
    return None


@mutation("adverse_finding_cites_nothing", intended=["ALL-GRD-006"],
          new=True)
def adverse_finding_cites_nothing(asset, out):
    """Add an adverse finding with zero citations of any kind."""
    out = copy.deepcopy(out)
    out["findings"].append(_fnd("f_mut_uncited", "FTC",
                                "potential_violation", "medium",
                                reasoning="mutation: free-floating"))
    return out


@mutation("wrong_asset_id", intended=["ALL-CON-001"], new=True)
def wrong_asset_id(asset, out):
    """The output claims to review a different asset."""
    out = copy.deepcopy(out)
    out["asset_id"] = "a_completely_different_asset"
    return out


@mutation("invalid_framework_value", intended=["ALL-CON-003"], new=True)
def invalid_framework_value(asset, out):
    """frameworks_evaluated contains a value outside the Framework enum."""
    out = copy.deepcopy(out)
    out["frameworks_evaluated"] = out["frameworks_evaluated"] + ["NOT_A_FRAMEWORK"]
    return out


@mutation("compliant_rated_high", intended=["ALL-CON-004"], new=True)
def compliant_rated_high(asset, out):
    """A compliant verdict carrying high severity is incoherent."""
    out = copy.deepcopy(out)
    for f in out["findings"]:
        if f["verdict"] == "compliant":
            f["severity"] = "high"
            return out
    return None


@mutation("orphan_framework_finding", intended=["ALL-CON-005"], new=True)
def orphan_framework_finding(asset, out):
    """File a finding under a framework the LLM never evaluated."""
    out = copy.deepcopy(out)
    out["findings"].append(_fnd("f_mut_orphan", "FCRA", "compliant", "low",
                                [asset["segments"][0]["segment_id"]],
                                reasoning="mutation: orphan framework"))
    return out


@mutation("missing_meta_key", intended=["ALL-STR-001"], new=True)
def missing_meta_key(asset, out):
    """Drop an audit-chain key from llm_meta."""
    out = copy.deepcopy(out)
    if "prompt_version" not in out["llm_meta"]:
        return None
    del out["llm_meta"]["prompt_version"]
    return out


# ---- FTC5 ------------------------------------------------------------------

@mutation("uncovered_guarantee_language", intended=["FTC5-COV-003"],
          new=True)
def uncovered_guarantee_language(asset, out):
    """Asset-side: inject guaranteed-approval language into a credit ad;
    the output covers none of it."""
    if asset["routing"]["product_type"] not in _CREDIT:
        return None
    asset = copy.deepcopy(asset)
    s = _seg(90, "Guaranteed approval — no credit check!")
    asset["segments"].append(s)
    asset["entities"].append(
        _ent(90, "guarantee_term", "Guaranteed approval", s))
    return asset, copy.deepcopy(out)


@mutation("absolute_claim_no_qualifier", intended=["FTC5-STR-001"],
          base="fx_credit", new=True)
def absolute_claim_no_qualifier(asset, out):
    """Asset-side: add a superlative and demote the only disclosure-role
    segment — absolute claim with no qualifying text anywhere."""
    asset = copy.deepcopy(asset)
    s = _seg(90, "America's best loan, hands down")
    asset["segments"].append(s)
    asset["entities"].append(_ent(90, "superlative", "best", s))
    asset["segments"][1]["role"] = "body"
    return asset, copy.deepcopy(out)


@mutation("disclosure_pushed_away", intended=["FTC5-STR-002"],
          allowed=["REGZ-STR-004"], base="fx_credit", new=True)
def disclosure_pushed_away(asset, out):
    """Asset-side: the measured claim->disclosure distance exceeds
    PROX_MAX. REGZ-STR-004's proximity clause shares the same geometry
    and fails alongside by design."""
    asset = copy.deepcopy(asset)
    for f in asset["cv_findings"]:
        if f["measurement"] == "disclosure_proximity":
            f["value"] = 0.90
    return asset, copy.deepcopy(out)


# ---- Reg Z ------------------------------------------------------------------

@mutation("trigger_terms_without_apr", intended=["REGZ-STR-001"],
          base="fx_credit", new=True)
def trigger_terms_without_apr(asset, out):
    """Asset-side: strip the APR disclosure while trigger terms remain."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["entities"] = [e for e in asset["entities"]
                         if e["entity_type"] != "apr"]
    asset["segments"][1]["text"] = ("Great terms for qualified borrowers. "
                                    "Conditions apply.")
    out["findings"][1]["quoted_evidence"] = "Great terms"
    out["findings"][1]["cited_entity_ids"] = []
    return asset, out


@mutation("rate_never_stated_as_apr", intended=["REGZ-STR-002"],
          allowed=["REGZ-STR-001"], base="fx_credit", new=True)
def rate_never_stated_as_apr(asset, out):
    """Asset-side: the APR becomes a bare rate with no APR wording.
    REGZ-STR-001 also fails by design: removing the APR disclosure trips
    the trigger-term rule too."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["segments"][1]["text"] = ("Low fixed rate of 17.5% for "
                                    "qualified borrowers.")
    asset["entities"] = [e for e in asset["entities"]
                         if e["entity_type"] != "apr"]
    s2 = asset["segments"][1]
    asset["entities"].append(_ent(3, "rate", "17.5%", s2, 17.5))
    out["findings"][1]["quoted_evidence"] = "Low fixed rate of 17.5%"
    return asset, out


@mutation("open_end_fee_without_apr", intended=["REGZ-STR-003"],
          base="fx_openend", new=True)
def open_end_fee_without_apr(asset, out):
    """Asset-side: credit-card fee advertised, APR disclosure stripped."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["entities"] = [e for e in asset["entities"]
                         if e["entity_type"] != "apr"]
    asset["segments"][1]["text"] = "Terms apply after the intro period."
    out["findings"][0]["quoted_evidence"] = None
    out["findings"][0]["cited_entity_ids"] = ["ent_1"]
    return asset, out


@mutation("apr_disclosure_shrunk", intended=["REGZ-STR-004"],
          allowed=["FTC5-STR-002"], base="fx_credit", new=True)
def apr_disclosure_shrunk(asset, out):
    """Asset-side: the APR fine print's measured height falls below the
    ratio floor. FTC5-STR-002's height clause shares the measurement and
    fails alongside by design."""
    asset = copy.deepcopy(asset)
    for f in asset["cv_findings"]:
        if f["finding_id"] == "cvf_h2":
            f["value"] = 0.5
    return asset, copy.deepcopy(out)


@mutation("missing_apr_violation_rated_low", intended=["REGZ-SEV-001"],
          allowed=["REGZ-STR-001"], base="fx_credit", new=True)
def missing_apr_violation_rated_low(asset, out):
    """Asset+output: mandatory APR disclosure missing (REGZ-STR-001
    precondition, by design) AND the TILA violation is waved off as low."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["entities"] = [e for e in asset["entities"]
                         if e["entity_type"] != "apr"]
    asset["segments"][1]["text"] = ("Great terms for qualified borrowers. "
                                    "Conditions apply.")
    f2 = out["findings"][1]
    f2["verdict"], f2["severity"] = "violation", "low"
    f2["quoted_evidence"], f2["cited_entity_ids"] = "Great terms", []
    return asset, out


# ---- Reg DD -----------------------------------------------------------------

@mutation("rate_never_stated_as_apy", intended=["REGDD-STR-001"],
          base="fx_deposit", new=True)
def rate_never_stated_as_apy(asset, out):
    """Asset-side: deposit return stated as 'interest', APY wording gone."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["segments"][0]["text"] = ("Earn 4.50% interest on your savings "
                                    "account")
    asset["entities"][0]["char_span"]["start"] = \
        asset["segments"][0]["text"].index("4.50%")
    asset["entities"][0]["char_span"]["end"] = \
        asset["entities"][0]["char_span"]["start"] + 5
    out["findings"][0]["quoted_evidence"] = asset["segments"][0]["text"]
    return asset, out


@mutation("free_account_with_fee", intended=["REGDD-STR-002"],
          base="fx_deposit", new=True)
def free_account_with_fee(asset, out):
    """Asset-side: 'free checking' plus a positive fee in the same ad."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["segments"][0]["text"] = ("Free checking plus 4.50% APY on your "
                                    "savings account")
    asset["entities"][0]["char_span"]["start"] = \
        asset["segments"][0]["text"].index("4.50%")
    asset["entities"][0]["char_span"]["end"] = \
        asset["entities"][0]["char_span"]["start"] + 5
    s3 = _seg(3, "A $5 monthly maintenance charge applies", "fine_print")
    asset["segments"].append(s3)
    asset["entities"].append(_ent(2, "fee", "$5", s3, 5.0))
    out["findings"][0]["quoted_evidence"] = asset["segments"][0]["text"]
    out["reviewed_clear"].append("seg_3")
    return asset, out


@mutation("bonus_without_conditions", intended=["REGDD-STR-003"],
          base="fx_deposit", new=True)
def bonus_without_conditions(asset, out):
    """Asset-side: a bonus advertised with zero quantified conditions."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["segments"][0]["text"] = ("Welcome bonus when you open a savings "
                                    "account today")
    asset["entities"] = []
    out["findings"][0]["quoted_evidence"] = asset["segments"][0]["text"]
    out["findings"][0]["cited_entity_ids"] = []
    return asset, out


@mutation("deposit_triggers_never_engaged", intended=["REGDD-COV-002"],
          base="fx_deposit", new=True)
def deposit_triggers_never_engaged(asset, out):
    """Output-side: drop the only Reg DD finding; the rate-bearing
    segment is covered by nothing."""
    out = copy.deepcopy(out)
    out["findings"] = []
    return out


@mutation("free_fee_violation_rated_low", intended=["REGDD-SEV-001"],
          allowed=["REGDD-STR-002"], base="fx_deposit", new=True)
def free_fee_violation_rated_low(asset, out):
    """Asset+output: free-with-fees contradiction (REGDD-STR-002
    precondition, by design) AND the Reg DD violation is rated low."""
    mutated = free_account_with_fee(asset, out)
    asset, out = mutated
    f1 = out["findings"][0]
    f1["verdict"], f1["severity"] = "violation", "low"
    return asset, out


# ---- FDIC Part 328 ----------------------------------------------------------

@mutation("fdic_wording_on_crypto", intended=["FDIC328-STR-001"],
          allowed=["FDIC328-STR-002"], base="fx_crypto", new=True)
def fdic_wording_on_crypto(asset, out):
    """Asset-side: insured-status wording lands on a crypto product.
    The hybrid-disclaimer check fails alongside by design ('Bitcoin' is
    investment lexicon and no disclaimer exists)."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["segments"].append(_seg(2, "FDIC insured up to $250,000"))
    out["reviewed_clear"].append("seg_2")
    return asset, out


@mutation("hybrid_ad_without_disclaimer", intended=["FDIC328-STR-002"],
          base="fx_deposit", new=True)
def hybrid_ad_without_disclaimer(asset, out):
    """Asset-side: Member-FDIC deposit ad gains investment content with
    no non-deposit disclaimer."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["segments"].append(
        _seg(3, "Grow your investment portfolio with us"))
    out["reviewed_clear"].append("seg_3")
    return asset, out


@mutation("fdic_misrep_rated_low", intended=["FDIC328-SEV-001"],
          allowed=["FDIC328-STR-001", "FDIC328-STR-002"],
          base="fx_crypto", new=True)
def fdic_misrep_rated_low(asset, out):
    """Asset+output: FDIC wording on an uninsurable product (both STR
    checks fail by design) with the violation rated low."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["segments"].append(_seg(2, "FDIC insured up to $250,000"))
    out["findings"].append(_fnd("f_mut", "SEC", "violation", "low",
                                ["seg_2"],
                                reasoning="mutation: waved-off misrep"))
    return asset, out


# ---- ECOA / Reg B -----------------------------------------------------------

@mutation("ecoa_routed_not_evaluated", intended=["REGB-COV-001"],
          allowed=["ALL-COV-001"], base="fx_credit", new=True)
def ecoa_routed_not_evaluated(asset, out):
    """Output-side: ECOA routed but missing from frameworks_evaluated
    (ALL-COV-001 is the generic companion of any framework drop)."""
    out = copy.deepcopy(out)
    out["frameworks_evaluated"] = [f for f in out["frameworks_evaluated"]
                                   if f != "ECOA"]
    return out


@mutation("uncovered_prohibited_basis", intended=["REGB-COV-002"],
          base="fx_credit", new=True)
def uncovered_prohibited_basis(asset, out):
    """Asset-side: prohibited-basis wording appears in a credit ad and
    the output covers none of it."""
    asset = copy.deepcopy(asset)
    asset["segments"].append(
        _seg(90, "No public assistance recipients need apply"))
    return asset, copy.deepcopy(out)


@mutation("basis_violation_rated_low", intended=["REGB-SEV-001"],
          base="fx_credit", new=True)
def basis_violation_rated_low(asset, out):
    """Asset+output: an affirmed prohibited-basis ECOA violation rated
    low."""
    asset, out = copy.deepcopy(asset), copy.deepcopy(out)
    asset["segments"].append(
        _seg(90, "No public assistance recipients need apply"))
    out["findings"].append(_fnd("f_mut", "ECOA", "violation", "low",
                                ["seg_90"],
                                reasoning="mutation: waved-off basis hit"))
    return asset, out


# ---- STATE_UDAP -------------------------------------------------------------

@mutation("state_udap_never_evaluated", intended=["STATE-COV-001"],
          allowed=["ALL-COV-001", "STATE-COV-002"], base="fx_state",
          new=True)
def state_udap_never_evaluated(asset, out):
    """Output-side: state law routed, but no STATE_UDAP finding and no
    frameworks_evaluated entry. STATE-COV-002 fails alongside by design
    (with no state findings, no state is individually considered)."""
    out = copy.deepcopy(out)
    out["findings"] = [f for f in out["findings"]
                       if f["framework"] != "STATE_UDAP"]
    out["frameworks_evaluated"] = [f for f in out["frameworks_evaluated"]
                                   if f != "STATE_UDAP"]
    return out


@mutation("state_never_individually_considered",
          intended=["STATE-COV-002"], base="fx_state", new=True)
def state_never_individually_considered(asset, out):
    """Output-side: the state finding names only US-CA; US-UT vanishes."""
    out = copy.deepcopy(out)
    for f in out["findings"]:
        if f["framework"] == "STATE_UDAP":
            f["reasoning"] = ("Reviewed under US-CA (Cal. Bus. & Prof. "
                              "Code § 17500): claim qualified.")
    return out


@mutation("federal_hit_state_compliant_unreconciled",
          intended=["STATE-SEV-001"], base="fx_state", new=True)
def federal_hit_state_compliant_unreconciled(asset, out):
    """Output-side: the federal finding becomes a high-severity deception
    hit while the state-compliant verdict never engages it. The flipped
    finding cites only the claim segment — citing the cleared disclosure
    would create an unrelated ALL-CON-002 contradiction."""
    out = copy.deepcopy(out)
    f_fed = next(f for f in out["findings"] if f["framework"] == "FTC")
    f_fed["verdict"], f_fed["severity"] = "potential_violation", "high"
    f_fed["cited_segment_ids"] = ["seg_1"]
    return out


@mutation("utah_price_claims_no_qualifier", intended=["STATE-STR-001"],
          base="fx_state", new=True)
def utah_price_claims_no_qualifier(asset, out):
    """Asset-side: demote the disclosure segment — Utah-targeted pricing
    claims with no qualifying text anywhere."""
    asset = copy.deepcopy(asset)
    asset["segments"][1]["role"] = "body"
    return asset, copy.deepcopy(out)


# ---------------------------------------------------------------------------
# Matrix runner
# ---------------------------------------------------------------------------

def run_matrix():
    from rule_engine import CHECK_REGISTRY

    def baseline(asset, out, label):
        rep = run_checks(asset, out)
        assert rep.passed, (f"base pair {label} no longer passes review "
                            f"checks — fix that before mutating: "
                            f"{[(r.check_id, r.evidence) for r in rep.failed_checks]}")
        return {r.check_id for r in rep.asset_defects}

    gold_pairs = []
    for out_path in sorted(OUT_DIR.glob("*.json")):
        out = json.loads(out_path.read_text())
        asset = next(json.loads(p.read_text()) for p in GOLD_DIR.glob("*.json")
                     if json.loads(p.read_text())["asset_id"] == out["asset_id"])
        defects = baseline(asset, out, out["asset_id"])
        gold_pairs.append((asset, out, defects))

    fixture_pairs = {}
    for name, builder in FIXTURE_BASES.items():
        asset, out = builder()
        defects = baseline(asset, out, name)
        assert not defects, f"fixture base {name} has baseline defects: {defects}"
        fixture_pairs[name] = (asset, out, defects)

    rows = []
    for name, intended, allowed, fn, base in MUTATIONS:
        if base is None:
            bases = gold_pairs
        else:
            bases = [fixture_pairs[base]]
        for asset, out, base_defects in bases:
            mutated = fn(asset, out)
            if mutated is None:
                continue
            if isinstance(mutated, tuple):
                m_asset, m_out = mutated
            else:
                m_asset, m_out = asset, mutated
            report = run_checks(m_asset, m_out)
            failed = {r.check_id for r in report.failed_checks}
            defects = {r.check_id for r in report.asset_defects}
            # each intended check must land in the bucket its registered
            # scope dictates
            caught = all(
                (cid in defects) if CHECK_REGISTRY[cid].scope == "asset"
                else (cid in failed)
                for cid in intended)
            all_fired = failed | defects
            companions = sorted(all_fired & set(allowed))
            cross = sorted(all_fired - set(intended) - set(allowed)
                           - base_defects)
            rows.append({"mutation": name,
                         "asset": base or m_asset["asset_id"],
                         "intended": list(intended), "caught": caught,
                         "companions": companions, "cross_fires": cross,
                         "new": name in NEW_MUTATION_NAMES})
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
    new_rows = [r for r in rows if r["new"]]
    new_caught = sum(r["caught"] for r in new_rows)
    new_cross = sum(len(r["cross_fires"]) for r in new_rows)
    print(f"\nNEW mutations only: {new_caught}/{len(new_rows)} caught "
          f"({100.0 * new_caught / len(new_rows):.1f}%), "
          f"{new_cross} cross-fires" if new_rows else "\nno new mutations")
    print(f"applicable (base, mutation) pairs: {total}")
    print(f"catch rate: {caught}/{total} "
          f"({100.0 * caught / total:.1f}%) — must be 100%")
    print(f"total cross-fires: {cross_total}")
    for r in rows:
        for c in r["cross_fires"]:
            print(f"  CROSS-FIRE to investigate: {c} "
                  f"(mutation={r['mutation']}, base={r['asset']})")

    # full-coverage guarantee: every registered check has >= 1 mutation
    from rule_engine import CHECK_REGISTRY
    covered = set()
    for _, intended, _, _, _ in MUTATIONS:
        covered |= set(intended)
    uncovered = sorted(set(CHECK_REGISTRY) - covered)
    print(f"\ncheck coverage: {len(covered & set(CHECK_REGISTRY))}/"
          f"{len(CHECK_REGISTRY)} registered checks have a mutation"
          + (f" — UNCOVERED: {uncovered}" if uncovered else ""))

    return 0 if caught == total and not uncovered else 1


if __name__ == "__main__":
    sys.exit(main())
