"""Canonical coordination metadata-key vocabulary.

Vocabulary discipline aid — names the metadata keys the coordination
substrate writes onto envelopes / traces / governance metadata so
typos and renames surface at import time rather than as silent drift
in audit dashboards.

This module is NOT a schema-enforcement layer:

* `CoordinationEnvelope.metadata` remains `Mapping[str, Any]` for
  deployment-specific extensibility,
* `StrEnum` members flow transparently into string contexts
  (``meta[CoordinationMetadataKey.SENDER] == "agent:retriever"`` works
  in both directions),
* external callers may write metadata keys outside this catalogue —
  the taxonomy is the canonical *substrate* set, not a closed
  universe.

Two complementary catalogues live here:

* `CoordinationMetadataKey`   — keys the runtime writes onto traces /
                                 envelopes / governance metadata when
                                 composing the dispatch.
* `CoordinationGovernanceAction`
                              — the canonical governance ``action``
                                 strings the runtime passes into
                                 `GovernanceContext.action`. One per
                                 `CoordinationMessageType` value plus
                                 the generic dispatch fallback. Pinned
                                 here so the same string flows across
                                 governance + audit + supervisor
                                 substrates.
"""

from __future__ import annotations

from enum import StrEnum


class CoordinationMetadataKey(StrEnum):
    """Canonical metadata keys the runtime writes.

    Keys are namespaced under ``coordination.*`` so they don't collide
    with caller-supplied free-form metadata.
    """

    DIRECTION = "coordination.direction"
    MESSAGE_TYPE = "coordination.message_type"
    PRIORITY = "coordination.priority"
    SENDER = "coordination.sender_id"
    RECIPIENT = "coordination.recipient_id"
    RECIPIENT_KIND = "coordination.recipient_kind"
    SEQUENCE = "coordination.sequence"
    IN_REPLY_TO = "coordination.in_reply_to"
    PARENT_COORDINATION_ID = "coordination.parent_coordination_id"
    PARENT_MESSAGE_ID = "coordination.parent_message_id"
    GOVERNANCE_DECISION_ID = "coordination.governance_decision_id"
    GOVERNANCE_CHAIN_ID = "coordination.governance_chain_id"
    OUTCOME = "coordination.outcome"


class CoordinationGovernanceAction(StrEnum):
    """Canonical governance ``action`` strings for coordination.

    The runtime emits exactly one of these as
    `GovernanceContext.action` for every dispatch — the value is a
    deterministic function of `CoordinationMessageType`. Pinning the
    catalogue here keeps governance policies and audit dashboards
    aligned on the action vocabulary.
    """

    REQUEST = "coordination.request"
    RESPONSE = "coordination.response"
    NOTIFICATION = "coordination.notification"
    HANDOFF = "coordination.handoff"
    SIGNAL = "coordination.signal"


__all__ = [
    "CoordinationMetadataKey",
    "CoordinationGovernanceAction",
]
