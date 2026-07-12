"""AdCoherent Labs — the connected four-layer compliance engine.

Public API:

    from engine import run_compliance_engine, resume_with_human_guidance

    result = run_compliance_engine(text="Get 5.99% APR!", product_tier="pro")
    result.status            # "passed" | "human_review" | "llm_error"
    result.llm_review        # final review (sample_output-LLMresponse.json shape)
    result.verification      # rule-engine verdict on the review
    result.rounds            # complete audit trail

CLI:  python -m engine.cli check --text "..." --tier pro
See ENGINE.md at the project root for the full story.
"""

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

from .orchestrator import (
    DEFAULT_MAX_LLM_ROUNDS,
    prepare_asset,
    resume_with_human_guidance,
    review_and_verify,
    run_compliance_engine,
)
from .report import EngineRunResult
from .tiers import OCR_TIER_BY_PRODUCT_TIER, PRODUCT_TIERS, TIERS, ocr_tier_for

__all__ = [
    "DEFAULT_MAX_LLM_ROUNDS",
    "EngineRunResult",
    "OCR_TIER_BY_PRODUCT_TIER",
    "PRODUCT_TIERS",
    "TIERS",
    "ocr_tier_for",
    "prepare_asset",
    "resume_with_human_guidance",
    "review_and_verify",
    "run_compliance_engine",
]
