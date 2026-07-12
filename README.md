# AdCoherentLabs

[![CI](https://github.com/utsavagg2007/AdCoherentLabs/actions/workflows/ci.yml/badge.svg)](https://github.com/utsavagg2007/AdCoherentLabs/actions/workflows/ci.yml)

AdCoherentLabs is an end-to-end framework for automating compliance validation
and auditing of fintech marketing creatives (ads, landing pages, email copy,
and carousel ads). A deterministic CV/NLP pipeline structures each creative,
an LLM layer judges it, and a pure-Python rule engine cross-checks the
judgment against a versioned regulatory coverage matrix.

---

## 🏗️ Architecture

```
                  ┌────────────────────────────────────────┐
                  │          Raw Creative Media            │
                  │        (Image, HTML, or Text)          │
                  └──────────────────┬─────────────────────┘
                                     │
                                     ▼
                  ┌────────────────────────────────────────┐
                  │    CV / NLP Pipeline (pipeline.py)     │
                  │   - OCR & coordinate bounding boxes    │
                  │   - Entity extraction (APRs, fees)      │
                  │   - Functional role text segmentation  │
                  └──────────────────┬─────────────────────┘
                                     │
                                     ▼
                       AssetRepresentation (schema.py)
                                     │
                  ┌──────────────────┴─────────────────────┐
                  │                                        │
                  ▼                                        ▼
    ┌──────────────────────────┐             ┌──────────────────────────┐
    │  LLM compliance-review   │             │   Deterministic Rule     │
    │     (llm_contract.py)    │             │   Engine (rule_engine/)  │
    │   - Issues judgments     │             │   - Checks consistency   │
    │   - Quotes evidence      │             │   - Cross-checks LLM     │
    │   - Emits findings       │             │   - Detects ad defects   │
    └─────────────┬────────────┘             └─────────────┬────────────┘
                  │                                        │
                  └──────────────────┬─────────────────────┘
                                     ▼
                              EngineReport
                       - review sound? (passed)
                       - failures to retry (LLM)
                       - un-fixable defects (Ad)
                       - advisory applicability flags
```

The system splits compliance logic into three distinct boundaries:

1. **CV/NLP Pipeline (Structurers, not Judges):** localize and extract text
   segments, entities, claims, and bounding-box measurements. They never
   render verdicts or severity scores.
2. **LLM Compliance-Review Layer (Judges, not Structurers):** evaluates the
   asset and issues structured findings citing the extracted
   segments/entities.
3. **Rule Engine (Guardrails & Verifiers):** a pure-Python engine checking the
   LLM's consistency, coverage, and citation grounding, reporting absolute
   defects in the creative, and emitting advisory applicability flags.

---

## 🚀 Quickstart

```bash
git clone git@github.com:utsavagg2007/AdCoherentLabs.git
cd AdCoherentLabs

python3.12 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
python -m spacy download en_core_web_sm      # entity patterns (falls back to blank "en")

# optional: the local OCR fallback backend (PaddleOCR is the preferred engine)
sudo apt-get install -y tesseract-ocr && pip install pytesseract

python -m pytest                              # full suite; needs no data/ directory
```

---

## 🔌 The Three Engines — Entry Points

### 1. CV (layer 1) — `cv/`

```python
from cv.ocr import run_ocr           # image -> (OcrLine list, semantic signals)
lines, signals = run_ocr("ad.png", tier="free")   # "paid" = Google Vision, falls back
```
Plus `cv.measure` (contrast, proximity geometry) and `cv.markers`
(sponsorship/footnote markers). Backend selection and measured floors: see
[OCR backends](#-ocr-backends-and-measured-floors).

### 2. NLP (layer 2) — `nlp/`

```python
from nlp.normalize import segment_text     # OCR lines / HTML / text -> role-tagged segments
from nlp.entities import extract_entities  # segments -> typed entities with exact spans
from nlp.claims import detect_claims       # segments + entities -> claim candidates
from nlp.routing import route              # -> RoutingLabel (product, frameworks, signal)
```

The one-call wrapper for both layers:

```python
from pipeline import analyze_asset

rep = analyze_asset("asset_001", text="Get 5.99% APR, guaranteed approval!")
rep = analyze_asset("asset_002", image_path="ad.png", tier="free",
                    target_jurisdictions=["US-CA"])
print(rep.model_dump_json(indent=2))        # a schema.AssetRepresentation
```

### 3. Rule engine (layer 3) — `rule_engine/`

```python
from rule_engine import run_checks
report = run_checks(asset_dict, llm_output_dict)     # -> EngineReport
report.passed          # review sound? (review-scope checks only)
report.failed_checks   # what the LLM must fix on retry
report.asset_defects   # true statements about the ad; no re-review changes them
report.advisories      # applicability flags (never gate, never retry)
```

The retry loop between engine and LLM layer:

```python
from rule_engine.orchestrator import evaluate_with_retry
result = evaluate_with_retry(asset_dict, get_llm_output, max_rounds=2)
result.status          # "passed" | "human_review", with the full audit trail
```

---

## 📜 The Contracts

Two frozen Pydantic contracts join the layers. Both evolve by **additive-only
minor bumps** (documented in their module docstrings); existing serialized
documents always validate unchanged.

| contract | producer -> consumer | carries |
|---|---|---|
| `schema.AssetRepresentation` | CV/NLP -> LLM + rule engine | segments (roles, bboxes), entities (types, exact spans, normalized values), claim candidates, cv_findings (measurements), routing, `target_jurisdictions`, provenance (`ruleset_hash`, `ocr_backend`, `embedding_model_version`) |
| `llm_contract.LLMOutput` | LLM layer -> rule engine | findings (framework, verdict, severity, cited ids, quoted evidence), `reviewed_clear`, `frameworks_evaluated`, `llm_meta` |

Everything the engine decides is decided from these two documents — nothing
else enters at check time.

---

## 🗺️ What We Cover — the Regulatory Coverage Matrix

Every source in the Regulatory Source Directory is classified in
[`docs/coverage_matrix.md`](docs/coverage_matrix.md) (generated from the
versioned constant `rule_engine/coverage_matrix.py`, which is hashed into the
ruleset — reclassifications change the ruleset hash). **99 rows: 73
structural, 17 coverage, 5 advisory, 4 out_of_scope.**

| mechanization | rows | what the engine actually does | examples |
|---|---|---|---|
| `structural` | 73 | Deterministic checks on the creative itself — wording, presence, geometry, numeric bounds. Failures are **asset defects**: true statements no re-review can change. | FTC §5, TILA/Reg Z trigger terms, Reg DD, FDIC 328 signage, MLA 36% MAPR cap, FCRA prescreen opt-out notice, CAN-SPAM opt-out presence, WCAG 4.5:1 contrast on disclosures, 51 state UDAP statutes |
| `coverage` | 17 | The engine **cannot judge the substance** — it enforces that the LLM evaluated the framework whenever the router attached it, and that those findings are grounded. One generated check per framework. | SEC Marketing Rule, FINRA 2210, COPPA, GLBA, SCRA, state privacy laws, mini-TCPAs, platform policies, card-network standards |
| `advisory` | 5 | Process/governance rules that apply to the **advertiser**, not the creative. The engine emits an informational applicability flag (never gates, never retries). | SEC 204-2 / FINRA 4511 retention, CFPB CMS, PCI DSS, NIST Privacy Framework |
| `out_of_scope` | 4 | Not advertising obligations at all; the reason is recorded on the row. | NCLC/Cozen/Justia research surveys (they verify the state table, they bind nobody) |

Being honest about the split: `structural` is the only class where the engine
itself decides compliance-relevant facts. `coverage` verifies *diligence*, not
*correctness* — substance stays with the LLM layer, and every check family's
non-mechanizable remainder is written down in
[`docs/check_taxonomy.md`](docs/check_taxonomy.md) (§7's "NOT MECHANIZABLE"
lists).

---

## 🔍 OCR Backends and Measured Floors

Every image-sourced number is bounded by the OCR backend that transcribed it
(recorded in `provenance.ocr_backend`; preference order `paddle > tesseract`,
see `cv/ocr.py:BACKEND_PREFERENCE`). Floors measured 2026-07-12 via
`python -m synth.backend_eval` (clean rendered banners, incl. small-text
disclosures) and `python -m synth.ocr_eval --source gold` (real screenshots):

| backend | clean-render CER | entity survival (clean) | real-screenshot word recall | real-screenshot char sim |
|---|---|---|---|---|
| PaddleOCR (preferred) | 0.001 | 0.98 | 0.994 | 0.67 |
| pytesseract (fallback) | 0.000 | 1.00 | **0.613** | 0.415 |

**No accuracy claim in this README may exceed the measured floor of the
weakest supported backend** (pytesseract on real creatives: ~61% word
recall). Any stronger claim must name the backend and cite a re-run of the
instruments above. Numbers are not comparable across backends.

---

## 🧪 Evaluation & CI

CI (`.github/workflows/ci.yml`) gates every push/PR on, and these are the
**only accuracy claims this README makes** — each is re-verified on every
green run, on seeded synthetic corpora, with no `data/` on the runner:

| gate | bar | instrument |
|---|---|---|
| entities F1 (clean synthetic) | >= 0.90 | `python -m synth.evaluate --n 600 --seed 7 --noise` |
| entities F1 (OCR-noised copy) | >= 0.80 | same run |
| claims recall | >= 0.85 | same run |
| segment role accuracy | >= 0.85 | same run |
| routing F1 | >= 0.90 | same run |
| mutation catch rate | = 100%, every registered check covered, 0 target misses | `python eval/test_rule_engine.py` |
| determinism audit | clean (stdlib + contracts only in `rule_engine/`) | `python -m rule_engine.determinism_audit` |

Other instruments (not CI gates): `python -m eval.run_eval` scores the
pipeline against locally held gold labels (directional only — gold is tiny
and held out); `python -m synth.role_eval` measures layout/role recovery on
rendered banners; `python -m rule_engine.coverage_matrix` regenerates the
coverage-matrix doc.

---

## 🧭 Invariants

1. **Structurers, not judges.** CV/NLP output carries measurements, spans,
   and candidate labels — never verdicts or severities.
2. **Deterministic floor.** Entity extraction is pure spaCy rules; the rule
   engine imports nothing beyond the standard library and the two contract
   modules — zero model calls, zero network calls at check time (enforced in
   CI by an AST audit).
3. **The frozen embedding model is a tagged fallback only.** MiniLM may
   suggest routing/claims when rules found nothing; its use is always marked
   in the routing signal and stamped into
   `provenance.embedding_model_version`.
4. **Everything that decides is versioned and hashed.** Extraction patterns,
   routing lexicons, check source code, lexicons/thresholds, the state UDAP
   table, and the coverage matrix all feed content hashes
   (`provenance.ruleset_hash`, `EngineReport.ruleset_hash`); any edit changes
   the hash even if version bumps are forgotten.
5. **Gold is held-out validation, never a tuning target.** All iteration
   happens on the seeded synthetic harness (`synth/`); the real corpora live
   outside git (`data/` is ignored) and no test depends on them.
6. **Contracts move additively.** Minor bumps only; existing documents always
   validate.
7. **Advisories never gate.** Advisory-scope results are applicability flags;
   they cannot fail a review or trigger a retry.
8. **OCR floors bound claims.** See the table above — downstream extraction
   cannot recover what OCR destroyed.

---

## 📂 Project Structure

```
├── cv/                        # layer 1: OCR (tiered), geometry measurements, markers
├── nlp/                       # layer 2: segmentation, entities, claims, routing (+ lexicons)
├── rule_engine/               # layer 3: deterministic checks + orchestrator
│   ├── core.py                #   registry, CheckResult scopes, runner
│   ├── checks_*.py            #   per-framework check modules (taxonomy §0-§7)
│   ├── coverage_matrix.py     #   versioned source-of-truth for regulatory coverage
│   ├── lexicons.py            #   versioned vocabulary + thresholds
│   ├── determinism_audit.py   #   CI purity gate (AST scan)
│   └── orchestrator.py        #   LLM evaluate/retry loop -> FinalResult
├── synth/                     # seeded synthetic corpus: generator, renderer, eval instruments
├── eval/                      # gold-label scorer (run_eval) + mutation harness
├── tests/                     # pytest suite (fully data-independent)
├── docs/                      # check taxonomy + generated coverage matrix
├── schema.py                  # contract: CV/NLP -> downstream (AssetRepresentation)
├── llm_contract.py            # contract: LLM layer -> rule engine (LLMOutput)
├── pipeline.py                # end-to-end asset analyzer (CV + NLP wiring)
└── version.py                 # NLP-side ruleset hashing + provenance stamping
```
