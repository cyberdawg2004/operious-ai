"""`CoordinationMessage` — the typed communicative artifact.

A coordination message is the runtime-grade representation of "one
agent / runtime communicates one thing to another agent / runtime /
supervisor". It is the unit governance evaluates, the unit
persistence records, the unit replay reconstructs.

The message itself is *content + identity*. Operational fields
(`status`, `sequence`, `dispatched_at`) live on the
`CoordinationEnvelope` that wraps the message — the message stays
a stable, replay-safe identifier-bearing artifact across multiple
dispatch attempts of the same logical content.

Authority discipline (Rule 1):

* `sender_id` is the explicit identity claim. The runtime validates
  it against `CoordinationRegistry`; unknown senders cannot dispatch.
* `recipient` carries explicit recipient identity. The runtime
  validates it against the registry; unknown recipients are
  rejected.

Replay-safety:

* The message id is independent from the coordination id; the same
  message id MAY appear under multiple `CoordinationId`s (e.g. when
  a replay tool re-dispatches the same logical message under a fresh
  dispatch identifier).
* `created_at` is the caller-controlled message authoring timestamp;
  the runtime preserves it verbatim across persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.coordination.enums import (
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import CoordinationMessageId
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient


@dataclass(frozen=True, slots=True)
class CoordinationMessage:
    """One coordination message — identity + content.

    Attributes:
        message_id:    Stable identifier for THIS message. The
                        substrate uses it for causality (the
                        `in_reply_to` field on a RESPONSE points at
                        the original REQUEST's message id) and for
                        replay reconstruction.
        message_type:  Semantic classification (REQUEST / RESPONSE /
                        NOTIFICATION / HANDOFF / SIGNAL).
        sender_id:     Stable identifier of the sender. Validated
                        against `CoordinationRegistry` at dispatch.
        recipient:     Typed recipient identity. Validated against
                        `CoordinationRegistry` at dispatch.
        payload:       Typed message body.
        priority:      Operational priority hint (audit-grade; does
                        NOT reorder dispatches).
        in_reply_to:   Optional id of the message THIS message
                        responds to. Preserves causality across
                        REQUEST/RESPONSE pairs.
        created_at:    Caller-controlled authoring timestamp.
                        Preserved across persistence verbatim. UTC.
        metadata:      Free-form, propagated across persistence.
    """

    message_id: CoordinationMessageId
    message_type: CoordinationMessageType
    sender_id: str
    recipient: CoordinationRecipient
    payload: CoordinationPayload
    priority: CoordinationPriority = CoordinationPriority.NORMAL
    in_reply_to: CoordinationMessageId | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = ["CoordinationMessage"]
