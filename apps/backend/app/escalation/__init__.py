"""Escalation substrate public surface."""

from app.escalation.enums import EscalationOutboxStatus, EscalationStatus
from app.escalation.exceptions import (
    EscalationError,
    EscalationNotFoundError,
    EscalationPersistenceError,
    EscalationResolutionError,
    EscalationRuntimeError,
)
from app.escalation.identity import (
    EscalationId,
    EscalationOutboxId,
    as_escalation_id,
    as_escalation_outbox_id,
    derive_escalation_event_id,
    derive_escalation_id,
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

__all__ = [
    "EscalationAgentRuntime",
    "EscalationError",
    "EscalationId",
    "EscalationNotFoundError",
    "EscalationOutboxId",
    "EscalationOutboxPage",
    "EscalationOutboxQuery",
    "EscalationOutboxRecord",
    "EscalationOutboxStatus",
    "EscalationPage",
    "EscalationPersistenceError",
    "EscalationPersistenceProtocol",
    "EscalationPublisher",
    "EscalationQuery",
    "EscalationRecord",
    "EscalationResolutionError",
    "EscalationRuntimeError",
    "EscalationStatus",
    "InMemoryEscalationPersistence",
    "as_escalation_id",
    "as_escalation_outbox_id",
    "derive_escalation_event_id",
    "derive_escalation_id",
    "derive_escalation_override_action_id",
    "derive_escalation_override_decision_id",
    "derive_escalation_outbox_id",
]
