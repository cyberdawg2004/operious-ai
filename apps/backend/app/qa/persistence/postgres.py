"""Postgres implementation of QA persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from app.qa.db.models import QAScoreRow
from app.qa.exceptions import QAPersistenceError
from app.qa.persistence.models import QAScorePage, QAScoreQuery
from app.qa.persistence.records import QAScoreRecord
from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page


class PostgresQAPersistence(BaseRepository):
    """Postgres-backed QA score persistence."""

    async def record_score(
        self,
        record: QAScoreRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        row = _record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise QAPersistenceError(
                f"QA score {record.score_id!r} already recorded; "
                "records are write-once"
            ) from exc

    async def get_score(
        self,
        score_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAScoreRecord | None:
        stmt = select(QAScoreRow).where(
            QAScoreRow.score_id == UUID(score_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(QAScoreRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def get_score_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAScoreRecord | None:
        stmt = select(QAScoreRow).where(
            QAScoreRow.inspection_id == UUID(inspection_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(QAScoreRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def list_scores(
        self,
        query: QAScoreQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAScorePage:
        stmt = select(QAScoreRow)
        stmt = _apply_filters(
            stmt,
            query=query,
            expected_tenant_id=expected_tenant_id,
        )
        stmt = stmt.order_by(QAScoreRow.scored_at, QAScoreRow.score_id)
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return QAScorePage(
            items=tuple(_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


def _apply_filters(
    stmt: Select[tuple[QAScoreRow]],
    *,
    query: QAScoreQuery,
    expected_tenant_id: str | None,
) -> Select[tuple[QAScoreRow]]:
    if expected_tenant_id is not None:
        stmt = stmt.where(QAScoreRow.tenant_id == expected_tenant_id)
    if query.score_id is not None:
        stmt = stmt.where(QAScoreRow.score_id == UUID(query.score_id))
    if query.inspection_id is not None:
        stmt = stmt.where(
            QAScoreRow.inspection_id == UUID(query.inspection_id)
        )
    if query.execution_id is not None:
        stmt = stmt.where(QAScoreRow.execution_id == UUID(query.execution_id))
    if query.tenant_id is not None:
        stmt = stmt.where(QAScoreRow.tenant_id == query.tenant_id)
    if query.supervisor_decision_kind is not None:
        stmt = stmt.where(
            QAScoreRow.supervisor_decision_kind
            == query.supervisor_decision_kind
        )
    # MVP-5: date range filtering for the QA signal aggregator.
    if query.scored_after is not None:
        stmt = stmt.where(QAScoreRow.scored_at >= query.scored_after)
    if query.scored_before is not None:
        stmt = stmt.where(QAScoreRow.scored_at <= query.scored_before)
    return stmt


def _record_to_row(record: QAScoreRecord) -> QAScoreRow:
    return QAScoreRow(
        score_id=UUID(record.score_id),
        inspection_id=UUID(record.inspection_id),
        execution_id=UUID(record.execution_id),
        tenant_id=record.tenant_id,
        tenant_authority_source=record.tenant_authority_source,
        diagnostic_accuracy=record.diagnostic_accuracy,
        policy_compliance=record.policy_compliance,
        timeline_integrity=record.timeline_integrity,
        resolution_quality=record.resolution_quality,
        semantic_grounding=record.semantic_grounding,
        overall_score=record.overall_score,
        supervisor_decision_kind=record.supervisor_decision_kind,
        finding_count=record.finding_count,
        evaluation_count=record.evaluation_count,
        escalation_count=record.escalation_count,
        scored_at=datetime.fromisoformat(record.scored_at),
        metadata_json=dict(record.metadata),
    )


def _row_to_record(row: QAScoreRow) -> QAScoreRecord:
    return QAScoreRecord(
        score_id=str(row.score_id),
        inspection_id=str(row.inspection_id),
        execution_id=str(row.execution_id),
        tenant_id=row.tenant_id,
        tenant_authority_source=row.tenant_authority_source,
        diagnostic_accuracy=row.diagnostic_accuracy,
        policy_compliance=row.policy_compliance,
        timeline_integrity=row.timeline_integrity,
        resolution_quality=row.resolution_quality,
        semantic_grounding=float(row.semantic_grounding or 0.0),
        overall_score=row.overall_score,
        supervisor_decision_kind=row.supervisor_decision_kind,
        finding_count=row.finding_count,
        evaluation_count=row.evaluation_count,
        escalation_count=row.escalation_count,
        scored_at=row.scored_at.isoformat(),
        metadata=dict(_as_dict(row.metadata_json)),
    )


def _enforce_expected_tenant(
    tenant_id: str,
    expected_tenant_id: str | None,
) -> None:
    if expected_tenant_id is not None and tenant_id != expected_tenant_id:
        raise QAPersistenceError(
            "QA score tenant_id does not match expected_tenant_id"
        )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    return {}


__all__ = ["PostgresQAPersistence"]
