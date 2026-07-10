"""NLP layer tests: normalize (segmentation), entities, claims, routing,
embeddings. Unit + integration + functional; the frozen embedding model
is monkeypatched everywhere except the `embed`-marked inference tests.

Run independently:  pytest tests/test_nlp.py
"""

from __future__ import annotations

import time

import pytest

import schema
from nlp.claims import detect_claims
from nlp.entities import extract_entities
from nlp.normalize import segment_text
from nlp.routing import SEMANTIC_FALLBACK_MARKER, route


# ===========================================================================
# normalize — text mode
# ===========================================================================

class TestSegmentTextMode:
    def test_first_chunk_is_headline(self):
        segs = segment_text(text="Big savings now\nApply today for a loan")
        assert segs[0]["role"] == "headline"

    def test_trailing_wall_of_text_is_fine_print(self):
        text = ("Headline\nmiddle line\n"
                "this trailing block has well over eight words of dense "
                "qualifying language in it")
        segs = segment_text(text=text)
        assert segs[-1]["role"] == "fine_print"

    def test_keyword_roles_beat_position(self):
        segs = segment_text(
            text="Member FDIC\nTerms apply. See terms.\nApply now")
        roles = [s["role"] for s in segs]
        assert roles == ["legal", "disclosure", "cta"]

    def test_cta_requires_short_text(self):
        # CTA wording inside a long sentence must not become a CTA
        long = ("Apply now and read this very long sentence about many "
                "wonderful product features and conditions")
        segs = segment_text(text=long)
        assert segs[0]["role"] != "cta"

    def test_empty_and_whitespace_inputs(self):
        assert segment_text(text="") == []
        assert segment_text(text="   \n\n  ") == []
        assert segment_text() == []

    def test_segment_ids_sequential_and_schema_valid(self):
        segs = segment_text(text="A headline\nBody one\nBody two")
        assert [s["segment_id"] for s in segs] == ["seg_1", "seg_2", "seg_3"]
        for s in segs:
            schema.Segment.model_validate(s)


# ===========================================================================
# normalize — HTML mode
# ===========================================================================

class TestSegmentHtmlMode:
    def test_tag_roles(self):
        html = ("<h1>Huge rates</h1><p>Body text here</p>"
                "<small>tiny footnote text</small><button>Apply</button>")
        segs = segment_text(html=html)
        roles = {s["text"]: s["role"] for s in segs}
        assert roles["Huge rates"] == "headline"
        assert roles["Body text here"] == "body"
        assert roles["tiny footnote text"] == "fine_print"
        assert roles["Apply"] == "cta"

    def test_script_and_style_skipped(self):
        html = "<p>real</p><script>var x = 'not text';</script><style>p{}</style>"
        segs = segment_text(html=html)
        assert [s["text"] for s in segs] == ["real"]

    def test_keyword_beats_tag(self):
        # <small>Member FDIC</small> is legal wording, not fine print
        segs = segment_text(html="<small>Member FDIC</small>")
        assert segs[0]["role"] == "legal"

    def test_source_field(self):
        assert segment_text(html="<p>x</p>")[0]["source"] == "html"


# ===========================================================================
# normalize — OCR mode (block merging)
# ===========================================================================

def _line(text, x, y, w, h, conf=0.9):
    return {"text": text, "box": (x, y, w, h), "confidence": conf}


