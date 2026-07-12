# Rule-Engine Check Taxonomy — v1 (Tier 1 federal, 5 frameworks)

Deterministic checks for the post-LLM compliance guardrail engine. Every check is
decidable from exactly two JSON inputs and nothing else:

- `A` — the `AssetRepresentation` (schema.py): segments, entities, claim_candidates,
  cv_findings, semantic_signals, routing, provenance.
- `L` — the `LLMOutput` (llm_contract.py): findings, reviewed_clear,
  frameworks_evaluated, llm_meta.

No model calls, no network calls, no runtime interpretation of regulation text.
Where a check needs regulatory vocabulary (trigger terms, "Member FDIC" wording,
prohibited bases), that vocabulary is a **versioned lexicon constant** compiled into
the engine (Appendix A) and hashed into `provenance.ruleset_hash` — the regulation
was interpreted once, at authoring time, here in this document.

**Sources in scope (manifest `adcoherent-regulatory-sources` v1.0.0, tier 1):**

| manifest id | citation | Framework enum value |
|---|---|---|
| `ftc-act-section-5` | 15 U.S.C. § 45 | `FTC` |
| `cfpb-reg-z-tila` | 12 CFR Part 1026 (§§ 1026.16, 1026.24) | `TILA` |
| `cfpb-reg-dd-tisa` | 12 CFR Part 1030 (§ 1030.8) | `Reg_DD` |
| `fdic-part-328` | 12 CFR Part 328 | **none — schema gap, see §4** |
| `cfpb-reg-b-ecoa` | 12 CFR Part 1002 | `ECOA` |

Everything else in the manifest is deferred (Appendix C).

## Check families (per engine spec)

- **coverage** — the LLM reviewed everything the asset structurally demanded
  (frameworks routed to it, claim candidates, lexicon-flagged segments).
- **grounding** — every LLM assertion is anchored to ids that resolve in `A` and to
  text that verbatim-matches cited segments.
- **consistency** — no internal contradictions between findings, the coverage
  record (`reviewed_clear`), routing, and the asset.
- **structural** — regulation-derived requirements decidable purely from asset
  structure: entity presence/co-occurrence, lexicon matches, CV measurements
  against versioned thresholds.
- **severity_sanity** — deterministic floors on LLM-assessed severity given
  structural facts (a mandatory-disclosure omission cannot be "low").

## Notation and conventions

- `LEX:NAME` — case-insensitive word-boundary regex match of the named lexicon
  (Appendix A) against whitespace-normalized `segment.text`.
- `covered(id)` — `id ∈ (⋃ L.findings[*].cited_segment_ids ∪ cited_entity_ids ∪
  claim_candidate_id) ∪ L.reviewed_clear`.
- `adverse(f)` — `f.verdict ∈ {violation, potential_violation}`.
- `CREDIT` — `A.routing.product_type ∈ {credit_card, personal_loan, mortgage,
  auto_loan, bnpl}`.
- Quote matching (grounding) collapses whitespace runs before substring comparison;
  no other normalization, no fuzzy matching.
- The **severity** column is the severity the *engine* attaches to the check
  failure in its report. Orchestrator policy (retry vs. advisory) keys off it;
  the engine itself only reports: critical/high are intended to force the retry
  loop, medium retries if round budget remains, low is logged as advisory.
- **Scope split (engine v1.1):** every check is registered as *review*-scope
  (judges the LLM output; failures gate `EngineReport.passed` and feed the
  retry loop) or *asset*-scope (decidable from the asset alone; failures are
  true statements about the ad that no re-review can change — reported as
  `EngineReport.asset_defects`, never retried, and not gating `passed`).
  Asset-scope checks: FTC5-STR-001/002, REGZ-STR-001/002/003/004,
  REGDD-STR-001/002/003, FDIC328-STR-001/002. Everything else — including
  ALL-STR-001, which judges `llm_meta` — is review-scope. Downstream
  consumers must read the verdict as `passed` (review sound) **plus**
  `asset_defects` (ad deficient); a clean review of a deficient ad is not
  an approval of the ad.
- Thresholds (`PROX_MAX`, `HEIGHT_MIN_PCT`, `APR_HEIGHT_RATIO_MIN`) are versioned
  constants (Appendix B), tunable only via a ruleset version bump. The CV layer
  emits measurements; the engine applies these thresholds — that division is by
  design (see `CVMeasurementType` docstring).

---

## 0. UNIVERSAL — checks on every asset, regardless of framework

