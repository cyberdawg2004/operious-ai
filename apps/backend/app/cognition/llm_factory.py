"""Factory for the platform's LLM client.

Single construction point for all call sites. Controlled by LLM_PROVIDER:

  LLM_PROVIDER=anthropic (default)
    Requires: ANTHROPIC_API_KEY
    Model: ANTHROPIC_DEFAULT_MODEL (bare model ID, e.g. "claude-sonnet-4-6")

  LLM_PROVIDER=bedrock
    Requires: AWS credentials in the standard chain
              (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + AWS_SESSION_TOKEN,
               or ~/.aws/credentials, or IAM instance role)
    Region:   LLM_AWS_REGION (default: us-east-1)
    Model:    BEDROCK_DEFAULT_MODEL (inference-profile ID, e.g.
              "us.anthropic.claude-haiku-4-5-20251001")

Tests / offline workers: in non-production only, when no key/bedrock region is
configured, the DeterministicDiagnosticLLMClient is returned automatically. A
production configuration must never silently use deterministic output.
"""

from __future__ import annotations

import logging

from app.cognition.exceptions import CognitionLLMConfigurationError
from app.cognition.llm import (
    AnthropicMessagesClient,
    DeterministicDiagnosticLLMClient,
    DiagnosticLLMClient,
)
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def build_llm_client(
    settings: Settings | None = None,
    *,
    prefer_reasoning_model: bool = False,
) -> DiagnosticLLMClient:
    """Return the appropriate LLM client for the current configuration.

    Parameters
    ----------
    settings:
        Override the global settings (useful in tests and factories that
        already hold a resolved Settings instance).
    prefer_reasoning_model:
        When True and LLM_PROVIDER=bedrock, use BEDROCK_REASONING_MODEL
        instead of BEDROCK_DEFAULT_MODEL. Has no effect on the direct-
        Anthropic path (which uses ANTHROPIC_DEFAULT_MODEL for all workloads).
    """
    resolved = settings or get_settings()

    provider = resolved.LLM_PROVIDER.strip().casefold()

    if provider == "bedrock":
        if not resolved.LLM_AWS_REGION.strip():
            if resolved.is_production:
                raise CognitionLLMConfigurationError(
                    "LLM_PROVIDER=bedrock requires LLM_AWS_REGION in production"
                )
            logger.debug(
                "LLM_PROVIDER=bedrock but LLM_AWS_REGION is empty "
                "— using deterministic LLM client for non-production"
            )
            return DeterministicDiagnosticLLMClient()
        return _build_bedrock_client(resolved, prefer_reasoning_model)

    # Default: direct Anthropic API.
    return _build_anthropic_client(resolved)


def _build_anthropic_client(settings: Settings) -> DiagnosticLLMClient:
    api_key = settings.ANTHROPIC_API_KEY.strip()
    if not api_key:
        if settings.is_production:
            raise CognitionLLMConfigurationError(
                "ANTHROPIC_API_KEY is required for production LLM clients"
            )
        logger.debug(
            "ANTHROPIC_API_KEY not set — using deterministic LLM client "
            "for non-production"
        )
        return DeterministicDiagnosticLLMClient()
    return AnthropicMessagesClient(
        api_key=api_key,
        model=settings.ANTHROPIC_DEFAULT_MODEL,
        base_url=settings.ANTHROPIC_BASE_URL,
        anthropic_version=settings.ANTHROPIC_VERSION,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
    )


def _build_bedrock_client(
    settings: Settings, prefer_reasoning_model: bool
) -> DiagnosticLLMClient:
    from app.cognition.llm_bedrock import BedrockAnthropicMessagesClient

    model = (
        settings.BEDROCK_REASONING_MODEL
        if prefer_reasoning_model
        else settings.BEDROCK_DEFAULT_MODEL
    )
    logger.debug(
        "Building Bedrock LLM client region=%s model=%s",
        settings.LLM_AWS_REGION,
        model,
    )
    return BedrockAnthropicMessagesClient(
        model=model,
        aws_region=settings.LLM_AWS_REGION,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
    )


__all__ = ["build_llm_client"]
