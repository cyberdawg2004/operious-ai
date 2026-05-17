"""In-memory `CoordinationTopologyPersistenceProtocol` implementation.

Reference implementation for tests and development. Honours every
persistence protocol guarantee:

* write-once per ``evaluation_id``,
* deterministic ``(runtime_instance_id, sequence)`` ordering for
  queries,
* `dict[str, record]` storage; tuple snapshots are returned to
  callers so external mutation cannot affect stored state.
"""

from __future__ import annotations

import asyncio

from app.coordination.topology.exceptions import (
    CoordinationTopologyPersistenceError,
)
from app.coordination.topology.persistence.models import (
    CoordinationTopologyQuery,
    RecordPage,
)
from app.coordination.topology.persistence.records import (
    CoordinationTopologyRecord,
)
from app.coordination.topology.persistence.repository import (
    CoordinationTopologyPersistenceProtocol,
)


class InMemoryCoordinationTopologyPersistence(
    CoordinationTopologyPersistenceProtocol
):
    """Deterministic in-memory store of `CoordinationTopologyRecord`s."""

    def __init__(self) -> None:
        self._records: dict[str, CoordinationTopologyRecord] = {}
        self._lock = asyncio.Lock()

    async def record_evaluation(
        self, record: CoordinationTopologyRecord
    ) -> None:
        async with self._lock:
            if record.evaluation_id in self._records:
                raise CoordinationTopologyPersistenceError(
                    f"evaluation_id already recorded: "
                    f"{record.evaluation_id!r}"
                )
            self._records[record.evaluation_id] = record

    async def get_evaluation(
        self, evaluation_id: str
    ) -> CoordinationTopologyRecord | None:
        return self._records.get(evaluation_id)

    async def query_evaluations(
        self, query: CoordinationTopologyQuery
    ) -> RecordPage[CoordinationTopologyRecord]:
        candidates = [
            r
            for r in self._records.values()
            if self._matches(r, query)
        ]
        candidates.sort(
            key=lambda r: (r.runtime_instance_id, r.sequence)
        )
        total = len(candidates)
        if query.offset:
            candidates = candidates[query.offset :]
        if query.limit > 0:
            candidates = candidates[: query.limit]
        return RecordPage(
            items=tuple(candidates),
            total=total,
            offset=query.offset,
        )

    # ─── Internals ───────────────────────────────────────────────────

    def _matches(
        self,
        record: CoordinationTopologyRecord,
        query: CoordinationTopologyQuery,
    ) -> bool:
        checks: list[tuple[str | None, str | None]] = [
            (query.evaluation_id, record.evaluation_id),
            (query.chain_id, record.chain_id),
            (query.topology_id, record.topology_id),
            (query.coordination_id, record.coordination_id),
            (
                query.coordination_message_id,
                record.coordination_message_id,
            ),
            (query.sender_id, record.sender_id),
            (query.recipient_id, record.recipient_id),
            (query.correlation_id, record.correlation_id),
            (
                query.parent_coordination_id,
                record.parent_coordination_id,
            ),
            (query.request_id, record.request_id),
            (query.tenant_id, record.tenant_id),
            (query.runtime_instance_id, record.runtime_instance_id),
            (query.direction, record.direction),
            (query.message_type, record.message_type),
            (query.aggregate_decision, record.aggregate_decision),
        ]
        return all(expected is None or expected == actual for expected, actual in checks)


__all__ = ["InMemoryCoordinationTopologyPersistence"]
