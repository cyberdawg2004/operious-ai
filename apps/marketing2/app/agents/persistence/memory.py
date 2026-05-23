"""In-memory reference repository for the agent runtime.

Used by tests and dev environments. Same Protocol contract as any
future production backend. Deterministic insertion-order iteration
for tests; deterministic filter ordering for replay.

Not thread-safe — the substrate is async-coroutine-friendly, and this
in-memory store is single-event-loop by design. Production backends
handle concurrency at the storage layer.
"""

from __future__ import annotations

from app.agents.persistence.models import ExecutionQuery, RecordPage
from app.agents.persistence.records import (
    AgentExecutionRecord,
    ToolInvocationRecord,
)


class InMemoryAgentRepository:
    """Reference repository — in-memory, deterministic, no I/O."""

    def __init__(self) -> None:
        self._executions: dict[str, AgentExecutionRecord] = {}
        self._tool_invocations: dict[str, list[ToolInvocationRecord]] = {}

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_execution(self, record: AgentExecutionRecord) -> None:
        if record.execution_id in self._executions:
            raise ValueError(
                f"execution {record.execution_id!r} already recorded; "
                "records are write-once"
            )
        self._executions[record.execution_id] = record

    async def record_tool_invocation(
        self, record: ToolInvocationRecord
    ) -> None:
        bucket = self._tool_invocations.setdefault(record.execution_id, [])
        if any(r.invocation_id == record.invocation_id for r in bucket):
            raise ValueError(
                f"tool invocation {record.invocation_id!r} already recorded"
            )
        bucket.append(record)

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_execution(
        self, execution_id: str
    ) -> AgentExecutionRecord | None:
        return self._executions.get(execution_id)

    async def get_tool_invocations(
        self, execution_id: str
    ) -> tuple[ToolInvocationRecord, ...]:
        return tuple(self._tool_invocations.get(execution_id, ()))

    # ─── Queries ─────────────────────────────────────────────────────

    async def query_executions(
        self, query: ExecutionQuery
    ) -> RecordPage[AgentExecutionRecord]:
        matches = [
            r for r in self._executions.values() if _matches_execution(r, query)
        ]
        matches.sort(key=lambda r: r.started_at)
        page = matches[query.offset : query.offset + query.limit]
        return RecordPage(
            items=tuple(page), total=len(matches), offset=query.offset
        )

    async def get_children(
        self, parent_execution_id: str
    ) -> tuple[AgentExecutionRecord, ...]:
        children = [
            r
            for r in self._executions.values()
            if r.parent_execution_id == parent_execution_id
        ]
        children.sort(key=lambda r: r.started_at)
        return tuple(children)


# ─── Filter helpers (pure) ───────────────────────────────────────────


def _matches_execution(
    record: AgentExecutionRecord, query: ExecutionQuery
) -> bool:
    if query.execution_id is not None and record.execution_id != query.execution_id:
        return False
    if query.correlation_id is not None and record.correlation_id != query.correlation_id:
        return False
    if query.request_id is not None and record.request_id != query.request_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.agent_id is not None and record.agent_id != query.agent_id:
        return False
    if query.parent_execution_id is not None and record.parent_execution_id != query.parent_execution_id:
        return False
    if query.final_state is not None and record.final_state != query.final_state:
        return False
    if query.runtime_instance_id is not None and record.runtime_instance_id != query.runtime_instance_id:
        return False
    return True


__all__ = ["InMemoryAgentRepository"]
