# LLM Integration & Backend Pipeline Guide

**Audience:** the engineer wiring a real LLM+RAG compliance-review layer into
this repo and building the end-to-end backend around it.
**State of the repo as of 2026-07-12:** ruleset 1.7.0, 73 registered checks,
mutation suite 152/152, CI green, all suites data-independent.
**Nothing in this document requires changing existing code** — the
integration surface is one callable you implement plus the models described
below.

---

## 1. The one thing you build

The entire integration surface is a single synchronous callable:

```python
def get_llm_output(asset: dict, prior: EngineReport | None) -> dict:
    """asset: AssetRepresentation dict (already validated upstream).
    prior:  None on round 1; the FULL EngineReport of the previous
            round on every retry.
    returns: an llm_contract.LLMOutput-shaped dict."""
```

You hand it to the orchestrator, which owns the review/check/retry loop:

```python
from rule_engine.orchestrator import evaluate_with_retry
result = evaluate_with_retry(asset_dict, get_llm_output, max_rounds=2)
```

Everything else — what the asset looks like, what you must return, what the
engine will do to your output, and how failures propagate — is specified
below.

---

## 2. End-to-end backend flow (recommended shape)

```
HTTP scan request (media + asset_id + target_jurisdictions)
        │
        ▼
pipeline.analyze_asset(asset_id,
                       image_path=... | text=... | html=...,
                       tier=None,                      # resolves from config
                       target_jurisdictions=["US-CA"]) # user-supplied targeting
        │            -> schema.AssetRepresentation (pydantic model)
        ▼
asset = rep.model_dump(mode="json")                    # engine consumes dicts
        │
        ▼
evaluate_with_retry(asset, get_llm_output, max_rounds=2)
        │            -> FinalResult
        ▼
persist: asset (with its provenance) + FinalResult (full audit trail)
        │
        ▼
respond by FinalResult.status:
  "passed"        -> review is sound; surface asset_defects + advisories
  "human_review"  -> review kept failing checks after max_rounds; queue it
  "llm_error"     -> YOUR layer failed (see §6); retry/alert at transport level
```

Key point about `"passed"`: it means **the LLM review is sound**, not that
the ad is clean. Real problems with the creative arrive as
`final_report.asset_defects` (deterministic, unfixable by re-review) and the
LLM's own adverse findings. Design the API response around all three
channels: review verdict, asset defects, advisories.

---

## 3. What you receive: `schema.AssetRepresentation`

Produced by `pipeline.analyze_asset()`. The parts your prompt/RAG layer will
consume:

| field | what it is | how you should use it |
|---|---|---|
| `asset_id` | scan identity | echo it back verbatim in your output |
| `segments[]` | role-tagged text blocks (`segment_id`, `text`, `role` ∈ headline/body/cta/disclosure/fine_print/legal/unknown, optional `bbox`, `ocr_confidence`) | the ONLY citable text units; quote from them verbatim |
| `entities[]` | typed facts with exact char spans and `normalized_value` (`apr`, `rate`, `fee`, `amount`, `percentage`, `time_period`, `superlative`, `guarantee_term`, `endorsement_marker`, `optout_marker`) | cite by `entity_id`; **any number you quote must match one of these** (§5, ALL-GRD-007) |
| `claim_candidates[]` | marketing claims a reviewer must examine (`claim_id`, `claim_type`, `text`, `segment_id`, `entity_ids`) | every one must be addressed — by a finding's `claim_candidate_id` or by `reviewed_clear` |
| `cv_findings[]` | visual measurements (contrast_ratio, text_height_percent, disclosure_proximity, marker_presence) | context for prominence judgments; the engine also checks them deterministically |
| `routing` | `product_type`, `frameworks[]`, human-readable `signal` naming every trigger | **`frameworks` is your work order** — every listed framework must be evaluated |
| `target_jurisdictions` | user-supplied `US`/`US-XX` codes | drives STATE_UDAP / state-privacy / mini-TCPA specificity (per-state statutes must be individually considered — see STATE-COV-002) |
| `provenance` | `cv_version`, `nlp_version`, `ruleset_hash` (NLP-side), `timestamp`, `ocr_backend`, `embedding_model_version` | store it per scan; join with FinalResult for the full audit record (§7) |

