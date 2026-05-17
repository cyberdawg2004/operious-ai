"""In-memory reference persistence for the coordination-policy substrate.

Same Protocol contract as any future production backend.
Deterministic insertion-order ordering within filter results;
ordering is `(runtime_instance_id, sequence)` ascending.

Not thread-safe — the substrate is async-coroutine-friendly and the
in-memory store is single-event-loop by design.
"""

from __future__ import annotations

from app.coordination.policy.exceptions import (
    CoordinationPolicyPersistenceError,
)
from app.coordination.policy.persistence.models import (
    CoordinationPolicyQuery,
    RecordPage,
)
from app.coordination.policy.persistence.records import (
    CoordinationPolicyRecord,
)


class InMemoryCoordinationPolicyPersistence:
    """Reference repository — in-memory, deterministic, no I/O."""

    def __init__(self) -> None:
        self._records: dict[str, CoordinationPolicyRecord] = {}

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_evaluation(
        self, record: CoordinationPolicyRecord
    ) -> None:
        if record.evaluation_id in self._records:
            raise CoordinationPolicyPersistenceError(
                f"evaluation_id {record.evaluation_id!r} already "
                f"recorded; records are write-once"
            )
        self._records[record.evaluation_id] = record

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_evaluation(
        self, evaluation_id: str
    ) -> CoordinationPolicyRecord | None:
        return self._records.get(evaluation_id)

    async def query_evaluations(
        self, query: CoordinationPolicyQuery
    ) -> RecordPage[CoordinationPolicyRecord]:
        matches = [
            r for r in self._records.values() if _matches(r, query)
        ]
        matches.sort(key=lambda r: (r.runtime_instance_id, r.sequence))
        page = matches[query.offset : query.offset + query.limit]
        return RecordPage(
            items=tuple(page), total=len(matches), offset=query.offset
        )


def _matches(
    record: CoordinationPolicyRecord,
    query: CoordinationPolicyQuery,
) -> bool:
    if (
        query.evaluation_id is not None
        and record.evaluation_id != query.evaluation_id
    ):
        return False
    if query.chain_id is not None and record.chain_id != query.chain_id:
        return False
    if (
        query.coordination_id is not None
        and record.coordination_id != query.coordination_id
    ):
        return False
    if (
        query.coordination_message_id is not None
        and record.coordination_message_id != query.coordination_message_id
    ):
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
    if (
        query.request_id is not None
        and record.request_id != query.request_id
    ):
        return False
    if (
        query.tenant_id is not None
        and record.tenant_id != query.tenant_id
    ):
        return False
    if (
        query.runtime_instance_id is not None
        and record.runtime_instance_id != query.runtime_instance_id
    ):
        return False
    if (
        query.direction is not None
        and record.direction != query.direction
    ):
        return False
    if (
        query.message_type is not None
        and record.message_type != query.message_type
    ):
        return False
    if (
        query.aggregate_decision is not None
        and record.aggregate_decision != query.aggregate_decision
    ):
        return False
    return True


__all__ = ["InMemoryCoordinationPolicyPersistence"]
