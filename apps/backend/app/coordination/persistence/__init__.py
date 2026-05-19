"""Coordination persistence — contracts and in-memory reference impl.

Sprint L1 ships:

* `records`     — persistable record shapes (frozen + slots,
                   `to_dict` / `from_dict`),
* `models`      — `CoordinationQuery`, `RecordPage`,
* `repository`  — `CoordinationPersistenceProtocol` (storage-agnostic
                   contract),
* `memory`      — `InMemoryCoordinationPersistence` (reference impl),
* `serializers` — pure envelope ↔ record converters.

NO event sourcing. NO distributed queues. NO brokers. Sprint L1 is
contracts + a deterministic reference implementation; future
sprints add Postgres / Elasticsearch backends behind the same
Protocol. No DB migrations are introduced.
"""

from app.coordination.persistence.memory import (
    InMemoryCoordinationPersistence,
)
from app.coordination.persistence.models import (
    CoordinationQuery,
    RecordPage,
)
from app.coordination.persistence.postgres import (
    PostgresCoordinationPersistence,
)
from app.coordination.persistence.records import (
    CoordinationRecord,
)
from app.coordination.persistence.repository import (
    CoordinationPersistenceProtocol,
)
from app.coordination.persistence.serializers import (
    envelope_to_record,
    record_to_envelope,
)

__all__ = [
    "CoordinationRecord",
    "CoordinationPersistenceProtocol",
    "InMemoryCoordinationPersistence",
    "PostgresCoordinationPersistence",
    "CoordinationQuery",
    "RecordPage",
    "envelope_to_record",
    "record_to_envelope",
]
