"""Coordination topology persistence — contracts and in-memory impl.

Sprint L3 ships:

* `records`     — persistable record shapes,
* `models`      — `CoordinationTopologyQuery`, `RecordPage`,
* `repository`  — `CoordinationTopologyPersistenceProtocol`,
* `memory`      — `InMemoryCoordinationTopologyPersistence`,
* `serializers` — pure result → records converters.

NO event sourcing. NO distributed queues. NO brokers. Contracts +
deterministic reference impl only.
"""

from app.coordination.topology.persistence.memory import (
    InMemoryCoordinationTopologyPersistence,
)
from app.coordination.topology.persistence.models import (
    CoordinationTopologyQuery,
    RecordPage,
)
from app.coordination.topology.persistence.records import (
    CoordinationTopologyFindingRecord,
    CoordinationTopologyRecord,
)
from app.coordination.topology.persistence.repository import (
    CoordinationTopologyPersistenceProtocol,
)
from app.coordination.topology.persistence.serializers import (
    envelope_to_record,
    result_to_record,
)

__all__ = [
    "CoordinationTopologyRecord",
    "CoordinationTopologyFindingRecord",
    "CoordinationTopologyQuery",
    "RecordPage",
    "CoordinationTopologyPersistenceProtocol",
    "InMemoryCoordinationTopologyPersistence",
    "envelope_to_record",
    "result_to_record",
]
