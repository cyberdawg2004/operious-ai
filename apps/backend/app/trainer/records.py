"""Persistable trainer recommendation records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

TrainingRecommendationPriority = Literal["low", "medium", "high"]
TrainingRecommendationStatus = Literal[
    "pending",
    "acknowledged",
    "applied",
    "dismissed",
]


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class TrainingRecommendationRecord:
    recommendation_id: str
    tenant_id: str
    session_id: str
    qa_score_id: str
    category: str
    finding_summary: str
    recommendation: str
    priority: TrainingRecommendationPriority
    created_at: datetime
    status: TrainingRecommendationStatus = "pending"
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "qa_score_id": self.qa_score_id,
            "category": self.category,
            "finding_summary": self.finding_summary,
            "recommendation": self.recommendation,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "TrainingRecommendationRecord":
        return cls(
            recommendation_id=str(data["recommendation_id"]),
            tenant_id=str(data["tenant_id"]),
            session_id=str(data["session_id"]),
            qa_score_id=str(data["qa_score_id"]),
            category=str(data["category"]),
            finding_summary=str(data["finding_summary"]),
            recommendation=str(data["recommendation"]),
            priority=_priority(str(data["priority"])),
            status=_status(str(data.get("status") or "pending")),
            created_at=_parse_datetime(data["created_at"]),
            metadata=dict(data.get("metadata") or {}),
        )


def _priority(value: str) -> TrainingRecommendationPriority:
    if value in {"low", "medium", "high"}:
        return value  # type: ignore[return-value]
    raise ValueError(f"unknown training recommendation priority: {value!r}")


def _status(value: str) -> TrainingRecommendationStatus:
    if value in {"pending", "acknowledged", "applied", "dismissed"}:
        return value  # type: ignore[return-value]
    raise ValueError(f"unknown training recommendation status: {value!r}")


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError("created_at must be a datetime or ISO timestamp")


__all__ = [
    "TrainingRecommendationPriority",
    "TrainingRecommendationRecord",
    "TrainingRecommendationStatus",
]
