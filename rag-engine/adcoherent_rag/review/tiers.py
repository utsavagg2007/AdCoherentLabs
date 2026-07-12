"""SaaS tier -> LLM routing and per-tier spend limits.

Five tiers. Paid starts at "hobby". Each tier pins a model and hard
budgets so a single review can never burn more credits than its tier's
pricing supports:

  max_output_tokens        enforced ceiling passed to the provider
  chunks_per_query         retrieval k per (framework, query) pair
  max_chunks_per_framework cap on regulation excerpts sent per framework
  max_context_chars        cap on the total regulation-excerpt text

Model pricing anchors (per MTok in/out): qwen-turbo ~$0.05/$0.20,
qwen-max ~$1.6/$6.4 (OpenRouter passes provider pricing through),
claude-sonnet-5 $3/$15, claude-opus-4-8 $5/$25. Budgets scale roughly
inversely with output price.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TierConfig:
    name: str
    paid: bool
    provider: str                 # "openrouter" | "anthropic"
    model: str
    max_output_tokens: int
    effort: str | None            # anthropic output_config.effort; None for openrouter
    chunks_per_query: int
    max_chunks_per_framework: int
    max_context_chars: int


# Free/hobby models are served via OpenRouter (OpenRouter-namespaced ids,
# env-overridable — catalog/pricing shifts are config, not code); the
# Claude models are fixed per the product spec.
_OPENROUTER_FREE_MODEL = os.environ.get("OPENROUTER_FREE_MODEL", "qwen/qwen-turbo")
_OPENROUTER_HOBBY_MODEL = os.environ.get("OPENROUTER_HOBBY_MODEL", "qwen/qwen-max")

TIERS: dict[str, TierConfig] = {
    "free": TierConfig(
        name="free", paid=False, provider="openrouter", model=_OPENROUTER_FREE_MODEL,
        max_output_tokens=1_500, effort=None,
        chunks_per_query=3, max_chunks_per_framework=6, max_context_chars=24_000,
    ),
    "hobby": TierConfig(
        name="hobby", paid=True, provider="openrouter", model=_OPENROUTER_HOBBY_MODEL,
        max_output_tokens=3_000, effort=None,
        chunks_per_query=4, max_chunks_per_framework=8, max_context_chars=40_000,
    ),
    "pro": TierConfig(
        name="pro", paid=True, provider="anthropic", model="claude-sonnet-5",
        max_output_tokens=8_000, effort="medium",
        chunks_per_query=5, max_chunks_per_framework=10, max_context_chars=60_000,
    ),
    "design": TierConfig(
        name="design", paid=True, provider="anthropic", model="claude-opus-4-8",
        max_output_tokens=16_000, effort="high",
        chunks_per_query=6, max_chunks_per_framework=12, max_context_chars=90_000,
    ),
    "enterprise": TierConfig(
        name="enterprise", paid=True, provider="anthropic", model="claude-opus-4-8",
        max_output_tokens=32_000, effort="high",
        chunks_per_query=8, max_chunks_per_framework=16, max_context_chars=140_000,
    ),
}


def get_tier(name: str) -> TierConfig:
    try:
        return TIERS[name.strip().lower()]
    except KeyError:
        raise ValueError(
            f"unknown tier {name!r}; expected one of {sorted(TIERS)}"
        ) from None
