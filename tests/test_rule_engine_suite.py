"""Rule-engine layer tests: core machinery, business rules (boundary
conditions), scope split / conflict behavior, lexicons, versioning,
state table, orchestrator, and regression scenarios — including the
full mutation matrix as a single regression gate.

Run independently:  pytest tests/test_rule_engine_suite.py
"""

from __future__ import annotations

import re

import pytest

from conftest import make_asset, make_finding, make_output, make_segment
from rule_engine import (
    CHECK_REGISTRY,
    RULESET_VERSION,
    CheckContext,
    CheckResult,
    EngineReport,
    register_check,
    ruleset_hash,
    run_checks,
)


# ===========================================================================
# core machinery
# ===========================================================================

class TestRegistry:
    def test_all_73_checks_registered(self):
        # 49 (taxonomy §0-§6) + 6 coverage-matrix checks (§7, ruleset
        # 1.5.0) + 13 generated per-framework coverage checks (§7.7,
        # ruleset 1.6.0) + 5 generated advisory checks (§7.8, ruleset
        # 1.7.0 — one per advisory-mechanization matrix row)
        assert len(CHECK_REGISTRY) == 73
        fams = {"coverage", "grounding", "consistency", "structural",
                "severity_sanity", "advisory"}
        for check in CHECK_REGISTRY.values():
            assert set(check.families) <= fams
            assert check.scope in ("review", "asset", "advisory")

    def test_duplicate_id_rejected(self, clean_registry):
        register_check("X-TST-001", families=["coverage"],
                       frameworks=["*"])(lambda ctx: None)
        with pytest.raises(ValueError, match="duplicate"):
            register_check("X-TST-001", families=["coverage"],
                           frameworks=["*"])(lambda ctx: None)

    def test_unknown_family_rejected(self, clean_registry):
        with pytest.raises(ValueError, match="families"):
            register_check("X-TST-002", families=["vibes"],
                           frameworks=["*"])(lambda ctx: None)

    def test_empty_frameworks_rejected(self, clean_registry):
        with pytest.raises(ValueError, match="frameworks"):
            register_check("X-TST-003", families=["coverage"],
                           frameworks=[])(lambda ctx: None)

    def test_bad_scope_rejected(self, clean_registry):
        with pytest.raises(ValueError, match="scope"):
            register_check("X-TST-004", families=["coverage"],
                           frameworks=["*"], scope="cosmic")(lambda ctx: None)


class TestRunChecks:
    def test_framework_gating(self, builders):
        # A Reg_DD-gated check must not run on an FTC-only asset
        asset = make_asset([make_segment(1, "hello")], fws=["FTC"])
        report = run_checks(asset, make_output(clear=["seg_1"]))
        ran = {r.check_id for r in report.results}
        assert "REGDD-COV-001" not in ran
        assert "ALL-CON-001" in ran

    def test_crash_containment(self, clean_registry, builders):
        @register_check("X-CRASH-001", families=["grounding"],
                        frameworks=["*"])
        def crasher(ctx):
            raise KeyError("boom")

        asset = make_asset([make_segment(1, "hello")])
        report = run_checks(asset, make_output(clear=["seg_1"]))
        failed = {r.check_id: r for r in report.failed_checks}
        assert "X-CRASH-001" in failed
        assert "crashed" in failed["X-CRASH-001"].message

    def test_wrong_check_id_containment(self, clean_registry):
        @register_check("X-WRONG-001", families=["grounding"],
                        frameworks=["*"])
        def masquerader(ctx):
            return CheckResult(check_id="SOMEONE-ELSE", passed=True,
                               severity="low", message="m")

        asset = make_asset([make_segment(1, "hello")])
        report = run_checks(asset, make_output(clear=["seg_1"]))
        assert "X-WRONG-001" in {r.check_id for r in report.failed_checks}

    def test_results_sorted_by_check_id(self):
        asset = make_asset([make_segment(1, "hello")])
        report = run_checks(asset, make_output(clear=["seg_1"]))
        ids = [r.check_id for r in report.results]
        assert ids == sorted(ids)

    def test_version_and_hash_stamped(self):
        asset = make_asset([make_segment(1, "hello")])
        report = run_checks(asset, make_output(clear=["seg_1"]))
        assert report.ruleset_version == RULESET_VERSION
        assert re.fullmatch(r"[0-9a-f]{16}", report.ruleset_hash)
        pinned = run_checks(asset, make_output(clear=["seg_1"]),
                            ruleset_version="pinned-v9")
        assert pinned.ruleset_version == "pinned-v9"

    def test_invalid_asset_contract_raises(self):
        with pytest.raises(Exception):
            run_checks({"asset_id": "x"}, make_output())  # no segments

    def test_invalid_output_contract_raises(self):
        asset = make_asset([make_segment(1, "hello")])
        bad = make_output()
        bad["findings"] = [{"finding_id": "f1"}]  # missing required fields
        with pytest.raises(Exception):
            run_checks(asset, bad)

    def test_accepts_parsed_models(self, gold_assets, reference_outputs):
        import schema
        from llm_contract import LLMOutput

        aid = "ref_clean"
        rep = schema.AssetRepresentation.model_validate(gold_assets[aid])
        out = LLMOutput.model_validate(reference_outputs[aid])
        assert run_checks(rep, out).passed


