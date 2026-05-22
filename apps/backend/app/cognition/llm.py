"""Provider-neutral LLM clients for diagnostic cognition."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

import httpx

from app.cognition.exceptions import (
    CognitionLLMConfigurationError,
    CognitionLLMProviderError,
)
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage

_GOVERNANCE_TERMS = (
    "approve",
    "approved",
    "chargeback",
    "compliance",
    "credit",
    "deny",
    "denied",
    "escalate",
    "fraud",
    "legal",
    "refund",
    "reject",
    "rejected",
    "replacement",
    "rma",
)


@dataclass(frozen=True, slots=True)
class DiagnosticLLMMessage:
    role: str
    content: str


@runtime_checkable
class DiagnosticLLMClient(Protocol):
    provider_name: str
    model_name: str

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
    ) -> DiagnosticLLMCompletion: ...


class AnthropicMessagesClient:
    """Small Anthropic Messages API adapter using HTTP, not vendor SDKs."""

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        anthropic_version: str = "2023-06-01",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key.strip():
            raise CognitionLLMConfigurationError("ANTHROPIC_API_KEY is not configured")
        if not model.strip():
            raise CognitionLLMConfigurationError("Anthropic model must be non-empty")
        self._api_key = api_key
        self.model_name = model
        self._base_url = base_url.rstrip("/")
        self._anthropic_version = anthropic_version
        self._timeout_seconds = timeout_seconds

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
    ) -> DiagnosticLLMCompletion:
        payload = {
            "model": self.model_name,
            "max_tokens": max_output_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self._anthropic_version,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/v1/messages",
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CognitionLLMProviderError(
                f"Anthropic diagnostic request failed: {exc.__class__.__name__}"
            ) from exc
        data = cast(dict[str, Any], response.json())
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=_extract_text(data),
            usage=_extract_usage(data),
            raw_metadata=_bounded_metadata(data),
        )


class DeterministicDiagnosticLLMClient:
    """Deterministic local LLM stand-in for tests and offline workers."""

    provider_name = "operious-deterministic-llm"
    model_name = "operious-diagnostic-local-v1"

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, max_output_tokens, temperature
        content = "\n".join(message.content for message in messages)
        lowered = content.casefold()
        category = _deterministic_category(lowered)
        governance_terms = tuple(term for term in _GOVERNANCE_TERMS if term in lowered)
        term_suffix = (
            f" Governance terms preserved: {', '.join(governance_terms)}."
            if governance_terms
            else ""
        )
        text = json.dumps(
            {
                "summary": (
                    f"Grounded diagnostic classification: {category}."
                    f"{term_suffix}"
                ),
                "category": category,
                "confidence": _deterministic_confidence(category),
            },
            sort_keys=True,
        )
        prompt_tokens = _estimate_tokens(content)
        completion_tokens = _estimate_tokens(text)
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=text,
            usage=DiagnosticLLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            raw_metadata={"deterministic": True},
        )


def _extract_text(data: Mapping[str, Any]) -> str:
    blocks_value = data.get("content")
    if not isinstance(blocks_value, list):
        raise CognitionLLMProviderError("Anthropic response missing content blocks")
    blocks = cast(list[object], blocks_value)
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        block_map = cast(Mapping[str, Any], block)
        text_value = block_map.get("text")
        if block_map.get("type") == "text" and isinstance(text_value, str):
            parts.append(text_value)
    text = "\n".join(part.strip() for part in parts if part.strip())
    if not text:
        raise CognitionLLMProviderError("Anthropic response contained no text")
    return text


def _extract_usage(data: Mapping[str, Any]) -> DiagnosticLLMUsage:
    usage = data.get("usage")
    input_tokens = 0
    output_tokens = 0
    if isinstance(usage, Mapping):
        usage_map = cast(Mapping[str, Any], usage)
        input_value = usage_map.get("input_tokens")
        output_value = usage_map.get("output_tokens")
        input_tokens = input_value if isinstance(input_value, int) else 0
        output_tokens = output_value if isinstance(output_value, int) else 0
    return DiagnosticLLMUsage(
        prompt_tokens=max(0, input_tokens),
        completion_tokens=max(0, output_tokens),
        total_tokens=max(0, input_tokens) + max(0, output_tokens),
    )


def _bounded_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("id", "model", "role", "stop_reason", "stop_sequence", "type"):
        value = data.get(key)
        if isinstance(value, str) or value is None:
            metadata[key] = value
    return metadata


def _deterministic_category(content: str) -> str:
    if any(token in content for token in ("charge", "charging", "battery", "cable")):
        return "charging_issue"
    if any(token in content for token in ("connect", "bluetooth", "wifi", "pair")):
        return "connectivity_issue"
    if any(token in content for token in ("account", "login", "billing", "invoice")):
        return "account_issue"
    return "unknown_issue"


def _deterministic_confidence(category: str) -> float:
    return {
        "charging_issue": 0.88,
        "connectivity_issue": 0.84,
        "account_issue": 0.82,
    }.get(category, 0.42)


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


__all__ = [
    "AnthropicMessagesClient",
    "DeterministicDiagnosticLLMClient",
    "DiagnosticLLMClient",
    "DiagnosticLLMMessage",
]
