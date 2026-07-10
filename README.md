# AdCoherentLabs

AdCoherentLabs is an end-to-end framework for automating compliance validation and auditing of fintech marketing creatives (ads, landing pages, email copy, and carousel ads). It provides a deterministic structure for extracting visual and textual components, which is then verified against LLM compliance judgments and regulatory check taxonomies (TILA, FTC §5, Regulation DD, FDIC Part 328, ECOA, etc.).

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
```

The system splits compliance logic into three distinct boundaries:
1. **CV/NLP Pipeline (Structurers, not Judges):** Localize and extract text segments, entities, and bounding box measurements. They never render verdicts or severity scores.
2. **LLM Compliance-Review Layer (Judges, not Structurers):** Evaluates the asset and issues structured findings citing the extracted segments/entities.
3. **Rule Engine (Guardrails & Verifiers):** A pure-Python engine checking the LLM's consistency, coverage, and citation grounding, and reporting absolute defects in the creative.

---

## 📂 Project Structure

```
├── cv/                      # Computer Vision components (OCR, bounding boxes, marker detectors)
├── nlp/                     # NLP components (Text segmentation, entity extraction, routing, embeddings)
├── rule_engine/             # Pure-Python deterministic compliance checks
│   ├── checks_universal.py  # Checks applied to all assets (all-framework coverage)
│   ├── checks_fdic328.py    # FDIC Part 328 checks (insured-status wording)
│   ├── checks_ftc5.py       # FTC §5 checks (deceptive/misleading advertising)
│   ├── checks_regb.py       # Regulation B / ECOA checks
│   ├── checks_regdd.py      # Regulation DD checks (deposits, APY disclosures)
│   ├── checks_regz.py       # Regulation Z / TILA checks (triggering terms, APR prominence)
│   ├── core.py              # Rule registry & check runner
│   ├── lexicons.py          # Versioned thresholds & trigger vocabulary
│   └── orchestrator.py      # LLM evaluation loop with structured retries
├── docs/                    # Check taxonomy documentation & specifications
├── eval/                    # Performance evaluation framework
│   ├── run_eval.py          # Pipeline score runner vs gold labels
│   └── test_rule_engine.py  # Rule engine mutation testing harness
├── schema.py                # Pydantic schema for CV/NLP extraction (AssetRepresentation)
├── llm_contract.py          # Pydantic schema for the LLM output contract (LLMOutput)
├── pipeline.py              # End-to-end asset analyzer wiring CV & NLP
├── shakedown.py             # Sandbox test scripts
└── version.py               # Extraction pipeline version tracking
```

---

## 🚀 Getting Started

### 1. Run the Pipeline
Extract structured representations of a marketing creative:
```python
from pipeline import analyze_asset

# For text assets:
rep = analyze_asset("asset_001", text="Get 5.99% APR, guaranteed approval!")
print(rep.model_dump_json(indent=2))

# For visual assets:
rep_visual = analyze_asset("asset_002", image_path="data/unlabeled/1023652900018510/1023652900018510_card1.jpg")
```

### 2. Run Deterministic Compliance Checks
Cross-check an LLM compliance review with the rule engine:
```python
import json
from rule_engine import run_checks

asset = json.load(open("data/gold/881224884306098.json"))
llm_output = json.load(open("data/llm_outputs/gold/881224884306098.json"))

# Run the checks
report = run_checks(asset, llm_output)

print(f"LLM Review Sound? {report.passed}")
print(f"LLM Errors: {[r.check_id for r in report.failed_checks]}")
print(f"Asset Defects: {[r.check_id for r in report.asset_defects]}")
```

---

## 🧪 Evaluation & Testing

The evaluation suite validates the accuracy of both the pipeline extraction and the rule engine checks.

### Run Extraction Pipeline Evaluation
Score extraction layers (entities, segments, claims, routing) against gold labels:
```bash
python3 -m eval.run_eval
```
*Evaluates recall, precision, and accuracy against quality bars defined in [eval/run_eval.py](eval/run_eval.py).*

### Run Rule Engine Mutation Tests
Validate that the rule engine catches corrupted/mutated LLM output scenarios:
```bash
python3 eval/test_rule_engine.py
```
*Ensures 100% catch rate of all registered checks.*