These run on every asset/output pair regardless of routing. Per-framework sections
below do not repeat them.

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| ALL-GRD-001 | ALL | any finding in `L.findings` | some `cited_segment_ids` entry ∉ `A.segments[*].segment_id` | finding_id, unresolved id(s), list of valid segment ids | high |
| ALL-GRD-002 | ALL | any finding | some `cited_entity_ids` entry ∉ `A.entities[*].entity_id` | finding_id, unresolved id(s) | high |
| ALL-GRD-003 | ALL | any finding with `claim_candidate_id` set | id ∉ `A.claim_candidates[*].claim_id` | finding_id, unresolved id | high |
| ALL-GRD-004 | ALL | any finding with `quoted_evidence` set | whitespace-normalized quote is not a substring of any cited segment's normalized text (of all segments if no segments cited) | finding_id, quote, texts of cited segments | high |
| ALL-GRD-005 | ALL | `L.reviewed_clear` non-empty | some entry resolves to neither a `segment_id` nor a `claim_id` in `A` — grounding-flavored coverage: an LLM cannot claim to have reviewed something that doesn't exist (proposed once as ALL-COV-003; implemented under this grounding id — same semantics, one check) | the unresolvable entries plus counts of valid ids | medium |
| ALL-GRD-006 | ALL | any finding with `adverse(f)` | `cited_segment_ids` empty AND `cited_entity_ids` empty AND `claim_candidate_id` null | finding_id, verdict, framework | high |
| ALL-GRD-007 | ALL | any finding whose `quoted_evidence` contains money- or percent-shaped numeric tokens (`$X[,XXX][.XX]`, `X[.X]%` — deliberately excludes bare counts/years like "8.3 times" or "Forbes 2025", which the entity layer does not extract) | some such token, after unit normalization ($ stripped, % kept as the number), matches no entity's non-null `normalized_value` within `NUM_TOL` — either the LLM misquoted a regulated figure or the deterministic extractor missed it; both must surface | finding_id, unmatched token(s) + parsed value, nearest entity normalized_value(s), `NUM_TOL` version | medium |
| ALL-CON-001 | ALL | always | `L.asset_id ≠ A.asset_id` | both ids | critical |
| ALL-CON-002 | ALL | any claim_id or segment_id in `L.reviewed_clear` | same id is also cited by an adverse finding (`claim_candidate_id` match for claims; `cited_segment_ids` match for segments) | the id, the adverse finding_id | high |
| ALL-CON-003 | ALL | `L.frameworks_evaluated` non-empty | some entry is not a valid `Framework` enum value | invalid entries, valid enum values | medium |
| ALL-CON-004 | ALL | any finding with `f.verdict = compliant` | `f.severity ∈ {critical, high}` | finding_id, verdict, severity | medium |
| ALL-CON-005 | ALL | any finding | `f.framework ∉ L.frameworks_evaluated` (finding issued under a framework the LLM says it did not evaluate) | finding_id, framework, frameworks_evaluated | medium |
| ALL-COV-001 | ALL | always | `A.routing.frameworks ⊄ L.frameworks_evaluated` | missing frameworks, `A.routing.signal` (the router's audit trail) | high |
| ALL-COV-002 | ALL | `A.claim_candidates` non-empty | some `claim_id` not covered: ∉ (`⋃ findings[*].claim_candidate_id ∪ L.reviewed_clear`) | uncovered claim ids, their `claim_type`, text, segment_id | high |
| ALL-STR-001 | ALL | always | `L.llm_meta` missing key `model` or `prompt_version` (audit-chain completeness; values are opaque) | present/missing keys | low |

---

## 1. FTC Act § 5 — Unfair or Deceptive Acts or Practices

**Source:** `ftc-act-section-5`, 15 U.S.C. § 45. Topics: `all_ads`, `deception`,
`unfairness`. Manifest note: baseline deception standard applied by the LLM layer;
operative advertising tests live in 16 CFR parts that are out of v1 scope.

The engine cannot decide deception. What it can decide: the FTC baseline was
evaluated at all (the router attaches `FTC` to every asset), the claim types that
carry a substantiation burden were each looked at, and absolute claims
(guarantees, superlatives, "risk-free") were not left standing with literally no
qualifying text anywhere in the asset.

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| FTC5-COV-001 | FTC | `"FTC" ∈ A.routing.frameworks` (always true under current router) | `"FTC" ∉ L.frameworks_evaluated` | routing.frameworks, frameworks_evaluated | high |
| FTC5-COV-002 | FTC | claim candidates with `claim_type ∈ {performance, comparative, guarantee, risk_free}` exist (substantiation-burden types) | any such `claim_id` not covered per ALL-COV-002 semantics — a strict subset of ALL-COV-002, kept so the failure is attributed to the § 5 substantiation duty (and survives if ALL-COV-002 is ever relaxed) | uncovered claim ids + type + text | high |
| FTC5-COV-003 | FTC | `CREDIT` AND (entity `guarantee_term` present OR `LEX:GUARANTEED_APPROVAL` matches a segment) | the matching segment/entity not `covered(...)` — "guaranteed approval" language reviewed by nobody | segment_id, matched lexeme / entity_id, raw_text | high |
| FTC5-STR-001 | FTC | entity `superlative` or `guarantee_term` present, OR claim `guarantee`/`risk_free` present | zero segments with `role ∈ {disclosure, fine_print, legal}` in the whole asset | triggering entity/claim ids, census of segment roles | medium |
| FTC5-STR-002 | FTC | a claim candidate's segment has a bbox AND ≥1 disclosure-role segment has a bbox (so `disclosure_proximity` and `text_height_percent` findings exist) | min `disclosure_proximity` from the claim segment > `PROX_MAX`, OR the nearest disclosure's `text_height_percent` < `HEIGHT_MIN_PCT` | cv finding_ids, measured values, threshold name+version | medium |
| FTC5-SEV-001 | FTC | adverse FTC finding whose `claim_candidate_id` resolves to a claim with `claim_type ∈ {guarantee, risk_free}` and `verdict = violation` | `severity = low` | finding_id, claim_type, severity | medium |

**NOT MECHANIZABLE — stays with LLM layer:** net-impression analysis; whether
substantiation actually exists or is adequate; materiality of the deception;
typicality of example-based claims (e.g. "8.3× faster" from one hypothetical —
the engine can see the claim and the disclosure exist, not whether the example is
representative); unfairness balancing (countervailing benefits, reasonable
avoidability); implied claims not surfaced as claim candidates.

---

## 2. Regulation Z / TILA — 12 CFR §§ 1026.16, 1026.24

**Source:** `cfpb-reg-z-tila`. Topics: `credit_ads`, `APR`, `trigger_terms`,
`loans`, `credit_cards`, `BNPL`. Manifest note: § 1026.16 = open-end (credit
cards, BNPL revolving), § 1026.24 = closed-end (personal/auto/mortgage loans).

This is the most mechanizable framework: triggering terms are enumerable facts
(§ 1026.24(d)(1): downpayment, repayment period/number of payments, payment
amount, finance-charge amount), and the deterministic entity layer already
extracts them (`amount`, `time_period`, `rate`, `apr`, `fee`). The invariant that
entity extraction stays rule-based exists precisely so these checks are auditable.

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| REGZ-COV-001 | TILA | `"TILA" ∈ A.routing.frameworks` | `"TILA" ∉ L.frameworks_evaluated` | routing.frameworks, frameworks_evaluated | high |
| REGZ-STR-001 | TILA | `CREDIT` (closed-end: personal_loan, mortgage, auto_loan, bnpl) AND trigger terms present: (entity `amount` AND entity `time_period` both exist) OR `LEX:TILA_TRIGGER` matches a segment — § 1026.24(d)(1) | no entity `apr` exists AND no segment matches `LEX:APR` — triggering terms advertised without the § 1026.24(d)(2)(ii) APR disclosure | triggering entity ids (raw_text, segment_id, char_span) or lexicon hits; statement that no APR entity/token found | high |
| REGZ-STR-002 | TILA | `CREDIT` AND ≥1 entity `rate` | zero entities `apr` AND the rate entity's segment does not match `LEX:APR` — a finance rate stated but never as an annual percentage rate (§ 1026.24(c) closed-end / § 1026.16(b)(2) open-end) | rate entity_id, raw_text, segment_id | high |
| REGZ-STR-003 | TILA | `A.routing.product_type ∈ {credit_card, bnpl}` AND ≥1 entity `fee` (open-end § 1026.6-type charge advertised) | no entity `apr` AND no `LEX:APR` match anywhere (§ 1026.16(b)(1) disclosure absent) | fee entity ids + raw_text | medium |
| REGZ-STR-004 | TILA | REGZ-STR-001 trigger fired AND an `apr` entity exists AND both its segment and a triggering segment have bboxes | `text_height_percent(APR segment) < APR_HEIGHT_RATIO_MIN × text_height_percent(triggering segment)` OR `disclosure_proximity(trigger seg → APR seg) > PROX_MAX` — clear-and-conspicuous floor on the mandated disclosure | both cv finding_ids + values, threshold name+version, both segment ids | medium |
| REGZ-COV-002 | TILA | REGZ-STR-001 trigger fired (triggering terms present) | no finding with `framework = TILA` exists AND none of the trigger-bearing segments are `covered(...)` — the LLM never engaged with the trigger-term geometry | trigger-bearing segment ids, list of frameworks in findings | high |
| REGZ-SEV-001 | TILA | REGZ-STR-001 **failed** (triggered, no APR anywhere) AND a TILA finding with `verdict = violation` exists | that finding's `severity ∈ {medium, low}` — omission of a mandatory disclosure has a floor of high | finding_id, severity, REGZ-STR-001 evidence | medium |
| REGZ-CON-001 | TILA | any finding with `framework = TILA` | NOT `CREDIT` AND zero `apr`/`rate` entities exist — TILA finding on an asset with no credit signals (advisory: likely misfiled framework) | finding_id, product_type, entity-type census | low |

**NOT MECHANIZABLE — stays with LLM layer:** whether "terms of repayment" are
*completely* disclosed (§ 1026.24(d)(2)(ii) requires full repayment terms, not
just the presence of numbers); whether advertised terms are "actually available"
(§ 1026.24(a) — requires advertiser records); arithmetic consistency of the
representative example (rate × term × amount ⇒ payment — computable in principle,
but linking which extracted numbers form one example is not deterministic today;
future candidate if the NLP layer ever groups example-tables); final
clear-and-conspicuous judgment beyond the geometric floor (REGZ-STR-004 is
evidence, not verdict).

---

## 3. Regulation DD / TISA — 12 CFR § 1030.8

**Source:** `cfpb-reg-dd-tisa`. Topics: `deposit_ads`, `APY`, `savings_accounts`,
`bonuses`.

**Boundary note (see also § 4):** Reg DD governs *deposit-account advertising
terms* — rates stated as APY, "free" account claims, bonus disclosures. It does
**not** govern insured-status wording; "Member FDIC" is FDIC Part 328 territory.
Every check below triggers on deposit product type plus rate/fee/bonus structure,
never on FDIC lexicon. REGDD-CON-001 actively polices the boundary because the
current router folds FDIC-insured-status wording into deposit routing.

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| REGDD-COV-001 | Reg_DD | `"Reg_DD" ∈ A.routing.frameworks` | `"Reg_DD" ∉ L.frameworks_evaluated` | routing.frameworks, frameworks_evaluated | high |
| REGDD-STR-001 | Reg_DD | `product_type = deposit_account` AND ≥1 entity `rate` (v1 restricts to `rate`, not `percentage` — marketing percentages like "72% savings" are not yield statements) | neither that entity's segment nor any other segment matches `LEX:APY` — a rate of return stated but never as "annual percentage yield" (§ 1030.8(b)) | rate entity_id, raw_text, segment_id; statement that no APY token found | high |
| REGDD-STR-002 | Reg_DD | `product_type = deposit_account` AND `LEX:FREE_ACCOUNT` matches a segment | ≥1 entity `fee` with `normalized_value > 0` exists — account advertised as free/no-fee while a fee is disclosed elsewhere in the same asset (§ 1030.8(a) misleading-advertisement prohibition) | free-lexicon segment_id + matched span, fee entity ids + raw_text + normalized_value | high |
| REGDD-STR-003 | Reg_DD | `product_type = deposit_account` AND `LEX:BONUS` matches a segment | zero entities `amount` AND zero entities `time_period` in the whole asset — a bonus advertised with no quantified condition at all (§ 1030.8(d) requires APY, minimum balance, and time requirements) | bonus segment_id + matched span, entity-type census | medium |
| REGDD-COV-002 | Reg_DD | `product_type = deposit_account` AND (REGDD-STR-001/002/003 trigger fired) | no finding with `framework = Reg_DD` AND none of the triggering segments `covered(...)` | triggering segment ids | high |
| REGDD-CON-001 | Reg_DD | any finding with `framework = Reg_DD` | the union of its cited segments' text + `quoted_evidence` matches `LEX:FDIC` AND matches nothing in `LEX:DEPOSIT_TERMS` — an insured-status-only finding filed under Reg DD (belongs to the Part 328 track, § 4) | finding_id, matched FDIC lexemes, absence of deposit-terms lexemes | medium |
| REGDD-SEV-001 | Reg_DD | REGDD-STR-002 **failed** (free + fee) AND a Reg_DD finding with `verdict = violation` cites the free-claim segment | `severity = low` | finding_id, severity, REGDD-STR-002 evidence | medium |

**NOT MECHANIZABLE — stays with LLM layer:** APY arithmetic accuracy (requires
compounding basis and balance tiers, not in `A`); completeness of § 1030.8(c)
additional disclosures (minimum balance to obtain the APY, variable-rate caveat,
time-annuity terms) — presence of *some* numbers is checkable (REGDD-STR-003),
sufficiency is not; whether the stated APY is actually offered; whether "profit"
or other prohibited descriptors are used misleadingly in context.

---

## 4. FDIC Part 328 — Official Signs, Advertising, Misrepresentation of Insured Status

**Source:** `fdic-part-328`, 12 CFR Part 328. Topics: `deposit_insurance_claims`,
`member_fdic`, `neobank_ads`, `pass_through_insurance`. Manifest note: recently
overhauled; critical for fintechs partnering with banks.

**This framework is deliberately kept separate from Reg DD.** Part 328 governs
*who may claim FDIC insurance and how* — the official advertising statement,
misrepresentation of insured status, and non-deposit-product disclaimers
(subpart B, § 328.102). Reg DD governs deposit *terms*. The current router
conflates the two (FDIC wording contributes to deposit routing); checks here key
exclusively on `LEX:FDIC` matches, never on product routing alone.

> **Schema gap (action item, not a check):** `schema.Framework` has no `FDIC`
> value, so the LLM cannot file a finding under Part 328 at all. Until
> `Framework.FDIC` is added (schema minor bump) and the router emits it, insured-
> status findings are expected under `CFPB` or `FTC`; FDIC328-CON-001 is advisory
> for that reason. Router change request: stop letting FDIC lexicon imply
> `deposit_account` routing; emit the (future) FDIC framework off the lexicon
> instead.

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| FDIC328-STR-001 | (Part 328) | `LEX:FDIC` matches any segment | `A.routing.product_type ∈ {investment, crypto, insurance}` — insured-status wording on an uninsurable product class (§ 328.102(b): misrepresentation; the classic neobank/crypto failure) | matching segment_id + matched span + text, product_type, routing.signal | critical |
| FDIC328-STR-002 | (Part 328) | `LEX:FDIC` matches AND `LEX:INVESTMENT` matches somewhere in the asset (hybrid ad: insured deposit claim + non-deposit product content) | no segment matches `LEX:NON_DEPOSIT_DISCLAIMER` ("not FDIC-insured / may lose value / not bank guaranteed" family, § 328.102(b)(5)) | FDIC segment_id, investment-lexicon segment_id, statement that no disclaimer lexeme found | medium |
| FDIC328-COV-001 | (Part 328) | `LEX:FDIC` matches segment S | S not `covered(...)` — an insured-status claim no finding cites and `reviewed_clear` doesn't list; insured-status wording must never pass unreviewed | S id, matched span + text | high |
| FDIC328-CON-001 | (Part 328) | `LEX:FDIC` matches segment S AND ≥1 finding cites S | every finding citing S has `framework = Reg_DD` — insured-status treated purely as a deposit-terms issue (mirror of REGDD-CON-001; advisory until `Framework.FDIC` exists) | finding ids + frameworks, S id | low |
| FDIC328-SEV-001 | (Part 328) | a finding cites an `LEX:FDIC`-matching segment with `verdict = violation` AND `product_type ∈ {investment, crypto, insurance}` | `severity ∈ {medium, low}` — misrepresenting deposit insurance on uninsurable products has a floor of high | finding_id, severity, FDIC328-STR-001 evidence | high |

**NOT MECHANIZABLE — stays with LLM layer (or needs inputs we don't have):**
whether the advertiser *is* an insured depository institution or a bona fide bank
partner (external registry fact — belongs in orchestrator-side advertiser
metadata, present in neither JSON; without it, "Member FDIC" on a deposit ad can
never be confirmed true or false by the engine); accuracy of pass-through /
sweep-program insurance representations (§ 328.102(b)(3) — program facts are
external); official-sign display specs of subpart A (§ 328.3 size/placement — the
free-tier CV layer does not detect the FDIC official sign; a future paid-tier
check could key on `semantic_signals` LOGO detections, noted as a phase-2
candidate, not a v1 check); whether "Member FDIC" attributes insurance to the
correct named bank.

---

## 5. ECOA / Regulation B — 12 CFR Part 1002

**Source:** `cfpb-reg-b-ecoa`. Topics: `discrimination`, `credit_ads`,
`targeting`, `discouragement`. The advertising-relevant core is § 1002.4(b): a
creditor shall not make statements to applicants or prospective applicants that
would discourage on a prohibited basis a reasonable person from applying.

Almost all of Reg B is judgment or requires inputs the pipeline does not carry
(media targeting, imagery semantics). The mechanizable slice is narrow and
honest: make sure prohibited-basis vocabulary in a credit ad was at least
*looked at*, and keep the coverage plumbing ready for when the router emits ECOA.

> **Router gap (action item, not a check):** the router never emits `ECOA` today
> (verified against `nlp/routing.py` — credit products route to TILA+CFPB only),
> so REGB-COV-001 is vacuous until that changes. REGB-COV-002 therefore triggers
> on product type + lexicon directly, not on routing. Router change request: add
> `ECOA` for `CREDIT` products.

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| REGB-COV-001 | ECOA | `"ECOA" ∈ A.routing.frameworks` (currently never — see router gap) | `"ECOA" ∉ L.frameworks_evaluated` | routing.frameworks, frameworks_evaluated | high |
| REGB-COV-002 | ECOA | `CREDIT` AND `LEX:PROHIBITED_BASIS` matches segment S | S not `covered(...)` — prohibited-basis vocabulary in a credit ad that no finding cites and `reviewed_clear` doesn't list | S id, matched lexeme + span | medium |
| REGB-CON-001 | ECOA | any finding with `framework = ECOA` | NOT `CREDIT` AND zero credit-signal entities (`apr`, `rate`, `fee`) — ECOA finding on an asset with no credit signals (advisory: likely misfiled) | finding_id, product_type, entity-type census | low |
| REGB-SEV-001 | ECOA | ECOA finding with `verdict = violation` whose cited segments match `LEX:PROHIBITED_BASIS` | `severity = low` — an affirmed prohibited-basis violation floors at medium | finding_id, severity, matched lexeme | low |

**NOT MECHANIZABLE — stays with LLM layer (or absent from inputs):**
discouragement analysis itself (tone, context, "reasonable person" standard —
§ 1002.4(b)); audience-targeting discrimination (media plan / platform targeting
criteria are in neither JSON); imagery-based discouragement (the CV layer emits
measurements, not demographic readings of imagery — by design); disparate-impact
analysis; special-purpose credit program (§ 1002.8) legitimacy; age/sex/gender
lexemes are deliberately **excluded** from the v1 prohibited-basis lexicon
(false-positive rate on ordinary marketing copy is too high — "senior discount",
"students save" — the LLM layer handles those contextually).

---

## 6. State UDAP — "little FTC acts" (STATE_UDAP umbrella framework)

**Source:** tier-2 `state_udap` manifest entries (51 jurisdictions), compiled
into the versioned metadata table `rule_engine/state_udap_table.py`
(**Appendix D**). State consumer-protection statutes are predominantly FTC §5
analogues, so these checks mirror the FTC5 logic **once**, parameterized per
state — never 50 near-copies. They gate on `STATE_UDAP` routing, which the
router emits only when user-supplied `A.target_jurisdictions` contains a US
state code; every failure's evidence carries the state's own statute citation
from the table — that citation is the downstream audit-trail payload. States
whose table entry has `credit_exempt=True` are skipped on credit-product
assets with the exemption cited (see Appendix D's VERIFY discipline).

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| STATE-COV-001 | STATE_UDAP | `"STATE_UDAP" ∈ A.routing.frameworks` | `"STATE_UDAP" ∉ L.frameworks_evaluated` AND no finding with `framework = STATE_UDAP` | targeted states + statutes, frameworks_evaluated | high |
| STATE-COV-002 | STATE_UDAP | routed AND targeted state codes present (skip `credit_exempt=True` states on CREDIT assets, citing the exemption) | some non-exempt targeted state's code appears in no STATE_UDAP finding's `reasoning`/`quoted_evidence` — each state must be individually considered, not "states generally" | unmentioned states + statutes; exempt-skipped states + exemption note | medium |
| STATE-SEV-001 | STATE_UDAP | adverse FTC finding with `severity ∈ {critical, high}` exists AND a `STATE_UDAP` finding with `verdict = compliant` exists | the compliant state finding's reasoning does not name the adverse federal `finding_id` (v1 deterministic proxy for "explicit reasoning") — little-FTC acts track the federal standard; a federal deception hit almost always implies state exposure | federal finding ids, unreconciled state finding ids, per-state statutes covered | medium |
| STATE-STR-001 | STATE_UDAP (scope=asset) | `"US-UT" ∈ target_jurisdictions` AND claims with `claim_type ∈ {pricing, comparative}` (Utah Truth in Advertising Act, § 13-11a — manifest: rare among states, warrants its own rules) | zero segments with `role ∈ {disclosure, fine_print, legal}` — price/comparison claims aimed at Utah with no qualifying text anywhere | triggering claim ids + the Utah statute citation, role census | medium |

**NOT MECHANIZABLE — stays with LLM layer:** per-state remedy and penalty
differences (statutory vs. treble damages, per-violation fines); private
right-of-action analysis (standing, ascertainable-loss and reliance elements,
e.g. NJ CFA / MA 93A demand-letter prerequisites); state-specific case-law
standards diverging from FTC interpretation; AG enforcement posture; whether
a specific state exemption applies to this advertiser's charter/licensing
(the table's `credit_exempt` is a product-category gate, not an
advertiser-level determination).

---

Compiled constants in the engine; case-insensitive, word-boundary regex over
whitespace-normalized segment text. The lexicon set and version are part of the
payload hashed into `provenance.ruleset_hash`. Editing any lexicon is a ruleset
version bump.

| lexicon | v1 members |
|---|---|
| `LEX:APR` | `apr`, `annual percentage rate` |
| `LEX:APY` | `apy`, `annual percentage yield` |
| `LEX:TILA_TRIGGER` | `per month`, `/mo`, `a month`, `monthly payment`, `payments of`, `down payment`, `no money down`, `-month term`, `month term`, `weekly payment` |
| `LEX:FDIC` | `fdic`, `member fdic`, `fdic insured`, `fdic-insured`, `federally insured`, `deposit insurance` |
| `LEX:DEPOSIT_TERMS` | `apy`, `annual percentage yield`, `interest rate`, `interest`, `bonus`, `minimum balance`, `fee`, `compounded` |
| `LEX:FREE_ACCOUNT` | `free`, `no fee`, `no fees`, `no monthly fee`, `no hidden fees`, `zero fees`, `no cost` |
| `LEX:BONUS` | `bonus`, `sign-up bonus`, `signup bonus`, `welcome bonus` |
| `LEX:NON_DEPOSIT_DISCLAIMER` | `not fdic insured`, `not fdic-insured`, `may lose value`, `not bank guaranteed`, `no bank guarantee`, `not insured by any federal government agency` |
| `LEX:INVESTMENT` | `invest`, `investment`, `securities`, `stocks`, `crypto`, `bitcoin`, `portfolio`, `returns` |
| `LEX:GUARANTEED_APPROVAL` | `guaranteed approval`, `approval guaranteed`, `guarantee approval`, `no credit check`, `everyone qualifies`, `no one refused`, `everyone('s| is) approved` |
| `LEX:PROHIBITED_BASIS` | `race`, `religion`, `national origin`, `marital status`, `public assistance` (conservative v1 — see § 5 note on age/sex exclusion) |

Ordering note: multi-word members are matched before their single-word prefixes
(`LEX:FDIC` matches `member fdic` as one hit, not `fdic` twice); `LEX:FREE_ACCOUNT`'s
bare `free` is expected to be noisy — it only ever *triggers* REGDD-STR-002, which
still requires a positive fee entity to fail, so the noise cannot produce a
failure on its own.

## 7. Coverage-matrix frameworks (ruleset 1.5.0)

**Source:** `docs/coverage_matrix.md` (rule_engine/coverage_matrix.py v1.0.0) —
the classified Regulatory Source Directory. This section mechanizes the
matrix's structural rows where the creative alone decides, adds one
parameterized coverage check for every matrix framework the router can attach,
and records the NOT MECHANIZABLE remainder per framework. Modules:
`checks_mla.py`, `checks_fcrav.py`, `checks_canspam.py`, `checks_wcag.py`,
`checks_endorsements.py`, `checks_matrix_coverage.py`. New lexicons and
thresholds are Appendix A/B v2 entries.

### 7.1 MLA — Military Lending Act (32 CFR Part 232)

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| MLA-STR-001 | MLA (scope=asset) | `"MLA" ∈ A.routing.frameworks` (military/servicemember/MAPR wording on a credit ad) | any `apr`/`rate` entity with `normalized_value > MAPR_CAP` (36.0) — the creative states a rate above the Military APR cap, 32 CFR 232.4(b) | offending entity ids + values, `MAPR_CAP` + thresholds version | high |

**NOT MECHANIZABLE — stays with LLM layer:** covered-borrower status (DoD
database check); MAPR *computation* from fee components (the cap check reads
only stated rates); required oral disclosures; arbitration-clause prohibitions.

### 7.2 FCRA / Reg V — prescreened firm offers (15 U.S.C. § 1681m(d))

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| FCRAV-STR-001 | FCRA (scope=asset) | `LEX:PRESCREEN_WORDING` matches a segment | zero segments match `LEX:PRESCREEN_OPTOUT_NOTICE` — prescreen solicitation with no 615(d) opt-out notice anywhere in the creative | prescreen segments + matched lexemes, lexicon version | high |

**NOT MECHANIZABLE — stays with LLM layer:** whether the offer actually
derives from a prescreened list; firm-offer genuineness; notice
clear-and-conspicuous adequacy beyond the presence test; permissible-purpose
analysis.

### 7.3 CAN-SPAM (16 CFR Part 316)

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| CANSPAM-STR-001 | CAN-SPAM (scope=asset) | `"CAN-SPAM" ∈ A.routing.frameworks` (email-structured creative per the router) | zero `optout_marker` entities AND zero `LEX:EMAIL_OPTOUT` matches — no opt-out mechanism at all | entity-type census, lexicon version | medium |

**NOT MECHANIZABLE — stays with LLM layer:** header/sender accuracy;
subject-line deception; whether opt-outs are honored within 10 days; postal
address validity (presence could mechanize once an address entity exists).

### 7.4 WCAG 2.x SC 1.4.3 — contrast (matrix row `wcag-contrast`)

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| WCAG-STR-001 | WCAG (scope=asset) | `contrast_ratio` cv_findings exist on disclosure-role segments (disclosure/fine_print/legal) | any measured ratio < `WCAG_CONTRAST_MIN` (4.5) | cv finding ids + values + roles, threshold + version | medium |

**NOT MECHANIZABLE — stays with LLM layer:** large-text 3:1 carve-out (point
size is not measured, only relative height); logotype/incidental-text
exemptions; non-text contrast (SC 1.4.11).

### 7.5 FTC Endorsement Guides (16 CFR Part 255)

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| ENDOR-COV-001 | FTC | `endorsement_marker` entities present | some marker where no FTC-framework finding cites its entity_id or segment_id AND its segment not in `reviewed_clear` — the 16 CFR 255 duty was reviewed by nobody | unaddressed entity ids + raw text, FTC finding ids checked | high |

**NOT MECHANIZABLE — stays with LLM layer:** endorsement truthfulness and
typicality; material-connection adequacy; disclosure conspicuousness relative
to the endorsement (FTC5-STR-002 geometry partially covers proximity).

### 7.6 Parameterized matrix coverage (structural-row frameworks)

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| MATRIX-COV-001 | matrix frameworks (parameterized once — mirrors §6's never-N-copies design) | any STRUCTURAL-mechanization matrix framework ∈ `A.routing.frameworks`, excluding legacy per-framework COV-001 holders (FTC, TILA, Reg_DD, ECOA, FDIC, STATE_UDAP); coverage-mechanization rows are owned by §7.7's generated checks | some such routed framework ∉ `L.frameworks_evaluated` — companion by design: ALL-COV-001 (same duty, unattributed) | missing frameworks, routing signal, coverage-matrix version | high |

### 7.7 Generated per-framework coverage checks (coverage-row frameworks)

Registered at import time from the versioned matrix constant
(`rule_engine/checks_coverage_ext.py`) — one check per
coverage-mechanization framework, deterministic because the matrix is a
constant hashed into the ruleset. Never N hand-written near-identical files.

| check_id | framework | trigger condition | fail condition | evidence to include | severity |
|---|---|---|---|---|---|
| `<FW>-COV-001` (generated: one per coverage-row framework — COPPA, SEC, FINRA, GLBA, SCRA, NMLS, CFTC_NFA, STATE_FINREG, STATE_PRIVACY, MINI_TCPA, PLATFORM_POLICY, CARD_NETWORK, SELF_REG) | FW | `FW ∈ A.routing.frameworks` (registration gates on it) | `FW ∉ L.frameworks_evaluated`, OR some finding under FW cites an unresolvable segment/entity/claim id (framework-attributed restatement of ALL-GRD-001/002/003, which fire alongside by design) | the framework's matrix source rows + citations, frameworks_evaluated / unresolved ids, matrix version | high |

Mutations are parameterized identically: for every generated check, one
drop-from-`frameworks_evaluated` mutation (companion: ALL-COV-001), plus one
ungrounded-finding mutation exercising the grounding leg.

### 7.8 Generated advisory checks (advisory-row frameworks)

Registered at import time from the matrix's `mechanization="advisory"` rows
(`rule_engine/checks_advisory.py`), with the third check scope,
`scope="advisory"`: informational applicability flags that land in
`EngineReport.advisories` (and `FinalResult.advisories` end-to-end), **never
gate `passed`, and never retry** — nothing about the creative can satisfy or
violate a process/governance rule.

| check_id | framework | trigger condition | emits | evidence to include | severity |
|---|---|---|---|---|---|
| `ADV-<source>` (generated: sec-204-2-books-records → SEC-routed; finra-4511-17a-4 → FINRA-routed; cfpb-cms → CFPB-routed; pci-dss, nist-privacy-framework → always) | matrix row's family | row's routing_trigger (framework routed, or always for advertiser-level baselines) | applicability flag: "retention/program obligations apply to this material; out of creative scope" | source id, citation, routing_trigger, matrix version | low |

Mutations are parameterized from the same rows: each `ADV-<source>` flag is
asserted present in `EngineReport.advisories` and absent from
`failed_checks`; the harness additionally asserts on every mutation that no
advisory-scope result ever appears in `failed_checks` or `asset_defects`.

**NOT MECHANIZABLE — stays with LLM layer (per framework):** SCRA —
benefit/rate-reduction eligibility. FDCPA/Reg F — false-representation and
harassment judgments in collection copy. Reg E — disclosure-content adequacy.
Reg M — lease-disclosure completeness beyond trigger terms. Reg N — deception
judgment on mortgage claims. NMLS — license validity lookup (a registry query
is a network call, outside the deterministic floor). COPPA —
audience-composition analysis. GLBA/Reg P + STATE_PRIVACY — privacy-notice
content adequacy; applicability beyond targeting codes. TCPA/MINI_TCPA —
consent sufficiency, established-business-relationship analysis. CFTC/NFA —
hypothetical-performance and risk-disclosure adequacy. SEC/FINRA (Marketing
Rule, 2210, 482/34b-1) — performance-presentation, testimonial, and
fair-balance judgments. CARD_NETWORK/PLATFORM_POLICY/SELF_REG — contractual
brand/policy compliance against evolving external rulebooks. FAIR_HOUSING —
discriminatory-content judgment. NCUA 740 — mirrors FDIC 328; dedicated
structural checks deferred until credit-union assets appear in the corpus.

---

## Appendix B — Versioned thresholds (v2)

All applied by the engine to CV-layer measurements; all tunable pending
calibration against gold/silver corpora, via ruleset version bump only.

| constant | value | used by | meaning |
|---|---|---|---|
| `PROX_MAX` | 0.60 | FTC5-STR-002, REGZ-STR-004 | max normalized bbox-center distance claim→disclosure (`disclosure_proximity`) |
| `HEIGHT_MIN_PCT` | 0.9 | FTC5-STR-002 | min disclosure `text_height_percent` (percent of asset height) |
| `APR_HEIGHT_RATIO_MIN` | 0.33 | REGZ-STR-004 | min ratio of APR-disclosure text height to triggering-claim text height |
| `NUM_TOL` | 0.005 | ALL-GRD-007 | max absolute difference between a unit-normalized quoted numeric and an entity `normalized_value` (i.e. equal after rounding both to 2 decimals) |
| `MAPR_CAP` | 36.0 | MLA-STR-001 | Military APR cap, 32 CFR 232.4(b) (v2 addition) |
| `WCAG_CONTRAST_MIN` | 4.5 | WCAG-STR-001 | WCAG 2.x SC 1.4.3 minimum contrast ratio (v2 addition) |

Appendix A v2 lexicon additions (see `rule_engine/lexicons.py`):
`LEX:MILITARY_CREDIT`, `LEX:PRESCREEN_WORDING`, `LEX:PRESCREEN_OPTOUT_NOTICE`,
`LEX:EMAIL_OPTOUT`.

## Appendix C — Deferred to later phase

**Tier 1 federal, out of v1 scope** (in-manifest, checks not authored yet):
`ftc-endorsement-guides` (16 CFR 255), `ftc-consumer-reviews-rule` (16 CFR 465),
`ftc-deceptive-pricing-guides` (16 CFR 233), `ftc-free-offer-guides` (16 CFR 251 —
note: v1's free-claim check REGDD-STR-002 cites Reg DD § 1030.8(a), *not* Part 251;
non-deposit "free" claims wait for this source), `ftc-telemarketing-sales-rule`
(16 CFR 310), `ftc-can-spam-rule` (16 CFR 316), `ftc-coppa` (16 CFR 312),
`cfpb-reg-m-leasing` (12 CFR 1013), `cfpb-reg-n-map` (12 CFR 1014),
`cfpb-udaap-statute` (12 U.S.C. §§ 5531/5536), `ncua-part-740` (12 CFR 740),
`sec-marketing-rule` (17 CFR 275.206(4)-1), `sec-rule-482` (17 CFR 230.482),
`sec-ica-rule-34b-1` (17 CFR 270.34b-1), `finra-rule-2210` (note: amendment
SR-FINRA-2026-004 in flight), `fcc-tcpa-rules` (47 CFR § 64.1200),
`hud-fair-housing-advertising` (24 CFR 100).

**Tier 2 — state UDAP / state finreg sources**: the 51 `state_udap` entries
now back the §6 STATE_UDAP checks via the Appendix D metadata table
(statute-level checks per state remain future work); `us-ca-dfpi-ccfpl` and
`us-ny-dfs-crypto-ads` (state finreg) stay deferred.

**Tier 3 — secondary references** (`ref-nclc-50-state-report`,
`ref-nclc-state-summaries`, `ref-cozen-50-state-chart`,
`ref-justia-50-state-survey`): deferred; per manifest these are routing/metadata
aids and are **never** check sources or citable legal text.

## Appendix D — State UDAP metadata table

Compiled constant: `rule_engine/state_udap_table.py` (`STATE_TABLE_VERSION`,
hashed into `ruleset_hash` like the lexicons). One entry per tier-2 manifest
jurisdiction (51): statute citation, statute name, `credit_exempt`, scope
notes. `credit_exempt=True` silently disables credit-ad state checks for that
state, so it is set only for textbook broad regulated-industry exemptions
(MI, RI, GA, OH, VA) and **every** True entry sits on the module's VERIFY
list; all uncertain states are conservatively `credit_exempt=False` with
VERIFY in notes. Verification reference: the NCLC 50-state UDAP report
(tier-3 `ref-nclc-50-state-report`) — routing metadata, never citable legal
text.

## Change requests surfaced by this authoring pass (not checks)

1. **schema.py:** add `FDIC = "FDIC"` to `Framework` (minor version bump) so Part
   328 findings can be filed under their own framework. — **DONE 2026-07-10**
   (also added `STATE_UDAP` umbrella value + `AssetRepresentation.
   target_jurisdictions`); the FDIC328 checks still key on lexicon, and the
   router-side half of this request remains open (#2).
2. **nlp/routing.py:** stop letting FDIC-insured-status wording contribute to
   `deposit_account` routing; route `LEX:FDIC` matches to the new FDIC framework.
   — **DONE 2026-07-10**: `fdic` removed from the deposit product rule (and bare
   `savings` tightened to `savings account` — cost-savings marketing is not a
   deposit signal); insured-status wording routes FDIC on every path, including
   the semantic fallback.
3. **nlp/routing.py:** emit `ECOA` for `CREDIT` products so REGB-COV-001 stops
   being vacuous. — **DONE 2026-07-10** (credit_card/personal_loan/mortgage/
   auto_loan/bnpl; credit_repair excluded — a service, not an extension of
   credit). Router also emits `STATE_UDAP` when user-supplied
   `target_jurisdictions` contains a US state code.
