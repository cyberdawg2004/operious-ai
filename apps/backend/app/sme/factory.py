"""Composition helpers for production SME review runtimes."""

from __future__ import annotations

from app.cognition import AnthropicMessagesClient
from app.core.config import Settings, get_settings
from app.runtime.conversation_generation import GroundedConversationGenerationRuntime
from app.sme.generated_reviewer import GeneratedSmeReviewer
from app.sme.runtime import SmeReviewRuntime


def build_sme_review_runtime(
    *,
    settings: Settings | None = None,
) -> SmeReviewRuntime:
    """Build the shared SME runtime used by API and worker entrypoints.

    Production never falls back to local deterministic/model-free authoring.
    If no Anthropic key is configured, review attempts fail closed and the
    approval case remains pending for escalation/remediation. Non-production
    keeps the local grounded fallback so hermetic tests and local development
    do not require provider credentials.
    """

    resolved_settings = settings or get_settings()
    llm_client = _sme_generation_llm_client(resolved_settings)
    if llm_client is None and resolved_settings.is_production:
        return SmeReviewRuntime(
            fail_closed_on_reviewer_error=True,
            fail_closed_without_reviewer=True,
        )
    return SmeReviewRuntime(
        llm_reviewer=GeneratedSmeReviewer(
            generation_runtime=GroundedConversationGenerationRuntime(
                llm_client=llm_client,
            ),
        ),
        fail_closed_on_reviewer_error=resolved_settings.is_production,
    )


def _sme_generation_llm_client(
    settings: Settings,
) -> AnthropicMessagesClient | None:
    api_key = settings.ANTHROPIC_API_KEY.strip()
    if not api_key:
        return None
    return AnthropicMessagesClient(
        api_key=api_key,
        model=settings.ANTHROPIC_DEFAULT_MODEL,
        base_url=settings.ANTHROPIC_BASE_URL,
        anthropic_version=settings.ANTHROPIC_VERSION,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
    )


__all__ = ["build_sme_review_runtime"]