`provenance.ocr_backend` names the engine that transcribed this specific
asset (`paddle`/`tesseract`/`google_vision`/None for text assets). It is
computed from the OCR call's own return value — safe under concurrency.

---

## 4. What you must return: `llm_contract.LLMOutput`

Validated with pydantic **inside** `run_checks`; a structurally invalid
document **raises** (see §6 for what that does to the loop). Shape:

```jsonc
{
  "asset_id": "…",                  // must equal asset.asset_id (ALL-CON-001, critical)
  "findings": [                     // compliant verdicts included; [] is valid
    {
      "finding_id": "llmf_001",     // unique within this output (validator-enforced)
      "framework": "TILA",          // must be a schema.Framework value (33 values; see routing.frameworks)
      "severity": "high",           // "critical" | "high" | "medium" | "low"
      "verdict": "violation",       // "violation" | "potential_violation" | "compliant"
      "cited_segment_ids": ["seg_2"],
      "cited_entity_ids": ["ent_3"],
      "quoted_evidence": "17.5% APR",   // VERBATIM from a cited segment, or null
      "claim_candidate_id": "clm_1",    // claim this addresses, or null
      "reasoning": "…"              // required, kept for the audit trail
    }
  ],
  "reviewed_clear": ["seg_5", "clm_2"],  // examined, found unproblematic, no finding
  "frameworks_evaluated": ["FTC", "TILA", "CFPB", "ECOA"],
  "llm_meta": {"model": "…", "prompt_version": "…"}   // both keys required (ALL-STR-001)
}
```

Definitions the engine uses:
- **adverse finding** = `verdict ∈ {violation, potential_violation}`.
- **covered id** = cited by any finding (segments, entities, claim id) ∪
  `reviewed_clear`.

---

## 5. The rules your output is graded against

The engine runs ~30–70 checks per asset (73 registered; framework-gated).
Full spec: `docs/check_taxonomy.md`. The ones that will actually bite your
first integration, in practice order:

### Grounding (get these right or nothing passes)
| rule | requirement |
|---|---|
| ALL-GRD-001/002/003 | every cited `segment_id` / `entity_id` / `claim_candidate_id` must exist in the asset. Never invent ids. |
| ALL-GRD-004 | `quoted_evidence` must appear **verbatim** (whitespace-normalized) in a cited segment's text. Don't paraphrase inside quotes; don't "fix" OCR typos — quote the text as extracted. |
| ALL-GRD-006 | adverse findings must cite *something* (segment, entity, or claim). |
| ALL-GRD-007 | any `$X`/`X%` figure inside a quote must match some entity's `normalized_value` within 0.005. If your model rounds 17.5% to 17.49%, this fires. |

### Coverage (the "did you do the whole job" checks)
| rule | requirement |
|---|---|
| ALL-COV-001 + per-framework `<FW>-COV-001` | `frameworks_evaluated ⊇ routing.frameworks`. Copy the routing list and evaluate all of it; the generated matrix checks attribute misses per framework. |
| ALL-COV-002 (+ FTC5-COV-002/003) | every `claim_id` in `claim_candidates` is covered (finding or `reviewed_clear`). |
| STATE-COV-002 | when states are targeted, each state must be *individually* named in a STATE_UDAP finding's reasoning/quote — "states generally" fails. |
| ENDOR-COV-001 | every `endorsement_marker` entity must be addressed by an FTC finding or cleared. |

### Consistency & severity sanity
| rule | requirement |
|---|---|
| ALL-CON-002 | don't put an id in `reviewed_clear` AND cite it in an adverse finding. |
| ALL-CON-004 | `compliant` verdicts can't carry `critical`/`high` severity. |
| ALL-CON-005 | every finding's `framework` must be in your own `frameworks_evaluated`. |
| REGDD-CON-001 / FDIC328-CON-001 etc. | file findings under the right framework (insured-status wording is FDIC, not Reg DD; ECOA findings need credit signals). |
| *-SEV-* | severity floors: e.g. affirmed guarantee/prohibited-basis violations can't be rated `low`. |

