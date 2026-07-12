"""Output contract for the AdCoherentLabs CV + NLP structuring layers.

This module defines the *exact* Pydantic shape emitted by the deterministic
CV (computer vision) and NLP layers and consumed downstream by the rule
engine and the LLM compliance layer.

Design principle: these layers are STRUCTURERS, NOT JUDGES. Every model here
carries measurements, extracted spans, and candidate labels — never verdicts,
severities, or compliance conclusions. Judgment is the exclusive job of the
rule engine and LLM layer, which cite these structures as evidence.

Contract minor bump (2026-07-10), additive only: Framework gains FDIC
(12 CFR Part 328) and STATE_UDAP (umbrella for state consumer-protection
law); AssetRepresentation gains optional ``target_jurisdictions``
(user-supplied ad-targeting codes; empty = unspecified). Existing
documents validate unchanged.

Contract minor bump (2026-07-12), additive only: Provenance gains
optional ``ocr_backend``; Framework gains one value per framework family
of the regulatory coverage matrix (docs/coverage_matrix.md), with
umbrella values where the Regulatory Source Directory groups sources
(STATE_PRIVACY, MINI_TCPA, PLATFORM_POLICY, CARD_NETWORK, SELF_REG,
STATE_FINREG). Existing documents validate unchanged.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: 'US' (nationwide/federal-only) or 'US-XX' state codes, uppercase.
_JURISDICTION_RE = re.compile(r"US(-[A-Z]{2})?")


# ---------------------------------------------------------------------------
# Enums — categorical vocabularies shared with the rule engine
# ---------------------------------------------------------------------------


class SegmentRole(str, Enum):
    """Functional role of a text segment within a marketing asset.

    Role drives which rules apply: disclosures and fine print carry
    prominence/proximity requirements (FTC "clear and conspicuous"
    standard), CTAs interact with TILA triggering-term rules, etc.
    """

    HEADLINE = "headline"
    BODY = "body"
    DISCLOSURE = "disclosure"
    FINE_PRINT = "fine_print"
    CTA = "cta"
    LEGAL = "legal"
    UNKNOWN = "unknown"


class SegmentSource(str, Enum):
    """Where the segment text was obtained.

    OCR-sourced text has lower fidelity; the rule engine may weight
    char-level evidence differently and the LLM layer may request
    re-extraction on low-confidence OCR spans.
    """

    TEXT = "text"
    HTML = "html"
    OCR = "ocr"


class EntityType(str, Enum):
    """Type of extracted fact.

    These are the atomic facts regulations attach to: an APR mention is
    governed by TILA advertising rules (12 CFR 1026.16 open-end /
    1026.24 closed-end), a superlative feeds
    FTC substantiation analysis, an opt-out marker is a CAN-SPAM /
    TCPA structural requirement, etc.
    """

    APR = "apr"
    FEE = "fee"
    RATE = "rate"
    AMOUNT = "amount"
    PERCENTAGE = "percentage"
    SUPERLATIVE = "superlative"
    ENDORSEMENT_MARKER = "endorsement_marker"
    OPTOUT_MARKER = "optout_marker"
    GUARANTEE_TERM = "guarantee_term"
    TIME_PERIOD = "time_period"


class ClaimType(str, Enum):
    """Category of claim a text span makes.

    Claim type routes to framework-specific analysis: performance and
    comparative claims require FTC substantiation; guarantee and
    risk-free claims implicate SEC/FINRA suitability and FTC deception
    rules; pricing claims trigger TILA/Reg DD disclosure requirements;
    endorsements fall under FTC 16 CFR Part 255.
    """

    PERFORMANCE = "performance"
    COMPARATIVE = "comparative"
    GUARANTEE = "guarantee"
    ENDORSEMENT = "endorsement"
    PRICING = "pricing"
    RISK_FREE = "risk_free"


class CVMeasurementType(str, Enum):
    """Type of visual measurement produced by the CV layer.

    Measurements only — the CV layer reports numbers (e.g. a contrast
    ratio of 2.7) and never conclusions (e.g. "fails WCAG"). The rule
    engine applies thresholds.
    """

    CONTRAST_RATIO = "contrast_ratio"
    TEXT_HEIGHT_PERCENT = "text_height_percent"
    DISCLOSURE_PROXIMITY = "disclosure_proximity"
    MARKER_PRESENCE = "marker_presence"


class SemanticSignalType(str, Enum):
    """Kind of semantic signal an external vision/semantic service emitted.

    These are auxiliary classification hints (e.g. Google Vision label,
    logo, or web-entity detections) that support routing and recall.
    They are hints with confidences, never verdicts.
    """

    LABEL = "label"
    LOGO = "logo"
    WEB_ENTITY = "web_entity"
    SAFE_SEARCH = "safe_search"


class ProductType(str, Enum):
    """Fintech product category the asset markets.

    Product type is the primary routing key: credit products route to
    TILA/ECOA, deposit products to Reg DD, investment products to
    SEC/FINRA, etc.
    """

    CREDIT_CARD = "credit_card"
    PERSONAL_LOAN = "personal_loan"
    MORTGAGE = "mortgage"
    AUTO_LOAN = "auto_loan"
    BNPL = "bnpl"
    DEPOSIT_ACCOUNT = "deposit_account"
    INVESTMENT = "investment"
    CRYPTO = "crypto"
    INSURANCE = "insurance"
    CREDIT_REPAIR = "credit_repair"
    UNKNOWN = "unknown"


class Framework(str, Enum):
    """US regulatory framework an asset may be evaluated against.

    FDIC covers 12 CFR Part 328 insured-status advertising — distinct
    from Reg_DD, which covers deposit-account terms. STATE_UDAP is the
    single umbrella value for state consumer-protection law; individual
    states are identified by ``AssetRepresentation.target_jurisdictions``
    codes, never by per-state enum values.
    """

    FTC = "FTC"
    CFPB = "CFPB"
    TILA = "TILA"
    SEC = "SEC"
    FINRA = "FINRA"
    CAN_SPAM = "CAN-SPAM"
    ECOA = "ECOA"
    FCRA = "FCRA"
    REG_DD = "Reg_DD"
    TCPA = "TCPA"
    FDIC = "FDIC"
    STATE_UDAP = "STATE_UDAP"
    # Coverage-matrix families (docs/coverage_matrix.md), 2026-07-12
    # minor bump. One value per framework family; umbrella values where
    # the Regulatory Source Directory groups sources.
    COPPA = "COPPA"
    REG_M = "Reg_M"
    REG_N = "Reg_N"
    REG_E = "Reg_E"
    NCUA = "NCUA"
    FAIR_HOUSING = "FAIR_HOUSING"
    MLA = "MLA"
    FDCPA = "FDCPA"
    WCAG = "WCAG"
    CFTC_NFA = "CFTC_NFA"
    GLBA = "GLBA"
    SCRA = "SCRA"
    NMLS = "NMLS"
    STATE_FINREG = "STATE_FINREG"       # state consumer-finance regulators
    STATE_PRIVACY = "STATE_PRIVACY"     # umbrella: CCPA/VCDPA/... via target_jurisdictions
    MINI_TCPA = "MINI_TCPA"             # umbrella: FTSA and sister mini-TCPAs
    PLATFORM_POLICY = "PLATFORM_POLICY" # umbrella: Google/Meta ad policies
    CARD_NETWORK = "CARD_NETWORK"       # umbrella: Visa/Mastercard standards
    SELF_REG = "SELF_REG"               # umbrella: NAD/CARU/DAA/NAI/IAB
    PCI_DSS = "PCI_DSS"
    NIST_PRIVACY = "NIST_PRIVACY"


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


class BoundingBox(BaseModel):
    """Axis-aligned bounding box in normalized coordinates.

    All values are fractions of the rendered asset's width/height in
    [0, 1], origin at the top-left. Normalized coordinates keep
    proximity and prominence measurements resolution-independent.
    """

    model_config = ConfigDict(frozen=True)

    x: float = Field(..., ge=0.0, le=1.0, description="Left edge, fraction of asset width.")
    y: float = Field(..., ge=0.0, le=1.0, description="Top edge, fraction of asset height.")
    width: float = Field(..., gt=0.0, le=1.0, description="Box width, fraction of asset width.")
    height: float = Field(..., gt=0.0, le=1.0, description="Box height, fraction of asset height.")

    @model_validator(mode="after")
    def _box_within_asset(self) -> "BoundingBox":
        if self.x + self.width > 1.0 + 1e-9:
            raise ValueError("bounding box extends past right edge (x + width > 1)")
        if self.y + self.height > 1.0 + 1e-9:
            raise ValueError("bounding box extends past bottom edge (y + height > 1)")
        return self


# ---------------------------------------------------------------------------
# Core structures
# ---------------------------------------------------------------------------


class Segment(BaseModel):
    """A contiguous span of asset text with a functional role.

    Segments are the addressing scheme for the whole contract: entities,
    claim candidates, and CV findings all reference segments by id.
    Segmentation must therefore be stable and deterministic for a given
    input asset.
    """

    segment_id: str = Field(
        ...,
        min_length=1,
        description="Stable, asset-unique identifier for this segment (e.g. 'seg_003').",
    )
    text: str = Field(
        ...,
        description=(
            "Verbatim segment text. char_span offsets in Entity and "
            "ClaimCandidate index into this string."
        ),
    )
    role: SegmentRole = Field(
        ...,
        description=(
            "Functional role. Determines which prominence/placement rules "
            "apply — e.g. DISCLOSURE segments are subject to FTC "
            "clear-and-conspicuous analysis."
        ),
    )
    source: SegmentSource = Field(
        ...,
        description="Extraction channel (native text, HTML parse, or OCR).",
    )
    bbox: Optional[BoundingBox] = Field(
        default=None,
        description=(
            "Location of the segment in the rendered asset, when the asset "
            "is visual. Required for CV proximity/prominence measurements; "
            "None for plain-text assets."
        ),
    )
    ocr_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Mean OCR confidence for this segment in [0, 1]. Only set when "
            "source is OCR; lets downstream layers discount low-fidelity text."
        ),
    )


class CharSpan(BaseModel):
    """Half-open character interval [start, end) into a segment's text."""

    model_config = ConfigDict(frozen=True)

    start: int = Field(..., ge=0, description="Start offset, inclusive, 0-based.")
    end: int = Field(..., gt=0, description="End offset, exclusive; must exceed start.")

    @model_validator(mode="after")
    def _end_after_start(self) -> "CharSpan":
        if self.end <= self.start:
            raise ValueError("char span end must be greater than start")
        return self


