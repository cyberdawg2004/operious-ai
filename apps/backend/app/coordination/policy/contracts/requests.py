"""`CoordinationPolicyEvaluationRequest` — typed input to `evaluate()`.

The request captures the topology dimensions every policy evaluator
needs:

* `sender_id`              — the dispatch sender identity.
* `recipient_id`           — the dispatch recipient identity.
* `recipient_kind`         — recipient classification
                              (``"agent"`` / ``"supervisor"`` /
                              ``"broadcast"`` / …).
* `direction`              — the operational direction.
* `message_type`           — the semantic classification.
* `priority`               — the audit-grade priority hint.
* `tenant_id`              — tenant scope, when known.
* `sender_tenant_id`       — explicit sender tenant (may differ from
                              the dispatch tenant for cross-tenant
                              checks).
* `recipient_tenant_id`    — explicit recipient tenant.
* `correlation_id`         — pipeline-level grouping (carried
                              verbatim onto the policy envelope).
* `coordination_id`        — id of the parent
                              `CoordinationRuntime.dispatch()` call.
                              Threads the policy evaluation into the
                              coordination lineage.
* `coordination_message_id`— id of the message being authorised.
* `parent_coordination_id` — causality ancestor at the dispatch level.
* `parent_message_id`      — causality ancestor at the message level.
* `request_id`             — platform-wide request id.
* `evaluator_names`        — optional whitelist; when ``None`` every
                              registered evaluator runs.
* `evaluation_id_override` — replay aid.
* `metadata`               — free-form, propagated onto trace + result.

The request is replay-safe: passing identical inputs (including
`evaluation_id_override`) produces an identical
`CoordinationPolicyEvaluationResult` modulo wall-clock fields.
"""

from __future__ import annotations

import uuid
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
from app.coordination.policy.identity import (
    CoordinationPolicyEvaluationId,
)
from app.identity import (
    AuthorityContext,
    check_tenant_authority_coexistence,
)


@dataclass(frozen=True, slots=True)
class CoordinationPolicyEvaluationRequest:
    """Input to one `CoordinationPolicyRuntime.evaluate()` call.

    Captures the topology slice of one coordination dispatch so the
    evaluator chain can authorise (or refuse to authorise) the
    sender→recipient communication on its own terms — independent
    of governance.
    """

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
    evaluator_names: tuple[str, ...] | None = None
    evaluation_id_override: CoordinationPolicyEvaluationId | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="CoordinationPolicyEvaluationRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )

    @property
    def topology_key(self) -> tuple[str, str, str, str]:
        """Canonical sortable key for the (sender, recipient, direction,
        message_type) tuple — handy for tests + audit diffs.
        """
        return (
            self.sender_id,
            self.recipient_id,
            self.direction.value,
            self.message_type.value,
        )


# Silence the unused-import warning for `uuid` which is referenced
# only by the `NewType` aliases.
_ = uuid


__all__ = ["CoordinationPolicyEvaluationRequest"]
