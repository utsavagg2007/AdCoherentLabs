"""LLM providers behind the review engine.

Two backends:
  AnthropicProvider — Pro/Design/Enterprise tiers. Structured outputs
      (output_config.format json_schema) guarantee the response parses
      against the review schema; streaming keeps 16k-32k max_tokens
      requests clear of HTTP timeouts.
  QwenProvider — Free/Hobby tiers via DashScope's OpenAI-compatible
      endpoint. JSON mode guarantees valid JSON only, so the shape is
      validated here and retried once with the validation errors.

SDKs are imported lazily so the rest of the package (and the test suite)
works without the provider packages installed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from .prompts import SCHEMA_ADDENDUM
from .schema import LLM_OUTPUT_SCHEMA, SchemaError, validate_llm_output
from .tiers import TierConfig

logger = logging.getLogger(__name__)

DASHSCOPE_DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


class ProviderError(RuntimeError):
    """The LLM call failed or its output could not be used."""


@dataclass
class CompletionResult:
    payload: dict[str, Any]   # validated review JSON (findings/reviewed_clear/...)
    model: str                # model id that actually served the request
    input_tokens: int | None = None
    output_tokens: int | None = None


class ReviewProvider(Protocol):
    def complete(self, tier: TierConfig, system: str, user: str) -> CompletionResult: ...


class AnthropicProvider:
    """Claude tiers (pro / design / enterprise)."""

    def __init__(self) -> None:
        import anthropic  # lazy: only needed on Claude tiers

        self._anthropic = anthropic
        self._client = anthropic.Anthropic()

    def complete(self, tier: TierConfig, system: str, user: str) -> CompletionResult:
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": LLM_OUTPUT_SCHEMA},
        }
        if tier.effort:
            output_config["effort"] = tier.effort

        try:
            with self._client.messages.stream(
                model=tier.model,
                max_tokens=tier.max_output_tokens,
                thinking={"type": "adaptive"},
                output_config=output_config,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                message = stream.get_final_message()
        except self._anthropic.APIError as exc:
            raise ProviderError(f"anthropic call failed: {exc}") from exc

        if message.stop_reason == "refusal":
            raise ProviderError("anthropic refused the request (stop_reason=refusal)")
        if message.stop_reason == "max_tokens":
            raise ProviderError(
                f"output truncated at the {tier.name} tier token limit "
                f"({tier.max_output_tokens}); upgrade the tier or reduce the asset size"
            )

        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:  # structured outputs make this unlikely
            raise ProviderError(f"anthropic returned non-JSON output: {exc}") from exc
        validate_llm_output(payload)

        usage = message.usage
        return CompletionResult(
            payload=payload,
            model=message.model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )


class QwenProvider:
    """Qwen tiers (free / hobby) via DashScope's OpenAI-compatible API."""

    def __init__(self) -> None:
        from openai import OpenAI  # lazy: only needed on Qwen tiers

        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise ProviderError("DASHSCOPE_API_KEY is not set (required for Qwen tiers)")
        self._client = OpenAI(
            api_key=api_key,
            base_url=os.environ.get("QWEN_BASE_URL", DASHSCOPE_DEFAULT_BASE_URL),
        )

    def complete(self, tier: TierConfig, system: str, user: str) -> CompletionResult:
        # Qwen does not enforce a schema server-side — embed it in the
        # system prompt and validate locally, with one corrective retry.
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system + SCHEMA_ADDENDUM},
            {"role": "user", "content": user},
        ]
        last_error = "unknown error"
        for attempt in range(2):
            try:
                response = self._client.chat.completions.create(
                    model=tier.model,
                    messages=messages,  # type: ignore[arg-type]
                    max_tokens=tier.max_output_tokens,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
            except Exception as exc:  # openai exception hierarchy
                raise ProviderError(f"qwen call failed: {exc}") from exc

            choice = response.choices[0]
            if choice.finish_reason == "length":
                raise ProviderError(
                    f"output truncated at the {tier.name} tier token limit "
                    f"({tier.max_output_tokens}); upgrade the tier or reduce the asset size"
                )
            text = choice.message.content or ""
            try:
                payload = json.loads(text)
                validate_llm_output(payload)
            except (json.JSONDecodeError, SchemaError) as exc:
                last_error = str(exc)
                logger.warning("qwen output invalid (attempt %d): %s", attempt + 1, exc)
                messages.append({"role": "assistant", "content": text})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your previous JSON was invalid: "
                        f"{last_error}. Return the corrected JSON object only."
                    ),
                })
                continue

            usage = response.usage
            return CompletionResult(
                payload=payload,
                model=response.model or tier.model,
                input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            )
        raise ProviderError(f"qwen output failed validation after retry: {last_error}")


def get_provider(tier: TierConfig) -> ReviewProvider:
    if tier.provider == "anthropic":
        return AnthropicProvider()
    if tier.provider == "qwen":
        return QwenProvider()
    raise ProviderError(f"unknown provider {tier.provider!r} for tier {tier.name!r}")