class Entity(BaseModel):
    """A single extracted fact anchored to a segment.

    Entities are the atomic evidence units: the rule engine matches on
    (entity_type, normalized_value) pairs — e.g. an APR entity inside a
    HEADLINE segment feeds TILA advertising analysis (rate-statement rules
    under 12 CFR 1026.16/1026.24; whether it or co-occurring terms trigger
    additional disclosures is the rule engine's call). Extraction is
    deterministic; no judgment is encoded here.
    """

    entity_id: str = Field(
        ...,
        min_length=1,
        description="Stable, asset-unique identifier for this entity (e.g. 'ent_012').",
    )
    entity_type: EntityType = Field(
        ...,
        description="Category of fact extracted (APR, fee, superlative, ...).",
    )
    raw_text: str = Field(
        ...,
        min_length=1,
        description="Verbatim matched text, exactly as it appears in the segment.",
    )
    normalized_value: Optional[float] = Field(
        default=None,
        description=(
            "Canonical numeric value for numeric entity types: APR/rate/"
            "percentage as the percentage number (24.99 for '24.99%'), "
            "fee/amount in USD, time_period in days. None for non-numeric "
            "types (superlative, endorsement_marker, optout_marker, "
            "guarantee_term)."
        ),
    )
    segment_id: str = Field(
        ...,
        min_length=1,
        description="Id of the Segment this entity was extracted from.",
    )
    char_span: CharSpan = Field(
        ...,
        description="Character offsets of raw_text within the segment's text.",
    )


