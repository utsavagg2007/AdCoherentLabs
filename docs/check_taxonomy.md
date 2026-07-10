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
| ALL-GRD-005 | ALL | `L.reviewed_clear` non-empty | some entry resolves to neither a `segment_id` nor a `claim_id` in `A` | unresolved entries | medium |
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

## Appendix A — Versioned lexicons (v1)

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

## Appendix B — Versioned thresholds (v1)

All applied by the engine to CV-layer measurements; all tunable pending
calibration against gold/silver corpora, via ruleset version bump only.

| constant | v1 value | used by | meaning |
|---|---|---|---|
| `PROX_MAX` | 0.60 | FTC5-STR-002, REGZ-STR-004 | max normalized bbox-center distance claim→disclosure (`disclosure_proximity`) |
| `HEIGHT_MIN_PCT` | 0.9 | FTC5-STR-002 | min disclosure `text_height_percent` (percent of asset height) |
| `APR_HEIGHT_RATIO_MIN` | 0.33 | REGZ-STR-004 | min ratio of APR-disclosure text height to triggering-claim text height |
| `NUM_TOL` | 0.005 | ALL-GRD-007 | max absolute difference between a unit-normalized quoted numeric and an entity `normalized_value` (i.e. equal after rounding both to 2 decimals) |

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

**Tier 2 — all state UDAP / state finreg sources** (51 entries, `us-al-udap`
through `us-wy-udap`, plus `us-ca-dfpi-ccfpl` and `us-ny-dfs-crypto-ads`):
deferred to later phase.

**Tier 3 — secondary references** (`ref-nclc-50-state-report`,
`ref-nclc-state-summaries`, `ref-cozen-50-state-chart`,
`ref-justia-50-state-survey`): deferred; per manifest these are routing/metadata
aids and are **never** check sources or citable legal text.

## Change requests surfaced by this authoring pass (not checks)

1. **schema.py:** add `FDIC = "FDIC"` to `Framework` (minor version bump) so Part
   328 findings can be filed under their own framework. — **DONE 2026-07-10**
   (also added `STATE_UDAP` umbrella value + `AssetRepresentation.
   target_jurisdictions`); the FDIC328 checks still key on lexicon, and the
   router-side half of this request remains open (#2).
2. **nlp/routing.py:** stop letting FDIC-insured-status wording contribute to
   `deposit_account` routing; route `LEX:FDIC` matches to the new FDIC framework.
3. **nlp/routing.py:** emit `ECOA` for `CREDIT` products so REGB-COV-001 stops
   being vacuous.
