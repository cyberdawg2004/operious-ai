"""L8: Central governance catches money/goods commitments the local detector may miss.

Two-layer architecture:
  Layer 1 (local):   money_goods_commitment.py regex — catches known reply phrasings
  Layer 2 (central): resolution_governance_gate.py — re-evaluates from local metadata

KEY FINDING (Phase-2 audit): The two layers share the same detector output
(central reads 'money_or_goods_commitment_kinds' from local metadata). A novel
phrasing that evades the local regex ALSO evades the central regex check.

HOWEVER: The action-type path is independent of regex:
  - If recommended_actions contains a type in _COMMITMENT_ACTION_TYPES
    (refund_request, replacement_order, warranty_claim) → caught by action type
    check regardless of reply text.
  - The realistic attack path requires both: (a) novel reply phrasing AND
    (b) no explicit action recommendation. Category must also be in
    reply_auto_send_categories.

These tests confirm:
  (1) Action type check is authoritative — explicit action → caught even with
      novel reply phrasing.
  (2) Reply text regex provides defense-in-depth for reply-only commitments.
  (3) Novel phrasing outside known patterns — documents the limitation clearly.
"""

from __future__ import annotations

import pytest

from app.runtime.money_goods_commitment import (
    has_money_or_goods_commitment,
    money_or_goods_commitment_kinds,
)


# ---------------------------------------------------------------------------
# (1) Action type check is authoritative — explicit action catches commitment
#     regardless of reply phrasing
# ---------------------------------------------------------------------------

def test_refund_action_type_caught_regardless_of_reply() -> None:
    """An explicit refund_request action catches the commitment even when the
    reply text uses no known phrasing — action type check is regex-independent.
    """
    result = has_money_or_goods_commitment(
        recommended_actions=[{"type": "refund_request"}],
        reply="We are pleased to assist you with the situation.",  # no known phrase
    )
    assert result is True, (
        "Expected commitment detected via action type 'refund_request', "
        "regardless of reply text. Action-type check is regex-independent."
    )


def test_replacement_action_type_caught_regardless_of_reply() -> None:
    result = has_money_or_goods_commitment(
        recommended_actions=[{"type": "replacement_order"}],
        reply="We appreciate your patience.",  # no known phrase
    )
    assert result is True


def test_warranty_action_type_caught_regardless_of_reply() -> None:
    result = has_money_or_goods_commitment(
        recommended_actions=[{"type": "warranty_claim"}],
        reply="We appreciate your patience.",
    )
    assert result is True


def test_refund_tool_name_caught_regardless_of_reply() -> None:
    """Tool name match is also regex-independent."""
    result = has_money_or_goods_commitment(
        recommended_actions=[{"tool_name": "refund.request"}],
        reply="We are pleased to assist you.",
    )
    assert result is True


# ---------------------------------------------------------------------------
# (2) Reply text regex provides depth for reply-only commitments (no action)
# ---------------------------------------------------------------------------

def test_known_refund_phrase_caught_without_action() -> None:
    """Known phrase in reply → caught even with no recommended action."""
    result = has_money_or_goods_commitment(
        recommended_actions=[],
        reply="We'll refund your order right away.",
    )
    assert result is True


def test_known_replacement_phrase_caught_without_action() -> None:
    result = has_money_or_goods_commitment(
        recommended_actions=[],
        reply="We will replace the defective unit at no extra cost.",
    )
    assert result is True


def test_no_commitment_no_action() -> None:
    """A purely informational reply with no action → no commitment detected."""
    result = has_money_or_goods_commitment(
        recommended_actions=[],
        reply="Thank you for contacting us. A specialist will review your case.",
    )
    assert result is False


# ---------------------------------------------------------------------------
# (3) Document the known limitation: novel phrasing with no action
#     This test confirms the gap is real and serves as a regression marker.
#     The fix is: if novel phrasings appear in production, add them to the
#     regex list. The action-type check remains the authoritative gate.
# ---------------------------------------------------------------------------

def test_novel_phrasing_with_no_action_is_gap(
    # This test documents a KNOWN LIMITATION — it asserts the current behavior,
    # not the ideal behavior. If this assertion ever flips to True, the regex
    # has been improved to cover this phrasing.
) -> None:
    """A novel money commitment phrasing with no recommended action is NOT
    caught by the current detector.

    This is a documented, known limitation of the local-only detection layer.
    The primary mitigation is the action-type check (tests 1-4 above): in
    the realistic attack path, a money/goods commitment IS backed by an
    explicit action recommendation (refund_request, replacement_order) which
    is caught action-type-independently.

    A reply-only money commitment without a recommended action in an auto-send
    category is a narrower gap. Teams adding to reply_auto_send_categories
    should validate that the category's resolution path ALWAYS produces an
    action recommendation for money/goods outcomes.
    """
    novel_phrasing = (
        "As a goodwill gesture, we are crediting your account with the full "
        "purchase amount, effective immediately."
    )
    result = has_money_or_goods_commitment(
        recommended_actions=[],
        reply=novel_phrasing,
    )
    # This MAY be False (gap) or True (if regex catches it).
    # The important thing: if True, the regex IS catching this novel phrasing.
    # If False, the action-type path is the authoritative backstop.
    # We assert it's False here to document the current state; update this
    # if a new regex pattern is added to cover "crediting your account".
    assert result is False, (
        "This test documents that the regex does NOT catch this novel phrasing. "
        "If it now returns True, update this comment — the coverage improved."
    )


def test_action_type_backstop_for_novel_phrasing() -> None:
    """Even when novel phrasing evades the regex, adding the right action type
    catches the commitment. This is the recommended defense: action types are
    structural, not text-pattern dependent.
    """
    novel_phrasing = (
        "As a goodwill gesture, we are crediting your account with the full "
        "purchase amount, effective immediately."
    )
    # Without action → gap (as above)
    without_action = has_money_or_goods_commitment(
        recommended_actions=[],
        reply=novel_phrasing,
    )
    assert without_action is False, "Confirming gap when no action is present"

    # With action → caught by action-type check, regex-independently
    with_action = has_money_or_goods_commitment(
        recommended_actions=[{"type": "refund_request"}],
        reply=novel_phrasing,
    )
    assert with_action is True, (
        "Action-type check must catch the commitment even when regex misses it"
    )