class ClaimCandidate(BaseModel):
    """A span of text that *may* constitute a regulated claim.

    'Candidate' is deliberate: the NLP layer flags spans whose surface
    form matches a claim pattern; whether the claim is compliant,
    deceptive, or unsubstantiated is decided downstream. Linked entities
    supply the facts the claim rests on (e.g. a PRICING claim linking to
    an APR entity).
    """

    claim_id: str = Field(
        ...,
        min_length=1,
        description="Stable, asset-unique identifier for this candidate (e.g. 'clm_002').",
    )
    claim_type: ClaimType = Field(
        ...,
        description="Claim category; routes to framework-specific rule sets.",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Verbatim claim span text.",
    )
    segment_id: str = Field(
        ...,
        min_length=1,
        description="Id of the Segment containing the claim span.",
    )
    char_span: CharSpan = Field(
        ...,
        description="Character offsets of the claim span within the segment's text.",
    )
    entity_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Ids of Entity records this claim relies on. Empty when the "
            "claim contains no extracted facts (e.g. a bare superlative "
            "already captured as its own entity elsewhere)."
        ),
    )
    pattern_id: Optional[str] = Field(
        default=None,
        description=(
            "Identifier of the deterministic pattern/rule that flagged this "
            "span, for auditability of the extraction itself."
        ),
    )


