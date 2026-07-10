# Three-Layer Test Suite — Summary Report (2026-07-10)

Framework: pytest 9.1.1 + pytest-cov, config in `pytest.ini` /
`.coveragerc`. Suites are independent per layer and are run separately:

```bash
pytest tests/test_nlp.py                # NLP layer
pytest tests/test_cv.py                 # CV layer
pytest tests/test_rule_engine_suite.py  # rule engine layer
```

## Final status

| layer | tests | status | statement coverage |
|---|---|---|---|
| NLP (`nlp/` + text pipeline) | 69 | **all pass** | nlp 88% (entities 99, normalize 98, claims 95, routing 90, embeddings 83) |
| CV (`cv/` + image pipeline) | 42 + 1 opt-in skip | **all pass** | markers/measure 100%, ocr 64%, pipeline 94% |
| RULE_ENGINE (`rule_engine/`) | 41 | **all pass** | 96% (7 of 13 modules at 100%) |

Every layer was run at least three times back-to-back with identical
results. Coverage excludes `__main__` demo blocks and `nlp/_demo.py`
(`.coveragerc`) — those are interactive demos, not product paths.

## Tests added (152 + 1 opt-in)

- **NLP** — segmentation across all three input modes (text position
  heuristics, HTML tag/keyword roles, OCR block-merge geometry: stacked
  merge, height-ratio blocking, band consolidation with both sides of
  the gap limit, reading order); entity extraction for all 10 types
  with normalization values, span integrity, overlap priority, comma
  numbers, determinism, and a 100-segment performance bound; claim
  detection (entity- and keyword-driven, dedup, role skips, semantic
  fallback gating with the model mocked out); routing (every framework
  rule, FDIC de-conflation, "deposit insurance" lookahead, STATE_UDAP
  on both paths, fallback gating); real frozen-model inference
  (`embed`-marked: self-similarity, symmetry, relatedness ordering,
  pinned version); end-to-end text pipeline determinism.
- **CV** — WCAG contrast/luminance/height/proximity math with exact
  known values, symmetry, and schema bounds; marker detection positives
  and the documented negatives (`#advantage`, `unsponsored`, `##ad`);
  OCR: frozen dataclass, box normalization + clamping, missing/corrupt
  files returning `[]` *without* engine init, PNG/JPG/BMP format
  reads, inference-failure containment, blank-text filtering, the
  tesseract word→line regrouping, tier dispatch (invalid tier, free
  never returns signals, paid falls back without credentials and names
  the env var, paid passes signals through, confidence clamping);
  image pipeline integration incl. carousel `seg_c<n>_` ids.
- **RULE_ENGINE** — registry guards, framework gating, crash and
  wrong-id containment, deterministic ordering, version/hash stamping,
  contract-violation raises, `CheckContext` lookups; scope-split
  semantics (asset defects don't fail review); threshold boundary
  conditions at exact values (`PROX_MAX` 0.60 vs 0.601, `HEIGHT_MIN_PCT`
  0.9 vs 0.899, `NUM_TOL` 0.005 vs 0.0051); severity floors; the
  REGDD/FDIC328 mirror conflation pair; lexicon boundary behavior;
  ruleset-hash stability/sensitivity + the source-less-check regression;
  state-table shape + VERIFY discipline; orchestrator (pass, retry-fix,
  human_review, budget accounting, validation); and regression gates:
  all 6 reference outputs pass, both known asset defects stay detected,
  and the full 127-pair mutation matrix (100% catch, 0 cross-fires,
  49/49 check coverage) runs as a single test.

## Issues found and fixes implemented

1. **Test-fixture bug (NLP)** — my band-consolidation fixture used cell
   gaps (0.20) beyond the documented `6.0 × line_h` limit (0.18). The
   merge tunables were behaving exactly as specified; fixed the fixture
   and added the complementary negative test (gap-limit respected).
2. **Test-fixture bug (rule engine)** — a scope-split fixture put a
   segment in `reviewed_clear` while an adverse finding cited it;
   `ALL-CON-002` correctly flagged the contradiction. Fixed the fixture
   and left a comment; the same trap was hit and fixed once before in
   the mutation harness — it is genuinely easy to write this
   contradiction by accident, which is evidence the check earns its keep.
3. **No implementation bugs surfaced.** All 152 tests pass against the
   production code unchanged; the two iterations above were test-side.
   Prior-session bugs already have permanent regressions here (hash
   bytecode fallback, routing fallback losing FDIC/STATE_UDAP,
   mutation-matrix gate).

## Determinism / isolation measures

- The frozen embedding model is monkeypatched out of claims/routing
  fallback tests; only the 3 `embed`-marked tests load it (from the
  local cache — no network).
- OCR backends are faked (`FakePaddlePipeline`, fake tesseract module);
  real-backend inference is opt-in via `RUN_OCR_TESTS=1`
  (`ocr_engine` marker). Google Vision is mocked at the function
  boundary; no test touches the network.
- Tests registering throwaway checks snapshot/restore the global
  `CHECK_REGISTRY` (`clean_registry` fixture) so ordering never matters.
- All temp files go through pytest `tmp_path`.

## GPU note (requirement N/A on this machine)

This host has **no CUDA device** (no NVIDIA driver; paddlepaddle and
torch are CPU-only builds). GPU acceleration and GPU-vs-CPU consistency
checks are therefore not executable here. The suite is CPU-deterministic;
when a GPU host exists, run the `embed` tests and `RUN_OCR_TESTS=1`
suite there and diff outputs against a CPU run — the fixtures already
make both runs comparable.

## Known limitations / follow-ups

- `cv/ocr.py` at 64%: the uncovered lines are the real PaddleOCR /
  tesseract initializers and the Google Vision request body — all
  external-service code, exercised only via the opt-in marker or real
  credentials. A recorded-response test for Vision would close most of
  the gap if the paid tier becomes load-bearing.
- `rule_engine/orchestrator.py` at 81%: uncovered lines are
  instruction-template branches for evidence shapes no current fixture
  produces; they are exercised indirectly by the mutation matrix.
- The `embed` tests add ~8s (model load); mark-deselect them
  (`-m "not embed"`) for a sub-5s NLP loop.
- Gold/silver routing *labels* still predate the FDIC/ECOA/STATE_UDAP
  routing policy (tracked separately); tests assert against current
  policy, not the stale labels.