class TestCheckContext:
    def test_lookups_and_addressed_set(self, builders):
        import schema
        from llm_contract import LLMOutput

        seg = make_segment(1, "Get 5.99% APR now")
        asset = make_asset(
            [seg], product="personal_loan", fws=["FTC", "TILA"],
            ents=[{"entity_id": "ent_1", "entity_type": "apr",
                   "raw_text": "5.99% APR", "normalized_value": 5.99,
                   "segment_id": "seg_1",
                   "char_span": {"start": 4, "end": 13}}],
            clms=[{"claim_id": "clm_1", "claim_type": "pricing",
                   "text": "Get 5.99% APR now", "segment_id": "seg_1",
                   "char_span": {"start": 0, "end": 17},
                   "entity_ids": ["ent_1"], "pattern_id": "t"}])
        out = make_output(
            findings=[make_finding("f1", fw="TILA", claim="clm_1",
                                   segs=["seg_1"])],
            clear=["seg_1"], ev=["FTC", "TILA"])
        ctx = CheckContext(schema.AssetRepresentation.model_validate(asset),
                           LLMOutput.model_validate(out))
        assert ctx.segment_by_id["seg_1"].text == "Get 5.99% APR now"
        assert ctx.entity_by_id["ent_1"].normalized_value == 5.99
        assert ctx.claim_by_id["clm_1"].claim_type.value == "pricing"
        assert ctx.routed_frameworks == {"FTC", "TILA"}
        assert set(ctx.findings_by_framework) == {"TILA"}
        assert ctx.addressed_claim_ids == {"clm_1", "seg_1"}


# ===========================================================================
# scope split — conflict resolution between review and asset verdicts
# ===========================================================================

class TestScopeSplit:
    def test_asset_defect_does_not_fail_review(self, builders):
        # Guarantee claim + zero disclosure segments => FTC5-STR-001
        # (asset scope) fires, but the review still passes
        seg = make_segment(1, "Guaranteed approval for all")
        asset = make_asset(
            [seg], product="personal_loan", fws=["FTC", "TILA"],
            ents=[{"entity_id": "ent_1", "entity_type": "guarantee_term",
                   "raw_text": "Guaranteed", "normalized_value": None,
                   "segment_id": "seg_1", "char_span": {"start": 0, "end": 10}}])
        out = make_output(
            findings=[make_finding("f1", fw="FTC",
                                   verdict="potential_violation",
                                   sev="medium", segs=["seg_1"],
                                   ents=["ent_1"])],
            ev=["FTC", "TILA"])  # seg_1 covered via the finding; adding
        # it to reviewed_clear would be an ALL-CON-002 contradiction
        report = run_checks(asset, out)
        assert report.passed  # review-scope clean
        assert "FTC5-STR-001" in {r.check_id for r in report.asset_defects}
        assert "FTC5-STR-001" not in {r.check_id for r in report.failed_checks}

    def test_scope_stamped_from_registration(self):
        asset = make_asset([make_segment(1, "hello")])
        report = run_checks(asset, make_output(clear=["seg_1"]))
        by_id = {r.check_id: r for r in report.results}
        assert by_id["ALL-STR-001"].scope == "review"
        assert by_id["FTC5-STR-001"].scope == "asset"

    def test_contradiction_cleared_and_indicted(self, builders):
        seg = make_segment(1, "Zero fees forever")
        asset = make_asset([seg])
        out = make_output(
            findings=[make_finding("f1", verdict="potential_violation",
                                   sev="medium", segs=["seg_1"])],
            clear=["seg_1"])
        report = run_checks(asset, out)
        assert "ALL-CON-002" in {r.check_id for r in report.failed_checks}

    def test_conflation_guards_fire_as_mirror_pair(self, builders):
        # Insured-status-only evidence filed under Reg_DD trips BOTH
        # boundary guards — the designed two-sided policing
        seg = make_segment(1, "Member FDIC")
        asset = make_asset([seg], product="deposit_account",
                           fws=["FTC", "Reg_DD", "CFPB"])
        out = make_output(
            findings=[make_finding("f1", fw="Reg_DD", segs=["seg_1"])],
            ev=["FTC", "Reg_DD", "CFPB"])
        failed = {r.check_id for r in run_checks(asset, out).failed_checks}
        assert {"REGDD-CON-001", "FDIC328-CON-001"} <= failed


