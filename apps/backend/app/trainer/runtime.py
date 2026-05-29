"""Read-only trainer agent runtime over QA score records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.qa.persistence import QAScoreRecord
from app.trainer.identity import derive_recommendation_id
from app.trainer.persistence import TrainingRecommendationRepository
from app.trainer.records import (
    TrainingRecommendationPriority,
    TrainingRecommendationRecord,
)

_DIMENSION_THRESHOLD = 0.7


class TrainerAgentRuntime:
    """
    READ-ONLY with respect to sessions, knowledge, governance, and policies.

    The runtime derives deterministic recommendation records from QA score
    evidence and persists those records through its own append-only store.
    """

    def __init__(
        self,
        *,
        recommendation_repository: TrainingRecommendationRepository | None = None,
    ) -> None:
        self._recommendations = recommendation_repository

    async def generate_recommendations(
        self,
        *,
        qa_score_record: QAScoreRecord,
        session_id: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> list[TrainingRecommendationRecord]:
        _assert_tenant(tenant_id, expected_tenant_id)
        _assert_tenant(qa_score_record.tenant_id, expected_tenant_id)
        if not session_id:
            raise ValueError("session_id is required")

        records: list[TrainingRecommendationRecord] = []
        created_at = datetime.now(timezone.utc)
        for dimension, score in _dimension_scores(qa_score_record):
            if score < _DIMENSION_THRESHOLD:
                records.append(
                    _recommendation_for_dimension(
                        qa_score_record=qa_score_record,
                        session_id=session_id,
                        tenant_id=tenant_id,
                        dimension=dimension,
                        score=score,
                        created_at=created_at,
                    )
                )

        if qa_score_record.escalation_count > 0:
            records.append(
                _escalation_recommendation(
                    qa_score_record=qa_score_record,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    created_at=created_at,
                )
            )

        if not records and qa_score_record.overall_score < 0.75:
            records.append(
                _overall_recommendation(
                    qa_score_record=qa_score_record,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    created_at=created_at,
                )
            )

        return records

    async def generate_and_persist(
        self,
        *,
        qa_score: QAScoreRecord,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> list[TrainingRecommendationRecord]:
        if self._recommendations is None:
            raise ValueError(
                "generate_and_persist requires recommendation_repository"
            )
        session_id = _session_id_from_score(qa_score)
        recommendations = await self.generate_recommendations(
            qa_score_record=qa_score,
            session_id=session_id,
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
        persisted: list[TrainingRecommendationRecord] = []
        for recommendation in recommendations:
            persisted.append(
                await self._recommendations.write(
                    recommendation,
                    expected_tenant_id=expected_tenant_id,
                )
            )
        return persisted


def _dimension_scores(
    score: QAScoreRecord,
) -> tuple[tuple[str, float], ...]:
    return (
        ("diagnostic_accuracy", score.diagnostic_accuracy),
        ("policy_compliance", score.policy_compliance),
        ("resolution_quality", score.resolution_quality),
    )


def _recommendation_for_dimension(
    *,
    qa_score_record: QAScoreRecord,
    session_id: str,
    tenant_id: str,
    dimension: str,
    score: float,
    created_at: datetime,
) -> TrainingRecommendationRecord:
    summary = (
        f"QA {dimension} score {score:.2f} is below "
        f"{_DIMENSION_THRESHOLD:.2f}."
    )
    return TrainingRecommendationRecord(
        recommendation_id=str(
            derive_recommendation_id(
                tenant_id=tenant_id,
                session_id=session_id,
                qa_score_id=qa_score_record.score_id,
                dimension=dimension,
            )
        ),
        tenant_id=tenant_id,
        session_id=session_id,
        qa_score_id=qa_score_record.score_id,
        category=dimension,
        finding_summary=summary,
        recommendation=_guidance_for_dimension(dimension),
        priority=_priority_for_score(score),
        created_at=created_at,
        metadata=_metadata(
            qa_score_record,
            dimension=dimension,
            dimension_score=score,
        ),
    )


def _escalation_recommendation(
    *,
    qa_score_record: QAScoreRecord,
    session_id: str,
    tenant_id: str,
    created_at: datetime,
) -> TrainingRecommendationRecord:
    dimension = "supervisor_escalation"
    return TrainingRecommendationRecord(
        recommendation_id=str(
            derive_recommendation_id(
                tenant_id=tenant_id,
                session_id=session_id,
                qa_score_id=qa_score_record.score_id,
                dimension=dimension,
            )
        ),
        tenant_id=tenant_id,
        session_id=session_id,
        qa_score_id=qa_score_record.score_id,
        category=dimension,
        finding_summary=(
            "Supervisor escalation recorded for this session; review the "
            "triggering findings with the operator."
        ),
        recommendation=(
            "Review escalated supervisor findings and capture the corrective "
            "coaching pattern for future sessions."
        ),
        priority="high",
        created_at=created_at,
        metadata=_metadata(
            qa_score_record,
            dimension=dimension,
            dimension_score=qa_score_record.overall_score,
        ),
    )


def _overall_recommendation(
    *,
    qa_score_record: QAScoreRecord,
    session_id: str,
    tenant_id: str,
    created_at: datetime,
) -> TrainingRecommendationRecord:
    dimension = "overall_quality"
    return TrainingRecommendationRecord(
        recommendation_id=str(
            derive_recommendation_id(
                tenant_id=tenant_id,
                session_id=session_id,
                qa_score_id=qa_score_record.score_id,
                dimension=dimension,
            )
        ),
        tenant_id=tenant_id,
        session_id=session_id,
        qa_score_id=qa_score_record.score_id,
        category=dimension,
        finding_summary=(
            f"QA overall score {qa_score_record.overall_score:.2f} is below "
            "the trainer trigger threshold."
        ),
        recommendation=(
            "Review the session transcript and reinforce the weakest QA "
            "dimension in operator coaching."
        ),
        priority=_priority_for_score(qa_score_record.overall_score),
        created_at=created_at,
        metadata=_metadata(
            qa_score_record,
            dimension=dimension,
            dimension_score=qa_score_record.overall_score,
        ),
    )


def _guidance_for_dimension(dimension: str) -> str:
    if dimension == "diagnostic_accuracy":
        return "Review SOP classification criteria for diagnostic_accuracy."
    if dimension == "policy_compliance":
        return "Governance policy thresholds may need adjustment for policy_compliance."
    if dimension == "resolution_quality":
        return "Response template for resolution_quality needs updating."
    return "Review QA findings and update operator coaching guidance."


def _priority_for_score(score: float) -> TrainingRecommendationPriority:
    if score < 0.5:
        return "high"
    if score < _DIMENSION_THRESHOLD:
        return "medium"
    return "low"


def _metadata(
    qa_score: QAScoreRecord,
    *,
    dimension: str,
    dimension_score: float,
) -> dict[str, Any]:
    return {
        "source": "qa_score_record",
        "inspection_id": qa_score.inspection_id,
        "execution_id": qa_score.execution_id,
        "overall_score": qa_score.overall_score,
        "dimension": dimension,
        "dimension_score": dimension_score,
        "supervisor_decision_kind": qa_score.supervisor_decision_kind,
        "finding_count": qa_score.finding_count,
        "evaluation_count": qa_score.evaluation_count,
        "escalation_count": qa_score.escalation_count,
        "qa_metadata": dict(qa_score.metadata),
    }


def _session_id_from_score(score: QAScoreRecord) -> str:
    for key in ("session_id", "source_session_id"):
        value = score.metadata.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError("QA score metadata does not include source_session_id")


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ValueError("trainer tenant_id does not match expected_tenant_id")


__all__ = ["TrainerAgentRuntime"]
