"""Storage-agnostic agent runtime repository contract.

`BaseAgentRepository` is the **single Protocol** every backend
implements. Sprint J ships:

* the Protocol itself,
* `InMemoryAgentRepository` — the reference implementation.

Future sprints add Postgres / Elasticsearch / S3 backends behind the
same Protocol. The substrate is untouched.

Three method groups:

* `record_*` — durable writes (write-once; records are immutable),
* `get_*`    — point reads by primary identity,
* `query_*`  — paginated reads by `ExecutionQuery`.

Async throughout — every storage backend the platform integrates
with is async-friendly.
"""

from __future__ import annotations

from typing import Protocol

from app.agents.persistence.models import ExecutionQuery, RecordPage
from app.agents.persistence.records import (
    AgentExecutionRecord,
    ToolInvocationRecord,
)


class BaseAgentRepository(Protocol):
    """Storage-agnostic contract for agent runtime persistence."""

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_execution(self, record: AgentExecutionRecord) -> None:
        """Persist an execution record. Records are write-once."""
        ...

    async def record_tool_invocation(
        self, record: ToolInvocationRecord
    ) -> None:
        """Persist a tool invocation record. Write-once."""
        ...

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_execution(
        self, execution_id: str
    ) -> AgentExecutionRecord | None:
        """Fetch one execution by id, or None."""
        ...

    async def get_tool_invocations(
        self, execution_id: str
    ) -> tuple[ToolInvocationRecord, ...]:
        """Fetch every tool invocation under one execution, in
        invocation order."""
        ...

    # ─── Queries ─────────────────────────────────────────────────────

    async def query_executions(
        self, query: ExecutionQuery
    ) -> RecordPage[AgentExecutionRecord]:
        """Paginated execution lookup."""
        ...

    async def get_children(
        self, parent_execution_id: str
    ) -> tuple[AgentExecutionRecord, ...]:
        """Fetch every direct child execution of a parent.

        Causality reads — sorted by started_at for deterministic
        traversal.
        """
        ...


__all__ = ["BaseAgentRepository"]
