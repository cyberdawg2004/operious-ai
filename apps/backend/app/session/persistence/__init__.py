"""Session persistence — storage-agnostic contracts."""

from app.session.persistence.memory import (
    InMemorySessionPersistence,
)
from app.session.persistence.models import (
    SessionCorrelationQuery,
    SessionEventQuery,
    SessionQuery,
    SessionRecordPage,
)
from app.session.persistence.postgres import (
    PostgresSessionPersistence,
)
from app.session.persistence.records import (
    SessionCorrelationRecord,
    SessionEventRecord,
    SessionRecord,
)
from app.session.persistence.repository import (
    SessionPersistenceProtocol,
)
from app.session.persistence.serializers import (
    correlation_record_to_model,
    event_record_to_model,
    event_to_record,
    record_to_session,
    session_to_record,
)

__all__ = [
    "InMemorySessionPersistence",
    "PostgresSessionPersistence",
    "SessionCorrelationQuery",
    "SessionCorrelationRecord",
    "SessionEventQuery",
    "SessionEventRecord",
    "SessionPersistenceProtocol",
    "SessionQuery",
    "SessionRecord",
    "SessionRecordPage",
    "correlation_record_to_model",
    "event_record_to_model",
    "event_to_record",
    "record_to_session",
    "session_to_record",
]
