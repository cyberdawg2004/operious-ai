"""Provider-neutral LLM clients for diagnostic cognition."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, cast, runtime_checkable

import httpx

from app.cognition.exceptions import (
    CognitionLLMConfigurationError,
    CognitionLLMProviderError,
    ProviderRateLimitError,
    ProviderTransientError,
)
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.core.http import get_shared_http_client
from app.runtime.provider_circuit_breaker import ProviderCircuitBreaker

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
class DiagnosticTextBlock:
    text: str


@dataclass(frozen=True, slots=True)
class DiagnosticImageBlock:
    """A B1a-stored, B1a-validated image attached to a diagnostic call.

    ``attachment_id``/``sha256_digest`` are carried alongside the bytes so
    the audit snapshot can reference this block without ever persisting
    ``base64_data`` — see ``_snapshot_content`` in diagnostic_runtime.py.
    """

    media_type: str  # "image/jpeg" | "image/png"
    base64_data: str
    attachment_id: str
    sha256_digest: str


@dataclass(frozen=True, slots=True)
class DiagnosticDocumentBlock:
    """A B1a-stored PDF attached to a diagnostic call (Claude reads the
    rendered pages natively — this is the OCR path, no rasterizer needed)."""

    media_type: str  # "application/pdf"
    base64_data: str
    attachment_id: str
    sha256_digest: str


DiagnosticContentBlock = DiagnosticTextBlock | DiagnosticImageBlock | DiagnosticDocumentBlock


@dataclass(frozen=True, slots=True)
class DiagnosticLLMMessage:
    role: str
    # str is the original, still-dominant shape — every existing call site
    # that passes a plain string is unaffected by this union. A tuple of
    # content blocks is the new vision path (see DiagnosticCognitionRuntime
    # ._load_attachment_blocks).
    content: "str | tuple[DiagnosticContentBlock, ...]"


def message_text(content: "str | tuple[DiagnosticContentBlock, ...]") -> str:
    """Return the text-only portion of a message's content.

    For the str form this is a no-op (the common case). For the block-tuple
    form, image/document blocks are dropped — callers that need the
    rendered content's text (the deterministic test client, token
    estimation) never need bytes.
    """
    if isinstance(content, str):
        return content
    return "\n".join(
        block.text for block in content if isinstance(block, DiagnosticTextBlock)
    )


def to_anthropic_content(
    content: "str | tuple[DiagnosticContentBlock, ...]",
) -> "str | list[dict[str, Any]]":
    """Render a message's content into the shape the Anthropic Messages API
    expects. Anthropic accepts a bare string OR a content-block array per
    message — this maps directly onto that, it isn't a workaround."""
    if isinstance(content, str):
        return content
    blocks: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, DiagnosticTextBlock):
            blocks.append({"type": "text", "text": block.text})
        elif isinstance(block, DiagnosticImageBlock):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": block.media_type,
                        "data": block.base64_data,
                    },
                }
            )
        else:
            blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": block.media_type,
                        "data": block.base64_data,
                    },
                }
            )
    return blocks


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
        tenant_id: str | None = None,
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
        http_client: httpx.AsyncClient | None = None,
        provider_circuit_breaker: ProviderCircuitBreaker | None = None,
        default_tenant_id: str = "platform",
    ) -> None:
        if not api_key.strip():
            raise CognitionLLMConfigurationError("ANTHROPIC_API_KEY is not configured")
        if not model.strip():
            raise CognitionLLMConfigurationError("Anthropic model must be non-empty")
        if not default_tenant_id.strip():
            raise CognitionLLMConfigurationError("default_tenant_id must be non-empty")
        # Stripped defensively: api_key/anthropic_version are sent verbatim as
        # HTTP header VALUES (x-api-key, anthropic-version below) — a stray
        # trailing newline or whitespace (a common artifact of how secrets get
        # pasted into env vars / CI secret stores) is invisible in the
        # emptiness check above but raises h11.LocalProtocolError ("illegal
        # header value") the moment a real request is sent.
        self._api_key = api_key.strip()
        self.model_name = model.strip()
        self._base_url = base_url.rstrip("/")
        self._anthropic_version = anthropic_version.strip()
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._provider_circuit_breaker = provider_circuit_breaker
        self._default_tenant_id = default_tenant_id

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        effective_tenant_id = tenant_id or self._default_tenant_id
        payload = {
            "model": self.model_name,
            "max_tokens": max_output_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {
                    "role": message.role,
                    "content": to_anthropic_content(message.content),
                }
                for message in messages
            ],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self._anthropic_version,
            "content-type": "application/json",
        }
        breaker = self._provider_circuit_breaker
        try:
            if breaker is not None:
                await breaker.before_request(
                    tenant_id=effective_tenant_id,
                    provider_name=self.provider_name,
                )
            client = self._http_client or get_shared_http_client()
            response = await client.post(
                f"{self._base_url}/v1/messages",
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            if breaker is not None:
                await breaker.record_success(
                    tenant_id=effective_tenant_id,
                    provider_name=self.provider_name,
                )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if breaker is not None:
                await breaker.record_http_status(
                    tenant_id=effective_tenant_id,
                    provider_name=self.provider_name,
                    status_code=status_code,
                    retry_after=exc.response.headers.get("retry-after"),
                )
            if status_code == 429:
                retry_after = _retry_after_seconds(
                    exc.response.headers.get("retry-after")
                )
                raise ProviderRateLimitError(
                    "Anthropic diagnostic request failed: HTTPStatusError:429",
                    retry_after_seconds=retry_after,
                ) from exc
            if status_code in {500, 503, 504, 408}:
                raise ProviderTransientError(
                    "Anthropic diagnostic request failed: "
                    f"HTTPStatusError:{status_code}"
                ) from exc
            raise CognitionLLMProviderError(
                "Anthropic diagnostic request failed: "
                f"HTTPStatusError:{status_code}"
            ) from exc
        except httpx.TimeoutException as exc:
            if breaker is not None:
                await breaker.record_transient_failure(
                    tenant_id=effective_tenant_id,
                    provider_name=self.provider_name,
                    reason="timeout",
                )
            raise ProviderTransientError(
                "Anthropic diagnostic request failed: TimeoutException"
            ) from exc
        except httpx.HTTPError as exc:
            if breaker is not None:
                await breaker.record_transient_failure(
                    tenant_id=effective_tenant_id,
                    provider_name=self.provider_name,
                    reason=exc.__class__.__name__,
                )
            raise CognitionLLMProviderError(
                f"Anthropic diagnostic request failed: {exc.__class__.__name__}"
            ) from exc
        data = cast(dict[str, Any], response.json())
        stop_reason = data.get("stop_reason")
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=_extract_text(data),
            usage=_extract_usage(data),
            stop_reason=stop_reason if isinstance(stop_reason, str) else None,
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
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del max_output_tokens, temperature, tenant_id
        content = "\n".join(message_text(message.content) for message in messages)
        if "generate governed customer-facing support replies" in system_prompt.casefold():
            return _deterministic_grounded_reply_completion(content)
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


def _deterministic_grounded_reply_completion(
    content: str,
) -> DiagnosticLLMCompletion:
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError:
        decoded = {}
    payload: Mapping[str, Any] = (
        cast(Mapping[str, Any], decoded) if isinstance(decoded, Mapping) else {}
    )
    evidence_value = payload.get("retrieved_evidence")
    evidence = cast(list[object], evidence_value) if isinstance(
        evidence_value, list
    ) else []
    first = evidence[0] if evidence else None
    if isinstance(first, Mapping):
        first_map = cast(Mapping[str, Any], first)
        rank = first_map.get("rank")
        excerpt_value = first_map.get("safe_excerpt") or first_map.get("title")
        excerpt = excerpt_value if isinstance(excerpt_value, str) else None
    else:
        rank = None
        excerpt = None
    if isinstance(rank, int) and rank > 0:
        text = json.dumps(
            {
                "language": "en",
                "segments": [
                    {
                        "kind": "claim",
                        "text": (
                            "I found approved support guidance relevant to "
                            f"this issue: {excerpt or 'support guidance'}."
                        ),
                        "citation_ranks": [rank],
                    },
                    {
                        "kind": "question",
                        "text": (
                            "Please share your order number or product model "
                            "so we can confirm the next support step."
                        ),
                        "citation_ranks": [],
                    },
                ],
            },
            sort_keys=True,
        )
    else:
        text = json.dumps(
            {
                "language": "en",
                "segments": [
                    {
                        "kind": "claim",
                        "text": (
                            "I could not find approved support knowledge that "
                            "grounds an automatic reply for this issue."
                        ),
                        "citation_ranks": [],
                    }
                ],
            },
            sort_keys=True,
        )
    prompt_tokens = _estimate_tokens(content)
    completion_tokens = _estimate_tokens(text)
    return DiagnosticLLMCompletion(
        provider=DeterministicDiagnosticLLMClient.provider_name,
        model=DeterministicDiagnosticLLMClient.model_name,
        text=text,
        usage=DiagnosticLLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        raw_metadata={"deterministic": True, "mode": "grounded_reply"},
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
    if any(token in content for token in ("defect", "loose", "flicker", "serial")):
        return "product_defect"
    if any(token in content for token in ("account", "login", "billing", "invoice")):
        return "account_issue"
    return "unknown_issue"


def _deterministic_confidence(category: str) -> float:
    return {
        "charging_issue": 0.88,
        "connectivity_issue": 0.84,
        "product_defect": 0.83,
        "account_issue": 0.82,
    }.get(category, 0.42)


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _retry_after_seconds(retry_after: str | None) -> int:
    if retry_after is None or not retry_after.strip():
        return 60
    stripped = retry_after.strip()
    try:
        return max(0, int(stripped))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(stripped)
        except (TypeError, ValueError):
            return 60
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((parsed - datetime.now(timezone.utc)).total_seconds()))


__all__ = [
    "AnthropicMessagesClient",
    "DeterministicDiagnosticLLMClient",
    "DiagnosticContentBlock",
    "DiagnosticDocumentBlock",
    "DiagnosticImageBlock",
    "DiagnosticLLMClient",
    "DiagnosticLLMMessage",
    "DiagnosticTextBlock",
    "message_text",
    "to_anthropic_content",
]
