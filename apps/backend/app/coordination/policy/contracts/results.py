"""`CoordinationPolicyEvaluationResult` — apex output of `evaluate()`.

Pairs 1:1 with `CoordinationPolicyTrace`. The persistence layer's
serialisers convert `(result, trace)` into the
`CoordinationPolicyRecord`.

Determinism contract:

* `findings` preserves evaluator-sort order, then per-evaluator
  emission order.
* `restrictions` and `escalations` are aggregated across all findings
  whose verdict matches the apex `aggregate_decision`.
* `aggregate_decision` is computed via
  `coordination_policy_precedence` (most-restrictive wins) over every
  finding's decision; ALLOW is the baseline when no findings are
  emitted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

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
from app.coordination.policy.models.escalation import (
    CoordinationPolicyEscalation,
)
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)
from app.coordination.policy.models.restriction import (
    CoordinationPolicyRestriction,
)


@dataclass(frozen=True, slots=True)
class CoordinationPolicyEvaluationResult:
    """Apex result of one coordination-policy evaluation.

    Attributes:
        evaluation_id:        Stable identifier of THIS evaluation.
        chain_id:             Stable identifier of the evaluator-chain
                               composition that ran.
        runtime_instance_id:  Stable id of the
                               `CoordinationPolicyRuntime` instance.
        sequence:             Monotonic per-runtime-instance ordering
                               field, mirroring the discipline of
                               `CoordinationEnvelope.sequence`.
        coordination_id:      The coordination dispatch this
                               evaluation authorises.
        coordination_message_id:
                               The message id being authorised.
        correlation_id:       Pipeline-level grouping.
        parent_coordination_id / parent_message_id:
                               Causality ancestors.
        request_id / tenant_id:
                               Platform + tenant lineage.
        sender_id / recipient_id / recipient_kind:
                               Routing identity captured verbatim.
        aggregate_decision:   Apex verdict over every finding's
                               decision; computed via
                               `coordination_policy_precedence`.
        findings:             All findings emitted by the chain, in
                               evaluator-sort then emission order.
        restrictions:         Aggregated restrictions from findings
                               whose decision matches
                               `aggregate_decision`.
        escalations:          Aggregated escalations from findings
                               whose decision matches
                               `aggregate_decision`.
        evaluator_names:      Names of evaluators that contributed.
        reason:               Short human-readable explanation.
        started_at / ended_at:Wall-clock window.
        latency_ms:           Total evaluation latency.
        error:                Set when the framework itself failed
                               (an evaluator raised, request was
                               malformed). The runtime never raises.
        metadata:             Free-form, propagated from request.
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
    aggregate_decision: CoordinationPolicyDecision
    findings: tuple[CoordinationPolicyFinding, ...]
    restrictions: tuple[CoordinationPolicyRestriction, ...]
    escalations: tuple[CoordinationPolicyEscalation, ...]
    evaluator_names: tuple[str, ...]
    reason: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: CoordinationCorrelationId | None = None
    parent_coordination_id: CoordinationId | None = None
    parent_message_id: CoordinationMessageId | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_allow(self) -> bool:
        return self.aggregate_decision is CoordinationPolicyDecision.ALLOW

    @property
    def is_blocking(self) -> bool:
        """True iff the apex verdict halts dispatch.

        Delegates to `is_blocking_policy_decision` — the single
        authority on blocking semantics across the substrate.
        """
        from app.coordination.policy.taxonomy import (
            is_blocking_policy_decision,
        )

        return is_blocking_policy_decision(self.aggregate_decision)


__all__ = ["CoordinationPolicyEvaluationResult"]