class CVFinding(BaseModel):
    """A single visual measurement. Numbers only — never a judgment.

    Examples: contrast ratio of a disclosure segment, rendered text
    height as % of asset height, pixel-normalized distance between a
    triggering claim and its disclosure, presence of a required marker
    (e.g. an '#ad' badge). The rule engine compares these against
    regulatory thresholds; this layer never does.
    """

    finding_id: str = Field(
        ...,
        min_length=1,
        description="Stable, asset-unique identifier for this measurement (e.g. 'cvf_004').",
    )
    measurement: CVMeasurementType = Field(
        ...,
        description="Which visual property was measured.",
    )
    value: float = Field(
        ...,
        description=(
            "The measurement. Units by type — contrast_ratio: WCAG ratio in "
            "[1, 21]; text_height_percent: [0, 100] of asset height; "
            "disclosure_proximity: normalized distance >= 0 between claim "
            "and disclosure boxes; marker_presence: 0.0 (absent) or 1.0 "
            "(present)."
        ),
    )
    segment_id: Optional[str] = Field(
        default=None,
        description=(
            "Segment the measurement applies to, when segment-scoped "
            "(e.g. contrast of a disclosure). None for asset-level "
            "measurements such as marker_presence."
        ),
    )
    related_segment_id: Optional[str] = Field(
        default=None,
        description=(
            "Second segment for relational measurements — for "
            "disclosure_proximity, the disclosure segment measured against "
            "segment_id's claim segment."
        ),
    )
    method: Optional[str] = Field(
        default=None,
        description=(
            "Short identifier of the measurement algorithm (e.g. "
            "'wcag2_relative_luminance'), for reproducibility audits."
        ),
    )

    @model_validator(mode="after")
    def _value_within_measurement_bounds(self) -> "CVFinding":
        v = self.value
        if self.measurement is CVMeasurementType.CONTRAST_RATIO:
            if not (1.0 <= v <= 21.0):
                raise ValueError("contrast_ratio must be within [1.0, 21.0] (WCAG range)")
        elif self.measurement is CVMeasurementType.TEXT_HEIGHT_PERCENT:
            if not (0.0 <= v <= 100.0):
                raise ValueError("text_height_percent must be within [0, 100]")
        elif self.measurement is CVMeasurementType.DISCLOSURE_PROXIMITY:
            if v < 0.0:
                raise ValueError("disclosure_proximity must be >= 0")
        elif self.measurement is CVMeasurementType.MARKER_PRESENCE:
            if v not in (0.0, 1.0):
                raise ValueError("marker_presence must be exactly 0.0 or 1.0")
        return self


