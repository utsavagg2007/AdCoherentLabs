"""CV layer tests: measure (pure math), markers, and the tiered OCR
provider. Real OCR inference is faked with a deterministic pipeline so
tests cover image reading (multiple formats), box normalization, tier
dispatch, and error handling without model downloads. Opt into a real
backend run with RUN_OCR_TESTS=1.

Run independently:  pytest tests/test_cv.py
"""

from __future__ import annotations

import math
import os

import pytest

import schema
from cv.markers import detect_markers, has_marker
from cv.measure import contrast_ratio, proximity, relative_luminance, \
    text_height_pct
from cv.ocr import OcrLine, _norm_box, run_ocr, run_ocr_google_vision, \
    run_ocr_local


# ===========================================================================
# measure — deterministic arithmetic
# ===========================================================================

class TestMeasure:
    def test_contrast_black_on_white_is_21(self):
        assert contrast_ratio((0, 0, 0), (255, 255, 255)) == \
            pytest.approx(21.0)

    def test_contrast_same_color_is_1(self):
        assert contrast_ratio((128, 128, 128), (128, 128, 128)) == \
            pytest.approx(1.0)

    def test_contrast_symmetric(self):
        a, b = (10, 200, 30), (240, 12, 250)
        assert contrast_ratio(a, b) == pytest.approx(contrast_ratio(b, a))

    def test_contrast_within_schema_bounds(self):
        # random-ish sweep stays inside CVFinding's [1, 21]
        colors = [(0, 0, 0), (255, 255, 255), (7, 99, 200), (200, 200, 0),
                  (128, 0, 128), (37, 37, 37)]
        for fg in colors:
            for bg in colors:
                assert 1.0 <= contrast_ratio(fg, bg) <= 21.0

    def test_luminance_known_values(self):
        assert relative_luminance((0, 0, 0)) == pytest.approx(0.0)
        assert relative_luminance((255, 255, 255)) == pytest.approx(1.0)
        # green dominates the coefficients
        assert relative_luminance((0, 255, 0)) > \
            relative_luminance((255, 0, 0)) > relative_luminance((0, 0, 255))

    def test_text_height_pct(self):
        assert text_height_pct(24, 1200) == pytest.approx(2.0)
        assert text_height_pct(0, 100) == 0.0

    def test_text_height_pct_rejects_bad_image_height(self):
        with pytest.raises(ValueError):
            text_height_pct(10, 0)
        with pytest.raises(ValueError):
            text_height_pct(10, -5)

    def test_proximity_coincident_and_known_distance(self):
        box = (0.1, 0.2, 0.3, 0.1)
        assert proximity(box, box) == 0.0
        a, b = (0.2, 0.2, 0.1, 0.1), (0.2, 0.6, 0.1, 0.1)
        assert proximity(a, b) == pytest.approx(0.4)

    def test_proximity_opposite_corners_is_sqrt2(self):
        a = (0.0, 0.0, 0.0, 0.0)
        b = (1.0, 1.0, 0.0, 0.0)
        assert proximity(a, b) == pytest.approx(math.sqrt(2))

    def test_proximity_symmetric(self):
        a, b = (0.1, 0.1, 0.2, 0.1), (0.7, 0.6, 0.2, 0.2)
        assert proximity(a, b) == pytest.approx(proximity(b, a))


# ===========================================================================
# markers
# ===========================================================================

class TestMarkers:
    @pytest.mark.parametrize("text", [
        "#ad Big rates inside",
        "Paid Partnership with FinCo",
        "paid  partnership announcement",
        "SPONSORED content follows",
    ])
    def test_positive_markers(self, text):
        assert has_marker(text)

    @pytest.mark.parametrize("text", [
        "Take #advantage of our rewards",   # substring of a word
        "Unsponsored opinions from members",
        "##ad is not a marker",
        "paid for by donors",               # 'paid' without 'partnership'
        "",
    ])
    def test_negative_markers(self, text):
        assert not has_marker(text)

    def test_detect_markers_values_and_shape(self):
        lines = [OcrLine("Earn 4.50% APY", (0.1, 0.1, 0.8, 0.1), 0.99),
                 {"text": "#ad Sponsored"},
                 "plain string line"]
        findings = detect_markers(lines)
        assert [f["value"] for f in findings] == [0.0, 1.0, 0.0]
        assert [f["finding_id"] for f in findings] == \
            ["cvf_marker_1", "cvf_marker_2", "cvf_marker_3"]
        for f in findings:
            schema.CVFinding.model_validate(f)

    def test_empty_input(self):
        assert detect_markers([]) == []


# ===========================================================================
# OCR — dataclass, normalization, dispatch, error handling
# ===========================================================================

class TestOcrLineAndNormBox:
    def test_ocrline_is_frozen(self):
        line = OcrLine("x", (0, 0, 0.1, 0.1), 0.5)
        with pytest.raises(Exception):
            line.text = "y"

    def test_norm_box_basic(self):
        assert _norm_box(10, 20, 110, 60, 200, 100) == \
            pytest.approx((0.05, 0.2, 0.5, 0.4))

    def test_norm_box_clamps_out_of_bounds(self):
        x, y, w, h = _norm_box(-50, -10, 400, 300, 200, 100)
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
        assert x + w <= 1.0 + 1e-9 and y + h <= 1.0 + 1e-9


