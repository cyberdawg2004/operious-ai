"""Operation classification taxonomy.

A pure, leaf module that encodes the canonical operational-domain
classification an Operious AI substrate stamps onto every boundary
trace. The classification is independent of:

* the substrate that emitted the operation,
* the governance decision that gated the operation,
* the boundary direction (ingress vs egress).

It exists to give audit / replay / supervisor surfaces a stable axis
for grouping operations across substrates without inferring intent
from action strings.

Membership doctrine
-------------------

* The catalog is closed — adding or renaming a value is a wire-format
  break. New domains require an explicit migration.
* Values are lowercase, dot-separated namespaces. The first segment
  is the operational domain (``conversation``, ``data``, ``tool``,
  ``governance``, ``coordination``, ``observability``); the second
  segment is the action category.
* Substrate-internal events (e.g. session lifecycle) classify as
  ``observability.lifecycle`` — they are observable but not
  externally-driven operations.

This module imports nothing from sibling substrates. ``governance``
owns it because governance is the canonical authority for what
counts as an "operation" in the substrate.
"""

from __future__ import annotations

from enum import StrEnum


class OperationClassification(StrEnum):
    """Canonical classification of an operational call.

    Stamped onto ``BoundaryTrace.metadata`` (key:
    ``"boundary.operation_classification"``) and propagated into
    sibling substrates' metadata as a join axis. ID-only — neither
    governance nor any other substrate branches behavior on the
    value; it is purely an audit/inspection axis.
    """

    # Conversational operations — turns, completions, voice.
    CONVERSATION_TURN = "conversation.turn"
    CONVERSATION_COMPLETION = "conversation.completion"
    CONVERSATION_VOICE = "conversation.voice"

    # Data operations — retrieval, ingest, query, write-back.
    DATA_RETRIEVAL = "data.retrieval"
    DATA_INGEST = "data.ingest"
    DATA_QUERY = "data.query"
    DATA_WRITEBACK = "data.writeback"

    # Tool / external system operations — RAG, tool invocation, API
    # call, webhook delivery.
    TOOL_INVOCATION = "tool.invocation"
    TOOL_WEBHOOK = "tool.webhook"
    TOOL_API_CALL = "tool.api_call"

    # Governance-owned operations — policy evaluation, escalation,
    # supervisor inspection. These flow through governance even when
    # callers only see the boundary edge.
    GOVERNANCE_EVALUATION = "governance.evaluation"
    GOVERNANCE_ESCALATION = "governance.escalation"
    GOVERNANCE_INSPECTION = "governance.inspection"

    # Coordination-owned operations — message dispatch, topology
    # transition, policy gate.
    COORDINATION_DISPATCH = "coordination.dispatch"
    COORDINATION_TOPOLOGY = "coordination.topology"
    COORDINATION_POLICY = "coordination.policy"

    # Observability — substrate-internal events, lifecycle, audit.
    OBSERVABILITY_LIFECYCLE = "observability.lifecycle"
    OBSERVABILITY_AUDIT = "observability.audit"

    # Unclassified — explicit fallback, never the silent default.
    # Producers MUST stamp something; ``GENERIC`` is the audit-grade
    # placeholder for events that pre-date a domain assignment.
    GENERIC = "generic"


# Canonical metadata key boundary substrates stamp on
# ``BoundaryTrace.metadata`` to carry an
# ``OperationClassification`` value. Defined here (next to the
# enum) so producers and consumers cannot drift on the key string.
BOUNDARY_OPERATION_CLASSIFICATION_KEY = "boundary.operation_classification"


__all__ = [
    "BOUNDARY_OPERATION_CLASSIFICATION_KEY",
    "OperationClassification",
]