class TestSegmentOcrMode:
    def test_stacked_lines_merge_into_one_block(self):
        # Two rows of same-height text directly stacked -> one segment
        lines = [_line("THE OTHER", 0.1, 0.10, 0.3, 0.05),
                 _line("WAY", 0.1, 0.16, 0.15, 0.05)]
        segs = segment_text(ocr_lines=lines)
        assert len(segs) == 1
        assert segs[0]["text"] == "THE OTHER WAY"

    def test_distant_blocks_stay_separate(self):
        lines = [_line("TOP", 0.1, 0.05, 0.2, 0.05),
                 _line("BOTTOM", 0.1, 0.80, 0.2, 0.05)]
        segs = segment_text(ocr_lines=lines)
        assert len(segs) == 2

    def test_height_ratio_blocks_merge(self):
        # A logo-size line above tiny fine print must not merge (2.1x)
        lines = [_line("synchrony", 0.1, 0.10, 0.3, 0.084),
                 _line("Member FDIC", 0.1, 0.20, 0.3, 0.04)]
        segs = segment_text(ocr_lines=lines)
        assert len(segs) == 2

    def test_band_consolidation_joins_table_row(self):
        # Table cells whose gaps exceed the same-row limit (1.0x height)
        # but stay within the band limit (6.0x height = 0.18 here)
        lines = [_line("U.S. Bank", 0.05, 0.5, 0.15, 0.03),
                 _line("7.20%", 0.35, 0.5, 0.10, 0.03),
                 _line("Weeks", 0.60, 0.5, 0.10, 0.03)]
        segs = segment_text(ocr_lines=lines)
        assert len(segs) == 1
        assert segs[0]["text"] == "U.S. Bank 7.20% Weeks"

    def test_band_consolidation_respects_gap_limit(self):
        # A gap beyond 6.0x line height must NOT band-merge
        lines = [_line("LEFT", 0.05, 0.5, 0.10, 0.03),
                 _line("RIGHT", 0.60, 0.5, 0.10, 0.03)]  # gap 0.45 > 0.18
        assert len(segment_text(ocr_lines=lines)) == 2

    def test_reading_order_left_to_right_top_to_bottom(self):
        lines = [_line("right", 0.5, 0.10, 0.2, 0.05),
                 _line("left", 0.1, 0.10, 0.2, 0.05)]
        segs = segment_text(ocr_lines=lines)
        assert segs[0]["text"] == "left right"

    def test_tallest_upper_block_is_headline(self):
        lines = [_line("HUGE HEADLINE HERE", 0.1, 0.1, 0.8, 0.08),
                 _line("smaller body text right here", 0.1, 0.5, 0.6, 0.03),
                 _line("supporting body copy for the ad", 0.1, 0.6, 0.6, 0.03)]
        segs = segment_text(ocr_lines=lines)
        by_text = {s["text"]: s["role"] for s in segs}
        assert by_text["HUGE HEADLINE HERE"] == "headline"

    def test_distinctly_small_text_is_fine_print(self):
        lines = [_line("NORMAL SIZE HEADLINE", 0.1, 0.1, 0.6, 0.06),
                 _line("normal body block text", 0.1, 0.3, 0.6, 0.05),
                 _line("another normal body block", 0.1, 0.4, 0.6, 0.05),
                 _line("microscopic qualifier text", 0.1, 0.9, 0.4, 0.01)]
        segs = segment_text(ocr_lines=lines)
        by_text = {s["text"]: s["role"] for s in segs}
        assert by_text["microscopic qualifier text"] == "fine_print"

    def test_blank_lines_dropped_and_empty_input(self):
        assert segment_text(ocr_lines=[]) == []
        assert segment_text(ocr_lines=[_line("   ", 0, 0, 0.1, 0.1)]) == []

    def test_accepts_ocrline_objects(self):
        from cv.ocr import OcrLine
        segs = segment_text(ocr_lines=[
            OcrLine("From an object", (0.1, 0.1, 0.4, 0.05), 0.88)])
        assert segs[0]["text"] == "From an object"
        assert segs[0]["ocr_confidence"] == pytest.approx(0.88)

    def test_bbox_is_union_and_schema_valid(self):
        lines = [_line("A", 0.1, 0.10, 0.2, 0.05),
                 _line("B", 0.1, 0.16, 0.3, 0.05)]
        seg = segment_text(ocr_lines=lines)[0]
        assert seg["bbox"]["width"] == pytest.approx(0.3)
        schema.Segment.model_validate(seg)

    def test_ocr_priority_over_html_and_text(self):
        segs = segment_text(text="TEXT", html="<p>HTML</p>",
                            ocr_lines=[_line("OCR", 0.1, 0.1, 0.2, 0.05)])
        assert segs[0]["source"] == "ocr"


# ===========================================================================
# entities
# ===========================================================================

