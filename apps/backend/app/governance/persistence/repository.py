"""Storage-agnostic governance repository contract.

`BaseGovernanceRepository` is the **single Protocol** every backend
implements. Sprint I Hardening ships:

* the Protocol itself,
* `InMemoryGovernanceRepository` — the reference implementation.

Future sprints add Postgres / Elasticsearch / S3 backends behind the
same Protocol. The substrate is untouched.

Three method groups:

* `record_*`             — durable writes (write-once; records are
                           immutable),
* `get_*`                — point reads by primary identity,
* `query_*`              — paginated reads by `DecisionQuery`.

Async throughout — every storage backend the platform integrates
with is async-friendly (asyncpg, aiobotocore, etc.).
"""

from __future__ import annotations

from typing import Protocol

from app.governance.persistence.models import DecisionQuery, RecordPage
from app.governance.persistence.records import (
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
)


class BaseGovernanceRepository(Protocol):
    """Storage-agnostic contract for governance persistence."""

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_decision(
        self, record: GovernanceDecisionRecord
    ) -> None:
        """Persist a decision record. Records are write-once."""
        ...

    async def record_trace(
        self, record: GovernanceTraceRecord
    ) -> None:
        """Persist a trace record. Write-once."""
        ...

    async def record_enforcement_action(
        self, record: EnforcementActionRecord
    ) -> None:
        """Persist an enforcement action record. Write-once."""
        ...

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_decision(
        self, decision_id: str
    ) -> GovernanceDecisionRecord | None:
        """Fetch one decision by id, or None."""
        ...

    async def get_trace(
        self, decision_id: str
    ) -> GovernanceTraceRecord | None:
        """Fetch the trace for one decision by `decision_id`."""
        ...

    async def get_enforcement_actions(
        self, decision_id: str
    ) -> tuple[EnforcementActionRecord, ...]:
        """Fetch every enforcement action for one decision."""
        ...

    # ─── Queries ─────────────────────────────────────────────────────

    async def query_decisions(
        self, query: DecisionQuery
    ) -> RecordPage[GovernanceDecisionRecord]:
        """Paginated decision lookup."""
        ...

    async def query_traces(
        self, query: DecisionQuery
    ) -> RecordPage[GovernanceTraceRecord]:
        """Paginated trace lookup."""
        ...


__all__ = ["BaseGovernanceRepository"]
