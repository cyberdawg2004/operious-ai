"""Coordination policy persistence — contracts and in-memory reference impl.

Sprint L2 ships:

* `records`     — persistable record shapes,
* `models`      — `CoordinationPolicyQuery`, `RecordPage`,
* `repository`  — `CoordinationPolicyPersistenceProtocol`,
* `memory`      — `InMemoryCoordinationPolicyPersistence` (reference),
* `serializers` — pure result/envelope → records converters.

NO event sourcing. NO distributed queues. NO brokers. Contracts +
deterministic reference impl only.
"""

from app.coordination.policy.persistence.memory import (
    InMemoryCoordinationPolicyPersistence,
)
from app.coordination.policy.persistence.models import (
    CoordinationPolicyQuery,
    RecordPage,
)
from app.coordination.policy.persistence.records import (
    CoordinationPolicyEscalationRecord,
    CoordinationPolicyFindingRecord,
    CoordinationPolicyRecord,
    CoordinationPolicyRestrictionRecord,
)
from app.coordination.policy.persistence.repository import (
    CoordinationPolicyPersistenceProtocol,
)
from app.coordination.policy.persistence.serializers import (
    envelope_to_record,
    result_to_record,
)

__all__ = [
    "CoordinationPolicyRecord",
    "CoordinationPolicyFindingRecord",
    "CoordinationPolicyRestrictionRecord",
    "CoordinationPolicyEscalationRecord",
    "CoordinationPolicyQuery",
    "RecordPage",
    "CoordinationPolicyPersistenceProtocol",
    "InMemoryCoordinationPolicyPersistence",
    "envelope_to_record",
    "result_to_record",
]