class TestEntities:
    CASES = [
        ("apr", "Rates from 8.99% APR with autopay discount.", 8.99),
        # "rate" is explicit "rate of X%" wording only. An APY-stated
        # yield is a percentage per the gold labeling guide (see below).
        ("rate", "Enjoy a rate of 4.50% on balances.", 4.5),
        # "4.50% APY" is a percentage whose span includes "APY".
        ("percentage", "Earn 4.50% APY on every dollar.", 4.5),
        ("fee", "No annual fee this year.", 0.0),
        ("amount", "Borrow up to $40,000 today.", 40000.0),
        ("percentage", "Members save 72% on interest.", 72.0),
        ("time_period", "Repay over 60 months easily.", 60 * 30.4375),
        # Hyphenated form: spaCy splits "60-month" into three tokens.
        ("time_period", "Approved for a 60-month term.", 60 * 30.4375),
        ("superlative", "The lowest rates in America.", None),
        ("endorsement_marker", "#ad Paid partnership with FinCo.", None),
        ("optout_marker", "Reply STOP to unsubscribe.", None),
        ("guarantee_term", "Completely risk-free approval.", None),
    ]

    @pytest.mark.parametrize("etype,text,norm", CASES,
                             ids=[c[0] for c in CASES])
    def test_each_type_extracts_and_normalizes(self, etype, text, norm):
        ents = extract_entities([{"segment_id": "seg_1", "text": text}])
        matches = [e for e in ents if e["entity_type"] == etype]
        assert matches, f"no {etype} extracted from {text!r}"
        if norm is not None:
            assert matches[0]["normalized_value"] == pytest.approx(norm)
        else:
            assert matches[0]["normalized_value"] is None

    def test_span_integrity(self):
        text = "Get 5.99% APR on loans up to $25,000 for 36 months."
        ents = extract_entities([{"segment_id": "s", "text": text}])
        assert ents
        for e in ents:
            span = e["char_span"]
            assert text[span["start"]:span["end"]] == e["raw_text"]

    def test_overlap_priority_apr_beats_percentage(self):
        ents = extract_entities(
            [{"segment_id": "s", "text": "Just 8.99% APR."}])
        types = [e["entity_type"] for e in ents]
        assert "apr" in types
        assert "percentage" not in types  # subsumed by the apr span

    def test_comma_number_normalization(self):
        ents = extract_entities(
            [{"segment_id": "s", "text": "Save $1,234,567 total"}])
        amounts = [e for e in ents if e["entity_type"] == "amount"]
        assert amounts[0]["normalized_value"] == 1234567.0

    def test_no_entities_in_plain_prose(self):
        ents = extract_entities(
            [{"segment_id": "s", "text": "We love helping people."}])
        assert ents == []

    def test_empty_inputs(self):
        assert extract_entities([]) == []
        assert extract_entities([{"segment_id": "s", "text": ""}]) == []

    def test_deterministic_and_ids_sequential(self):
        segs = [{"segment_id": "a", "text": "8.99% APR and a $29 late fee"},
                {"segment_id": "b", "text": "guaranteed for 12 months"}]
        first, second = extract_entities(segs), extract_entities(segs)
        assert first == second
        assert [e["entity_id"] for e in first] == \
            [f"ent_{i}" for i in range(1, len(first) + 1)]

    def test_schema_valid(self):
        ents = extract_entities(
            [{"segment_id": "seg_1", "text": "Rates from 8.99% APR"}])
        for e in ents:
            schema.Entity.model_validate(e)

    def test_performance_100_segments(self):
        segs = [{"segment_id": f"s{i}",
                 "text": f"Offer {i}: {5 + i % 20}.99% APR on ${1000 * i}"}
                for i in range(1, 101)]
        t0 = time.perf_counter()
        ents = extract_entities(segs)
        elapsed = time.perf_counter() - t0
        assert len(ents) >= 100
        assert elapsed < 10.0, f"too slow: {elapsed:.1f}s for 100 segments"


# ===========================================================================
# claims
# ===========================================================================

@pytest.fixture()
def no_semantic(monkeypatch):
    """Disable the semantic fallback so claim tests never load the
    embedding model."""
    import nlp.claims as claims_mod

    monkeypatch.setattr(claims_mod, "_semantic_claims", lambda text: [])


