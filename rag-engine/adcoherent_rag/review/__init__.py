"""LLM compliance-review layer.

Takes the NLP layer's asset analysis (nlp-result-template.json shape),
retrieves the regulation chunks for the frameworks the NLP router named,
and asks the tier-appropriate LLM to produce a structured compliance
review (sample_output-LLMresponse.json shape).
"""

from .engine import ReviewError, review_asset  # noqa: F401
from .tiers import TIERS, TierConfig, get_tier  # noqa: F401