class RoutingLabel(BaseModel):
    """Deterministic routing decision: which rule sets should examine this asset.

    Routing is a candidacy signal, not a finding — it says 'these
    frameworks plausibly apply', and the signal string preserves *why*
    for the audit trail (examiners and internal QA must be able to
    reconstruct every routing decision).
    """

    product_type: ProductType = Field(
        ...,
        description="Detected fintech product category; primary routing key.",
    )
    frameworks: list[Framework] = Field(
        ...,
        min_length=1,
        description=(
            "Regulatory frameworks the asset routes to for evaluation. "
            "At least one; FTC applies to nearly all marketing."
        ),
    )
    signal: str = Field(
        ...,
        min_length=1,
        description=(
            "Human-readable audit note explaining the routing, e.g. "
            "'APR entity in headline + credit_card product -> TILA; "
            "superlative claim -> FTC'."
        ),
    )


class SemanticSignal(BaseModel):
    """One semantic hint from an external vision/semantic service.

    Examples: a Google Vision label ('advertisement'), a detected brand
    logo, a web entity, or a safe-search category. Signals support
    framework routing and claim recall; they carry a confidence and a
    source for auditability, and never encode a compliance conclusion.
    """

    signal_type: SemanticSignalType = Field(
        ...,
        description="Kind of signal (label, logo, web_entity, safe_search).",
    )
    value: str = Field(
        ...,
        min_length=1,
        description="The detected label/logo/entity text, verbatim from the service.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Service-reported confidence in [0, 1].",
    )
    source: str = Field(
        ...,
        min_length=1,
        description="Producing service identifier, e.g. 'google_vision'.",
    )


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class Provenance(BaseModel):
    """Versioning stamp making every output reproducible and auditable.

    Compliance reviews must be reconstructable months later: the exact
    CV/NLP code versions and ruleset content that produced a structure
    are part of the evidentiary record.
    """

    model_config = ConfigDict(frozen=True)

    cv_version: str = Field(
        ...,
        min_length=1,
        description="Semantic version of the CV layer that produced cv_findings.",
    )
    nlp_version: str = Field(
        ...,
        min_length=1,
        description="Semantic version of the NLP layer that produced segments/entities/claims.",
    )
    ruleset_hash: str = Field(
        ...,
        min_length=1,
        description=(
            "Content hash (e.g. sha256 hex) of the extraction pattern/"
            "routing ruleset in effect, pinning the exact deterministic "
            "behavior."
        ),
    )
    timestamp: datetime = Field(
        ...,
        description="UTC time the asset was processed (ISO 8601 on the wire).",
    )
    embedding_model_version: Optional[str] = Field(
        default=None,
        description=(
            "Exact name+version of the frozen embedding model that produced "
            "any semantic-similarity-based output (e.g. "
            "'sentence-transformers/all-MiniLM-L6-v2@<revision>'). None when "
            "no embedding model was used."
        ),
    )
    ocr_backend: Optional[str] = Field(
        default=None,
        description=(
            "OCR engine that transcribed the source media ('paddle', "
            "'tesseract', 'google_vision'). Backends have materially "
            "different measured accuracy floors (see cv.ocr.MEASURED_FLOORS), "
            "so OCR-derived numbers are only comparable within one backend. "
            "None for non-image assets."
        ),
    )


# ---------------------------------------------------------------------------
# Top-level output
# ---------------------------------------------------------------------------


