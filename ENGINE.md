# AdCoherent Labs — The Connected Four-Layer Compliance Engine

*The single document for understanding, running, and operating the AI engine.
Written after wiring the four layers together; verified end-to-end on
2026-07-12 (all commands below were actually run — see [Verification](#10-verification--what-was-actually-run)).*

---

## 1. What this engine is

AdCoherent Labs reviews fintech marketing creatives (banner images, ad copy,
HTML pages, carousel ads) for regulatory compliance and produces an
**auditable, reproducible verdict** — decision support for a compliance desk,
not legal advice.

The engine is four layers, executed **synchronously, in order**, for every ad:

```
            user's ad (image | text | html) + product tier + targeting
                                    |
    +-------------------------------v--------------------------------+
    | LAYER 1 - CV  (CV-RULE_ENG-NLP/cv/)                            |
    |   Normalization: OCR text out of pixels (PaddleOCR on every    |
    |   tier, for now), normalized bounding boxes, contrast          |
    |   measurement, marker/footnote detection, proximity geometry   |
    +-------------------------------v--------------------------------+
    | LAYER 2 - NLP (CV-RULE_ENG-NLP/nlp/)                           |
    |   Segmentation into roles (headline/disclosure/cta/...),       |
    |   entity extraction (APR, APY, fees, guarantee terms),         |
    |   claim-candidate detection, FRAMEWORK ROUTING (FTC, TILA,     |
    |   Reg_DD, STATE_UDAP, ...)                                     |
    |          ==> AssetRepresentation (schema.py contract)          |
    +-------------------------------v--------------------------------+
    | LAYER 3 - LLM + RAG (rag-engine/adcoherent_rag/review/)        |
    |   Pulls regulation chunks for every routed framework from the  |
    |   versioned corpus (pgvector + tsvector hybrid RRF), then the  |
    |   TIER'S LLM reviews the ad against those excerpts             |
    |          ==> LLM review document (sample_output-LLMresponse    |
    |              .json shape, with scope_of_improvement)           |
    +-------------------------------v--------------------------------+
    | LAYER 4 - RULE ENGINE (CV-RULE_ENG-NLP/rule_engine/)           |
    |   ~50 deterministic checks: is the review complete, grounded,  |
    |   consistent, severity-sane? Plus structural asset checks      |
    |   (prominence floors, WCAG contrast, prohibited wording).      |
    |   NOT SATISFIED -> calls Layer 3 back with fix instructions    |
    |   (max 2 callbacks), then requests HUMAN INTERFERENCE.         |
    +-------------------------------v--------------------------------+
                        EngineRunResult (one JSON document:
                 verdict + review + audit trail + provenance)
```

The connective tissue lives in the **`engine/` package** at the project root —
it is the only new code; the four layers themselves were left intact (one
additive parameter added, see [§7](#7-what-was-changed-to-connect-the-layers)).

---

## 2. Intuition — why the engine is shaped like this

**The LLM is a judge, not an oracle.** Layers 1–2 are deterministic
*structurers*: they never render verdicts, they produce measurements, spans,
and candidates. Layer 3 is the only place judgment happens — and judgment is
probabilistic, so Layer 4 exists to make it *defensible*: every finding must
cite real segment/entity ids, quote the ad verbatim, cover every routed
framework and claim, and stay within deterministic severity floors. A review
that fails these checks is not "wrong about the law" — it is **unverifiable**,
and an unverifiable compliance verdict is worthless to an auditor.

**The callback loop is quality control, not retry-on-error.** When Layer 4
rejects a review it does not just re-ask — it sends back *machine-derived fix
instructions* ("claims ['clm_2'] are unaddressed: evaluate each in a finding
or add to reviewed_clear"). The LLM gets 1 initial attempt + 2 corrective
callbacks. If it still cannot produce a sound review, the run stops and asks
for **human interference** — the operator sees exactly which checks failed and
prompts direction; the engine runs one more steered round per prompt.

**Cheap layers shrink expensive layers.** Every claim Layer 2 isolates is one
less thing the tier LLM has to discover, and one more thing Layer 4 can check
deterministically. Retrieval is tier-budgeted (chunks per framework, context
chars) so cost scales with what the customer pays.

**Asset defects are separate from review failures.** "The disclosure fails
WCAG contrast" is a true statement about the *ad* — no re-review changes it.
Those are reported as `asset_defects` and never burn LLM callbacks. Only
*review-scope* failures (the LLM's homework) drive the loop.

**Everything that decides is versioned.** OCR backend, NLP ruleset hash,
prompt version, RAG corpus hash, rule-engine ruleset hash, model id — all
stamped into the result's `provenance`. A verdict can be reproduced and
explained months later (regulation text is even effective-dated, so an audit
replay can ask "what did the rules say on the ad's run date?" via `--as-of`).

---

## 3. The five product tiers

Tier routing is a **table, not code** (`engine/tiers.py` +
`rag-engine/adcoherent_rag/review/tiers.py`). The engine is identical across
tiers; only the model and budgets swap.

| tier       | LLM (Layer 3)                  | OCR (Layer 1)       | max output tok | chunks/framework | context chars |
|------------|--------------------------------|---------------------|---------------:|-----------------:|--------------:|
| free       | qwen/qwen-turbo (OpenRouter)   | local **PaddleOCR** |          1,500 |                6 |        24,000 |
| hobby      | qwen/qwen-max (OpenRouter)     | local **PaddleOCR** |          3,000 |                8 |        40,000 |
| pro        | claude-sonnet-5 (Anthropic)    | local **PaddleOCR** |          8,000 |               10 |        60,000 |
| design     | claude-opus-4-8 (Anthropic)    | local **PaddleOCR** |         16,000 |               12 |        90,000 |
| enterprise | claude-opus-4-8 (Anthropic)    | local **PaddleOCR** |         32,000 |               16 |       140,000 |

* **PaddleOCR everywhere is deliberate and temporary** (per product decision;
  it will be swapped after production). The swap point is one dict:
  `engine/tiers.py: OCR_TIER_BY_PRODUCT_TIER` — flip a tier to `"paid"` to use
  Google Vision (with automatic local fallback), or extend `cv/ocr.py` with a
  new backend.
* Free/hobby run Qwen models **through OpenRouter** (one key, OpenAI-
  compatible API); the OpenRouter-namespaced ids are env-overridable
  (`OPENROUTER_FREE_MODEL`, `OPENROUTER_HOBBY_MODEL`) so a model swap on
  those tiers is config, not code. Claude ids are pinned per product spec.
* Print this matrix anytime: `python -m engine.cli tiers`.

---

## 4. How to run

### 4.1 One-time setup (Windows dev machine, current state)

The working virtualenv is **`CV-RULE_ENG-NLP/.venv`** (Python 3.11) — it now
contains the dependencies of BOTH repos (the `rag-engine/.venv` in this folder
was built on macOS and does not run on Windows). On a fresh machine:

```powershell
cd CV-RULE_ENG-NLP
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r ..\rag-engine\requirements.txt
.venv\Scripts\python -m spacy download en_core_web_sm   # optional, better NER
```

Configuration: `copy .env.example .env` at the **project root** and fill what
you need (the engine loads the root `.env` first, then each repo's own):

| variable | needed for | notes |
|---|---|---|
| `OPENROUTER_API_KEY` | free/hobby tiers | Qwen models via OpenRouter (https://openrouter.ai/keys); optional `OPENROUTER_SITE_URL` / `OPENROUTER_APP_NAME` attribution headers |
| `ANTHROPIC_API_KEY` | pro/design/enterprise | Claude |
| `DATABASE_URL` | grounded reviews | Supabase Postgres w/ pgvector, direct connection |
| `OCR_TIER` | Layer 1 | `free` (default, PaddleOCR) or `paid` (Google Vision) |
| `EMBEDDING_FAKE=1` | offline dry-runs | deterministic vectors, no model download |

**Without any of these the engine still runs** (see 4.3) — it degrades
loudly, never crashes: no DB → empty retrieval (LLM told to answer
`needs_review` where grounding matters); no API key → `status=llm_error` with
the exact cause preserved.

### 4.2 Prove the wiring (no keys, no DB, no network)

```powershell
# from the project root
CV-RULE_ENG-NLP\.venv\Scripts\python -m engine.selftest
```

Runs the REAL Layers 1, 2, 4 with a deterministic stub LLM + stub retrieval
and asserts all five paths: adapter units, clean pass, callback-with-
instructions, human-interference + resume, and llm-error surfacing.
Expected output ends with `SELFTEST PASSED`.

### 4.3 Review an ad (CLI)

```powershell
$py = "CV-RULE_ENG-NLP\.venv\Scripts\python"

# text ad, real Claude review (needs ANTHROPIC_API_KEY):
& $py -m engine.cli check --text "Get 5.99% APR, guaranteed approval!" --tier pro --jurisdictions US-CA --out report.json

# image ad through PaddleOCR, free tier (needs OPENROUTER_API_KEY):
& $py -m engine.cli check --image ad-banner.png --tier free --out report.json

# carousel = multiple images:
& $py -m engine.cli check --image card1.png card2.png card3.png --tier design

# HTML creative:
& $py -m engine.cli check --html-file landing.html --tier hobby

# audit replay against the regulations effective on a past date:
& $py -m engine.cli check --text "..." --tier enterprise --as-of 2026-01-15

# no keys yet? full pipeline demo with a deterministic offline stub LLM:
& $py -m engine.cli check --image sample-ad-banner.png --tier free --stub-llm

# when a run ends in human_review, drive the operator loop interactively:
& $py -m engine.cli check --text "..." --tier pro --interactive
```

Exit codes: `0` passed · `2` human_review (operator input still needed) ·
`3` llm_error · `1` usage error.

### 4.4 Use it as a library (what the SaaS worker will call)

```python
from engine import run_compliance_engine, resume_with_human_guidance

result = run_compliance_engine(
    text="Get 5.99% APR, guaranteed approval!",   # or image_path= / html=
    product_tier="pro",
    target_jurisdictions=["US-CA"],
    include_asset=True,                           # keep for a possible resume
)

result.status          # "passed" | "human_review" | "llm_error"
result.llm_review      # final LLM review document (product format)
result.verification    # rule-engine verdict: failed_checks / asset_defects / advisories
result.rounds          # full audit trail: every round + the feedback that produced it
result.provenance      # models, versions, hashes - the reproducibility block
result.model_dump(mode="json")                    # -> persist as layer_outputs / report

# human interference after an exhausted run:
if result.status == "human_review":
    print(result.human_review.instructions)       # what the LLM kept getting wrong
    result2 = resume_with_human_guidance(
        result.asset,
        "The APR claim is substantiated by the rate sheet on file; "
        "evaluate clm_2 against TILA trigger-term rules and clear it if "
        "the disclosure block satisfies 1026.24(d).",
        product_tier="pro",
        previous=result,
    )
```

### 4.5 Stand up the full RAG corpus (for grounded production reviews)

```powershell
cd rag-engine
# point DATABASE_URL at Supabase Postgres (direct connection, pgvector available)
python -m adcoherent_rag.cli init-db     # schema + indexes
python -m adcoherent_rag.cli ingest      # tier-1 federal + priority states
python -m adcoherent_rag.cli stats
python -m adcoherent_rag.cli retrieve "APY advertising disclosure" --framework Reg_DD --k 8
```

See `rag-engine/README.md` for state-coverage details and
`RAG-ingest-approach-steps.txt` for the update-detection design
(Federal Register poller, eCFR diffs, effective-dating).

### 4.6 SaaS mode — the engine as a tenant operation (Supabase)

`engine/saas.py` wires the engine to the self-hosted Supabase data plane
(schema in `supabase/migrations/`, ops doc in `supabase.md`). The defining
property: **the product tier is fetched from the database** — the org's
Stripe-synced `subscriptions` row via `app.org_tier()` — never taken from
the caller. Change the subscription row and the very next run reviews with
the new tier's LLM, budgets, and framework scope; no code or config moves.

```python
from engine.saas import run_for_user, resume_run

result = run_for_user(
    user="reviewer@acme.com",            # auth.users id or email
    text="Get 5.99% APR, guaranteed approval!",
    target_jurisdictions=["US-CA"],
    title="Q3 landing banner",
)
result.provenance["saas"]                # org / submission / analysis_run ids
# CLI equivalent (tier line shows what the DB decided):
#   python -m engine.cli check --text "..." --user reviewer@acme.com
#   python -m engine.cli quota --user reviewer@acme.com
#   python -m engine.cli saas-selftest   # live integration proof (stub LLM)
```

What one call does, in order (every step visible in the DB):

1. **Identity + tenancy** — `auth.users` lookup; org derived from
   `memberships` (a supplied `org=` only selects among the user's own
   orgs; membership is always re-verified). Reviewer+ role and confirmed
   email required, or the run is refused before any layer executes.
2. **Entitlements** — tier + model + token caps + per-tier `frameworks`
   from `plan_entitlements`; drift against the engine's compiled `TIERS`
   is audited (`entitlements.drift`).
3. **Rows first, quota second** — `submissions` -> `assets` (sha256
   checksum) -> `analysis_runs(queued)`, then
   `app.consume_scan_quota(org, run)` atomically consumes or rejects
   (rejected runs are recorded: status `failed`, audit
   `run.quota_rejected`) — expensive layers never start over cap.
4. **Layers with live status** — `running_cv -> running_nlp ->
   running_llm -> reconciling` on the run row (Realtime pushes these to
   the UI); plan frameworks scope routing before Layer 3 (deterministic
   checks are framework-registered, so their rules drop out with them —
   drops are surfaced in `result.warnings`).
5. **Persistence** — all four `layer_outputs` (the stored `nlp` payload
   lets a resume skip re-OCR), `findings` rows (LLM findings verbatim +
   rule-engine asset defects as `potential_violation` with the check id
   as `rule_ref`), token spend in `usage_events`, terminal status
   `complete | human_review | failed` (`human_review` is a first-class
   DB status — migration 0007 — with `engine_run_id` correlating DB rows
   to report files).
6. **Audit** — hash-chained `audit_logs` events at every lifecycle edge
   (`submission.created`, `run.started`, `run.completed`, ...).

`resume_run(user=..., run=<uuid or engine_run_id>, guidance=...)` is the
persisted operator-interference path: a NEW `analysis_runs` row linked via
`resumed_from_run_id`, no extra scan quota (same creative), tokens metered,
`run.resumed` audited. API keys for Pro+ programmatic access:
`SupabaseDataPlane.issue_api_key/verify_api_key` (sha256 at rest, scope +
`api_access` entitlement checks, revocation).

Security contract: the module connects as a privileged DB role that
**bypasses RLS** — every statement sets `org_id` explicitly, it must stay
server-side, and its connection string (`SUPABASE_DB_URL`, falling back to
`DATABASE_URL`) is env-only. `python -m engine.cli saas-selftest` proves
the whole contract live: 32 checks covering tier fetch, gates, quota,
persistence, API keys, the audit hash chain, cross-tenant RLS isolation,
and the Realtime publication, against a throwaway org it deletes after.

---

## 5. The run lifecycle in detail

1. **`prepare_asset`** (Layers 1+2). Exactly one of `image_path | text | html`.
   Images go through OCR (`cv/ocr.py`, PaddleOCR preferred; backend recorded
   in provenance because accuracy floors differ per backend). Segmentation,
   entities, claims, routing produce a validated **`AssetRepresentation`**.
   Carousel ads: pass a list of image paths; segments are namespaced per card.

2. **Round 1 review** (Layer 3). `review_asset(asset, tier)`:
   * builds retrieval queries from claims + key segments,
   * pulls chunks per routed framework (tier-budgeted; state targeting
     automatically unions `US` so federal rules are never filtered out),
   * calls the tier's LLM (Anthropic structured outputs / OpenRouter JSON-mode
     with local validation + one corrective retry),
   * sanitizes hallucinated citations (unknown ids dropped, logged),
   * returns the review document; `llm_meta` carries model, prompt version,
     corpus hash, token counts, latency.

3. **Verification** (Layer 4). `run_checks(asset, adapted_review)` runs every
   registered deterministic check (~50 for a typical routed ad, zero network,
   zero model calls) and splits results by scope:
   * `review`-scope failures → the LLM must fix them (drives the loop),
   * `asset`-scope failures → **asset defects**, true statements about the ad,
   * `advisory` → applicability flags (never gate, never retry).

4. **Callback loop.** On review failure, `build_retry_payload` renders each
   failed check into an actionable instruction; the engine re-invokes Layer 3
   with those instructions injected into the prompt as an authoritative
   *"Reviewer feedback"* section. Budget: **1 initial call + 2 callbacks**
   (`DEFAULT_MAX_LLM_ROUNDS = 3`; override with `--max-llm-rounds`).

5. **Human interference.** Budget exhausted → `status="human_review"`; the
   result carries the outstanding failed checks + instructions + how to
   resume. `resume_with_human_guidance` (or `--interactive`) runs exactly one
   more steered round per operator prompt — the guidance enters the same
   feedback channel, marked `OPERATOR GUIDANCE`, and the new run is linked to
   the exhausted one via `resumed_from_run_id`.

6. **Result assembly.** `EngineRunResult` = final review + verification +
   per-round audit trail (including the exact feedback string each round saw)
   + provenance + warnings + timings. `--out report.json` persists it.

---

## 6. Contracts between the layers

| contract | producer → consumer | file |
|---|---|---|
| `AssetRepresentation` | CV/NLP → LLM + rule engine | `CV-RULE_ENG-NLP/schema.py` |
| LLM review document | RAG/LLM → product + (adapted) rule engine | `rag-engine/adcoherent_rag/review/schema.py`, sample in `rag-engine/sample_output-LLMresponse.json` |
| `LLMOutput` | (adapted review) → rule engine | `CV-RULE_ENG-NLP/llm_contract.py` |
| `EngineReport` / `FinalResult` | rule engine → orchestrator | `CV-RULE_ENG-NLP/rule_engine/core.py`, `orchestrator.py` |
| `EngineRunResult` | engine → SaaS backend / UI | `engine/report.py` |

**The adapter** (`engine/adapter.py`) bridges the two review dialects — this
was the one real impedance mismatch between the repos:

| difference | RAG review layer | rule-engine contract | bridge |
|---|---|---|---|
| verdicts | `potential_violation, needs_review, compliant` | `violation, potential_violation, compliant` | `needs_review → potential_violation` (both mean "needs a human / more evidence") |
| framework labels | free strings ("Reg DD", "reg_dd") | `Framework` enum values | case/`-`/`_`-insensitive coercion; uncoercible findings dropped **loudly** into `adapter_notes` (a coverage gap then fails deterministically → feeds the retry loop instead of crashing) |
| extra fields | `regulation_citations`, `scope_of_improvement` | not in contract | ride along untouched (pydantic ignores unknown keys); the ORIGINAL document is what the product stores |

Every transformation is recorded per-round in `rounds[i].adapter_notes` — the
audit trail never lies about what the rule engine actually saw.

---

## 7. What was changed to connect the layers

**New code — `engine/` package** (project root):

| file | role |
|---|---|
| `engine/_paths.py` | sys.path bootstrap for both repos + root `.env` loading |
| `engine/tiers.py` | product tier → OCR tier map (**the** OCR swap point) + re-export of LLM tier table |
| `engine/adapter.py` | review-dialect bridge + feedback rendering (rule-engine instructions, operator guidance) |
| `engine/llm_layer.py` | Layer 3 as the callable Layer 4 invokes; RAG wiring with graceful offline degradation; per-round audit capture |
| `engine/orchestrator.py` | `prepare_asset` / `review_and_verify` / `run_compliance_engine` / `resume_with_human_guidance` |
| `engine/report.py` | `EngineRunResult` — the engine's single output document |
| `engine/cli.py`, `__main__.py` | CLI (`check`, `selftest`, `tiers`) |
| `engine/selftest.py` | offline wiring proof (real L1/L2/L4, stub L3) |

**Modified (additive only, both suites still green):**

* `rag-engine/adcoherent_rag/review/prompts.py` — `build_user_prompt(...,
  feedback=None)`: renders an authoritative "Reviewer feedback" section into
  the user turn. This is the channel BOTH the rule-engine callbacks and human
  guidance travel through.
* `rag-engine/adcoherent_rag/review/engine.py` — `review_asset(...,
  feedback=None)` passes it through.

**Environment:** installed `psycopg[binary] pgvector anthropic openai requests
beautifulsoup4 lxml PyMuPDF` into `CV-RULE_ENG-NLP/.venv` so one interpreter
runs all four layers (the checked-in `rag-engine/.venv` is a macOS venv and
cannot run on this Windows machine).

**Design choices worth knowing:**

* **3 total LLM calls** = the spec's "initial + max 2 callbacks". The rule
  engine's `evaluate_with_retry` counts *total rounds*, so the engine passes
  `max_rounds=3`.
* **State targeting unions `US`** in the retrieval filter — the corpus tags
  federal rows `US` and state rows `US-XX` with an exact-match filter;
  filtering to `["US-CA"]` alone would silently exclude every federal
  regulation.
* **Degrade loudly, never die**: unreachable DB → empty retrieval with a
  warning in `result.warnings`; missing API key / provider outage →
  `status="llm_error"` with the exception preserved; a blank image →
  "nothing extracted" placeholder asset rather than a crash.
* **Prompt-injection posture** (playbook §8): ad text enters the LLM prompt
  as inert data inside a JSON block; system instructions stay in the system
  turn; the feedback section is engine/operator-authored, never ad-derived;
  and everything the LLM answers is deterministically re-verified by Layer 4,
  which is the real containment.

---

## 8. Reading the result

```jsonc
{
  "run_id": "run_0207fb7678b0",
  "asset_id": "ad_28ef97f29291",
  "tier": "pro",
  "status": "passed",                  // passed | human_review | llm_error
  "llm_rounds_used": 1,
  "max_llm_rounds": 3,
  "llm_review": { /* final review: findings with severity, verdict,
                     quoted_evidence, regulation_citations, reasoning,
                     scope_of_improvement; reviewed_clear; llm_meta */ },
  "verification": {
    "review_passed": true,
    "checks_run": 50,
    "failed_checks": [],               // review-scope: the LLM's homework
    "asset_defects": [ /* true statements about the ad itself */ ],
    "advisories":   [ /* advertiser-level applicability flags */ ],
    "ruleset_version": "...", "ruleset_hash": "..."
  },
  "rounds": [ /* per round: feedback_sent_to_llm, llm_review,
                 adapter_notes, rule_engine_passed, failed_checks */ ],
  "human_review": null,                // set when operator input is requested
  "warnings": [],
  "provenance": { /* tier, model, prompt_version, rag_corpus_hash,
                     ocr_backend, ruleset versions, as_of */ },
  "timings_ms": { "prepare_asset": 2100, "review_and_verify": 14210 }
}
```

How to act on it:

* `status=passed` — the review is **sound** (complete, grounded, consistent).
  The ad may still have problems: read `llm_review.findings` (the judgments)
  and `verification.asset_defects` (deterministic creative defects). "Passed"
  means *trustworthy report*, not *clean ad*.
* `status=human_review` — show `human_review.instructions` to the operator,
  collect guidance, call `resume_with_human_guidance` (or use
  `--interactive`). Repeat as needed; every resumed run links back via
  `resumed_from_run_id`.
* `status=llm_error` — provider/transport failure; `llm_error` has the cause;
  completed rounds are preserved. Retry policy belongs to the job queue (the
  playbook's async backbone), not the engine.

---

## 9. Testing story

| suite | what it proves | command (from project root) |
|---|---|---|
| engine selftest | 4-layer wiring: clean pass, callback w/ instructions, human resume, llm-error — real L1/L2/L4, stub L3 | `...\python -m engine.selftest` |
| CV/NLP/rule-engine suite | 184 tests: extraction, routing, every check, orchestrator retry loop, determinism audit | `cd CV-RULE_ENG-NLP && .venv\Scripts\python -m pytest` |
| RAG suite | 67 tests: chunking, normalizers, manifest, review engine (incl. tier registry = product spec) | `cd rag-engine && ..\CV-RULE_ENG-NLP\.venv\Scripts\python -m pytest tests` |

All three were green after the integration changes (2026-07-12).

---

## 10. Verification — what was actually run

* `python -m engine.selftest` → **SELFTEST PASSED** (33/33 checks: adapter
  units, clean path 1 round, callback path 2 rounds with instructions
  verified inside the round-2 prompt, human-review after exactly 3 rounds,
  operator resume → passed, llm-error surfacing).
* Text E2E via CLI (`--stub-llm`): `"Get 5.99% APR, guaranteed approval!"`,
  tier pro, US-CA → **50 checks, review sound**, and the rule engine caught a
  real asset defect: *FTC5-STR-001 — absolute claim ("guaranteed") with no
  disclosure segment anywhere in the asset*.
* Image E2E via CLI (`--stub-llm`): a rendered banner PNG through **real
  PaddleOCR (PP-OCRv6)** → 45 checks; CV measurements caught *FTC5-STR-002*
  (disclosure prominence floor) and *WCAG-STR-001* (fine print measured below
  the 4.5:1 contrast minimum) — actual pixel-level findings, not stubs.
* Both existing test suites re-run green (184+67) after the additive changes.
* Sample artifacts left in the repo: `engine-sample-report.json`,
  `sample-ad-banner.png`.

---

## 11. Troubleshooting

| symptom | cause / fix |
|---|---|
| `warning: DATABASE_URL is not set - running with EMPTY regulation retrieval` | expected without a corpus DB; reviews lean on `needs_review`. Set `DATABASE_URL`, run `init-db` + `ingest` (§4.5). |
| `status=llm_error ... OPENROUTER_API_KEY is not set` | free/hobby tier without an OpenRouter key — set it (https://openrouter.ai/keys), or use a Claude tier, or `--stub-llm` for wiring demos. |
| `status=llm_error ... anthropic call failed` | check `ANTHROPIC_API_KEY`, network; completed rounds are preserved in `rounds`. |
| first image run is slow | PaddleOCR downloads PP-OCRv6 models to `~/.paddlex` once; subsequent runs use the cache. |
| `output truncated at the <tier> tier token limit` | the creative is too rich for the tier's output budget — upgrade the tier or split the asset. |
| pgvector / `_supabase` pooler issues on the self-hosted stack | see the socat direct-connection workaround in `rag-engine/README.md`. |
| Windows: `rag-engine/.venv` won't run | it is a macOS venv; use `CV-RULE_ENG-NLP/.venv` (already provisioned with both repos' deps). |

---

## 12. Where this goes next (per the build playbook)

The engine is the product; this repo is the engine plus its harness. The
playbook (`AdCoherent_Labs_Build_Playbook.pdf`) sequences the rest: wrap
`run_compliance_engine` in the async worker behind a queue (Phase 4), persist
`EngineRunResult.rounds` into `layer_outputs`/`findings` with RLS (Phase 2),
gate tiers via Stripe-synced entitlements (Phase 6), and build the golden-set
evaluation harness before claiming FP/FN numbers (Phase 5). The OCR swap
after production is a one-dict change (§3); the model routing already goes
through the single tier table the playbook prescribes.