### Not your problem (informational)
- **Asset-scope checks** (`asset_defects`): deterministic facts about the
  creative (MLA rate cap, missing prescreen opt-out, low-contrast
  disclosures…). They never fail your review and are never retried.
- **Advisories** (`FinalResult.advisories` / `report.advisories`):
  applicability flags (SEC 204-2 / FINRA 4511 retention, CFPB CMS, PCI DSS,
  NIST PF). Informational only; store/display them, never treat as failures.

**Prompt-design corollary:** give your model the routing frameworks + claim
list as an explicit checklist, force verbatim quoting with exact ids, and
have it emit `reviewed_clear` for everything it looked at but didn't flag.
That covers ~90% of first-integration failures.

---

## 6. The retry loop — exact semantics

`evaluate_with_retry(asset, get_llm_output, max_rounds=2)`:

1. **Round 1:** `get_llm_output(asset, None)`.
2. Engine runs; if `report.passed` → `FinalResult(status="passed")`.
3. Otherwise **round 2:** `get_llm_output(asset, prior_report)` — `prior` is
   the **full `EngineReport`**, not a rendered payload. To get actionable
   fix directives, call:
   ```python
   from rule_engine.orchestrator import build_retry_payload
   instructions = build_retry_payload(prior)   # list[RetryInstruction]
   # each: check_id, severity, message, instruction (imperative fix), evidence
   ```
   Feed `instruction` strings into your retry prompt.
4. Still failing after `max_rounds` → `FinalResult(status="human_review")`
   with every round's report and payload preserved in `round_records`.

### If your callable raises (new, ruleset ≥ this week)
Any exception from `get_llm_output` (timeout, rate limit, provider outage)
returns `FinalResult(status="llm_error")` — it does **not** crash the scan:
- `llm_error` = `"ExceptionType: message"`,
- `round_records` preserves every round completed before the failure,
- `final_report` = last completed round's report (`None` if round 1 failed),
- `rounds` = number of *completed* rounds.

### What is still YOUR responsibility inside the callable
- **Timeouts** — the orchestrator will wait forever; set client timeouts.
- **Transport retries / rate limiting** — the loop's `max_rounds` is for
  *check failures*, not network errors. Do provider-level retries inside
  your callable; raise only when genuinely giving up (that raise is now
  safely converted to `llm_error`).
- **Async bridging** — the orchestrator is strictly synchronous. If your
  layer is async: run the whole `evaluate_with_retry` in a worker thread
  (`anyio.to_thread.run_sync` / executor) from your async handler. Do NOT
  call `asyncio.run()` inside the callable if you're already in an event
  loop.
- **Output validity** — a structurally invalid LLMOutput dict raises inside
  `run_checks` and propagates out of the loop **uncaught** (only the LLM
  call itself is guarded). Validate before returning:
  ```python
  from llm_contract import LLMOutput
  LLMOutput.model_validate(candidate)   # raise inside YOUR code, not the loop
  ```
- **Partial output** — there is no partial-result channel. If your model
  errored on some claims, either (a) return a *valid* output covering what
  you have — the gaps become coverage failures and consume a retry round —
  or (b) raise and get `llm_error`. Never return a malformed document.

---

## 7. Audit trail: what to persist per scan

Store both documents; together they are the complete evidentiary record:

| from | field | why |
|---|---|---|
| asset | `provenance.cv_version`, `nlp_version`, `ruleset_hash`, `ocr_backend`, `embedding_model_version`, `timestamp` | pins the extraction behavior that produced the evidence |
| FinalResult | `ruleset_version` (top level), `final_report.ruleset_hash`, per-round reports (each independently stamped) | pins the exact rule content that graded the review — independent of your `llm_meta` |
| FinalResult | `round_records[]` (reports + retry payloads), `status`, `llm_error` | reconstructs the whole conversation months later |
| you | `llm_meta` (model, prompt_version, RAG corpus hash) | your layer's own versioning; the engine only checks presence of `model` + `prompt_version` |

Two different `ruleset_hash`es exist by design: `asset.provenance.ruleset_hash`
covers the **NLP extraction rules**; `EngineReport.ruleset_hash` covers the
**rule-engine content** (checks source, lexicons, thresholds, state table,
coverage matrix). Log both.

---