# ===========================================================================
# business rules — boundary conditions on versioned thresholds
# ===========================================================================

def _prominence_asset(prox, height):
    seg1 = make_segment(1, "Double your money fast", role="headline",
                        bbox=(0.1, 0.1, 0.8, 0.06))
    seg2 = make_segment(2, "Results not typical.", role="disclosure",
                        bbox=(0.1, 0.9, 0.3, 0.02))
    return make_asset(
        [seg1, seg2],
        clms=[{"claim_id": "clm_1", "claim_type": "performance",
               "text": "Double your money fast", "segment_id": "seg_1",
               "char_span": {"start": 0, "end": 22}, "entity_ids": [],
               "pattern_id": "t"}],
        cv=[{"finding_id": "h2", "measurement": "text_height_percent",
             "value": height, "segment_id": "seg_2",
             "related_segment_id": None, "method": "t"},
            {"finding_id": "p1", "measurement": "disclosure_proximity",
             "value": prox, "segment_id": "seg_1",
             "related_segment_id": "seg_2", "method": "t"}])


class TestThresholdBoundaries:
    def _run(self, prox, height):
        out = make_output(clear=["clm_1", "seg_1", "seg_2"])
        report = run_checks(_prominence_asset(prox, height), out)
        return "FTC5-STR-002" in {r.check_id for r in report.asset_defects}

    def test_prox_exactly_at_max_passes(self):
        assert self._run(prox=0.60, height=2.0) is False

    def test_prox_just_over_max_fails(self):
        assert self._run(prox=0.601, height=2.0) is True

    def test_height_exactly_at_min_passes(self):
        assert self._run(prox=0.30, height=0.9) is False

    def test_height_just_under_min_fails(self):
        assert self._run(prox=0.30, height=0.899) is True

    def test_num_tol_boundary(self, builders):
        # quoted 5.99 vs entity 5.985 -> |diff| = 0.005 exactly: passes;
        # entity 5.9849 -> 0.0051: fails
        def run(entity_value):
            seg = make_segment(1, "Get 5.99% APR now")
            asset = make_asset(
                [seg],
                ents=[{"entity_id": "ent_1", "entity_type": "apr",
                       "raw_text": "5.99% APR", "normalized_value": entity_value,
                       "segment_id": "seg_1",
                       "char_span": {"start": 4, "end": 13}}])
            out = make_output(
                findings=[make_finding("f1", segs=["seg_1"],
                                       quote="Get 5.99% APR now")],
                clear=["seg_1"])
            report = run_checks(asset, out)
            return "ALL-GRD-007" in {r.check_id for r in report.failed_checks}
        assert run(5.985) is False
        assert run(5.9849) is True

    def test_severity_floor_guarantee_violation(self, builders):
        seg = make_segment(1, "Risk-free returns guaranteed")
        seg2 = make_segment(2, "Investing involves risk.", role="disclosure")
        claim = {"claim_id": "clm_1", "claim_type": "risk_free",
                 "text": seg["text"], "segment_id": "seg_1",
                 "char_span": {"start": 0, "end": len(seg["text"])},
                 "entity_ids": [], "pattern_id": "t"}
        asset = make_asset([seg, seg2], clms=[claim])

        def run(sev):
            out = make_output(
                findings=[make_finding("f1", verdict="violation", sev=sev,
                                       segs=["seg_1"], claim="clm_1")],
                clear=["seg_2"])
            report = run_checks(asset, out)
            return "FTC5-SEV-001" in {r.check_id for r in report.failed_checks}
        assert run("low") is True
        assert run("medium") is False


