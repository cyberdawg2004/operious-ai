"""Escalation substrate public surface."""

from app.escalation.enums import (
    EscalationHandoffKind,
    EscalationOutboxStatus,
    EscalationPriority,
    EscalationStatus,
)
from app.escalation.exceptions import (
    EscalationError,
    EscalationNotFoundError,
    EscalationPersistenceError,
    EscalationResolutionError,
    EscalationRuntimeError,
)
from app.escalation.identity import (
    EscalationId,
    EscalationOutboxClaimId,
    EscalationOutboxId,
    as_escalation_id,
    as_escalation_outbox_claim_id,
    as_escalation_outbox_id,
    derive_escalation_event_id,
    derive_escalation_id,
    derive_escalation_outbox_claim_id,
    derive_escalation_override_action_id,
    derive_escalation_override_decision_id,
    derive_escalation_outbox_id,
)
from app.escalation.persistence import (
    EscalationOutboxPage,
    EscalationOutboxQuery,
    EscalationOutboxRecord,
    EscalationPage,
    EscalationPersistenceProtocol,
    EscalationQuery,
    EscalationRecord,
    InMemoryEscalationPersistence,
)
from app.escalation.publisher import EscalationPublisher
from app.escalation.runtime import EscalationAgentRuntime
from app.escalation.deferred_publisher import (
    DeferredEscalationPublisher,
    EscalationOutboxPublishError,
)

__all__ = [
    "DeferredEscalationPublisher",
    "EscalationAgentRuntime",
    "EscalationError",
    "EscalationId",
    "EscalationHandoffKind",
    "EscalationNotFoundError",
    "EscalationOutboxClaimId",
    "EscalationOutboxId",
    "EscalationOutboxPublishError",
    "EscalationOutboxPage",
    "EscalationOutboxQuery",
    "EscalationOutboxRecord",
    "EscalationOutboxStatus",
    "EscalationPage",
    "EscalationPersistenceError",
    "EscalationPersistenceProtocol",
    "EscalationPriority",
    "EscalationPublisher",
    "EscalationQuery",
    "EscalationRecord",
    "EscalationResolutionError",
    "EscalationRuntimeError",
    "EscalationStatus",
    "InMemoryEscalationPersistence",
    "as_escalation_id",
    "as_escalation_outbox_claim_id",
    "as_escalation_outbox_id",
    "derive_escalation_event_id",
    "derive_escalation_id",
    "derive_escalation_outbox_claim_id",
    "derive_escalation_override_action_id",
    "derive_escalation_override_decision_id",
    "derive_escalation_outbox_id",
]
