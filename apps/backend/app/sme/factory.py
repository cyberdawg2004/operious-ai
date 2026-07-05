"""Composition helpers for production SME review runtimes."""

from __future__ import annotations

from app.cognition.llm import DiagnosticLLMClient
from app.cognition.llm_factory import build_llm_client
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
    If no LLM is configured (neither Anthropic key nor Bedrock), review
    attempts fail closed and the approval case remains pending for
    escalation/remediation. Non-production keeps the local grounded fallback
    so hermetic tests and local development do not require credentials.
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
) -> DiagnosticLLMClient | None:
    if not _llm_configured(settings):
        return None
    # SME review is reasoning-heavy: prefer the Sonnet-tier model on Bedrock.
    return build_llm_client(settings, prefer_reasoning_model=True)


def _llm_configured(settings: Settings) -> bool:
    """Return True if any real LLM provider is configured."""
    provider = settings.LLM_PROVIDER.strip().casefold()
    if provider == "bedrock":
        return bool(settings.LLM_AWS_REGION.strip())
    return bool(settings.ANTHROPIC_API_KEY.strip())


__all__ = ["build_sme_review_runtime"]
