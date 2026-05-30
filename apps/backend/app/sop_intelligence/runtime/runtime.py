"""SOP Intelligence Agent runtime.

The runtime is proposal-only. It reconstructs evidence from persisted
records and writes a pending approval proposal. It never mutates tenant
knowledge documents, session records, supervisor inspections, QA scores,
or governance history.
"""

from __future__ import annotations

from collections.abc import Coroutine, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, cast

from app.governance.persistence import (
    BaseGovernanceRepository,
    GovernanceDecisionRecord,
)
from app.qa.persistence import QAPersistenceProtocol, QAScoreRecord
from app.session.identity import as_session_id
from app.session.lifecycle.classifier import is_terminal
from app.session.persistence import SessionPersistenceProtocol, SessionRecord
from app.sop_intelligence.enums import ApprovalStatus
from app.sop_intelligence.exceptions import (
    SOPIntelligenceEligibilityError,
    SOPIntelligenceNotFoundError,
    SOPIntelligencePersistenceError,
)
from app.sop_intelligence.identity import (
    as_approval_id,
    derive_approval_id,
)
from app.sop_intelligence.persistence import (
    ApprovalPage,
    ApprovalQuery,
    ApprovalRecord,
    SOPApprovalPersistenceProtocol,
)
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    InspectionQuery,
    InspectionRecord,
)
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.persistence import (
    TenantConfigurationRepository,
    TenantKnowledgeDocumentQuery,
    TenantKnowledgeDocumentRecord,
)

_PROPOSED_BY = "sop_intelligence_agent:v1"
_MIN_QA_CONFIDENCE = 0.85
_INSPECTION_SCAN_LIMIT = 500


