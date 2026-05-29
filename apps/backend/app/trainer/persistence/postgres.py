"""Postgres implementation of trainer recommendation persistence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError

from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page
from app.trainer.db.models import TrainingRecommendationRow
from app.trainer.persistence.protocol import (
    TrainingFailurePattern,
    TrainingRecommendationPage,
)
from app.trainer.records import (
    TrainingRecommendationPriority,
    TrainingRecommendationRecord,
    TrainingRecommendationStatus,
)

_FAILURE_PATTERN_SCAN_LIMIT = 500


class PostgresTrainingRecommendationRepository(BaseRepository):
    async def write(
        self,
        record: TrainingRecommendationRecord,
        *,
        expected_tenant_id: str,
    ) -> TrainingRecommendationRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        row = _record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError:
            existing = await self.get(
                record.recommendation_id,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is not None:
                return existing
            raise
        return record

    async def get(
        self,
        recommendation_id: str,
        *,
        expected_tenant_id: str,
    ) -> TrainingRecommendationRecord | None:
        stmt = select(TrainingRecommendationRow).where(
            TrainingRecommendationRow.recommendation_id == UUID(recommendation_id),
            TrainingRecommendationRow.tenant_id == expected_tenant_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def list(
        self,
        *,
        expected_tenant_id: str,
        status: str | None = None,
        qa_score_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TrainingRecommendationPage:
        stmt = select(TrainingRecommendationRow).where(
            TrainingRecommendationRow.tenant_id == expected_tenant_id
        )
        stmt = _apply_filters(stmt, status=status, qa_score_id=qa_score_id)
        stmt = stmt.order_by(
            TrainingRecommendationRow.created_at,
            TrainingRecommendationRow.recommendation_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=limit,
            offset=offset,
        )
        return TrainingRecommendationPage(
            items=tuple(_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def update_status(
        self,
        recommendation_id: str,
        *,
        expected_tenant_id: str,
        status: TrainingRecommendationStatus,
    ) -> TrainingRecommendationRecord | None:
        stmt = select(TrainingRecommendationRow).where(
            TrainingRecommendationRow.recommendation_id == UUID(recommendation_id),
            TrainingRecommendationRow.tenant_id == expected_tenant_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        row.status = status
        return _row_to_record(row)

    async def list_failure_patterns(
        self,
        *,
        expected_tenant_id: str,
        since: datetime,
        threshold: int,
    ) -> tuple[TrainingFailurePattern, ...]:
        stmt = (
            select(
                TrainingRecommendationRow.category,
                func.count().label("recommendation_count"),
            )
            .where(
                TrainingRecommendationRow.tenant_id == expected_tenant_id,
                TrainingRecommendationRow.status == "pending",
                TrainingRecommendationRow.created_at > since,
            )
            .group_by(TrainingRecommendationRow.category)
            .having(func.count() >= threshold)
            .order_by(TrainingRecommendationRow.category)
            .limit(_FAILURE_PATTERN_SCAN_LIMIT)
        )
        rows = (await self.session.execute(stmt)).all()  # bounded-load-ok
        return tuple(
            TrainingFailurePattern(
                tenant_id=expected_tenant_id,
                category=str(row.category),
                recommendation_count=int(row.recommendation_count),
            )
            for row in rows
        )

    async def list_all_failure_patterns(
        self,
        *,
        since: datetime,
        threshold: int,
    ) -> tuple[TrainingFailurePattern, ...]:
        stmt = (
            select(
                TrainingRecommendationRow.tenant_id,
                TrainingRecommendationRow.category,
                func.count().label("recommendation_count"),
            )
            .where(
                TrainingRecommendationRow.status == "pending",
                TrainingRecommendationRow.created_at > since,
            )
            .group_by(
                TrainingRecommendationRow.tenant_id,
                TrainingRecommendationRow.category,
            )
            .having(func.count() >= threshold)
            .order_by(
                TrainingRecommendationRow.tenant_id,
                TrainingRecommendationRow.category,
            )
            .limit(_FAILURE_PATTERN_SCAN_LIMIT)
        )
        rows = (await self.session.execute(stmt)).all()  # bounded-load-ok
        return tuple(
            TrainingFailurePattern(
                tenant_id=str(row.tenant_id),
                category=str(row.category),
                recommendation_count=int(row.recommendation_count),
            )
            for row in rows
        )


def _apply_filters(
    stmt: Select[tuple[TrainingRecommendationRow]],
    *,
    status: str | None,
    qa_score_id: str | None,
) -> Select[tuple[TrainingRecommendationRow]]:
    if status not in (None, "all"):
        stmt = stmt.where(TrainingRecommendationRow.status == status)
    if qa_score_id is not None:
        stmt = stmt.where(TrainingRecommendationRow.qa_score_id == UUID(qa_score_id))
    return stmt


def _record_to_row(record: TrainingRecommendationRecord) -> TrainingRecommendationRow:
    return TrainingRecommendationRow(
        recommendation_id=UUID(record.recommendation_id),
        tenant_id=record.tenant_id,
        session_id=UUID(record.session_id),
        qa_score_id=UUID(record.qa_score_id),
        category=record.category,
        finding_summary=record.finding_summary,
        recommendation=record.recommendation,
        priority=record.priority,
        status=record.status,
        created_at=record.created_at,
        metadata_json=dict(record.metadata),
    )


def _row_to_record(row: TrainingRecommendationRow) -> TrainingRecommendationRecord:
    return TrainingRecommendationRecord(
        recommendation_id=str(row.recommendation_id),
        tenant_id=row.tenant_id,
        session_id=str(row.session_id),
        qa_score_id=str(row.qa_score_id),
        category=row.category,
        finding_summary=row.finding_summary,
        recommendation=row.recommendation,
        priority=_priority(row.priority),
        status=_status(row.status),
        created_at=row.created_at,
        metadata=dict(_as_dict(row.metadata_json)),
    )


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ValueError("training recommendation tenant mismatch")


def _priority(value: str) -> TrainingRecommendationPriority:
    if value in {"low", "medium", "high"}:
        return value  # type: ignore[return-value]
    raise ValueError(f"unknown training priority: {value!r}")


def _status(value: str) -> TrainingRecommendationStatus:
    if value in {"pending", "acknowledged", "applied", "dismissed"}:
        return value  # type: ignore[return-value]
    raise ValueError(f"unknown training recommendation status: {value!r}")


def _as_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    mapping = cast(Mapping[object, Any], value)
    result: dict[str, Any] = {}
    for key, item in mapping.items():
        result[str(key)] = item
    return result


__all__ = ["PostgresTrainingRecommendationRepository"]