# ===========================================================================
# lexicons
# ===========================================================================

class TestLexicons:
    def test_word_boundaries(self):
        from rule_engine.lexicons import match_lexicon

        assert match_lexicon("FREE_ACCOUNT", "freedom DEBT RELIEF") == []
        assert "free" in match_lexicon("FREE_ACCOUNT", "Free checking")
        # documented behavior: singular member does not match plurals
        assert match_lexicon("DEPOSIT_TERMS", "Fees may apply") == []

    def test_multiword_preferred_over_prefix(self):
        from rule_engine.lexicons import match_lexicon

        assert match_lexicon("FDIC", "Member FDIC") == ["member fdic"]

    def test_nonword_boundary_members(self):
        from rule_engine.lexicons import match_lexicon

        assert match_lexicon("TILA_TRIGGER", "$500/mo for two years")

    def test_covered_ids_union(self):
        from llm_contract import LLMOutput
        from rule_engine.lexicons import covered_ids

        out = LLMOutput.model_validate(make_output(
            findings=[make_finding("f1", segs=["seg_9"], ents=["ent_9"],
                                   claim="clm_9")],
            clear=["seg_2"]))
        assert covered_ids(out) == {"seg_9", "ent_9", "clm_9", "seg_2"}


# ===========================================================================
# versioning / ruleset identity
# ===========================================================================

class TestVersioning:
    def test_hash_stable_within_process(self):
        assert ruleset_hash() == ruleset_hash()

    def test_hash_changes_when_registry_changes(self, clean_registry):
        before = ruleset_hash()

        @register_check("X-HASH-001", families=["coverage"],
                        frameworks=["*"])
        def extra(ctx):
            return CheckResult(check_id="X-HASH-001", passed=True,
                               severity="low", message="m")
        assert ruleset_hash() != before

    def test_sourceless_check_does_not_crash_hash(self, clean_registry):
        # Regression: inspect.getsource raises OSError for exec-defined
        # functions; the hash must fall back to a bytecode fingerprint
        ns = {}
        exec("def ghost(ctx):\n    return None", ns)
        register_check("X-GHOST-001", families=["coverage"],
                       frameworks=["*"])(ns["ghost"])
        assert re.fullmatch(r"[0-9a-f]{16}", ruleset_hash())

    def test_version_is_semver(self):
        assert re.fullmatch(r"\d+\.\d+\.\d+", RULESET_VERSION)


class TestStateTable:
    def test_shape_and_coverage(self):
        from rule_engine.state_udap_table import STATE_UDAP_TABLE

        assert len(STATE_UDAP_TABLE) == 51  # 50 states + DC
        for code, row in STATE_UDAP_TABLE.items():
            assert re.fullmatch(r"US-[A-Z]{2}", code)
            assert row["statute"] and row["name"]
            assert isinstance(row["credit_exempt"], bool)

    def test_verify_discipline_every_exempt_state_flagged(self):
        from rule_engine.state_udap_table import STATE_UDAP_TABLE

        for code, row in STATE_UDAP_TABLE.items():
            if row["credit_exempt"]:
                assert "VERIFY" in row["notes"], (
                    f"{code}: credit_exempt=True must carry VERIFY — "
                    f"True silently disables checks")


# ===========================================================================
# orchestrator
# ===========================================================================

