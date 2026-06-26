"""Shared money/goods commitment detection for resolution autonomy gates."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_COMMITMENT_ACTION_TYPES = frozenset(
    {
        "refund_request",
        "replacement_order",
        "warranty_claim",
    }
)

_COMMITMENT_TOOL_NAMES = frozenset(
    {
        "refund.request",
        "replacement.order",
        "warranty.claim",
        "replacement.dispatch",
        "warranty.dispatch",
    }
)

_COMMITMENT_REPLY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "refund",
        re.compile(
            r"\b(?:we|we'll|we will|can|can process|can offer)\b.{0,80}\brefund\b"
        ),
    ),
    ("refund", re.compile(r"\brefund is approved\b|\bapproved for refund\b")),
    (
        "replacement",
        re.compile(
            r"\b(?:we|we'll|we will)\b.{0,80}\breplace(?:ment)?\b"
        ),
    ),
    (
        "replacement",
        re.compile(
            r"\breplacement will arrive\b|\bsend you a replacement\b|\bapproved for replacement\b"
        ),
    ),
    (
        "replacement",
        re.compile(r"\bship a replacement\b|\breplacement is on the way\b"),
    ),
    (
        "warranty",
        re.compile(r"\bcovered under warranty\b|\bwarranty covers\b"),
    ),
    (
        "warranty",
        re.compile(r"\bapproved warranty claim\b|\bwe will honor your warranty\b"),
    ),
    ("credit", re.compile(r"\bissue a credit\b|\bapply a credit\b|\bstore credit\b")),
    (
        "shipment",
        re.compile(r"\bwe will ship\b|\bshipment is on the way\b"),
    ),
    (
        "prepaid_label",
        re.compile(r"\bprepaid label\b|\bprepaid return label\b|\breturn label\b"),
    ),
)


def money_or_goods_commitment_kinds(
    *,
    recommended_actions: Sequence[Mapping[str, Any]],
    reply: str | None = None,
) -> tuple[str, ...]:
    """Return stable commitment-kind evidence for money/goods disbursement.

    The invariant keys on the commitment kind, not on any parsed amount. A
    reply or action that promises a refund, replacement, warranty
    fulfillment, shipment, credit, or prepaid label must route to human
    approval regardless of amount or tenant config.
    """

    kinds: list[str] = []
    for action in recommended_actions:
        action_type = action.get("type")
        if isinstance(action_type, str) and action_type.strip() in _COMMITMENT_ACTION_TYPES:
            kinds.append(f"action_type:{action_type.strip()}")
        tool_name = action.get("tool_name")
        if isinstance(tool_name, str) and tool_name.strip() in _COMMITMENT_TOOL_NAMES:
            kinds.append(f"tool_name:{tool_name.strip()}")
    if reply:
        lowered_reply = reply.lower()
        for kind, pattern in _COMMITMENT_REPLY_PATTERNS:
            if pattern.search(lowered_reply):
                kinds.append(f"reply_text:{kind}")
    return tuple(dict.fromkeys(kinds))


def has_money_or_goods_commitment(
    *,
    recommended_actions: Sequence[Mapping[str, Any]],
    reply: str | None = None,
) -> bool:
    return bool(
        money_or_goods_commitment_kinds(
            recommended_actions=recommended_actions,
            reply=reply,
        )
    )


__all__ = [
    "has_money_or_goods_commitment",
    "money_or_goods_commitment_kinds",
]
