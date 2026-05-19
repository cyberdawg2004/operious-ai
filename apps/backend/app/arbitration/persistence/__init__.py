"""Arbitration persistence — storage-agnostic contracts.

* `records`      — `ArbitrationRecord`, `ArbitrationFindingRecord`,
                    `ArbitrationConflictRecord`,
                    `ArbitrationDeadlockRecord`.
* `models`       — `ArbitrationQuery`, `RecordPage`.
* `repository`   — `ArbitrationPersistenceProtocol`.
* `serializers`  — `result_to_record`, `envelope_to_record`.
* `memory`       — `InMemoryArbitrationPersistence`.
"""

from app.arbitration.persistence.memory import (
    InMemoryArbitrationPersistence,
)
from app.arbitration.persistence.models import (
    ArbitrationQuery,
    RecordPage,
)
from app.arbitration.persistence.postgres import (
    PostgresArbitrationPersistence,
)
from app.arbitration.persistence.records import (
    ArbitrationConflictRecord,
    ArbitrationDeadlockRecord,
    ArbitrationFindingRecord,
    ArbitrationRecord,
)
from app.arbitration.persistence.repository import (
    ArbitrationPersistenceProtocol,
)
from app.arbitration.persistence.serializers import (
    envelope_to_record,
    result_to_record,
)

__all__ = [
    "ArbitrationConflictRecord",
    "ArbitrationDeadlockRecord",
    "ArbitrationFindingRecord",
    "ArbitrationPersistenceProtocol",
    "ArbitrationQuery",
    "ArbitrationRecord",
    "InMemoryArbitrationPersistence",
    "PostgresArbitrationPersistence",
    "RecordPage",
    "envelope_to_record",
    "result_to_record",
]
