"""In-memory reference persistence for the coordination substrate.

Used by tests and dev environments. Same Protocol contract as any
future production backend.

Determinism:

* Iteration is sorted by ``(runtime_instance_id, sequence)`` ascending
  — the substrate's canonical global ordering.
* Filter predicates apply in the same order as the
  `CoordinationQuery` field declarations.

Not thread-safe — the substrate is async-coroutine-friendly, and
this in-memory store is single-event-loop by design.

NO event-sourcing semantics, NO out-of-band delivery, NO queueing
behaviour: the store is a plain immutable record set keyed by
`coordination_id`.
"""

from __future__ import annotations

from app.coordination.exceptions import CoordinationPersistenceError
from app.coordination.persistence.models import (
    CoordinationQuery,
    RecordPage,
)
from app.coordination.persistence.records import CoordinationRecord


class InMemoryCoordinationPersistence:
    """Reference repository — in-memory, deterministic, no I/O."""

    def __init__(self) -> None:
        self._records: dict[str, CoordinationRecord] = {}

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_envelope(self, record: CoordinationRecord) -> None:
        if record.coordination_id in self._records:
            raise CoordinationPersistenceError(
                f"coordination_id {record.coordination_id!r} already "
                f"recorded; records are write-once"
            )
        self._records[record.coordination_id] = record

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_envelope(
        self, coordination_id: str
    ) -> CoordinationRecord | None:
        return self._records.get(coordination_id)

    async def query_envelopes(
        self, query: CoordinationQuery
    ) -> RecordPage[CoordinationRecord]:
        matches = [r for r in self._records.values() if _matches(r, query)]
        matches.sort(key=lambda r: (r.runtime_instance_id, r.sequence))
        page = matches[query.offset : query.offset + query.limit]
        return RecordPage(
            items=tuple(page), total=len(matches), offset=query.offset
        )


def _matches(record: CoordinationRecord, query: CoordinationQuery) -> bool:
    if (
        query.coordination_id is not None
        and record.coordination_id != query.coordination_id
    ):
        return False
    if query.message_id is not None and record.message_id != query.message_id:
        return False
    if query.sender_id is not None and record.sender_id != query.sender_id:
        return False
    if (
        query.recipient_id is not None
        and record.recipient_id != query.recipient_id
    ):
        return False
    if (
        query.correlation_id is not None
        and record.correlation_id != query.correlation_id
    ):
        return False
    if (
        query.parent_coordination_id is not None
        and record.parent_coordination_id != query.parent_coordination_id
    ):
        return False
    if query.request_id is not None and record.request_id != query.request_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if (
        query.runtime_instance_id is not None
        and record.runtime_instance_id != query.runtime_instance_id
    ):
        return False
    if query.direction is not None and record.direction != query.direction:
        return False
    if (
        query.message_type is not None
        and record.message_type != query.message_type
    ):
        return False
    if query.status is not None and record.status != query.status:
        return False
    return True


__all__ = ["InMemoryCoordinationPersistence"]