class SOPIntelligenceRuntime:
    """Proposal-only runtime for SOP improvement approval records."""

    def __init__(
        self,
        *,
        approval_persistence: SOPApprovalPersistenceProtocol,
        session_persistence: SessionPersistenceProtocol,
        supervisor_repository: BaseSupervisorRepository,
        qa_persistence: QAPersistenceProtocol,
        governance_repository: BaseGovernanceRepository,
        tenant_configuration_repository: TenantConfigurationRepository,
        minimum_confidence: float = _MIN_QA_CONFIDENCE,
    ) -> None:
        self._approval_persistence = approval_persistence
        self._session_persistence = session_persistence
        self._supervisor_repository = supervisor_repository
        self._qa_persistence = qa_persistence
        self._governance_repository = governance_repository
        self._tenant_configuration_repository = (
            tenant_configuration_repository
        )
        self._minimum_confidence = minimum_confidence

    async def propose_for_session(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
        inspection_id: str | None = None,
    ) -> ApprovalRecord:
        """Create or return a pending SOP proposal for one session."""

        if not expected_tenant_id:
            raise SOPIntelligenceEligibilityError(
                "expected_tenant_id is required"
            )
        session = await self._load_session(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
        )
        inspection = await self._load_inspection(
            session_id=str(session.session_id),
            expected_tenant_id=expected_tenant_id,
            inspection_id=inspection_id,
        )
        score = await self._load_qa_score(
            inspection_id=inspection.inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        self._assert_eligible(session=session, inspection=inspection, score=score)
        document = await self._select_document(
            expected_tenant_id=expected_tenant_id
        )
        governance_decisions = await self._load_governance_decisions(
            inspection=inspection,
            score=score,
            expected_tenant_id=expected_tenant_id,
        )
        evidence_sessions = _evidence_sessions(
            session_id=str(session.session_id),
            metadata_sources=(inspection.metadata, score.metadata),
        )
        approval_id = str(
            derive_approval_id(
                tenant_id=expected_tenant_id,
                document_id=document.document_id,
                evidence_sessions=evidence_sessions,
                qa_score_id=score.score_id,
            )
        )
        existing = await self._approval_persistence.get_approval_record(
            approval_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is not None:
            return existing

        confidence = _proposal_confidence(score=score, inspection=inspection)
        policy_chains = _policy_chains(governance_decisions)
        record = ApprovalRecord(
            approval_id=approval_id,
            tenant_id=expected_tenant_id,
            document_id=str(document.document_id),
            proposed_change=_proposed_change(
                document=document,
                session=session,
                inspection=inspection,
                score=score,
                policy_chains=policy_chains,
            ),
            evidence_sessions=evidence_sessions,
            confidence=confidence,
            status=ApprovalStatus.PENDING_REVIEW.value,
            proposed_by=_PROPOSED_BY,
            reviewed_by=None,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "session_id": str(session.session_id),
                "inspection_id": inspection.inspection_id,
                "qa_score_id": score.score_id,
                "qa_overall_score": score.overall_score,
                "supervisor_decision_id": inspection.decision.decision_id,
                "supervisor_decision_kind": inspection.decision.kind,
                "supervisor_compliance_score": inspection.compliance_score,
                "policy_chain_ids": list(policy_chains),
                "governance_decision_ids": [
                    decision.decision_id
                    for decision in governance_decisions
                ],
                "document_version_before": document.version,
                "document_status": document.status.value,
                "proposal_only": True,
            },
        )
        try:
            await self._approval_persistence.create_approval_record(
                record,
                expected_tenant_id=expected_tenant_id,
            )
        except SOPIntelligencePersistenceError:
            existing = await self._approval_persistence.get_approval_record(
                approval_id,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is not None:
                return existing
            raise
        return record

    def propose_from_failure_pattern(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        category: str,
        recommendation_count: int,
        synthesized_proposed_change: str | None = None,
    ) -> Coroutine[Any, Any, ApprovalRecord]:
        """Create or return a pending SOP proposal from repeated QA failures."""

        return self._propose_from_failure_pattern(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            category=category,
            recommendation_count=recommendation_count,
            synthesized_proposed_change=synthesized_proposed_change,
        )

    async def _propose_from_failure_pattern(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        category: str,
        recommendation_count: int,
        synthesized_proposed_change: str | None = None,
    ) -> ApprovalRecord:
        """Create or return a pending SOP proposal from repeated QA failures."""

        if tenant_id != expected_tenant_id:
            raise SOPIntelligenceEligibilityError(
                "tenant_id does not match expected_tenant_id"
            )
        if not category:
            raise SOPIntelligenceEligibilityError("category is required")
        if recommendation_count < 1:
            raise SOPIntelligenceEligibilityError(
                "recommendation_count must be positive"
            )
        document = await self._select_document(
            expected_tenant_id=expected_tenant_id
        )
        evidence_sessions = (
            f"training_recommendation_pattern:{category}",
        )
        qa_score_id = f"failure_pattern:{category}"
        approval_id = str(
            derive_approval_id(
                tenant_id=expected_tenant_id,
                document_id=document.document_id,
                evidence_sessions=evidence_sessions,
                qa_score_id=qa_score_id,
            )
        )
        existing = await self._approval_persistence.get_approval_record(
            approval_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is not None:
            return existing

        proposed_change = (
            synthesized_proposed_change
            if synthesized_proposed_change is not None
            else _failure_pattern_proposed_change(
                document=document,
                category=category,
                recommendation_count=recommendation_count,
            )
        )
        record = ApprovalRecord(
            approval_id=approval_id,
            tenant_id=expected_tenant_id,
            document_id=str(document.document_id),
            proposed_change=proposed_change,
            evidence_sessions=evidence_sessions,
            confidence=_failure_pattern_confidence(recommendation_count),
            status=ApprovalStatus.PENDING_REVIEW.value,
            proposed_by=_PROPOSED_BY,
            reviewed_by=None,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "failure_pattern": True,
                "category": category,
                "recommendation_count": recommendation_count,
                "document_version_before": document.version,
                "document_status": document.status.value,
                "proposal_only": True,
                "synthesized_proposed_change": (
                    synthesized_proposed_change is not None
                ),
            },
        )
        try:
            await self._approval_persistence.create_approval_record(
                record,
                expected_tenant_id=expected_tenant_id,
            )
        except SOPIntelligencePersistenceError:
            existing = await self._approval_persistence.get_approval_record(
                approval_id,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is not None:
                return existing
            raise
        return record

    async def get_approval_record(
        self,
        approval_id: str,
        *,
        expected_tenant_id: str,
    ) -> ApprovalRecord | None:
        as_approval_id(approval_id)
        return await self._approval_persistence.get_approval_record(
            approval_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_approval_records(
        self,
        *,
        query: ApprovalQuery,
        expected_tenant_id: str,
    ) -> ApprovalPage:
        return await self._approval_persistence.list_approval_records(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def _load_session(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
    ) -> SessionRecord:
        session = await self._session_persistence.get_session(
            as_session_id(session_id),
            expected_tenant_id=expected_tenant_id,
        )
        if session is None:
            raise SOPIntelligenceNotFoundError("session not found")
        if session.tenant_id != expected_tenant_id:
            raise SOPIntelligenceEligibilityError(
                "session tenant_id does not match expected_tenant_id"
            )
        return session

    async def _load_inspection(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
        inspection_id: str | None,
    ) -> InspectionRecord:
        if inspection_id is not None:
            inspection = await self._supervisor_repository.get_inspection(
                inspection_id,
                expected_tenant_id=expected_tenant_id,
            )
            if inspection is None:
                raise SOPIntelligenceNotFoundError(
                    "supervisor inspection not found"
                )
            if _metadata_session_id(inspection.metadata) != session_id:
                raise SOPIntelligenceEligibilityError(
                    "supervisor inspection does not belong to session"
                )
            return inspection

        page = await self._supervisor_repository.query_inspections(
            InspectionQuery(
                tenant_id=expected_tenant_id,
                limit=_INSPECTION_SCAN_LIMIT,
            ),
            expected_tenant_id=expected_tenant_id,
        )
        matches = [
            inspection
            for inspection in page.items
            if _metadata_session_id(inspection.metadata) == session_id
        ]
        if not matches:
            raise SOPIntelligenceNotFoundError(
                "supervisor inspection not found for session"
            )
        return sorted(
            matches,
            key=lambda record: (record.ended_at, record.inspection_id),
        )[-1]

    async def _load_qa_score(
        self,
        *,
        inspection_id: str,
        expected_tenant_id: str,
    ) -> QAScoreRecord:
        score = await self._qa_persistence.get_score_for_inspection(
            inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        if score is None:
            raise SOPIntelligenceNotFoundError("QA score not found")
        return score

    async def _select_document(
        self,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentRecord:
        page = await self._tenant_configuration_repository.list_knowledge_documents(
            TenantKnowledgeDocumentQuery(
                document_type=TenantKnowledgeDocumentType.SOP,
                status=TenantKnowledgeDocumentStatus.ACTIVE,
                limit=50,
            ),
            expected_tenant_id=expected_tenant_id,
        )
        if not page.items:
            raise SOPIntelligenceNotFoundError(
                "active SOP knowledge document not found"
            )
        return sorted(
            page.items,
            key=lambda record: (record.title, str(record.document_id)),
        )[0]

    async def _load_governance_decisions(
        self,
        *,
        inspection: InspectionRecord,
        score: QAScoreRecord,
        expected_tenant_id: str,
    ) -> tuple[GovernanceDecisionRecord, ...]:
        records: list[GovernanceDecisionRecord] = []
        seen: set[str] = set()
        for decision_id in _governance_decision_ids(inspection, score):
            if decision_id in seen:
                continue
            seen.add(decision_id)
            record = await self._governance_repository.get_decision(
                decision_id,
                expected_tenant_id=expected_tenant_id,
            )
            if record is not None:
                records.append(record)
        return tuple(records)

    def _assert_eligible(
        self,
        *,
        session: SessionRecord,
        inspection: InspectionRecord,
        score: QAScoreRecord,
    ) -> None:
        if not is_terminal(session.lifecycle_phase):
            raise SOPIntelligenceEligibilityError(
                "SOP proposal requires a completed session"
            )
        if score.overall_score < self._minimum_confidence:
            raise SOPIntelligenceEligibilityError(
                "QA score is below SOP proposal confidence threshold"
            )
        if inspection.decision.kind != "accept":
            raise SOPIntelligenceEligibilityError(
                "SOP proposal requires an accepted supervisor decision"
            )


def _metadata_session_id(metadata: object) -> str | None:
    if not isinstance(metadata, Mapping):
        return None
    typed_metadata = cast(Mapping[str, object], metadata)
    value = typed_metadata.get("session_id")
    return str(value) if value is not None else None


def _governance_decision_ids(
    inspection: InspectionRecord,
    score: QAScoreRecord,
) -> tuple[str, ...]:
    values: list[str] = []
    _extend_ids(values, inspection.metadata.get("governance_decision_ids"))
    _append_id(values, score.metadata.get("source_decision_id"))
    _append_id(values, inspection.decision.decision_id)
    return tuple(values)


def _extend_ids(values: list[str], candidate: object) -> None:
    if isinstance(candidate, list | tuple):
        for value in cast(Iterable[object], candidate):
            _append_id(values, value)


def _append_id(values: list[str], candidate: object) -> None:
    if candidate is not None:
        values.append(str(candidate))


def _evidence_sessions(
    *,
    session_id: str,
    metadata_sources: Iterable[object],
) -> tuple[str, ...]:
    values: list[str] = [session_id]
    for metadata in metadata_sources:
        if not isinstance(metadata, Mapping):
            continue
        typed_metadata = cast(Mapping[str, object], metadata)
        for key in ("evidence_sessions", "supporting_session_ids"):
            raw = typed_metadata.get(key)
            if isinstance(raw, list | tuple):
                values.extend(
                    str(value) for value in cast(Iterable[object], raw)
                )
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _proposal_confidence(
    *,
    score: QAScoreRecord,
    inspection: InspectionRecord,
) -> float:
    return round(
        max(
            0.0,
            min(1.0, (score.overall_score + inspection.compliance_score) / 2),
        ),
        4,
    )


def _policy_chains(
    decisions: tuple[GovernanceDecisionRecord, ...],
) -> tuple[str, ...]:
    values = sorted(
        {
            decision.policy_chain_id
            for decision in decisions
            if decision.policy_chain_id
        }
    )
    return tuple(values)


def _proposed_change(
    *,
    document: TenantKnowledgeDocumentRecord,
    session: SessionRecord,
    inspection: InspectionRecord,
    score: QAScoreRecord,
    policy_chains: tuple[str, ...],
) -> str:
    chain_text = ", ".join(policy_chains) if policy_chains else "none recorded"
    return (
        f"Propose updating '{document.title}' with the validated resolution "
        f"pattern from session {session.session_id}. Supervisor decision "
        f"{inspection.decision.kind!r} scored "
        f"{inspection.compliance_score:.2f}; QA overall score "
        f"{score.overall_score:.2f}. Preserve policy-chain constraints: "
        f"{chain_text}."
    )


def _failure_pattern_proposed_change(
    *,
    document: TenantKnowledgeDocumentRecord,
    category: str,
    recommendation_count: int,
) -> str:
    return (
        f"Propose updating '{document.title}' for repeated QA failures in "
        f"{category}. Trainer recommendations flagged this category "
        f"{recommendation_count} times in the configured lookback window; "
        "review the SOP guidance and add corrective operator steps."
    )


def _failure_pattern_confidence(recommendation_count: int) -> float:
    return round(min(0.85, 0.55 + (0.05 * max(0, recommendation_count - 3))), 4)


__all__ = ["SOPIntelligenceRuntime"]
