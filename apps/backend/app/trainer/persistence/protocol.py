"""Storage contract for trainer recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.trainer.records import (
    TrainingRecommendationRecord,
    TrainingRecommendationStatus,
)


@dataclass(frozen=True, slots=True)
class TrainingRecommendationPage:
    items: tuple[TrainingRecommendationRecord, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class TrainingFailurePattern:
    tenant_id: str
    category: str
    recommendation_count: int


class TrainingRecommendationRepository(Protocol):
    async def write(
        self,
        record: TrainingRecommendationRecord,
        *,
        expected_tenant_id: str,
    ) -> TrainingRecommendationRecord: ...

    async def get(
        self,
        recommendation_id: str,
        *,
        expected_tenant_id: str,
    ) -> TrainingRecommendationRecord | None: ...

    async def list(
        self,
        *,
        expected_tenant_id: str,
        status: str | None = None,
        qa_score_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TrainingRecommendationPage: ...

    async def update_status(
        self,
        recommendation_id: str,
        *,
        expected_tenant_id: str,
        status: TrainingRecommendationStatus,
    ) -> TrainingRecommendationRecord | None: ...

    async def list_failure_patterns(
        self,
        *,
        expected_tenant_id: str,
        since: datetime,
        threshold: int,
    ) -> tuple[TrainingFailurePattern, ...]: ...

    async def list_all_failure_patterns(
        self,
        *,
        since: datetime,
        threshold: int,
    ) -> tuple[TrainingFailurePattern, ...]: ...


__all__ = [
    "TrainingFailurePattern",
    "TrainingRecommendationPage",
    "TrainingRecommendationRepository",
]
