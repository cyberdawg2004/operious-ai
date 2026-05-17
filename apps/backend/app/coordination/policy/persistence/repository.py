"""Storage-agnostic coordination-policy repository contract.

`CoordinationPolicyPersistenceProtocol` is the single contract every
backend implements. Sprint L2 ships the Protocol + an in-memory
reference impl.

Three method groups:

* `record_evaluation` — durable write-once persist,
* `get_evaluation`   — point read by `evaluation_id`,
* `query_evaluations`— paginated read, sorted by
                        ``(runtime_instance_id, sequence)``.

Forbidden by architectural rule:

* NO event sourcing,
* NO distributed queues,
* NO brokers,
* NO pub/sub fan-out.

The Protocol surface deliberately exposes only the operations the
substrate needs (persist + read). Anything else is the orchestration
layer's concern.
"""

from __future__ import annotations

from typing import Protocol

from app.coordination.policy.persistence.models import (
    CoordinationPolicyQuery,
    RecordPage,
)
from app.coordination.policy.persistence.records import (
    CoordinationPolicyRecord,
)


class CoordinationPolicyPersistenceProtocol(Protocol):
    """Storage-agnostic contract for coordination-policy persistence."""

    async def record_evaluation(
        self, record: CoordinationPolicyRecord
    ) -> None:
        """Persist a record. Records are write-once.

        Implementations MUST raise
        `CoordinationPolicyPersistenceError` on:

        * duplicate `evaluation_id`,
        * backend I/O failure.
        """
        ...

    async def get_evaluation(
        self, evaluation_id: str
    ) -> CoordinationPolicyRecord | None:
        """Return the record for `evaluation_id`, or ``None``."""
        ...

    async def query_evaluations(
        self, query: CoordinationPolicyQuery
    ) -> RecordPage[CoordinationPolicyRecord]:
        """Paginated lookup ordered by
        ``(runtime_instance_id, sequence)`` ascending.
        """
        ...


__all__ = ["CoordinationPolicyPersistenceProtocol"]
