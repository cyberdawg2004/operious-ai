"""In-memory reference repository.

Used by tests and dev environments. Same Protocol contract as any
future production backend. Deterministic insertion-order iteration
for tests; deterministic filter ordering for replay.

Not thread-safe — the substrate is async-coroutine-friendly, and
this in-memory store is single-event-loop by design. Production
backends (Postgres + asyncpg) handle concurrency at the storage
layer.
"""

from __future__ import annotations

from app.governance.persistence.models import DecisionQuery, RecordPage
from app.governance.persistence.records import (
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
)


class InMemoryGovernanceRepository:
    """Reference repository — in-memory, deterministic, no I/O."""

    def __init__(self) -> None:
        self._decisions: dict[str, GovernanceDecisionRecord] = {}
        self._traces: dict[str, GovernanceTraceRecord] = {}
        self._actions: dict[str, list[EnforcementActionRecord]] = {}

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_decision(self, record: GovernanceDecisionRecord) -> None:
        if record.decision_id in self._decisions:
            raise ValueError(
                f"decision {record.decision_id!r} already recorded; "
                "records are write-once"
            )
        self._decisions[record.decision_id] = record

    async def record_trace(self, record: GovernanceTraceRecord) -> None:
        if record.decision_id in self._traces:
            raise ValueError(
                f"trace for decision {record.decision_id!r} already recorded; "
                "records are write-once"
            )
        self._traces[record.decision_id] = record

    async def record_enforcement_action(
        self, record: EnforcementActionRecord
    ) -> None:
        self._actions.setdefault(record.decision_id, []).append(record)

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_decision(
        self, decision_id: str
    ) -> GovernanceDecisionRecord | None:
        return self._decisions.get(decision_id)

    async def get_trace(
        self, decision_id: str
    ) -> GovernanceTraceRecord | None:
        return self._traces.get(decision_id)

    async def get_enforcement_actions(
        self, decision_id: str
    ) -> tuple[EnforcementActionRecord, ...]:
        return tuple(self._actions.get(decision_id, ()))

    # ─── Queries ─────────────────────────────────────────────────────

    async def query_decisions(
        self, query: DecisionQuery
    ) -> RecordPage[GovernanceDecisionRecord]:
        matches = [r for r in self._decisions.values() if _matches_decision(r, query)]
        matches.sort(key=lambda r: r.decided_at)
        page = matches[query.offset : query.offset + query.limit]
        return RecordPage(items=tuple(page), total=len(matches), offset=query.offset)

    async def query_traces(
        self, query: DecisionQuery
    ) -> RecordPage[GovernanceTraceRecord]:
        matches = [t for t in self._traces.values() if _matches_trace(t, query)]
        matches.sort(key=lambda t: t.started_at)
        page = matches[query.offset : query.offset + query.limit]
        return RecordPage(items=tuple(page), total=len(matches), offset=query.offset)


# ─── Filter helpers (pure) ───────────────────────────────────────────


def _matches_decision(
    record: GovernanceDecisionRecord, query: DecisionQuery
) -> bool:
    """2.5-C2: parity with ``_matches_trace``.

    Pre-2.5-C2 this matcher silently ignored ``query.request_id``,
    ``query.tenant_id``, and ``query.subject_kind`` even though
    ``DecisionQuery`` exposed them — multi-tenant audit queries
    leaked rows across tenants. The fix in 2.5-C1 added these fields
    to the record; this matcher now honors them at parity.
    """
    if query.decision_id is not None and record.decision_id != query.decision_id:
        return False
    if query.correlation_id is not None and record.correlation_id != query.correlation_id:
        return False
    if query.request_id is not None and record.request_id != query.request_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.stage is not None and record.stage != query.stage:
        return False
    if query.policy_chain_id is not None and record.policy_chain_id != query.policy_chain_id:
        return False
    if query.subject_kind is not None and record.subject_kind != query.subject_kind:
        return False
    if query.final_decision is not None and record.decision != query.final_decision:
        return False
    return True


def _matches_trace(
    record: GovernanceTraceRecord, query: DecisionQuery
) -> bool:
    if query.decision_id is not None and record.decision_id != query.decision_id:
        return False
    if query.correlation_id is not None and record.correlation_id != query.correlation_id:
        return False
    if query.request_id is not None and record.request_id != query.request_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.stage is not None and record.stage != query.stage:
        return False
    if query.policy_chain_id is not None and record.policy_chain_id != query.policy_chain_id:
        return False
    if query.subject_kind is not None and record.subject_kind != query.subject_kind:
        return False
    if query.final_decision is not None and record.final_decision != query.final_decision:
        return False
    return True


__all__ = ["InMemoryGovernanceRepository"]
