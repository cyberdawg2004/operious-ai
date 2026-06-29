from __future__ import annotations

from app.runtime.conversation_generation import (
    GroundedReplyDraft,
    GroundedReplySegment,
    render_grounded_reply,
)


def test_break_control_i_multiple_asks_render_as_numbered_list() -> None:
    """(i): 2+ QUESTION segments must render as a numbered list, not a
    run-on sentence."""
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="acknowledgment",
                text="Thanks for reaching out, sorry to hear about the issue.",
            ),
            GroundedReplySegment(
                kind="claim",
                text="Your purchase is within the warranty period.",
                citation_ranks=(1,),
            ),
            GroundedReplySegment(
                kind="question",
                text="What is your order number?",
            ),
            GroundedReplySegment(
                kind="question",
                text="What is the seller name?",
            ),
        ),
    )

    rendered = render_grounded_reply(draft)

    assert rendered == (
        "Thanks for reaching out, sorry to hear about the issue. "
        "Your purchase is within the warranty period. [1]\n\n"
        "1. What is your order number?\n"
        "2. What is the seller name?"
    )


def test_break_control_ii_single_ask_stays_clean_not_fragmented() -> None:
    """(ii): a single-point reply (ack + claim + one question) stays a
    single flowing paragraph -- it must not be artificially split."""
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="acknowledgment",
                text="Thanks for reaching out.",
            ),
            GroundedReplySegment(
                kind="claim",
                text="Approved support guidance covers this issue.",
                citation_ranks=(1,),
            ),
            GroundedReplySegment(
                kind="question",
                text="Could you share your order number?",
            ),
        ),
    )

    rendered = render_grounded_reply(draft)

    assert "\n" not in rendered
    assert rendered == (
        "Thanks for reaching out. Approved support guidance covers this "
        "issue. [1] Could you share your order number?"
    )


def test_break_control_iii_question_only_reply_is_not_a_list() -> None:
    """A single QUESTION segment with no other segments is not promoted to
    a numbered list of one."""
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="question",
                text="What is your order number?",
            ),
        ),
    )

    rendered = render_grounded_reply(draft)

    assert rendered == "What is your order number?"
    assert "1." not in rendered


def test_break_control_iv_segment_content_and_citations_unchanged() -> None:
    """(iv): this is presentation only -- citation markers still attach to
    the exact claim they were attached to, and the same content renders
    regardless of the new join logic."""
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="claim",
                text="We will process a replacement.",
                citation_ranks=(1, 2),
            ),
        ),
    )

    rendered = render_grounded_reply(draft)

    assert rendered == "We will process a replacement. [1,2]"


def test_single_segment_reply_is_unaffected() -> None:
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="claim",
                text="This issue is covered by approved support guidance.",
                citation_ranks=(),
            ),
        ),
    )

    assert render_grounded_reply(draft) == (
        "This issue is covered by approved support guidance."
    )


def test_trailing_next_step_acknowledgment_renders_after_the_list() -> None:
    """The full target shape: opener -> context -> numbered asks -> a
    trailing next-step line. The next-step acknowledgment comes AFTER
    the question segments in the draft, so it must render as its own
    paragraph after the list, not folded backward into the opener."""
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="acknowledgment",
                text="Thanks for reaching out, sorry to hear about the issue.",
            ),
            GroundedReplySegment(
                kind="claim",
                text="This may indicate a connector or cable issue.",
                citation_ranks=(1,),
            ),
            GroundedReplySegment(kind="question", text="Which model do you have?"),
            GroundedReplySegment(kind="question", text="Which cable are you using?"),
            GroundedReplySegment(
                kind="acknowledgment",
                text="Once we have these details, we'll check eligibility.",
            ),
        ),
    )

    rendered = render_grounded_reply(draft)

    assert rendered == (
        "Thanks for reaching out, sorry to hear about the issue. "
        "This may indicate a connector or cable issue. [1]\n\n"
        "1. Which model do you have?\n"
        "2. Which cable are you using?\n\n"
        "Once we have these details, we'll check eligibility."
    )


def test_three_or_more_questions_all_appear_in_the_numbered_list() -> None:
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(kind="acknowledgment", text="Thanks for reaching out."),
            GroundedReplySegment(kind="question", text="What is your order number?"),
            GroundedReplySegment(kind="question", text="What is the seller name?"),
            GroundedReplySegment(kind="question", text="When did you purchase it?"),
        ),
    )

    rendered = render_grounded_reply(draft)

    assert rendered == (
        "Thanks for reaching out.\n\n"
        "1. What is your order number?\n"
        "2. What is the seller name?\n"
        "3. When did you purchase it?"
    )
