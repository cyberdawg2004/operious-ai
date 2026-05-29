"""Service layer for the Command Center supervisor inbox."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.qa.persistence import QAPersistenceProtocol, QAScoreRecord
from app.repositories.pagination import SERVER_PAGE_HARD_CAP
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    EscalationDecisionRecord,
    InspectionQuery,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
)
from app.trainer.persistence import TrainingRecommendationRepository
from app.trainer.records import TrainingRecommendationRecord

_RISKY_SCORE_THRESHOLD = 0.75


@dataclass(frozen=True, slots=True)
class SupervisorInboxItem:
    inspection: InspectionRecord
    qa_score: QAScoreRecord | None
    category: str
    session_id: str | None
    escalation_count: int
    is_risky: bool


@dataclass(frozen=True, slots=True)
class SupervisorInboxPage:
    items: tuple[SupervisorInboxItem, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class SupervisorInspectionDetail:
    inspection: InspectionRecord
    qa_score: QAScoreRecord | None
    findings: tuple[RuntimeFindingRecord, ...]
    evaluations: tuple[QAEvaluationRecord, ...]
    escalations: tuple[EscalationDecisionRecord, ...]
    training_recommendations: tuple[TrainingRecommendationRecord, ...]
    category: str
    session_id: str | None
    is_risky: bool


class SupervisorInboxNotFoundError(RuntimeError):
    """Raised when an inspection is absent or tenant-invisible."""


class SupervisorInboxService:
    def __init__(
        self,
        *,
        supervisor_repository: BaseSupervisorRepository,
        qa_persistence: QAPersistenceProtocol,
        training_repository: TrainingRecommendationRepository,
    ) -> None:
        self._supervisor = supervisor_repository
        self._qa = qa_persistence
        self._training = training_repository

    async def list_inspections(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        status: str,
        session_id: str | None,
        limit: int,
        offset: int,
    ) -> SupervisorInboxPage:
        _assert_tenant(tenant_id, expected_tenant_id)
        page = await self._supervisor.query_inspections(
            InspectionQuery(limit=SERVER_PAGE_HARD_CAP, offset=0),
            expected_tenant_id=expected_tenant_id,
        )
        items: list[SupervisorInboxItem] = []
        for inspection in page.items:
            qa_score = await self._qa.get_score_for_inspection(
                inspection.inspection_id,
                expected_tenant_id=expected_tenant_id,
            )
            if session_id is not None and session_id != _session_id(
                inspection,
                qa_score,
            ):
                continue
            escalations = await self._supervisor.get_escalations_for_inspection(
                inspection.inspection_id,
                expected_tenant_id=expected_tenant_id,
            )
            findings = await self._supervisor.get_findings_for_inspection(
                inspection.inspection_id,
                expected_tenant_id=expected_tenant_id,
            )
            risky = _is_risky(qa_score, escalation_count=len(escalations))
            if status == "risky" and not risky:
                continue
            items.append(
                SupervisorInboxItem(
                    inspection=inspection,
                    qa_score=qa_score,
                    category=_category(inspection, findings),
                    session_id=_session_id(inspection, qa_score),
                    escalation_count=max(
                        len(escalations),
                        qa_score.escalation_count if qa_score else 0,
                    ),
                    is_risky=risky,
                )
            )
        items.sort(
            key=lambda item: _parse_datetime(item.inspection.started_at),
            reverse=True,
        )
        return SupervisorInboxPage(
            items=tuple(items[offset : offset + limit]),
            total=len(items),
            limit=limit,
            offset=offset,
        )

    async def get_inspection(
        self,
        *,
        inspection_id: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> SupervisorInspectionDetail:
        _assert_tenant(tenant_id, expected_tenant_id)
        inspection = await self._supervisor.get_inspection(
            inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        if inspection is None:
            raise SupervisorInboxNotFoundError(inspection_id)
        qa_score = await self._qa.get_score_for_inspection(
            inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        findings = await self._supervisor.get_findings_for_inspection(
            inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        evaluations = await self._supervisor.get_evaluations_for_inspection(
            inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        escalations = await self._supervisor.get_escalations_for_inspection(
            inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        training_recommendations: tuple[TrainingRecommendationRecord, ...] = ()
        if qa_score is not None:
            training_page = await self._training.list(
                expected_tenant_id=expected_tenant_id,
                qa_score_id=qa_score.score_id,
                status=None,
                limit=SERVER_PAGE_HARD_CAP,
                offset=0,
            )
            training_recommendations = training_page.items
        return SupervisorInspectionDetail(
            inspection=inspection,
            qa_score=qa_score,
            findings=findings,
            evaluations=evaluations,
            escalations=escalations,
            training_recommendations=training_recommendations,
            category=_category(inspection, findings),
            session_id=_session_id(inspection, qa_score),
            is_risky=_is_risky(qa_score, escalation_count=len(escalations)),
        )


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise SupervisorInboxNotFoundError("tenant mismatch")


def _is_risky(
    qa_score: QAScoreRecord | None,
    *,
    escalation_count: int,
) -> bool:
    if escalation_count > 0:
        return True
    if qa_score is None:
        return False
    return (
        qa_score.overall_score < _RISKY_SCORE_THRESHOLD
        or qa_score.escalation_count > 0
    )


def _category(
    inspection: InspectionRecord,
    findings: tuple[RuntimeFindingRecord, ...],
) -> str:
    if findings:
        return findings[0].category
    value = inspection.metadata.get("resolution_category")
    if isinstance(value, str) and value:
        return value
    return inspection.decision.kind


def _session_id(
    inspection: InspectionRecord,
    qa_score: QAScoreRecord | None,
) -> str | None:
    empty: Mapping[str, Any] = {}
    sources: tuple[Mapping[str, Any], Mapping[str, Any]] = (
        inspection.metadata,
        qa_score.metadata if qa_score else empty,
    )
    for source in sources:
        for key in ("session_id", "source_session_id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


__all__ = [
    "SupervisorInboxItem",
    "SupervisorInboxNotFoundError",
    "SupervisorInboxPage",
    "SupervisorInboxService",
    "SupervisorInspectionDetail",
]
