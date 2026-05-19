"""Storage-agnostic coordination repository contract.

`CoordinationPersistenceProtocol` is the **single Protocol** every
backend implements. Sprint L1 ships:

* the Protocol itself,
* `InMemoryCoordinationPersistence` — the reference implementation.

Future sprints add Postgres / Elasticsearch / S3 backends behind the
same Protocol. The runtime substrate is untouched.

Three method groups:

* `record` — durable write (write-once; records are immutable),
* `get`    — point reads by primary identity,
* `query`  — paginated reads sorted by
              `(runtime_instance_id, sequence)`.

Async throughout — every storage backend the platform integrates
with is async-friendly.

Forbidden by architectural rule:

* NO event sourcing.
* NO distributed queues.
* NO brokers.
* NO pub/sub fan-out.

The Protocol surface deliberately exposes only the two operations
the substrate needs (persist + query). Anything else is the
orchestration layer's concern.
"""

from __future__ import annotations

from typing import Protocol

from app.coordination.persistence.models import (
    CoordinationQuery,
    RecordPage,
)
from app.coordination.persistence.records import CoordinationRecord


class CoordinationPersistenceProtocol(Protocol):
    """Storage-agnostic contract for coordination persistence."""

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_envelope(self, record: CoordinationRecord) -> None:
        """Persist a coordination record. Records are write-once.

        Implementations MUST raise `CoordinationPersistenceError` on:

        * duplicate `coordination_id` (write-once contract),
        * backend I/O failure.
        """
        ...

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_envelope(
        self,
        coordination_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> CoordinationRecord | None:
        """Return the record for `coordination_id`, or ``None``.

        Wedge 2.75-ε: when ``expected_tenant_id`` is supplied,
        envelopes belonging to a different tenant return ``None``
        (row-level isolation indistinguishable from absence).
        """
        ...

    async def query_envelopes(
        self, query: CoordinationQuery
    ) -> RecordPage[CoordinationRecord]:
        """Paginated lookup.

        Results MUST be sorted by ``(runtime_instance_id, sequence)``
        ascending so callers can stream in deterministic order.
        """
        ...


__all__ = ["CoordinationPersistenceProtocol"]