class AssetRepresentation(BaseModel):
    """Complete structured representation of one marketing asset.

    This is the single object handed to the rule engine and LLM layer.
    It contains everything they need to judge the asset — text structure,
    extracted facts, claim candidates, visual measurements, and routing —
    and nothing that pre-judges it.

    Referential integrity (every segment_id/entity_id reference resolves)
    is validated at construction.
    """

    asset_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the source marketing asset.",
    )
    segments: list[Segment] = Field(
        ...,
        min_length=1,
        description="All text segments; the addressing base for every other list.",
    )
    entities: list[Entity] = Field(
        default_factory=list,
        description="Extracted facts. Empty if the asset contains none.",
    )
    claim_candidates: list[ClaimCandidate] = Field(
        default_factory=list,
        description="Flagged claim spans. Empty if no claim patterns matched.",
    )
    cv_findings: list[CVFinding] = Field(
        default_factory=list,
        description=(
            "Visual measurements. Empty for non-visual assets (plain text, "
            "email source without rendering)."
        ),
    )
    semantic_signals: list[SemanticSignal] = Field(
        default_factory=list,
        description=(
            "Auxiliary semantic hints from external services (e.g. Google "
            "Vision labels/logos/web entities). Empty when no such service "
            "ran (free tier, non-visual assets)."
        ),
    )
    routing: RoutingLabel = Field(
        ...,
        description="Which frameworks should evaluate this asset, and why.",
    )
    target_jurisdictions: list[str] = Field(
        default_factory=list,
        description=(
            "Where the ad runs: ISO-style state codes ('US-CA', 'US-TX') "
            "or ['US'] for federal-only/nationwide. USER-SUPPLIED at scan "
            "time — targeting cannot be extracted from the creative. "
            "Empty means 'not specified'; state (STATE_UDAP) checks do "
            "not run without it."
        ),
    )
    provenance: Provenance = Field(
        ...,
        description="Version/ruleset/timestamp stamp for reproducibility.",
    )

    @model_validator(mode="after")
    def _referential_integrity(self) -> "AssetRepresentation":
        for code in self.target_jurisdictions:
            if not _JURISDICTION_RE.fullmatch(code):
                raise ValueError(
                    f"invalid jurisdiction code {code!r}; expected 'US' or "
                    f"'US-XX' state codes"
                )
        segment_ids = {s.segment_id for s in self.segments}
        if len(segment_ids) != len(self.segments):
            raise ValueError("duplicate segment_id in segments")

        entity_ids = {e.entity_id for e in self.entities}
        if len(entity_ids) != len(self.entities):
            raise ValueError("duplicate entity_id in entities")

        claim_ids = {c.claim_id for c in self.claim_candidates}
        if len(claim_ids) != len(self.claim_candidates):
            raise ValueError("duplicate claim_id in claim_candidates")

        seg_text = {s.segment_id: s.text for s in self.segments}

        for e in self.entities:
            if e.segment_id not in segment_ids:
                raise ValueError(f"entity {e.entity_id} references unknown segment {e.segment_id}")
            if e.char_span.end > len(seg_text[e.segment_id]):
                raise ValueError(
                    f"entity {e.entity_id} char_span exceeds segment {e.segment_id} text length"
                )

        for c in self.claim_candidates:
            if c.segment_id not in segment_ids:
                raise ValueError(f"claim {c.claim_id} references unknown segment {c.segment_id}")
            if c.char_span.end > len(seg_text[c.segment_id]):
                raise ValueError(
                    f"claim {c.claim_id} char_span exceeds segment {c.segment_id} text length"
                )
            for eid in c.entity_ids:
                if eid not in entity_ids:
                    raise ValueError(f"claim {c.claim_id} references unknown entity {eid}")

        for f in self.cv_findings:
            for sid in (f.segment_id, f.related_segment_id):
                if sid is not None and sid not in segment_ids:
                    raise ValueError(f"cv finding {f.finding_id} references unknown segment {sid}")

        return self