class TestOrchestrator:
    def _pair(self):
        asset = make_asset([make_segment(1, "Budgeting tips for the year")])
        good = make_output(clear=["seg_1"])
        return asset, good

    def test_passes_round_one(self):
        from rule_engine.orchestrator import evaluate_with_retry

        asset, good = self._pair()
        res = evaluate_with_retry(asset, lambda a, prior: good)
        assert res.status == "passed" and res.rounds == 1
        assert res.ruleset_version == RULESET_VERSION

    def test_retry_fixes_on_round_two(self):
        from rule_engine.orchestrator import build_retry_payload, \
            evaluate_with_retry

        asset, good = self._pair()
        bad = make_output(
            findings=[make_finding("f1", verdict="potential_violation",
                                   sev="low", segs=["seg_404"])],
            clear=["seg_1"])

        def llm(a, prior):
            if prior is None:
                return bad
            payload = build_retry_payload(prior)
            assert any("seg_404" in i.instruction for i in payload)
            return good

        res = evaluate_with_retry(asset, llm, max_rounds=2)
        assert res.status == "passed" and res.rounds == 2
        assert res.round_records[0].retry_payload is not None

    def test_human_review_after_budget(self):
        from rule_engine.orchestrator import evaluate_with_retry

        asset, _ = self._pair()
        bad = make_output(ev=["TILA"], clear=["seg_1"])  # FTC never evaluated
        calls = []
        res = evaluate_with_retry(
            asset, lambda a, prior: (calls.append(1), bad)[1], max_rounds=2)
        assert res.status == "human_review"
        assert res.rounds == 2 and len(calls) == 2
        # budget exhausted -> no payload after the final round
        assert res.round_records[-1].retry_payload is None

    def test_max_rounds_validation(self):
        from rule_engine.orchestrator import evaluate_with_retry

        with pytest.raises(ValueError):
            evaluate_with_retry({}, lambda a, p: {}, max_rounds=0)

    def test_llm_error_on_round_one(self):
        # The very first LLM call fails: no completed rounds, no final
        # report — but a structured llm_error result, never a raise.
        from rule_engine.orchestrator import evaluate_with_retry

        asset, _ = self._pair()

        def exploding(a, prior):
            raise TimeoutError("provider timed out after 30s")

        res = evaluate_with_retry(asset, exploding, max_rounds=2)
        assert res.status == "llm_error"
        assert res.llm_error == "TimeoutError: provider timed out after 30s"
        assert res.rounds == 0 and res.round_records == []
        assert res.final_report is None
        assert res.asset_id == asset["asset_id"]

    def test_llm_error_on_retry_preserves_round_records(self):
        # Round 1 completes (and fails review); the round-2 call raises.
        # The completed round-1 record and report must survive intact.
        from rule_engine.orchestrator import evaluate_with_retry

        asset, _ = self._pair()
        bad = make_output(ev=["TILA"], clear=["seg_1"])  # FTC never evaluated

        def llm(a, prior):
            if prior is None:
                return bad
            raise ConnectionError("rate limited")

        res = evaluate_with_retry(asset, llm, max_rounds=2)
        assert res.status == "llm_error"
        assert res.llm_error == "ConnectionError: rate limited"
        assert res.rounds == 1 and len(res.round_records) == 1
        assert res.round_records[0].report.passed is False
        assert res.final_report is res.round_records[0].report
        # engine identity still logged per scan despite the LLM failure
        assert res.ruleset_version == RULESET_VERSION


# ===========================================================================
# regression gates — reference outputs and the full mutation matrix
# ===========================================================================

class TestRegressionGates:
    def test_all_reference_outputs_pass(self, gold_assets,
                                        reference_outputs):
        for aid, out in reference_outputs.items():
            report = run_checks(gold_assets[aid], out)
            assert report.passed, (aid, [r.check_id
                                         for r in report.failed_checks])

    def test_known_asset_defects_still_detected(self, gold_assets,
                                                reference_outputs):
        # Deliberate true positives — do not tune thresholds to erase
        expected = {"ref_str001": "FTC5-STR-001",
                    "ref_str002": "FTC5-STR-002"}
        for aid, check in expected.items():
            report = run_checks(gold_assets[aid], reference_outputs[aid])
            assert check in {r.check_id for r in report.asset_defects}

    def test_mutation_matrix_full_catch_no_crossfire(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "eval" / \
            "test_rule_engine.py"
        spec = importlib.util.spec_from_file_location("mutation_harness",
                                                      path)
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        rows = harness.run_matrix()
        assert rows and all(r["caught"] for r in rows)
        assert all(not r["cross_fires"] for r in rows)
        covered = set()
        for _, intended, _, _, _ in harness.MUTATIONS:
            covered |= set(intended)
        assert set(CHECK_REGISTRY) <= covered