class TestClaims:
    def test_entity_driven_pricing_claim(self, no_semantic):
        seg = {"segment_id": "s1", "text": "Just 8.99% APR", "role": "body"}
        ents = [{"entity_id": "e1", "entity_type": "apr", "segment_id": "s1"}]
        claims = detect_claims([seg], ents)
        assert [c["claim_type"] for c in claims].count("pricing") == 1
        c = next(c for c in claims if c["claim_type"] == "pricing")
        assert c["pattern_id"] == "ent_apr"
        assert c["entity_ids"] == ["e1"]

    @pytest.mark.parametrize("text,ctype", [
        ("Better than any other banks out there", "comparative"),
        ("Approval guaranteed every time", "guarantee"),
        ("Totally risk-free investing", "risk_free"),
        ("Trusted by five-star reviews", "endorsement"),
        ("Approved in just minutes", "performance"),
        ("Zero fees forever", "pricing"),
    ])
    def test_keyword_driven_types(self, no_semantic, text, ctype):
        seg = {"segment_id": "s1", "text": text, "role": "body"}
        claims = detect_claims([seg], [])
        hit = [c for c in claims if c["claim_type"] == ctype]
        assert hit and hit[0]["pattern_id"] == f"kw_{ctype}"

    def test_dedup_one_claim_per_segment_and_type(self, no_semantic):
        # Entity AND keyword both indicate pricing -> single pricing claim
        seg = {"segment_id": "s1", "text": "8.99% APR and zero fees",
               "role": "body"}
        ents = [{"entity_id": "e1", "entity_type": "apr", "segment_id": "s1"}]
        claims = detect_claims([seg], ents)
        assert [c["claim_type"] for c in claims].count("pricing") == 1

    def test_disclosure_and_legal_roles_skipped(self, no_semantic):
        segs = [{"segment_id": "s1", "text": "Zero fees!", "role": "disclosure"},
                {"segment_id": "s2", "text": "Zero fees!", "role": "legal"}]
        assert detect_claims(segs, []) == []

    def test_span_covers_whole_segment(self, no_semantic):
        seg = {"segment_id": "s1", "text": "Zero fees forever", "role": "body"}
        c = detect_claims([seg], [])[0]
        assert c["char_span"] == {"start": 0, "end": len(seg["text"])}

    def test_semantic_fallback_marked_and_gated(self, monkeypatch):
        import nlp.claims as claims_mod

        monkeypatch.setattr(claims_mod, "_semantic_claims",
                            lambda text: [("guarantee", 0.71)])
        # No rules fire on this text -> fallback runs, sem_ pattern id
        seg = {"segment_id": "s1", "text": "Your approval is assured.",
               "role": "body"}
        claims = detect_claims([seg], [])
        assert claims[0]["pattern_id"] == "sem_guarantee:0.71"
        # Rules fire -> fallback must NOT run even though it would match
        seg2 = {"segment_id": "s2", "text": "Zero fees forever",
                "role": "body"}
        claims2 = detect_claims([seg2], [])
        assert all(not c["pattern_id"].startswith("sem_") for c in claims2)

    def test_schema_valid(self, no_semantic):
        seg = {"segment_id": "s1", "text": "Save 72% vs other banks",
               "role": "body"}
        for c in detect_claims([seg], []):
            schema.ClaimCandidate.model_validate(c)


# ===========================================================================
# routing
# ===========================================================================

def _segs(*texts):
    return [{"segment_id": f"seg_{i}", "text": t, "role": "body",
             "source": "text"} for i, t in enumerate(texts, 1)]


