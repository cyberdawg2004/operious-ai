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
        self,
        decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> GovernanceDecisionRecord | None:
        """Fetch one decision by id, or ``None``.

        PR-B2 (M8 closure): when ``expected_tenant_id`` is supplied,
        decisions belonging to a different tenant MUST return
        ``None`` — the persisted row exists but is invisible from
        the requesting tenant's perspective (row-level isolation,
        mirroring the contract every sibling-substrate point read
        already honours per
        ``docs/governance/tenant-scoped-persistence.md``). ``None``
        is also returned for the regular "not found" case, so
        callers cannot distinguish "absent" from "another tenant's
        row" — that distinction would leak existence across tenants.

        Governance decisions MAY legitimately be ``tenant_id is
        None`` (system-level / tenantless decisions); when the
        stored ``tenant_id`` is ``None`` it is **never visible**
        through a tenant-scoped read (``expected_tenant_id !=
        None``) and is only visible when the caller passes
        ``expected_tenant_id=None`` (substrate-internal /
        admin paths).
        """
        ...

    async def get_trace(
        self,
        decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> GovernanceTraceRecord | None:
        """Fetch the trace for one decision by ``decision_id``.

        Same tenant-scoping contract as :meth:`get_decision`.
        Tenant scope is enforced on the trace record's own
        ``tenant_id`` column (no parent-record join).
        """
        ...

    async def get_enforcement_actions(
        self,
        decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[EnforcementActionRecord, ...]:
        """Fetch every enforcement action for one decision.

        Tenant scope resolves through the owning
        :class:`GovernanceDecisionRecord` — an action is visible
        from tenant ``T`` iff the decision it belongs to is owned
        by ``T`` (or ``expected_tenant_id is None``). Mirrors the
        ``session.get_event`` / ``supervisor.get_findings_for_inspection``
        sub-record patterns: tenant scope inherits from the apex
        record so sub-record columns don't have to duplicate
        ``tenant_id`` and risk drift between sub-record and apex.
        """
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
