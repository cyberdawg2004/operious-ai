"""Storage-agnostic supervisor repository contract.

`BaseSupervisorRepository` is the **single Protocol** every backend
implements. Sprint K ships:

* the Protocol itself,
* `InMemorySupervisorRepository` — the reference implementation.

Future sprints add Postgres / Elasticsearch / S3 backends behind the
same Protocol. The runtime substrate is untouched.

Three method groups:

* `record_*` — durable writes (write-once; records are immutable),
* `get_*`    — point reads by primary identity,
* `query_*`  — paginated reads.

Async throughout — every storage backend the platform integrates
with is async-friendly.
"""

from __future__ import annotations

from typing import Protocol

from app.supervisor.persistence.models import InspectionQuery, RecordPage
from app.supervisor.persistence.records import (
    EscalationDecisionRecord,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
)


class BaseSupervisorRepository(Protocol):
    """Storage-agnostic contract for supervisor persistence."""

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_inspection(self, record: InspectionRecord) -> None:
        """Persist an inspection record. Records are write-once."""
        ...

    async def record_finding(self, record: RuntimeFindingRecord) -> None:
        """Persist a finding record. Write-once."""
        ...

    async def record_evaluation(self, record: QAEvaluationRecord) -> None:
        """Persist a per-evaluator record. Write-once."""
        ...

    async def record_escalation(
        self, record: EscalationDecisionRecord
    ) -> None:
        """Persist an escalation record. Write-once."""
        ...

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> InspectionRecord | None:
        """Point read by inspection_id.

        Wedge 2.75-ε: when ``expected_tenant_id`` is supplied,
        inspections belonging to a different tenant return
        ``None`` (row-level isolation).
        """
        ...

    async def get_findings_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[RuntimeFindingRecord, ...]:
        """Findings belonging to ``inspection_id``.

        Tenant scope resolved via the owning :class:`InspectionRecord`:
        if the parent inspection is invisible from the requesting
        tenant, the findings collection is empty.
        """
        ...

    async def get_evaluations_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[QAEvaluationRecord, ...]:
        """Evaluations belonging to ``inspection_id``.

        Tenant scope resolved via the owning inspection.
        """
        ...

    async def get_escalations_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[EscalationDecisionRecord, ...]:
        """Escalations belonging to ``inspection_id``.

        Tenant scope resolved via the owning inspection.
        """
        ...

    # ─── Queries ─────────────────────────────────────────────────────

    async def query_inspections(
        self,
        query: InspectionQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> RecordPage[InspectionRecord]:
        """Paginated inspection lookup.

        Wedge 2.75-ε (extended): when ``expected_tenant_id`` is
        supplied, results are clamped to that tenant before the
        caller's ``query.tenant_id`` filter is applied. Cross-
        tenant rows cannot leak through this surface.
        """
        ...


__all__ = ["BaseSupervisorRepository"]
