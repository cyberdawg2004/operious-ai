"""In-memory reference repository for the supervisor.

Used by tests and dev environments. Same Protocol contract as any
future production backend. Deterministic insertion-order iteration
within each inspection_id bucket; deterministic filter ordering on
queries.

Not thread-safe — the substrate is async-coroutine-friendly, and this
in-memory store is single-event-loop by design.
"""

from __future__ import annotations

from app.supervisor.exceptions import SupervisorPersistenceError
from app.supervisor.persistence.models import InspectionQuery, RecordPage
from app.supervisor.persistence.records import (
    EscalationDecisionRecord,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
)


class InMemorySupervisorRepository:
    """Reference repository — in-memory, deterministic, no I/O."""

    def __init__(self) -> None:
        self._inspections: dict[str, InspectionRecord] = {}
        self._findings: dict[str, list[RuntimeFindingRecord]] = {}
        # finding_id → inspection_id (so we can answer queries-by-finding).
        self._finding_index: dict[str, str] = {}
        self._evaluations: dict[str, list[QAEvaluationRecord]] = {}
        self._escalations: dict[str, list[EscalationDecisionRecord]] = {}

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_inspection(self, record: InspectionRecord) -> None:
        if record.inspection_id in self._inspections:
            raise SupervisorPersistenceError(
                f"inspection {record.inspection_id!r} already recorded; "
                "records are write-once"
            )
        self._inspections[record.inspection_id] = record

    async def record_finding(self, record: RuntimeFindingRecord) -> None:
        if record.finding_id in self._finding_index:
            raise SupervisorPersistenceError(
                f"finding {record.finding_id!r} already recorded; "
                "records are write-once"
            )
        inspection_id = _require_inspection_id(record.metadata)
        bucket = self._findings.setdefault(inspection_id, [])
        bucket.append(record)
        self._finding_index[record.finding_id] = inspection_id

    async def record_evaluation(self, record: QAEvaluationRecord) -> None:
        bucket = self._evaluations.setdefault(record.inspection_id, [])
        for existing in bucket:
            if existing.evaluator_name == record.evaluator_name:
                raise SupervisorPersistenceError(
                    f"evaluation for inspection {record.inspection_id!r} / "
                    f"evaluator {record.evaluator_name!r} already recorded"
                )
        bucket.append(record)

    async def record_escalation(
        self, record: EscalationDecisionRecord
    ) -> None:
        bucket = self._escalations.setdefault(record.inspection_id, [])
        for existing in bucket:
            if existing.escalation_id == record.escalation_id:
                raise SupervisorPersistenceError(
                    f"escalation {record.escalation_id!r} already recorded"
                )
        bucket.append(record)

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> InspectionRecord | None:
        record = self._inspections.get(inspection_id)
        if record is None:
            return None
        # 2.75-ε: tenant-scoped row-level isolation.
        if (
            expected_tenant_id is not None
            and record.tenant_id != expected_tenant_id
        ):
            return None
        return record

    async def get_findings_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[RuntimeFindingRecord, ...]:
        # 2.75-ε: tenant scope inherits from the parent inspection.
        if expected_tenant_id is not None:
            parent = self._inspections.get(inspection_id)
            if (
                parent is None
                or parent.tenant_id != expected_tenant_id
            ):
                return ()
        return tuple(self._findings.get(inspection_id, ()))

    async def get_evaluations_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[QAEvaluationRecord, ...]:
        if expected_tenant_id is not None:
            parent = self._inspections.get(inspection_id)
            if (
                parent is None
                or parent.tenant_id != expected_tenant_id
            ):
                return ()
        return tuple(self._evaluations.get(inspection_id, ()))

    async def get_escalations_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[EscalationDecisionRecord, ...]:
        if expected_tenant_id is not None:
            parent = self._inspections.get(inspection_id)
            if (
                parent is None
                or parent.tenant_id != expected_tenant_id
            ):
                return ()
        return tuple(self._escalations.get(inspection_id, ()))

    # ─── Queries ─────────────────────────────────────────────────────

    async def query_inspections(
        self, query: InspectionQuery
    ) -> RecordPage[InspectionRecord]:
        matches = [
            r for r in self._inspections.values() if _matches(r, query)
        ]
        matches.sort(key=lambda r: r.started_at)
        page = matches[query.offset : query.offset + query.limit]
        return RecordPage(items=tuple(page), total=len(matches), offset=query.offset)


def _require_inspection_id(metadata: object) -> str:
    """Findings carry their parent `inspection_id` in metadata under the
    canonical `"inspection_id"` key. The in-memory repo enforces this
    so it can answer `get_findings_for_inspection`. Production backends
    typically store the relationship as a column.
    """
    if isinstance(metadata, dict) and "inspection_id" in metadata:
        return str(metadata["inspection_id"])
    raise SupervisorPersistenceError(
        "RuntimeFindingRecord.metadata must carry an 'inspection_id' key "
        "when persisted via the in-memory repository"
    )


def _matches(record: InspectionRecord, query: InspectionQuery) -> bool:
    if query.inspection_id is not None and record.inspection_id != query.inspection_id:
        return False
    if query.execution_id is not None and record.execution_id != query.execution_id:
        return False
    if query.correlation_id is not None and record.correlation_id != query.correlation_id:
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
    if query.decision_kind is not None and record.decision.kind != query.decision_kind:
        return False
    if (
        query.inspection_mode is not None
        and record.inspection_mode != query.inspection_mode
    ):
        return False
    return True


__all__ = ["InMemorySupervisorRepository"]
