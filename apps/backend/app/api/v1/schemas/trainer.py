"""Transport contracts for trainer recommendations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.trainer.records import TrainingRecommendationRecord

TrainerPatchStatus = Literal["acknowledged", "dismissed"]


def _empty_training_recommendations() -> list[TrainingRecommendationResponse]:
    return []


class TrainerRecommendationStatusPatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: TrainerPatchStatus


class TrainingRecommendationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    recommendation_id: str
    tenant_id: str
    session_id: str
    qa_score_id: str
    category: str
    finding_summary: str
    recommendation: str
    priority: str
    status: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls,
        record: TrainingRecommendationRecord,
    ) -> "TrainingRecommendationResponse":
        return cls(
            recommendation_id=record.recommendation_id,
            tenant_id=record.tenant_id,
            session_id=record.session_id,
            qa_score_id=record.qa_score_id,
            category=record.category,
            finding_summary=record.finding_summary,
            recommendation=record.recommendation,
            priority=record.priority,
            status=record.status,
            created_at=record.created_at,
            metadata=dict(record.metadata),
        )


class TrainingRecommendationListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TrainingRecommendationResponse] = Field(
        default_factory=_empty_training_recommendations
    )
    total: int
    offset: int
    limit: int


__all__ = [
    "TrainerRecommendationStatusPatchRequest",
    "TrainingRecommendationListResponse",
    "TrainingRecommendationResponse",
]
