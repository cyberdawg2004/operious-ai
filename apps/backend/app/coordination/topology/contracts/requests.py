"""`CoordinationTopologyEvaluationRequest` — typed input to `evaluate()`.

The request captures the **structural** axes every topology
evaluator inspects:

* `sender_id` / `recipient_id` — runtime participant identifiers
  the evaluators resolve against the declared topology's nodes.
* `recipient_kind`             — recipient classification.
* `direction`                  — operational direction.
* `message_type` / `priority`  — semantic + priority hints.
* `tenant_id` /
  `sender_tenant_id` /
  `recipient_tenant_id`         — tenant boundary annotations.
* `coordination_id` /
  `coordination_message_id`     — coordination lineage threading.
* `correlation_id` /
  `parent_coordination_id` /
  `parent_message_id`           — lineage / causality continuity.
* `request_id`                 — platform-wide request id.
* `chain_depth`                — declared by the caller. The
                                  coordination runtime propagates a
                                  child dispatch's `chain_depth` as
                                  `parent.chain_depth + 1`. The
                                  topology substrate trusts the
                                  caller's value.
* `evaluator_names`            — optional whitelist; ``None`` runs
                                  every registered evaluator.
* `evaluation_id_override`     — replay aid.
* `metadata`                   — free-form, propagated onto trace +
                                  result.

The request is replay-safe: passing identical inputs (including
`evaluation_id_override`) produces an identical
`CoordinationTopologyEvaluationResult` modulo wall-clock fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
from app.coordination.topology.identity import (
    CoordinationTopologyEvaluationId,
)
from app.identity import (
    AuthorityContext,
    check_tenant_authority_coexistence,
)


@dataclass(frozen=True, slots=True)
class CoordinationTopologyEvaluationRequest:
    """Input to one `CoordinationTopologyRuntime.evaluate()` call."""

    sender_id: str
    recipient_id: str
    direction: CoordinationDirection
    message_type: CoordinationMessageType
    coordination_id: CoordinationId
    coordination_message_id: CoordinationMessageId
    recipient_kind: str = "agent"
    priority: CoordinationPriority = CoordinationPriority.NORMAL
    tenant_id: str | None = None
    sender_tenant_id: str | None = None
    recipient_tenant_id: str | None = None
    correlation_id: CoordinationCorrelationId | None = None
    parent_coordination_id: CoordinationId | None = None
    parent_message_id: CoordinationMessageId | None = None
    request_id: str | None = None
    chain_depth: int = 0
    evaluator_names: tuple[str, ...] | None = None
    evaluation_id_override: CoordinationTopologyEvaluationId | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="CoordinationTopologyEvaluationRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


__all__ = ["CoordinationTopologyEvaluationRequest"]
