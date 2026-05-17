"""Vendor-neutral inference data shapes.

Every type here exists so that downstream code (gateway, services,
future orchestration runtimes) can be written once and execute against
any provider. Vendor-specific fields belong in `InferenceResponse.raw`
where they remain accessible for debugging without leaking into the
domain.

`InferenceRequest` and `InferenceResponse` are deliberately frozen
dataclasses — immutability matters because requests fan out to retries,
audits, and traces, and accidental in-flight mutation is the kind of
bug that's near-impossible to diagnose after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class Message:
    """One vendor-neutral chat message."""
    role: Role
    content: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Vendor-neutral token-accounting bucket."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    """Vendor-neutral inference request.

    `metadata` is opaque, propagated into traces; it is NOT sent to the
    provider. `timeout_s` overrides the gateway's per-attempt timeout
    for this single request only.
    """

    messages: tuple[Message, ...]
    model: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    timeout_s: float | None = None


@dataclass(frozen=True, slots=True)
class InferenceResponse:
    """Vendor-neutral inference response.

    `model` is the model the provider actually used (may differ from
    the requested model — providers sometimes alias). `raw` is the
    vendor-native payload, preserved for debugging but never relied on
    by downstream code.
    """

    content: str
    model: str
    finish_reason: str | None
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: Mapping[str, Any] | None = None


class ProviderCapability(str, Enum):
    """Coarse-grained capability flags advertised by each provider."""
    CHAT = "chat"
    EMBEDDINGS = "embeddings"
    STREAMING = "streaming"
    TOOLS = "tools"
    VISION = "vision"


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Identity + capability descriptor for a provider."""
    name: str
    capabilities: frozenset[ProviderCapability]
    default_model: str | None = None


__all__ = [
    "Role",
    "Message",
    "TokenUsage",
    "InferenceRequest",
    "InferenceResponse",
    "ProviderCapability",
    "ProviderInfo",
]
