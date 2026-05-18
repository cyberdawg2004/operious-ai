"""Coordination policy traces.

Two trace shapes — same discipline as the parent coordination
substrate:

* `CoordinationPolicyTraceContext`  — identity bundle propagated
                                       into / out of an evaluation.
* `CoordinationPolicyTrace`         — one per
                                       `CoordinationPolicyRuntime.evaluate()`
                                       call. Pairs 1:1 with the
                                       `CoordinationPolicyEvaluationResult`.

Both are frozen, slotted, replay-safe. The trace is the lineage
artefact the persistence layer embeds into `CoordinationPolicyRecord`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import (
    CoordinationCorrelationId,
    CoordinationId,
    CoordinationMessageId,
)
from app.coordination.policy.enums import CoordinationPolicyDecision
from app.coordination.policy.identity import (
    CoordinationPolicyChainId,
    CoordinationPolicyEvaluationId,
)


@dataclass(frozen=True, slots=True)
class CoordinationPolicyTraceContext:
    """Lineage identifiers propagated through a policy evaluation.

    Mirrors `CoordinationTraceContext` in shape. Threaded through
    every evaluator invocation; never mutated; safe to embed as a
    dict key in tests.
    """

    evaluation_id: CoordinationPolicyEvaluationId
    chain_id: CoordinationPolicyChainId
    coordination_id: CoordinationId
    coordination_message_id: CoordinationMessageId
    correlation_id: CoordinationCorrelationId | None = None
    parent_coordination_id: CoordinationId | None = None
    parent_message_id: CoordinationMessageId | None = None
    request_id: str | None = None
    tenant_id: str | None = None


@dataclass(frozen=True, slots=True)
class CoordinationPolicyTrace:
    """Apex trace for one `CoordinationPolicyRuntime.evaluate()` call.

    Carries the lineage every audit / replay consumer needs to
    reconstruct the evaluation:

    * routing identity (sender, recipient, direction, message_type),
    * policy decision lineage (chain, aggregate decision, finding
      count, restriction count, escalation count),
    * timing window,
    * error attribution (set when the framework itself failed),
    * full metadata bag.
    """

    evaluation_id: CoordinationPolicyEvaluationId
    chain_id: CoordinationPolicyChainId
    runtime_instance_id: uuid.UUID
    sequence: int
    coordination_id: CoordinationId
    coordination_message_id: CoordinationMessageId
    sender_id: str
    recipient_id: str
    recipient_kind: str
    direction: CoordinationDirection
    message_type: CoordinationMessageType
    priority: CoordinationPriority
    aggregate_decision: CoordinationPolicyDecision
    evaluator_names: tuple[str, ...]
    finding_count: int
    restriction_count: int
    escalation_count: int
    correlation_id: CoordinationCorrelationId | None
    parent_coordination_id: CoordinationId | None
    parent_message_id: CoordinationMessageId | None
    request_id: str | None
    tenant_id: str | None
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    tenant_authority_source: str | None = None


__all__ = [
    "CoordinationPolicyTraceContext",
    "CoordinationPolicyTrace",
]