class TestRouting:
    def test_ftc_always_routed(self):
        r = route(_segs("Hello world, buy our widget"), [])
        assert r["frameworks"][0] == "FTC"

    def test_credit_product_routes_tila_cfpb_ecoa(self):
        r = route(_segs("Get a personal loan today"), [])
        assert {"TILA", "CFPB", "ECOA"} <= set(r["frameworks"])
        assert r["product_type"] == "personal_loan"

    def test_credit_repair_gets_no_ecoa(self):
        r = route(_segs("Debt relief and debt settlement services"), [])
        assert r["product_type"] == "credit_repair"
        assert "ECOA" not in r["frameworks"]

    def test_deposit_terms_route_reg_dd(self):
        r = route(_segs("Open a savings account, earn APY"), [])
        assert r["product_type"] == "deposit_account"
        assert "Reg_DD" in r["frameworks"]

    def test_fdic_wording_routes_fdic_not_deposit(self):
        # Regression (change request #2): "Member FDIC" alone must not
        # imply a deposit product / Reg DD
        r = route(_segs("THIS WAY", "synchrony", "Member FDIC"), [])
        assert "FDIC" in r["frameworks"]
        assert "Reg_DD" not in r["frameworks"]
        assert r["product_type"] == "unknown"

    def test_deposit_insurance_phrase_not_a_deposit_signal(self):
        r = route(_segs("Your funds carry deposit insurance protection"), [])
        assert r["product_type"] != "deposit_account"
        assert "FDIC" in r["frameworks"]

    def test_investment_routes_sec_finra(self):
        r = route(_segs("Grow your investment portfolio with stocks"), [])
        assert {"SEC", "FINRA"} <= set(r["frameworks"])

    def test_optout_entity_routes_canspam_tcpa(self):
        r = route(_segs("Reply STOP to unsubscribe"),
                  [{"entity_type": "optout_marker", "segment_id": "seg_1"}])
        assert {"CAN-SPAM", "TCPA"} <= set(r["frameworks"])

    def test_state_udap_rule_path(self):
        r = route(_segs("Get a personal loan today"), [],
                  target_jurisdictions=["US-CA", "US-TX"])
        assert "STATE_UDAP" in r["frameworks"]
        assert "targets US-CA, US-TX -> state UDAP applies" in r["signal"]

    def test_us_nationwide_alone_is_not_state_targeting(self):
        r = route(_segs("Get a personal loan today"), [],
                  target_jurisdictions=["US"])
        assert "STATE_UDAP" not in r["frameworks"]

    def test_fallback_path_keeps_fdic_and_state(self, monkeypatch):
        # Regression: the semantic-fallback early return used to skip
        # the FDIC wording check entirely
        import nlp.routing as routing_mod

        monkeypatch.setattr(
            routing_mod, "_semantic_route",
            lambda text: (0.42, "credit/APR marketing", ["TILA", "CFPB"]))
        r = route(_segs("Take control of your money, Member FDIC"), [],
                  target_jurisdictions=["US-NY"])
        assert SEMANTIC_FALLBACK_MARKER in r["signal"]
        assert "FDIC" in r["frameworks"]
        assert "STATE_UDAP" in r["frameworks"]
        assert "targets US-NY -> state UDAP applies" in r["signal"]

    def test_no_fallback_without_financial_wording(self, monkeypatch):
        import nlp.routing as routing_mod

        def boom(text):  # pragma: no cover - must not be called
            raise AssertionError("semantic fallback ran on non-financial text")
        monkeypatch.setattr(routing_mod, "_semantic_route", boom)
        r = route(_segs("Fresh flowers delivered daily"), [])
        assert r["frameworks"] == ["FTC"]

    def test_frameworks_deduped_and_schema_valid(self):
        r = route(_segs("personal loan personal loan personal loan"), [])
        assert len(r["frameworks"]) == len(set(r["frameworks"]))
        schema.RoutingLabel.model_validate(r)


# ===========================================================================
# embeddings — real frozen-model inference (cached locally)
# ===========================================================================

@pytest.mark.embed
class TestEmbeddings:
    def test_self_similarity_and_symmetry(self):
        from nlp.embeddings import semantic_similarity

        s = "Open a savings account with a great APY"
        assert semantic_similarity(s, s) == pytest.approx(1.0, abs=1e-4)
        a, b = "low APR loans", "high yield savings"
        assert semantic_similarity(a, b) == pytest.approx(
            semantic_similarity(b, a), abs=1e-6)

    def test_related_text_scores_above_unrelated(self):
        from nlp.embeddings import semantic_similarity

        ref = "Apply now for a credit card or loan with a low APR."
        related = semantic_similarity("Get a personal loan, 5.99% APR", ref)
        unrelated = semantic_similarity("Fresh flowers delivered daily", ref)
        assert related > unrelated

    def test_version_string_pinned(self):
        from nlp.embeddings import MODEL_NAME, get_embedding_model_version

        v = get_embedding_model_version()
        assert v.startswith(MODEL_NAME)


# ===========================================================================
# integration — full text pipeline
# ===========================================================================

class TestPipelineTextIntegration:
    def test_text_asset_end_to_end(self):
        from pipeline import analyze_asset

        rep = analyze_asset(
            "it_text", text="Get 5.99% APR, guaranteed approval!",
            target_jurisdictions=["US-CA"])
        assert isinstance(rep, schema.AssetRepresentation)
        assert rep.segments and rep.entities and rep.claim_candidates
        fws = [f.value for f in rep.routing.frameworks]
        assert "FTC" in fws and "STATE_UDAP" in fws
        assert rep.target_jurisdictions == ["US-CA"]
        # deterministic: identical run yields identical structures
        rep2 = analyze_asset(
            "it_text", text="Get 5.99% APR, guaranteed approval!",
            target_jurisdictions=["US-CA"])
        exclude = {"provenance"}  # timestamp differs by design
        assert rep.model_dump(exclude=exclude) == \
            rep2.model_dump(exclude=exclude)
