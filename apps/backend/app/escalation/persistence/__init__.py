"""Escalation persistence public surface."""

from app.escalation.persistence.memory import InMemoryEscalationPersistence
from app.escalation.persistence.models import EscalationPage, EscalationQuery
from app.escalation.persistence.postgres import PostgresEscalationPersistence
from app.escalation.persistence.records import EscalationRecord
from app.escalation.persistence.repository import EscalationPersistenceProtocol

__all__ = [
    "EscalationPage",
    "EscalationPersistenceProtocol",
    "EscalationQuery",
    "EscalationRecord",
    "InMemoryEscalationPersistence",
    "PostgresEscalationPersistence",
]
