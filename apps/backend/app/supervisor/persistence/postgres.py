"""Postgres implementation of :class:`BaseSupervisorRepository`.

Behavioural parity with :class:`InMemorySupervisorRepository` —
write-once on every record type, tenant-scoped reads (sub-records
inherit scope from the apex inspection via a parent SELECT),
canonical ``started_at`` ordering on inspections.

Finding rows pull ``inspection_id`` from ``record.metadata`` at
write time, identical to the in-memory contract. The PostgreSQL
column makes this relationship queryable and FK-enforced.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.repositories.base import BaseRepository
from app.supervisor.db.models import (
    SupervisorEscalationRow,
    SupervisorEvaluationRow,
    SupervisorFindingRow,
    SupervisorInspectionRow,
)
from app.supervisor.exceptions import SupervisorPersistenceError
from app.supervisor.persistence.models import (
    InspectionQuery,
    RecordPage,
)
from app.supervisor.persistence.records import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)


class PostgresSupervisorRepository(BaseRepository):
    """Postgres-backed supervisor persistence."""

    # ─── Writes ──────────────────────────────────────────────────────

    async def record_inspection(self, record: InspectionRecord) -> None:
        row = _inspection_record_to_row(record)
        try:
            # SAVEPOINT isolation — see governance repo for doctrine.
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise SupervisorPersistenceError(
                f"inspection {record.inspection_id!r} already recorded; "
                "records are write-once"
            ) from exc

    async def record_finding(self, record: RuntimeFindingRecord) -> None:
        inspection_id = _require_inspection_id(record.metadata)
        row = _finding_record_to_row(record, inspection_id=inspection_id)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise SupervisorPersistenceError(
                f"finding {record.finding_id!r} already recorded; "
                "records are write-once"
            ) from exc

    async def record_evaluation(self, record: QAEvaluationRecord) -> None:
        row = _evaluation_record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise SupervisorPersistenceError(
                f"evaluation for inspection {record.inspection_id!r} / "
                f"evaluator {record.evaluator_name!r} already recorded"
            ) from exc

    async def record_escalation(
        self, record: EscalationDecisionRecord
    ) -> None:
        row = _escalation_record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise SupervisorPersistenceError(
                f"escalation {record.escalation_id!r} already recorded"
            ) from exc

    # ─── Reads ───────────────────────────────────────────────────────

    async def get_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> InspectionRecord | None:
        stmt = select(SupervisorInspectionRow).where(
            SupervisorInspectionRow.inspection_id == UUID(inspection_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(
                SupervisorInspectionRow.tenant_id == expected_tenant_id
            )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _inspection_row_to_record(row)

    async def get_findings_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[RuntimeFindingRecord, ...]:
        if not await self._parent_visible(inspection_id, expected_tenant_id):
            return ()
        stmt = (
            select(SupervisorFindingRow)
            .where(SupervisorFindingRow.inspection_id == UUID(inspection_id))
            .order_by(SupervisorFindingRow.detected_at)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return tuple(_finding_row_to_record(r) for r in rows)

    async def get_evaluations_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[QAEvaluationRecord, ...]:
        if not await self._parent_visible(inspection_id, expected_tenant_id):
            return ()
        stmt = (
            select(SupervisorEvaluationRow)
            .where(
                SupervisorEvaluationRow.inspection_id == UUID(inspection_id)
            )
            .order_by(SupervisorEvaluationRow.evaluator_name)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return tuple(_evaluation_row_to_record(r) for r in rows)

    async def get_escalations_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[EscalationDecisionRecord, ...]:
        if not await self._parent_visible(inspection_id, expected_tenant_id):
            return ()
        stmt = (
            select(SupervisorEscalationRow)
            .where(
                SupervisorEscalationRow.inspection_id == UUID(inspection_id)
            )
            .order_by(SupervisorEscalationRow.decided_at)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return tuple(_escalation_row_to_record(r) for r in rows)

    # ─── Queries ─────────────────────────────────────────────────────

    async def query_inspections(
        self,
        query: InspectionQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> RecordPage[InspectionRecord]:
        stmt = select(SupervisorInspectionRow)
        if expected_tenant_id is not None:
            stmt = stmt.where(
                SupervisorInspectionRow.tenant_id == expected_tenant_id
            )
        stmt = _apply_inspection_filters(stmt, query)
        stmt = stmt.order_by(SupervisorInspectionRow.started_at)
        all_rows = list(
            (await self.session.execute(stmt)).scalars().all()
        )
        total = len(all_rows)
        sliced = all_rows[query.offset : query.offset + query.limit]
        return RecordPage(
            items=tuple(_inspection_row_to_record(r) for r in sliced),
            total=total,
            offset=query.offset,
        )

    # ─── Helpers ─────────────────────────────────────────────────────

    async def _parent_visible(
        self,
        inspection_id: str,
        expected_tenant_id: str | None,
    ) -> bool:
        if expected_tenant_id is None:
            # Admin / substrate-internal path: parent existence
            # alone gates visibility; if there is no parent we still
            # return empty because findings without a parent are
            # forensic noise.
            stmt = select(SupervisorInspectionRow.inspection_id).where(
                SupervisorInspectionRow.inspection_id == UUID(inspection_id)
            )
            return (
                await self.session.execute(stmt)
            ).scalar_one_or_none() is not None
        stmt = select(SupervisorInspectionRow.tenant_id).where(
            SupervisorInspectionRow.inspection_id == UUID(inspection_id)
        )
        owner = (
            await self.session.execute(stmt)
        ).scalar_one_or_none()
        return owner == expected_tenant_id


# ─── Filter composer ────────────────────────────────────────────────────


def _apply_inspection_filters(stmt, query: InspectionQuery):  # type: ignore[no-untyped-def]
    if query.inspection_id is not None:
        stmt = stmt.where(
            SupervisorInspectionRow.inspection_id
            == UUID(query.inspection_id)
        )
    if query.execution_id is not None:
        stmt = stmt.where(
            SupervisorInspectionRow.execution_id
            == UUID(query.execution_id)
        )
    if query.correlation_id is not None:
        stmt = stmt.where(
            SupervisorInspectionRow.correlation_id == query.correlation_id
        )
    if query.request_id is not None:
        stmt = stmt.where(
            SupervisorInspectionRow.request_id == query.request_id
        )
    if query.tenant_id is not None:
        stmt = stmt.where(
            SupervisorInspectionRow.tenant_id == query.tenant_id
        )
    if query.runtime_instance_id is not None:
        stmt = stmt.where(
            SupervisorInspectionRow.runtime_instance_id
            == UUID(query.runtime_instance_id)
        )
    if query.decision_kind is not None:
        stmt = stmt.where(
            SupervisorInspectionRow.decision_kind == query.decision_kind
        )
    if query.inspection_mode is not None:
        stmt = stmt.where(
            SupervisorInspectionRow.inspection_mode == query.inspection_mode
        )
    return stmt


# ─── Record ↔ Row converters ────────────────────────────────────────────


def _inspection_record_to_row(
    record: InspectionRecord,
) -> SupervisorInspectionRow:
    from datetime import datetime

    return SupervisorInspectionRow(
        inspection_id=UUID(record.inspection_id),
        execution_id=UUID(record.execution_id),
        runtime_instance_id=UUID(record.runtime_instance_id),
        correlation_id=record.correlation_id,
        request_id=record.request_id,
        tenant_id=record.tenant_id,
        tenant_authority_source=record.tenant_authority_source,
        inspection_mode=record.inspection_mode,
        decision=record.decision.to_dict(),
        decision_kind=record.decision.kind,
        evaluator_names=list(record.evaluator_names),
        started_at=datetime.fromisoformat(record.started_at),
        ended_at=datetime.fromisoformat(record.ended_at),
        latency_ms=record.latency_ms,
        error=record.error,
        metadata_json=dict(record.metadata),
    )


def _inspection_row_to_record(
    row: SupervisorInspectionRow,
) -> InspectionRecord:
    return InspectionRecord(
        inspection_id=str(row.inspection_id),
        execution_id=str(row.execution_id),
        runtime_instance_id=str(row.runtime_instance_id),
        correlation_id=row.correlation_id,
        request_id=row.request_id,
        tenant_id=row.tenant_id,
        tenant_authority_source=row.tenant_authority_source,
        inspection_mode=row.inspection_mode,
        decision=SupervisorDecisionRecord.from_dict(_as_dict(row.decision)),
        evaluator_names=tuple(_as_list_of_str(row.evaluator_names)),
        started_at=row.started_at.isoformat(),
        ended_at=row.ended_at.isoformat(),
        latency_ms=row.latency_ms,
        error=row.error,
        metadata=dict(_as_dict(row.metadata_json)),
    )


def _finding_record_to_row(
    record: RuntimeFindingRecord, *, inspection_id: str
) -> SupervisorFindingRow:
    from datetime import datetime

    return SupervisorFindingRow(
        finding_id=UUID(record.finding_id),
        inspection_id=UUID(inspection_id),
        evaluator_name=record.evaluator_name,
        category=record.category,
        severity=record.severity,
        code=record.code,
        message=record.message,
        evidence=record.evidence.to_dict(),
        detected_at=datetime.fromisoformat(record.detected_at),
        metadata_json=dict(record.metadata),
    )


def _finding_row_to_record(
    row: SupervisorFindingRow,
) -> RuntimeFindingRecord:
    return RuntimeFindingRecord(
        finding_id=str(row.finding_id),
        evaluator_name=row.evaluator_name,
        category=row.category,
        severity=row.severity,
        code=row.code,
        message=row.message,
        evidence=EvaluationEvidenceRecord.from_dict(_as_dict(row.evidence)),
        detected_at=row.detected_at.isoformat(),
        metadata=dict(_as_dict(row.metadata_json)),
    )


def _evaluation_record_to_row(
    record: QAEvaluationRecord,
) -> SupervisorEvaluationRow:
    from datetime import datetime

    return SupervisorEvaluationRow(
        inspection_id=UUID(record.inspection_id),
        evaluator_name=record.evaluator_name,
        status=record.status,
        score=record.score,
        finding_ids=list(record.finding_ids),
        started_at=datetime.fromisoformat(record.started_at),
        ended_at=datetime.fromisoformat(record.ended_at),
        latency_ms=record.latency_ms,
        error=record.error,
        metadata_json=dict(record.metadata),
    )


def _evaluation_row_to_record(
    row: SupervisorEvaluationRow,
) -> QAEvaluationRecord:
    return QAEvaluationRecord(
        inspection_id=str(row.inspection_id),
        evaluator_name=row.evaluator_name,
        status=row.status,
        score=row.score,
        finding_ids=tuple(_as_list_of_str(row.finding_ids)),
        started_at=row.started_at.isoformat(),
        ended_at=row.ended_at.isoformat(),
        latency_ms=row.latency_ms,
        error=row.error,
        metadata=dict(_as_dict(row.metadata_json)),
    )


def _escalation_record_to_row(
    record: EscalationDecisionRecord,
) -> SupervisorEscalationRow:
    from datetime import datetime

    return SupervisorEscalationRow(
        escalation_id=UUID(record.escalation_id),
        inspection_id=UUID(record.inspection_id),
        decision_id=UUID(record.decision_id),
        level=record.level,
        reason=record.reason,
        triggering_finding_ids=list(record.triggering_finding_ids),
        decided_at=datetime.fromisoformat(record.decided_at),
        metadata_json=dict(record.metadata),
    )


def _escalation_row_to_record(
    row: SupervisorEscalationRow,
) -> EscalationDecisionRecord:
    return EscalationDecisionRecord(
        escalation_id=str(row.escalation_id),
        inspection_id=str(row.inspection_id),
        decision_id=str(row.decision_id),
        level=row.level,
        reason=row.reason,
        triggering_finding_ids=tuple(_as_list_of_str(row.triggering_finding_ids)),
        decided_at=row.decided_at.isoformat(),
        metadata=dict(_as_dict(row.metadata_json)),
    )


# ─── Helpers ────────────────────────────────────────────────────────────


def _require_inspection_id(metadata: object) -> str:
    """Mirror the in-memory ``_require_inspection_id`` contract.

    Findings carry their parent inspection_id in ``metadata`` under
    the canonical ``"inspection_id"`` key. The substrate raises if
    that contract is violated; the Postgres backend honours the
    same wire shape so callers don't have to special-case backends.
    """
    if isinstance(metadata, dict) and "inspection_id" in metadata:
        return str(metadata["inspection_id"])
    raise SupervisorPersistenceError(
        "RuntimeFindingRecord.metadata must carry an "
        "'inspection_id' key when persisted"
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    return {}


def _as_list_of_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return []


__all__ = ["PostgresSupervisorRepository"]
