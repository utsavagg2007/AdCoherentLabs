# rule_engine — deterministic compliance guardrail

A pure-Python engine that cross-checks an LLM's compliance review of a fintech
marketing asset against the asset's deterministic structure. It answers one
question per run — **did the LLM do its job?** — and reports, separately, what
is deterministically wrong with the ad itself. It never calls an LLM, never
touches the network, and produces byte-identical verdicts for identical inputs
and ruleset.

```
CV/NLP structurers          LLM+RAG review            THIS PACKAGE
AssetRepresentation  ──┬──> LLMOutput          ──┬──> run_checks() ──> EngineReport
(pipeline.py)          │    (co-founder's layer)│         ▲
                       └────────────────────────┴─────────┘
                            orchestrator.evaluate_with_retry() owns the loop
```

## Quick start

```python
import json
from rule_engine import run_checks

asset = json.load(open("data/gold/881224884306098.json"))       # AssetRepresentation
llm_output = json.load(open("data/llm_outputs/gold/881224884306098.json"))  # LLMOutput

report = run_checks(asset, llm_output)          # ruleset_version defaults
print(report.passed)                            # review sound?
print([r.check_id for r in report.failed_checks])   # LLM's problems (retryable)
print([r.check_id for r in report.asset_defects])   # the AD's problems (not retryable)
```

With the retry loop (plug in the LLM layer as a callable):

```python
from rule_engine.orchestrator import evaluate_with_retry, build_retry_payload

def get_llm_output(asset: dict, prior_report) -> dict:
    """Your LLM layer. prior_report is None on round 1; on retries it is
    the failed EngineReport — render it with build_retry_payload(prior_report)
    to get [{check_id, severity, message, instruction, evidence}, ...] for
    your retry prompt. Must return an LLMOutput-shaped dict."""
    ...

result = evaluate_with_retry(asset, get_llm_output, max_rounds=2)
# result.status: "passed" | "human_review"
# result.round_records: every round's EngineReport + the payload sent after it
```

Run from the repo root with the project venv (`source .venv/bin/activate`);
the repo is flat, so `schema.py` and `llm_contract.py` resolve from the root.
`import rule_engine` registers all checks as a side effect — the engine is
ready immediately.

## The two input contracts

Both inputs may be dicts (validated on entry — a contract violation **raises**,
it is not a finding) or already-parsed models.

**1. `schema.AssetRepresentation`** (repo root `schema.py`, produced by
`pipeline.analyze_asset`) — the deterministic structure of one marketing asset:

| field | what it is |
|---|---|
| `asset_id` | unique id; must match the LLMOutput's |
| `segments[]` | text blocks with `segment_id`, `text`, `role` (headline/body/disclosure/fine_print/cta/legal/unknown), optional `bbox` |
| `entities[]` | rule-extracted facts: `entity_id`, `entity_type` (apr/fee/rate/amount/percentage/…), `raw_text`, `normalized_value`, `segment_id`, `char_span` |
| `claim_candidates[]` | flagged claim spans: `claim_id`, `claim_type` (performance/comparative/guarantee/endorsement/pricing/risk_free), `segment_id` |
| `cv_findings[]` | visual measurements (numbers, never conclusions): `text_height_percent`, `disclosure_proximity`, `contrast_ratio`, `marker_presence` |
| `routing` | `product_type` + `frameworks` the asset must be evaluated under |
| `provenance` | CV/NLP layer versions (unrelated to this engine's versioning) |

**2. `llm_contract.LLMOutput`** (repo root `llm_contract.py`, produced by the
LLM+RAG layer) — the review being guarded:

| field | what it is |
|---|---|
| `asset_id` | must equal the asset's |
| `findings[]` | judgments: `finding_id`, `framework` (schema Framework enum), `severity` (critical/high/medium/low), `verdict` (violation/potential_violation/compliant), `cited_segment_ids`, `cited_entity_ids`, `quoted_evidence` (verbatim from a cited segment), `claim_candidate_id`, `reasoning` |
| `reviewed_clear[]` | claim/segment ids examined and found unproblematic — the coverage record |
| `frameworks_evaluated[]` | framework values actually evaluated; must cover `routing.frameworks` |
| `llm_meta` | audit keys; the engine only checks `model` and `prompt_version` exist |

## Signatures

```python
run_checks(asset: dict | AssetRepresentation,
           llm_output: dict | LLMOutput,
           ruleset_version: str | None = None) -> EngineReport

evaluate_with_retry(asset: dict,
                    get_llm_output: Callable[[dict, EngineReport | None], dict],
                    max_rounds: int = 2,
                    *, ruleset_version: str | None = None) -> FinalResult

build_retry_payload(report: EngineReport) -> list[RetryInstruction]
```

`run_checks` executes every registered check whose framework gate matches
`routing.frameworks` (universal checks always run), in sorted check_id order.
A check that crashes or misreports its id becomes a high-severity *failure* —
a buggy check can never silently pass an asset.

`evaluate_with_retry` calls `get_llm_output(asset, None)` on round 1, re-checks,
and on failure passes the failed report back to the callable — at most
`max_rounds` total LLM rounds, then exits `"human_review"`. Only review-scope
failures drive retries.

## Output shapes

**`EngineReport`** (pydantic; `model_dump_json()` for storage):

| field | meaning |
|---|---|
| `passed` | **review-scope checks all green — "the LLM did its job". NOT ad approval.** |
| `results[]` | every executed check: `check_id`, `passed`, `severity`, `scope`, `message`, `evidence` |
| `failed_checks[]` | review-scope failures — the LLM's to fix; source of the retry payload |
| `asset_defects[]` | asset-scope failures — deterministic true statements about the ad (missing APR disclosure, prominence floor, …) that **no re-review can change**; never retried, never gate `passed`. Downstream must read the verdict as `passed` + `asset_defects` together: a clean review of a deficient ad is not approval of the ad. |
| `ruleset_version` / `ruleset_hash` | see versioning below |
| `timestamp` | the report's only nondeterminism |

**`FinalResult`** (orchestrator): `status` ("passed"/"human_review"),
`asset_id`, `rounds`, `ruleset_version`, `final_report`, and `round_records[]`
— per round: the full `EngineReport` plus the `RetryInstruction` list sent to
the LLM afterwards (None if the round passed or the budget was spent). This is
the complete audit trail: what failed, what was asked, what changed.

## Determinism invariant — enforced in review

Checks are pure functions of the two inputs. Inside `rule_engine/`, the only
permitted imports are the standard library and the two contract modules
(`schema`, `llm_contract`). **No model calls, no network calls, no external
services, no clock reads inside checks. PRs that add any of these to a check
must be rejected** — reproducibility is the product: a regulator-facing audit
trail must replay byte-identically. Regulatory vocabulary (trigger terms,
"Member FDIC" wording) and thresholds live as versioned constants in
`rule_engine/lexicons.py`, interpreted once at authoring time in
`docs/check_taxonomy.md` — never fetched or inferred at check time. The
orchestrator is the single sanctioned impurity boundary: the injected
`get_llm_output` callable is where the LLM layer's nondeterminism lives.

## Versioning: `ruleset_version` and `ruleset_hash`

`rule_engine/version.py` defines:

- `RULESET_VERSION` — human-assigned; **bump it whenever a check, lexicon, or
  threshold changes semantics** (history in the file's docstring).
- `ruleset_hash(registry=None)` — sha256 (16 hex) over every registered check's
  id, registration metadata (families, frameworks, scope), and exact source
  code, plus the lexicon and threshold tables. Two reports with equal hashes
  were produced by byte-identical rules; a forgotten version bump still changes
  the hash.

Every `EngineReport` carries both. `run_checks(..., ruleset_version=...)`
exists to pin a label per run (e.g. in evals); leave it None to default to
`RULESET_VERSION`. Do not confuse this with `schema.Provenance.ruleset_hash`,
which identifies the *CV/NLP* layer's extraction rules.

## How to add a check — all three or the PR is incomplete

1. **Taxonomy row first** — add the check to `docs/check_taxonomy.md` in its
   framework section: check_id (`<FW>-<FAMILY>-<NNN>`), family (coverage /
   grounding / consistency / structural / severity_sanity), trigger condition,
   fail condition, evidence, severity, and scope (review vs asset). Every
   condition must be decidable from the two JSON inputs alone; if it can't be,
   it goes under that section's "NOT MECHANIZABLE — stays with LLM layer"
   heading instead of becoming a weak check.
2. **Implementation** — one function in the right `checks_*.py`, registered via
   `@register_check(check_id, families=[...], frameworks=[...], scope=...)`,
   docstring = the taxonomy row verbatim, returning a `CheckResult` whose
   `evidence` carries the specific ids/values that caused the outcome (not just
   a message). `frameworks=["*"]` for universal checks; `scope="asset"` iff the
   check reads only the asset.
3. **A mutation for it** — in `eval/test_rule_engine.py`: a function that
   corrupts a passing reference LLMOutput in exactly the way the check exists
   to catch, mapped to the check_id. Run the harness: catch rate must stay
   100% and new cross-fires must be justified or fixed. Asset-scope checks
   can't be triggered by output mutations — those need a synthetic
   asset+output fixture pair instead.

Then bump `RULESET_VERSION`. Reference "correct LLM" outputs for every gold
asset live in `data/llm_outputs/gold/` — if your check fails any of them,
either the check is wrong or the reference output needs a justified update.

## Verifying an integration

```bash
python3 rule_engine/core.py            # minimal demo: registry + report shape
python3 rule_engine/orchestrator.py    # both retry-loop paths with audit trail
python3 eval/test_rule_engine.py       # mutation matrix; exits 0 iff catch rate 100%
```

## File map

| file | contents |
|---|---|
| `core.py` | CheckResult/CheckContext/EngineReport, registry, `run_checks` |
| `checks_universal.py` | 15 `ALL-*` checks (run on every asset) |
| `checks_ftc5.py` / `checks_regz.py` / `checks_regdd.py` / `checks_fdic328.py` / `checks_regb.py` | 30 framework checks (FTC §5, Reg Z/TILA, Reg DD, FDIC Part 328, ECOA/Reg B) |
| `lexicons.py` | versioned lexicons + thresholds (taxonomy Appendices A/B) |
| `version.py` | `RULESET_VERSION`, `ruleset_hash()` |
| `orchestrator.py` | `evaluate_with_retry`, `build_retry_payload`, `FinalResult` |
| `../docs/check_taxonomy.md` | the check definitions this package implements |
| `../eval/test_rule_engine.py` | mutation-testing harness |

## Known gaps (tracked in the taxonomy's change-request list)

- `schema.Framework` now has `FDIC` (added 2026-07-10), but the router does
  not emit it yet, so FDIC checks still key on wording, not routing.
  `STATE_UDAP` also exists as an umbrella framework value; state checks are
  a future phase gated on `AssetRepresentation.target_jurisdictions`
  (user-supplied ad-targeting codes; empty = state checks don't run).
- The router never emits `ECOA`, so ECOA routing-coverage checks are vacuous
  until it does; Reg B checks gate on product type + lexicon instead.
- FDIC-insured-status wording currently influences deposit routing (the
  REGDD-CON-001 / FDIC328-CON-001 mirror pair polices the resulting
  conflation from both sides).
