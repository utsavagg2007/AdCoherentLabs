"""Request/response models (pydantic v2, strict — unknown fields rejected).

The engine's own documents (EngineRunResult, review docs) are persisted as
JSON and returned verbatim; these models cover the backend's request surface.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# -- submissions ---------------------------------------------------------------

class InlineSubmission(StrictModel):
    kind: Literal["text", "html"]
    content: str = Field(min_length=1, max_length=2_000_000)
    title: str | None = Field(default=None, max_length=300)
    target_jurisdictions: list[str] = Field(default_factory=list, max_length=60)
    #: What the advertiser says backs the claims in this creative. Collected
    #: conversationally before the run and handed to Layer 3 as authoritative
    #: operator direction (engine.orchestrator.review_and_verify's
    #: `human_guidance`), the same channel a reviewer's resume guidance uses.
    #: Optional: without it the engine reasons from the creative alone, which
    #: is what every run did before this field existed.
    substantiation: str | None = Field(default=None, max_length=20_000)


class SubmissionAccepted(StrictModel):
    submission_id: str
    run_id: str
    credits_charged: int
    balance: dict


# -- runs -----------------------------------------------------------------------

class ResumeRequest(StrictModel):
    guidance: str = Field(min_length=1, max_length=20_000)


# -- findings ---------------------------------------------------------------------

class FindingPatch(StrictModel):
    status: Literal["approved", "flagged", "dismissed"]


# -- orgs / members ----------------------------------------------------------------

class OrgCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)


class MemberAdd(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["admin", "reviewer", "viewer"]


class MemberPatch(StrictModel):
    user_id: str
    role: Literal["admin", "reviewer", "viewer"]


# -- api keys -------------------------------------------------------------------------

class ApiKeyCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[Literal["submit", "read", "admin"]] = Field(
        default_factory=lambda: ["submit", "read"])
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=100_000)


# -- billing ------------------------------------------------------------------------------

class SubscriptionCheckout(StrictModel):
    tier: Literal["hobby", "pro", "design", "enterprise"]
    interval: Literal["monthly", "annual"] = "monthly"


class PackCheckout(StrictModel):
    pack: Literal["starter", "growth", "scale"]


# -- admin -----------------------------------------------------------------------------------

class AdminCreditAdjust(StrictModel):
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    bucket: Literal["subscription", "purchased"]
    note: str = Field(min_length=3, max_length=500)

    @field_validator("delta")
    @classmethod
    def _nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("delta must be non-zero")
        return v