class TestRunOcrLocal:
    def test_missing_file_returns_empty_without_engine(self, monkeypatch):
        # Guard: the missing-file path must not initialize any backend
        import cv.ocr as ocr

        def boom():  # pragma: no cover - must not be called
            raise AssertionError("engine initialized for a missing file")
        monkeypatch.setattr(ocr, "_get_engine", boom)
        assert run_ocr_local("/nonexistent/nope.jpg") == []

    def test_corrupt_image_returns_empty(self, monkeypatch, tmp_path):
        import cv.ocr as ocr

        def boom():  # pragma: no cover
            raise AssertionError("engine initialized for a corrupt file")
        monkeypatch.setattr(ocr, "_get_engine", boom)
        bad = tmp_path / "corrupt.jpg"
        bad.write_bytes(b"this is not an image at all")
        assert run_ocr_local(str(bad)) == []

    @pytest.mark.parametrize("ext", ["png", "jpg", "bmp"])
    def test_formats_read_and_normalized(self, fake_paddle_engine,
                                         tiny_images, ext):
        lines = run_ocr_local(tiny_images[ext])
        assert [l.text for l in lines] == \
            ["Earn 4.50% APY today", "#ad Sponsored"]
        for l in lines:
            x, y, w, h = l.box
            assert 0 <= x <= 1 and 0 <= y <= 1
            assert 0 < w <= 1 and 0 < h <= 1
            assert 0 <= l.confidence <= 1

    def test_output_consistency_same_image_twice(self, fake_paddle_engine,
                                                 tiny_images):
        assert run_ocr_local(tiny_images["png"]) == \
            run_ocr_local(tiny_images["png"])

    def test_engine_inference_failure_returns_empty(self, monkeypatch,
                                                    tiny_images):
        import cv.ocr as ocr

        class Exploding:
            def predict(self, img):
                raise RuntimeError("inference exploded")
        monkeypatch.setattr(ocr, "_engine", ("paddle", Exploding()))
        assert run_ocr_local(tiny_images["png"]) == []

    def test_blank_texts_skipped(self, monkeypatch, tiny_images):
        import cv.ocr as ocr

        class Blanky:
            def predict(self, img):
                return [{"rec_texts": ["  ", "real"],
                         "rec_scores": [0.9, 0.8],
                         "rec_polys": [[(0, 0), (10, 0), (10, 5), (0, 5)],
                                       [(0, 10), (10, 10), (10, 15), (0, 15)]]}]
        monkeypatch.setattr(ocr, "_engine", ("paddle", Blanky()))
        lines = run_ocr_local(tiny_images["png"])
        assert [l.text for l in lines] == ["real"]

    def test_tesseract_backend_groups_words_into_lines(self, monkeypatch,
                                                       tiny_images):
        import cv.ocr as ocr

        class FakeTesseract:
            class Output:
                DICT = "dict"

            @staticmethod
            def image_to_data(img, output_type=None):
                return {
                    "text": ["Earn", "4.50%", "", "Apply"],
                    "conf": ["96", "90", "-1", "88"],
                    "block_num": [1, 1, 1, 2],
                    "par_num": [1, 1, 1, 1],
                    "line_num": [1, 1, 1, 1],
                    "left": [10, 60, 0, 10],
                    "top": [10, 10, 0, 40],
                    "width": [40, 50, 0, 40],
                    "height": [10, 10, 0, 10],
                }
        monkeypatch.setattr(ocr, "_engine", ("tesseract", FakeTesseract()))
        lines = run_ocr_local(tiny_images["png"])
        assert [l.text for l in lines] == ["Earn 4.50%", "Apply"]
        assert lines[0].confidence == pytest.approx(0.93)


class TestRunOcrDispatcher:
    def test_invalid_tier_raises(self):
        with pytest.raises(ValueError, match="unknown OCR tier"):
            run_ocr("whatever.jpg", tier="premium")

    def test_free_tier_never_returns_signals(self, fake_paddle_engine,
                                             tiny_images):
        lines, signals, backend = run_ocr(tiny_images["png"], tier="free")
        assert signals == []
        assert lines
        assert backend == "paddle"    # named per call, not shared state

    def test_paid_without_credentials_names_env_var(self, monkeypatch,
                                                    tiny_images):
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        with pytest.raises(RuntimeError,
                           match="GOOGLE_APPLICATION_CREDENTIALS"):
            run_ocr_google_vision(tiny_images["png"])

    def test_paid_tier_falls_back_to_local(self, monkeypatch,
                                           fake_paddle_engine, tiny_images,
                                           capsys):
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        lines, signals, backend = run_ocr(tiny_images["png"], tier="paid")
        assert signals == []          # served by the local fallback
        assert lines                  # ...which still produced text
        assert backend == "paddle"    # the fallback names itself honestly
        assert "falling back to local OCR" in capsys.readouterr().err

    def test_paid_tier_success_passes_signals_through(self, monkeypatch,
                                                      tiny_images):
        import cv.ocr as ocr

        canned = ([OcrLine("From Vision", (0.1, 0.1, 0.5, 0.1), 0.99)],
                  [{"signal_type": "label", "value": "Font",
                    "confidence": 0.9, "source": "google_vision"}])
        monkeypatch.setattr(ocr, "run_ocr_google_vision",
                            lambda path: canned)
        lines, signals, backend = run_ocr(tiny_images["png"], tier="paid")
        assert (lines, signals) == canned
        assert backend == "google_vision"

    def test_signal_helper_clamps_confidence(self):
        from cv.ocr import _signal

        s = _signal("web_entity", "FinCo", 1.7)  # web scores can exceed 1
        assert s["confidence"] == 1.0
        schema.SemanticSignal.model_validate(s)


