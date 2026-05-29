"""In-memory trainer recommendation persistence."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime

from app.trainer.persistence.protocol import (
    TrainingFailurePattern,
    TrainingRecommendationPage,
)
from app.trainer.records import (
    TrainingRecommendationRecord,
    TrainingRecommendationStatus,
)


class InMemoryTrainingRecommendationRepository:
    def __init__(self) -> None:
        self._records: dict[str, TrainingRecommendationRecord] = {}

    async def write(
        self,
        record: TrainingRecommendationRecord,
        *,
        expected_tenant_id: str,
    ) -> TrainingRecommendationRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        existing = self._records.get(record.recommendation_id)
        if existing is not None:
            _assert_tenant(existing.tenant_id, expected_tenant_id)
            return existing
        self._records[record.recommendation_id] = record
        return record

    async def get(
        self,
        recommendation_id: str,
        *,
        expected_tenant_id: str,
    ) -> TrainingRecommendationRecord | None:
        record = self._records.get(recommendation_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list(
        self,
        *,
        expected_tenant_id: str,
        status: str | None = None,
        qa_score_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TrainingRecommendationPage:
        records = [
            record
            for record in self._records.values()
            if record.tenant_id == expected_tenant_id
            and (status in (None, "all") or record.status == status)
            and (qa_score_id is None or record.qa_score_id == qa_score_id)
        ]
        records.sort(key=lambda item: (item.created_at, item.recommendation_id))
        return TrainingRecommendationPage(
            items=tuple(records[offset : offset + limit]),
            total=len(records),
            limit=limit,
            offset=offset,
        )

    async def update_status(
        self,
        recommendation_id: str,
        *,
        expected_tenant_id: str,
        status: TrainingRecommendationStatus,
    ) -> TrainingRecommendationRecord | None:
        record = await self.get(
            recommendation_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            return None
        updated = replace(record, status=status)
        self._records[recommendation_id] = updated
        return updated

    async def list_failure_patterns(
        self,
        *,
        expected_tenant_id: str,
        since: datetime,
        threshold: int,
    ) -> tuple[TrainingFailurePattern, ...]:
        counter: Counter[str] = Counter()
        for record in self._records.values():
            if record.tenant_id != expected_tenant_id:
                continue
            if record.status != "pending" or record.created_at <= since:
                continue
            counter[record.category] += 1
        return tuple(
            TrainingFailurePattern(
                tenant_id=expected_tenant_id,
                category=category,
                recommendation_count=count,
            )
            for category, count in sorted(counter.items())
            if count >= threshold
        )

    async def list_all_failure_patterns(
        self,
        *,
        since: datetime,
        threshold: int,
    ) -> tuple[TrainingFailurePattern, ...]:
        counter: Counter[tuple[str, str]] = Counter()
        for record in self._records.values():
            if record.status != "pending" or record.created_at <= since:
                continue
            counter[(record.tenant_id, record.category)] += 1
        return tuple(
            TrainingFailurePattern(
                tenant_id=tenant_id,
                category=category,
                recommendation_count=count,
            )
            for (tenant_id, category), count in sorted(counter.items())
            if count >= threshold
        )


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ValueError("training recommendation tenant mismatch")


__all__ = ["InMemoryTrainingRecommendationRepository"]
