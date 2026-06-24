"""GeneratedSmeReviewer must not discard an already-governed reply.

Regression coverage for the live finding: an eligible warranty case's
proposal was correctly rendered from a tenant-authored, pre-approved
verdict-override template (resolution.approved.replacement) -- but
GeneratedSmeReviewer.review() unconditionally regenerated a fresh reply
via the LLM generation pipeline regardless of operator guidance, ignoring
SmeCaseContext.proposed_customer_reply entirely. The regenerated reply
had an uncited claim and was denied at delivery -- not because the
override was broken, but because an always-on, override-unaware SME
review step silently superseded its correct output. The fix mirrors
app.sme.runtime's deterministic reviewer: when there's no real operator
guidance to incorporate, preserve the existing reply verbatim instead of
regenerating.
"""

from __future__ import annotations

import pytest

from app.runtime.conversation_generation import (
    ConversationGenerationRequest,
    ConversationGenerationResult,
    GroundedReplyDraft,
    GroundedReplySegment,
)
from app.sme.generated_reviewer import GeneratedSmeReviewer
from app.sme.models import SmeCaseContext

_TENANT = "tenant-generated-sme-reviewer"


class _RecordingGenerationRuntime:
    def __init__(self) -> None:
        self.calls: list[ConversationGenerationRequest] = []

    async def generate_reply(
        self, request: ConversationGenerationRequest
    ) -> ConversationGenerationResult:
        self.calls.append(request)
        return ConversationGenerationResult(
            draft=GroundedReplyDraft(
                language="en",
                segments=(
                    GroundedReplySegment(
                        kind="claim",
                        text="freshly generated, unrelated to the proposal's reply",
                        citation_ranks=(),
                    ),
                ),
            ),
            provider="anthropic",
            model="claude-sonnet-4-6",
            raw_text="freshly generated, unrelated to the proposal's reply",
        )


def _context(*, proposed_customer_reply: str | None) -> SmeCaseContext:
    return SmeCaseContext(
        approval_case_id="case-1",
        tenant_id=_TENANT,
        entry_category="refund_warranty",
        issue_summary="warranty_replacement_inquiry",
        proposed_customer_reply=proposed_customer_reply,
        recommended_actions=({"type": "warranty_claim"},),
        citations=({"rank": 1, "citation_label": "[1]"},),
        metadata={"confidence": 0.82},
    )


@pytest.mark.asyncio
async def test_unguided_review_preserves_an_existing_reply_verbatim() -> None:
    generation = _RecordingGenerationRuntime()
    reviewer = GeneratedSmeReviewer(generation_runtime=generation)
    existing_reply = (
        "Hi, thanks for reaching out. We've verified your purchase "
        "(order ORDER-AMZ-9024-RK, purchased 2025-11-20 from amazon.com) "
        "and confirmed it's within the warranty period."
    )

    recommendation = await reviewer.review(
        _context(proposed_customer_reply=existing_reply),
        recommendation_id="rec-1",
        guidance=None,
    )

    assert recommendation.recommended_reply == existing_reply
    assert recommendation.metadata["reviewer"] == "preserved_existing_reply:v1"
    assert recommendation.metadata["guidance_incorporated"] is False
    assert generation.calls == []  # never regenerated


@pytest.mark.asyncio
async def test_blank_guidance_also_preserves_the_existing_reply() -> None:
    """Whitespace-only guidance is not real guidance."""
    generation = _RecordingGenerationRuntime()
    reviewer = GeneratedSmeReviewer(generation_runtime=generation)
    existing_reply = "We've approved your warranty replacement."

    recommendation = await reviewer.review(
        _context(proposed_customer_reply=existing_reply),
        recommendation_id="rec-2",
        guidance="   ",
    )

    assert recommendation.recommended_reply == existing_reply
    assert generation.calls == []


@pytest.mark.asyncio
async def test_real_guidance_still_regenerates() -> None:
    """A genuine human edit must still go through the model so the
    revised reply can be (re)grounded -- only the no-guidance case
    should preserve verbatim."""
    generation = _RecordingGenerationRuntime()
    reviewer = GeneratedSmeReviewer(generation_runtime=generation)

    recommendation = await reviewer.review(
        _context(proposed_customer_reply="We've approved your replacement."),
        recommendation_id="rec-3",
        guidance="Mention the replacement ships within 5 business days.",
    )

    assert len(generation.calls) == 1
    assert recommendation.recommended_reply == (
        "freshly generated, unrelated to the proposal's reply"
    )
    assert recommendation.metadata["guidance_incorporated"] is True


@pytest.mark.asyncio
async def test_no_existing_reply_still_regenerates_even_unguided() -> None:
    """A genuinely novel case with no prior reply has nothing to
    preserve -- it must still get a first draft."""
    generation = _RecordingGenerationRuntime()
    reviewer = GeneratedSmeReviewer(generation_runtime=generation)

    recommendation = await reviewer.review(
        _context(proposed_customer_reply=None),
        recommendation_id="rec-4",
        guidance=None,
    )

    assert len(generation.calls) == 1
    assert recommendation.recommended_reply == (
        "freshly generated, unrelated to the proposal's reply"
    )
