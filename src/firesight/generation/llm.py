"""
Provider-swappable LLM client.

The spec requires the model be changeable in one config line, so the provider
and model id both come from env and nothing downstream imports a vendor SDK.
Token counts and cost come back with every reply because the eval harness has
to report cost per query.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from firesight.config import settings


class LLMError(Exception):
    """The model call failed, or no credentials are configured."""


# Anything matching these is scrubbed out of error text before it can reach an
# eval report, a log line, or a traceback. Provider SDK exceptions do not
# normally echo request headers, but "normally" is not a guarantee worth
# betting a live credential on, and these strings flow into committed JSON
# reports via `failure_reason`.
_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)(authorization|x-api-key)\s*[:=]\s*\S+"),
)


def redact(text: str) -> str:
    """Replace any credential-shaped substring with a marker."""
    out = str(text)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("<redacted>", out)
    return out


# USD per million tokens (input, output). Used only for reporting; update when
# pricing changes. An unknown model reports 0.0 rather than a guessed cost.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (15.00, 75.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-5-5": (3.00, 15.00),
    "claude-haiku-5-5": (1.00, 5.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


@dataclass(frozen=True)
class Reply:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str


def _cost(model: str, tin: int, tout: int) -> float:
    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    return (tin * rates[0] + tout * rates[1]) / 1_000_000


def available() -> bool:
    """True when the configured provider has credentials."""
    if settings.llm_provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if settings.llm_provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    return False


def complete(
    prompt: str, *, max_tokens: int = 1500, temperature: float | None = None
) -> Reply:
    """
    Single-turn completion.

    `temperature` is omitted from the request unless explicitly given: it is
    deprecated on the Claude 5 family and sending it returns HTTP 400. The
    practical consequence is that generation is NOT strictly deterministic, so
    re-running an eval suite can shift a borderline question. Reported numbers
    are one run, not a fixed point.
    """
    provider = settings.llm_provider
    model = settings.llm_model

    if provider == "anthropic":
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise LLMError("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("anthropic SDK not installed: `uv sync --extra llm`") from e
        try:
            client = anthropic.Anthropic()
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            msg = client.messages.create(**kwargs)
        except Exception as e:  # noqa: BLE001 - wrapped for the caller
            raise LLMError(redact(str(e))) from None
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        tin, tout = msg.usage.input_tokens, msg.usage.output_tokens
        return Reply(text, tin, tout, _cost(model, tin, tout), model)

    if provider == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            raise LLMError("OPENAI_API_KEY is not set")
        try:
            import openai
        except ImportError as e:
            raise LLMError("openai SDK not installed: `uv sync --extra llm`") from e
        try:
            client = openai.OpenAI()
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001 - wrapped for the caller
            raise LLMError(redact(str(e))) from None
        text = resp.choices[0].message.content or ""
        tin = resp.usage.prompt_tokens if resp.usage else 0
        tout = resp.usage.completion_tokens if resp.usage else 0
        return Reply(text, tin, tout, _cost(model, tin, tout), model)

    raise LLMError(f"unknown provider {provider!r}; expected 'anthropic' or 'openai'")