@pytest.mark.ocr_engine
@pytest.mark.skipif(not os.environ.get("RUN_OCR_TESTS"),
                    reason="real OCR backend is slow; set RUN_OCR_TESTS=1")
class TestRealOcrBackend:
    def test_real_backend_reads_tiny_image(self, tiny_images):
        lines = run_ocr_local(tiny_images["png"])
        assert isinstance(lines, list)  # blank bar image may yield []


# ===========================================================================
# integration — OCR output feeds segmentation and markers
# ===========================================================================

class TestCvNlpIntegration:
    def test_fake_ocr_through_segmentation(self, fake_paddle_engine,
                                           tiny_images):
        from nlp.normalize import segment_text

        lines, _, _ = run_ocr(tiny_images["png"], tier="free")
        segments = segment_text(ocr_lines=lines)
        assert segments
        for s in segments:
            schema.Segment.model_validate(s)
        marker_findings = detect_markers(lines)
        assert any(f["value"] == 1.0 for f in marker_findings)

    def test_pipeline_single_image(self, fake_paddle_engine, tiny_images):
        from pipeline import analyze_asset

        rep = analyze_asset("img_asset", image_path=tiny_images["png"],
                            tier="free")
        assert isinstance(rep, schema.AssetRepresentation)
        assert rep.segments and rep.cv_findings
        kinds = {f.measurement.value for f in rep.cv_findings}
        assert {"marker_presence", "text_height_percent"} <= kinds
        assert rep.semantic_signals == []  # free tier

    def test_pipeline_carousel_encodes_card_ids(self, fake_paddle_engine,
                                                tiny_images):
        from pipeline import analyze_asset

        rep = analyze_asset(
            "carousel_asset",
            image_path=[tiny_images["png"], tiny_images["jpg"]],
            tier="free")
        seg_ids = [s.segment_id for s in rep.segments]
        assert any(i.startswith("seg_c1_") for i in seg_ids)
        assert any(i.startswith("seg_c2_") for i in seg_ids)
        assert len(seg_ids) == len(set(seg_ids))


# ===========================================================================
# concurrency — provenance must come from each call's own OCR return value
# ===========================================================================

class TestConcurrentProvenance:
    def test_concurrent_tiers_each_get_own_backend(self, fake_paddle_engine,
                                                   tiny_images, monkeypatch):
        """Two analyze_asset calls on different tiers, running on real
        threads with both OCR calls in flight simultaneously (barrier),
        must each stamp THEIR OWN backend into provenance. Regression
        for the removed cv.ocr._last_served shared global, which let one
        call's backend overwrite another's."""
        import threading
        import time

        import cv.ocr as ocr
        from pipeline import analyze_asset

        barrier = threading.Barrier(2, timeout=10)

        def fake_vision(path):
            barrier.wait()          # meet the free-tier call mid-flight
            time.sleep(0.05)        # keep both calls overlapping
            return ([OcrLine("Earn 4.50% APY today", (0.1, 0.1, 0.8, 0.1),
                             0.99)],
                    [{"signal_type": "label", "value": "bank",
                      "confidence": 0.9, "source": "google_vision"}])

        real_local = ocr.run_ocr_local

        def slow_local(path, max_dim=None):
            barrier.wait()
            time.sleep(0.05)
            return real_local(path, max_dim)

        monkeypatch.setattr(ocr, "run_ocr_google_vision", fake_vision)
        monkeypatch.setattr(ocr, "run_ocr_local", slow_local)

        results: dict = {}
        errors: list = []

        def scan(name, tier):
            try:
                results[name] = analyze_asset(
                    name, image_path=tiny_images["png"], tier=tier)
            except Exception as exc:  # surfaced after join
                errors.append((name, exc))

        threads = [threading.Thread(target=scan, args=("paid_asset", "paid")),
                   threading.Thread(target=scan, args=("free_asset", "free"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors, errors
        assert results["paid_asset"].provenance.ocr_backend == "google_vision"
        assert results["free_asset"].provenance.ocr_backend == "paddle"
        assert results["paid_asset"].semantic_signals  # Vision served it
        assert results["free_asset"].semantic_signals == []
