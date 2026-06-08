"""Proposal-only SME review runtime."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from typing import Protocol

from app.approvals.identity import derive_sme_recommendation_id
from app.sme.exceptions import SmeReviewUnavailableError
from app.sme.models import SmeCaseContext, SmeRecommendation

logger = logging.getLogger(__name__)

_UNTRUSTED_GUIDANCE_BEGIN = "BEGIN_UNTRUSTED_OPERATOR_GUIDANCE"
_UNTRUSTED_GUIDANCE_END = "END_UNTRUSTED_OPERATOR_GUIDANCE"


class SmeLLMReviewer(Protocol):
    """Optional LLM-backed reviewer contract."""

    async def review(
        self,
        context: SmeCaseContext,
        *,
        recommendation_id: str,
        guidance: str | None = None,
    ) -> SmeRecommendation: ...


class SmeReviewRuntime:
    """SME reviewer that recommends but never sends or fires actions.

    When an LLM reviewer is configured and it errors, behaviour is
    governed by ``fail_closed_on_reviewer_error``:

    * ``True`` (enterprise default for configured reviewers): raise
      :class:`SmeReviewUnavailableError` so the case stays pending and a
      human still signs off rather than silently degrading quality.
    * ``False``: fall back to the deterministic reviewer, but record the
      failure on the recommendation so the degradation is observable.

    The deterministic reviewer is proposal-only and never fabricates new
    grounded customer prose from operator guidance; it preserves the
    agent's original grounded reply and flags that real-model authoring
    is required to act on free-text guidance.
    """

    def __init__(
        self,
        *,
        llm_reviewer: SmeLLMReviewer | None = None,
        fail_closed_on_reviewer_error: bool = False,
        fail_closed_without_reviewer: bool = False,
    ) -> None:
        self._llm_reviewer = llm_reviewer
        self._fail_closed_on_reviewer_error = fail_closed_on_reviewer_error
        self._fail_closed_without_reviewer = fail_closed_without_reviewer

    async def review_case(
        self,
        context: SmeCaseContext,
        *,
        guidance: str | None = None,
        guidance_round: int = 0,
    ) -> SmeRecommendation:
        recommendation_id = str(
            derive_sme_recommendation_id(
                approval_case_id=context.approval_case_id,
                guidance_round=guidance_round,
            )
        )
        reviewer_error: str | None = None
        if self._llm_reviewer is not None:
            try:
                return await self._llm_reviewer.review(
                    context,
                    recommendation_id=recommendation_id,
                    guidance=_wrap_untrusted_guidance(guidance),
                )
            except Exception as exc:  # noqa: BLE001 - degrade/observe or fail closed.
                reviewer_error = type(exc).__name__
                logger.exception(
                    "sme_llm_reviewer_failed",
                    extra={
                        "approval_case_id": context.approval_case_id,
                        "tenant_id": context.tenant_id,
                        "entry_category": context.entry_category,
                        "guidance_round": guidance_round,
                        "fail_closed": self._fail_closed_on_reviewer_error,
                    },
                )
                if self._fail_closed_on_reviewer_error:
                    raise SmeReviewUnavailableError(
                        "configured SME reviewer failed; case stays pending"
                    ) from exc
        if self._fail_closed_without_reviewer:
            raise SmeReviewUnavailableError(
                "SME review requires a configured model reviewer; "
                "case stays pending"
            )
        return _deterministic_recommendation(
            context,
            recommendation_id=recommendation_id,
            guidance=guidance,
            guidance_round=guidance_round,
            reviewer_error=reviewer_error,
        )


def _deterministic_recommendation(
    context: SmeCaseContext,
    *,
    recommendation_id: str,
    guidance: str | None,
    guidance_round: int,
    reviewer_error: str | None = None,
) -> SmeRecommendation:
    # The deterministic reviewer preserves the agent's original (already
    # grounded) reply verbatim. It never authors new customer prose from
    # free-text guidance, so the approve path treats this as an
    # "unchanged" reply and delivers the original grounded text.
    reply = (
        context.proposed_customer_reply
        or "A human-approved response is required before customer delivery."
    ).strip()
    flags = list(_risk_flags(context))
    confidence = _confidence(context)
    rationale = (
        "Deterministic SME fallback reviewed the proposed resolution, "
        "citations, action descriptors, and lifecycle category."
    )
    metadata: dict[str, Any] = {
        "reviewer": "deterministic_sme_fallback:v1",
        "proposal_only": True,
        "entry_category": context.entry_category,
        "guidance_round": guidance_round,
        "guidance_incorporated": False,
    }
    if reviewer_error is not None:
        metadata["llm_reviewer_failed"] = True
        metadata["llm_reviewer_error"] = reviewer_error
        flags.append("sme_model_unavailable")
    wrapped_guidance = _wrap_untrusted_guidance(guidance)
    if wrapped_guidance is not None:
        rationale += (
            " Operator guidance was recorded as untrusted input but cannot "
            "be incorporated into a new grounded reply without a model "
            "reviewer; the original grounded reply is preserved."
        )
        metadata["untrusted_guidance"] = wrapped_guidance
        flags.append("guidance_requires_model_authoring")
    return SmeRecommendation(
        recommendation_id=recommendation_id,
        recommended_reply=reply,
        recommended_actions=tuple(dict(action) for action in context.recommended_actions),
        rationale=rationale,
        confidence=confidence,
        citations=tuple(dict(citation) for citation in context.citations),
        risk_flags=tuple(dict.fromkeys(flags)),
        created_at=datetime.now(timezone.utc),
        reply_segments=(),
        metadata=metadata,
    )


def _risk_flags(context: SmeCaseContext) -> tuple[str, ...]:
    flags: list[str] = []
    category = context.entry_category
    summary = (context.issue_summary or "").lower()
    if "low_confidence" in category:
        flags.append("low_confidence")
    if "refund" in category or "refund" in summary or "return" in summary:
        flags.append("refund_policy")
    if "warranty" in category or "warranty" in summary:
        flags.append("warranty_policy")
    if "crisis" in category:
        flags.append("crisis_policy")
    if not context.citations:
        flags.append("citation_review_required")
    return tuple(dict.fromkeys(flags))


def _confidence(context: SmeCaseContext) -> float:
    raw = context.metadata.get("confidence")
    if isinstance(raw, bool):
        return 0.5
    if isinstance(raw, int | float):
        return max(0.0, min(1.0, float(raw)))
    return 0.65 if context.citations else 0.45


def _wrap_untrusted_guidance(guidance: str | None) -> str | None:
    if guidance is None:
        return None
    stripped = guidance.strip()
    if not stripped:
        return None
    return (
        f"{_UNTRUSTED_GUIDANCE_BEGIN}\n"
        f"{stripped}\n"
        f"{_UNTRUSTED_GUIDANCE_END}"
    )


__all__ = ["SmeLLMReviewer", "SmeReviewRuntime"]
