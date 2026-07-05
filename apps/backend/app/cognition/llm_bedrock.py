"""AWS Bedrock transport for the DiagnosticLLMClient protocol.

Uses boto3 bedrock-runtime.converse() — NO anthropic SDK import, preserving
the Phase 5-C constitutional constraint that vendor SDKs stay out of the
cognition package. boto3 is an allowed dependency (already in requirements.txt).

Authentication via the standard AWS credential chain:
  1. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN (env vars)
  2. ~/.aws/credentials (shared credentials file)
  3. IAM instance role / ECS task role

Model IDs must be cross-region inference-profile IDs (region-prefixed), e.g.:
  us.anthropic.claude-haiku-4-5-20251001
  us.anthropic.claude-sonnet-4-6
These differ from bare model IDs used by the direct Anthropic API.

The Bedrock converse() API accepts the same role/content message shape as
the Anthropic Messages API, with minor field name differences handled here.
Prompts, governance, and agent logic are identical on both paths.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

from app.cognition.exceptions import (
    CognitionLLMConfigurationError,
    CognitionLLMProviderError,
    ProviderRateLimitError,
    ProviderTransientError,
)
from app.cognition.llm import DiagnosticLLMMessage, to_anthropic_content
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage

logger = logging.getLogger(__name__)


class BedrockAnthropicMessagesClient:
    """boto3 bedrock-runtime-backed implementation of DiagnosticLLMClient.

    Satisfies the same protocol as AnthropicMessagesClient. Drop-in swap:
    callers that accept DiagnosticLLMClient receive this transparently.
    """

    provider_name = "bedrock"

    def __init__(
        self,
        *,
        model: str,
        aws_region: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not model.strip():
            raise CognitionLLMConfigurationError(
                "Bedrock model (inference profile ID) must be non-empty"
            )
        if not aws_region.strip():
            raise CognitionLLMConfigurationError("LLM_AWS_REGION must be non-empty")
        self.model_name = model.strip()
        self._aws_region = aws_region.strip()
        self._timeout_seconds = timeout_seconds
        # boto3 resolves credentials via the standard chain at client creation.
        # Lazy import so this module stays importable without boto3 installed
        # (test environments with DeterministicDiagnosticLLMClient won't hit
        # this path), but boto3 is pinned in requirements.txt for production.
        import boto3

        self._bedrock: Any = cast("Any", boto3).client(
            "bedrock-runtime",
            region_name=self._aws_region,
        )

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del tenant_id  # not used for transport; preserved for protocol compat

        converse_messages = _build_converse_messages(messages)

        try:
            response: dict[str, Any] = cast("dict[str, Any]", self._bedrock.converse(
                modelId=self.model_name,
                messages=converse_messages,
                system=[{"text": system_prompt}],
                inferenceConfig={
                    "maxTokens": max_output_tokens,
                    "temperature": temperature,
                },
            ))
        except Exception as exc:
            error_code = _bedrock_error_code(exc)
            if error_code == "ThrottlingException":
                raise ProviderRateLimitError(
                    f"Bedrock rate limit: {exc}",
                    retry_after_seconds=60,
                ) from exc
            if error_code in {
                "ServiceUnavailableException",
                "InternalServerException",
                "ModelErrorException",
            }:
                raise ProviderTransientError(
                    f"Bedrock transient error ({error_code}): {exc}"
                ) from exc
            if error_code == "RequestTimeoutException":
                raise ProviderTransientError(
                    "Bedrock request timed out"
                ) from exc
            raise CognitionLLMProviderError(
                f"Bedrock API error ({error_code or type(exc).__name__}): {exc}"
            ) from exc

        return _parse_converse_response(response, self.model_name, self.provider_name)


def _build_converse_messages(
    messages: Sequence[DiagnosticLLMMessage],
) -> list[dict[str, Any]]:
    """Convert DiagnosticLLMMessages to Bedrock converse() message shape.

    Bedrock converse() uses the same role/content shape as Anthropic, with
    content blocks as a list of {"text": "..."} dicts for text messages.
    Image and document blocks are translated to their Bedrock equivalents.
    """
    result: list[dict[str, Any]] = []
    for message in messages:
        content = message.content
        if isinstance(content, str):
            blocks: list[dict[str, Any]] = [{"text": content}]
        else:
            # Convert DiagnosticContentBlock tuple to Bedrock content blocks.
            # to_anthropic_content() already produces the right shape for text;
            # for images/docs we adapt to the Bedrock converse block format.
            anthropic_content = to_anthropic_content(content)
            if isinstance(anthropic_content, str):
                blocks = [{"text": anthropic_content}]
            else:
                blocks = _adapt_anthropic_blocks_to_bedrock(anthropic_content)
        result.append({"role": message.role, "content": blocks})
    return result


def _adapt_anthropic_blocks_to_bedrock(
    anthropic_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate Anthropic content blocks to Bedrock converse format."""
    bedrock_blocks: list[dict[str, Any]] = []
    for block in anthropic_blocks:
        btype = block.get("type")
        if btype == "text":
            bedrock_blocks.append({"text": block.get("text", "")})
        elif btype == "image":
            source = block.get("source", {})
            bedrock_blocks.append({
                "image": {
                    "format": _image_media_type_to_format(
                        source.get("media_type", "image/jpeg")
                    ),
                    "source": {
                        "bytes": source.get("data", ""),
                    },
                }
            })
        elif btype == "document":
            source = block.get("source", {})
            bedrock_blocks.append({
                "document": {
                    "format": "pdf",
                    "name": "attachment",
                    "source": {
                        "bytes": source.get("data", ""),
                    },
                }
            })
    return bedrock_blocks


def _image_media_type_to_format(media_type: str) -> str:
    return {
        "image/jpeg": "jpeg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
    }.get(media_type, "jpeg")


def _parse_converse_response(
    response: dict[str, Any],
    model_name: str,
    provider_name: str,
) -> DiagnosticLLMCompletion:
    output = response.get("output", {})
    message = output.get("message", {})
    content_blocks = message.get("content", [])

    parts = [
        block["text"]
        for block in content_blocks
        if "text" in block and isinstance(block["text"], str)
    ]
    text = "\n".join(part.strip() for part in parts if part.strip())
    if not text:
        raise CognitionLLMProviderError("Bedrock response contained no text")

    usage = response.get("usage", {})
    input_tokens = usage.get("inputTokens", 0) or 0
    output_tokens = usage.get("outputTokens", 0) or 0

    stop_reason_raw = response.get("stopReason")
    stop_reason = str(stop_reason_raw) if stop_reason_raw else None

    return DiagnosticLLMCompletion(
        provider=provider_name,
        model=model_name,
        text=text,
        usage=DiagnosticLLMUsage(
            prompt_tokens=max(0, input_tokens),
            completion_tokens=max(0, output_tokens),
            total_tokens=max(0, input_tokens + output_tokens),
        ),
        stop_reason=stop_reason,
        raw_metadata={
            "model": model_name,
            "stop_reason": stop_reason,
        },
    )


def _bedrock_error_code(exc: BaseException) -> str | None:
    """Extract the Bedrock error code from a botocore ClientError."""
    try:
        response = getattr(exc, "response", None)
        if response is not None:
            error = response.get("Error", {})
            code = error.get("Code")
            return str(code) if code else None
    except Exception:  # noqa: BLE001
        pass
    return None


__all__ = ["BedrockAnthropicMessagesClient"]