## 8. Configuration (config.py / .env)

- `config.get_settings()` (cached) reads the nearest `.env` up the tree at
  import — in this monorepo that is the repo-root `.env` (regenerated by
  `python scripts/sync_env.py`). Free tier needs no configuration at all.
- `OCR_TIER=free|paid` — `analyze_asset(tier=None)` resolves from this;
  per-call override still works. `paid` = Google Vision (adds
  `semantic_signals`, better OCR); **any** paid-tier failure degrades to
  local OCR per call, never crashes.
- `OCR_TIER=paid` without working credentials logs ONE startup warning
  naming exactly what's missing, then runs free. Never raises.
- `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json` — only read for paid.

---

## 9. Concurrency: what's safe, what isn't (audited 2026-07-12)

Safe today:
- `evaluate_with_retry` and `run_checks` — pure local state, fully
  re-entrant.
- Provenance `ocr_backend` — threaded through return values (regression
  test exists); no shared state.
- `CHECK_REGISTRY` — read-only at runtime.

**Not guaranteed thread-safe (known, deliberate):**
- `cv/ocr.py:_engine` — unlocked lazy init; the shared PaddleOCR pipeline
  object is not documented thread-safe for concurrent `.predict()`.
- `nlp/entities.py:_nlp/_matcher`, `nlp/embeddings.py:_model` — unlocked
  lazy singletons (double-load race on first concurrent use).
- Root `version.py:ruleset_hash()` is uncached — recomputed per
  `analyze_asset` (CPU overhead only).

**Recommended deployment:** process-based workers (gunicorn/uvicorn workers,
celery prefork), one OCR/NLP engine per process, `analyze_asset` serialized
*per worker*. Thread-level parallelism is fine for `evaluate_with_retry`
(the LLM-bound part) but not for concurrent `analyze_asset` image scans in
one process. If you need in-process image concurrency later, the fix is a
lock around each lazy init + a documented single-engine policy — small,
known work.

---

## 10. Testing your layer

- **Golden path:** build outputs against the synthetic reference pairs in
  `tests/conftest.py::_reference_pairs()` (`ref_clean`, `ref_str001`,
  `ref_str002`) — they encode a passing review and two deliberate asset
  defects, with zero data dependencies.
- **Grade any candidate output directly:**
  `run_checks(asset_dict, your_output)` → inspect `failed_checks[*].evidence`
  (it's the same payload your retry prompt will see).
- **Adversarial reference:** `eval/test_rule_engine.py` registers 73
  mutations — a catalog of exactly the corruptions the engine catches. Read
  it as "what my model must not do."
- **CI gates** (all data-free, run on every push): full pytest, mutation
  suite at 100%, synthetic extraction bars (entities F1 ≥0.90 clean /
  ≥0.80 OCR-noisy, claims ≥0.85, segments ≥0.85, routing ≥0.90),
  determinism audit. Your layer can rely on those invariants holding.

---

## 11. Quick reference

- **Framework values** (33): see `schema.Framework`; the router only emits
  values from this enum, and your `frameworks_evaluated`/`finding.framework`
  must use the exact wire strings (`"CAN-SPAM"`, `"Reg_DD"`, `"Reg_N"`, …).
- **Coverage matrix** (what each framework demands of you):
  `docs/coverage_matrix.md` — `structural` rows the engine checks itself;
  `coverage` rows exist to verify YOU evaluated them; `advisory` rows are
  flags; per-framework "NOT MECHANIZABLE" lists in `docs/check_taxonomy.md`
  §7 describe exactly the judgment left to your layer.
- **Check-id anatomy:** `<FAMILY-OR-FW>-<COV|GRD|CON|STR|SEV>-NNN`; scope
  `review` (yours to fix) / `asset` (creative's fault) / `advisory` (FYI).
- **Statuses:** `passed` / `human_review` / `llm_error` — plus per-report
  `passed`, `failed_checks`, `asset_defects`, `advisories`.

*Questions this doc can't answer are probably answered by
`docs/check_taxonomy.md` (check semantics), `docs/coverage_matrix.md`
(regulatory scope), or the module docstrings of `rule_engine/orchestrator.py`
and `llm_contract.py` — all of which are kept authoritative.*
