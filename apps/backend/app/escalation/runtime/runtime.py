"""EscalationAgent runtime over persisted governance denial lineage."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

from app.escalation.enums import EscalationOutboxStatus, EscalationStatus
from app.escalation.exceptions import (
    EscalationNotFoundError,
    EscalationResolutionError,
    EscalationRuntimeError,
)
from app.escalation.identity import (
    derive_escalation_id,
    derive_escalation_override_action_id,
    derive_escalation_override_decision_id,
    derive_escalation_outbox_claim_id,
    derive_escalation_outbox_id,
)
from app.escalation.persistence import (
    EscalationOutboxQuery,
    EscalationOutboxRecord,
    EscalationPage,
    EscalationPersistenceProtocol,
    EscalationQuery,
    EscalationRecord,
)
from app.governance.enums import Decision
from app.governance.persistence import (
    BaseGovernanceRepository,
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    PolicyEvaluationResultRecord,
)
from app.session.identity import as_session_id
from app.session.persistence import SessionPersistenceProtocol

_SESSION_METADATA_KEYS = (
    "session_id",
    "session.id",
    "operational_session_id",
    "operational.session_id",
)
_OVERRIDE_POLICY_CHAIN_ID = "escalation.manager_override"
_OVERRIDE_POLICY_NAME = "escalation.human_approval"
_OVERRIDE_RULE_ID = "manager_override"
_OVERRIDE_HANDLER = "human_manager_override"
_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EscalationOutboxClaimResult:
    """Outcome of claiming one escalation outbox row."""

    claimed: bool
    outbox: EscalationOutboxRecord | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class EscalationOutboxReconcileSweepResult:
    """Rows recovered from stuck escalation publication state."""

    requeued: tuple[EscalationOutboxRecord, ...]


@dataclass(frozen=True, slots=True)
class EscalationOutboxPreparation:
    """Escalation record plus its durable publication row."""

    escalation: EscalationRecord
    outbox: EscalationOutboxRecord


class EscalationAgentRuntime:
    """Creates and resolves human approval queue records.

    The agent entrypoint creates pending escalation records only from
    persisted governance DENY lineage. Manager approval/rejection is
    a separate runtime method used by the Command Center service.
    """

    def __init__(
        self,
        *,
        escalation_persistence: EscalationPersistenceProtocol,
        governance_repository: BaseGovernanceRepository,
        session_persistence: SessionPersistenceProtocol,
    ) -> None:
        self._escalations = escalation_persistence
        self._governance = governance_repository
        self._sessions = session_persistence

    async def create_for_governance_denial(
        self,
        *,
        governance_decision_id: str,
        expected_tenant_id: str,
        session_id: str | None = None,
    ) -> EscalationRecord:
        """Create or return the pending escalation for one DENY decision."""

        _require_nonempty(expected_tenant_id, "expected_tenant_id")
        existing = await self._escalations.get_escalation_for_governance_decision(
            governance_decision_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is not None:
            return existing

        decision = await self._governance.get_decision(
            governance_decision_id,
            expected_tenant_id=expected_tenant_id,
        )
        if decision is None:
            raise EscalationRuntimeError(
                "unknown governance decision for escalation: "
                f"{governance_decision_id}"
            )
        if decision.decision != Decision.DENY.value:
            raise EscalationRuntimeError(
                "escalation records can only be created from governance DENY"
            )
        if decision.tenant_id != expected_tenant_id:
            raise EscalationRuntimeError(
                "governance decision tenant_id does not match expected_tenant_id"
            )

        resolved_session_id = session_id or _session_id_from_metadata(
            decision.metadata
        )
        if resolved_session_id is None:
            raise EscalationRuntimeError(
                "governance denial lineage does not include a session_id"
            )
        session = await self._sessions.get_session(
            as_session_id(resolved_session_id),
            expected_tenant_id=expected_tenant_id,
        )
        if session is None:
            raise EscalationRuntimeError(
                "governance denial session is absent or tenant-invisible: "
                f"{resolved_session_id}"
            )

        now = datetime.now(timezone.utc)
        escalation_id = derive_escalation_id(
            tenant_id=expected_tenant_id,
            session_id=resolved_session_id,
            governance_decision_id=governance_decision_id,
        )
        record = EscalationRecord(
            escalation_id=str(escalation_id),
            session_id=str(resolved_session_id),
            tenant_id=expected_tenant_id,
            reason=decision.reason,
            governance_decision_id=decision.decision_id,
            status=EscalationStatus.PENDING.value,
            created_at=now.isoformat(),
            metadata={
                "projection_source": "governance_denial",
                "source_governance_decision_id": decision.decision_id,
                "source_policy_chain_id": decision.policy_chain_id,
                "source_stage": decision.stage,
                "source_subject_kind": decision.subject_kind,
                "source_request_id": decision.request_id,
                "source_correlation_id": decision.correlation_id,
                "session_id": str(resolved_session_id),
                "record_only_agent": True,
            },
        )
        await self._escalations.create_escalation(
            record,
            expected_tenant_id=expected_tenant_id,
        )
        return record

    async def get_escalation(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str,
    ) -> EscalationRecord | None:
        _require_nonempty(expected_tenant_id, "expected_tenant_id")
        return await self._escalations.get_escalation(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_escalations(
        self,
        *,
        query: EscalationQuery,
        expected_tenant_id: str,
    ) -> EscalationPage:
        _require_nonempty(expected_tenant_id, "expected_tenant_id")
        return await self._escalations.list_escalations(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def ensure_outbox_for_escalation(
        self,
        record: EscalationRecord,
        *,
        expected_tenant_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> EscalationOutboxRecord:
        """Create or return the durable publication row for an escalation."""

        _require_nonempty(expected_tenant_id, "expected_tenant_id")
        if record.tenant_id != expected_tenant_id:
            raise EscalationRuntimeError(
                "escalation tenant_id does not match expected_tenant_id"
            )
        existing = await self._escalations.get_escalation_outbox_by_escalation(
            record.escalation_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is not None:
            return existing
        now = datetime.now(timezone.utc)
        outbox = EscalationOutboxRecord(
            outbox_id=str(
                derive_escalation_outbox_id(
                    escalation_id=record.escalation_id,
                    tenant_id=record.tenant_id,
                )
            ),
            escalation_id=record.escalation_id,
            tenant_id=record.tenant_id,
            status=EscalationOutboxStatus.PENDING,
            created_at=now,
            metadata={
                "governance_decision_id": record.governance_decision_id,
                "session_id": record.session_id,
                **dict(metadata or {}),
            },
        )
        return await self._escalations.save_escalation_outbox(
            outbox,
            expected_tenant_id=expected_tenant_id,
        )

    async def prepare_governance_denial_outbox(
        self,
        *,
        governance_decision_id: str,
        expected_tenant_id: str,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EscalationOutboxPreparation:
        """Prepare the escalation publication row from denial lineage."""

        record = await self.create_for_governance_denial(
            governance_decision_id=governance_decision_id,
            expected_tenant_id=expected_tenant_id,
            session_id=session_id,
        )
        outbox = await self.ensure_outbox_for_escalation(
            record,
            expected_tenant_id=expected_tenant_id,
            metadata=metadata,
        )
        return EscalationOutboxPreparation(escalation=record, outbox=outbox)

    async def get_outbox_by_escalation(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str,
    ) -> EscalationOutboxRecord | None:
        _require_nonempty(expected_tenant_id, "expected_tenant_id")
        return await self._escalations.get_escalation_outbox_by_escalation(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def claim_outbox_for_escalation(
        self,
        *,
        escalation_id: str,
        publisher_id: str,
        expected_tenant_id: str,
    ) -> EscalationOutboxClaimResult:
        """Transition a pending outbox row to publishing."""

        _require_nonempty(publisher_id, "publisher_id")
        _require_nonempty(expected_tenant_id, "expected_tenant_id")
        current = await self._escalations.get_escalation_outbox_by_escalation(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )
        if current is None:
            return EscalationOutboxClaimResult(
                claimed=False,
                outbox=None,
                reason="outbox_missing",
            )
        if current.status is not EscalationOutboxStatus.PENDING:
            return EscalationOutboxClaimResult(
                claimed=False,
                outbox=current,
                reason=f"outbox_not_publishable:{current.status.value}",
            )
        next_republish_count = current.republish_count + 1
        claim_id = str(
            derive_escalation_outbox_claim_id(
                outbox_id=current.outbox_id,
                publisher_id=publisher_id,
                republish_count=next_republish_count,
            )
        )
        claimed_at = datetime.now(timezone.utc)
        claimed = await self._escalations.claim_escalation_outbox(
            escalation_id=escalation_id,
            publisher_id=publisher_id,
            claim_id=claim_id,
            claimed_at=claimed_at,
            expected_tenant_id=expected_tenant_id,
        )
        if claimed is None:
            return EscalationOutboxClaimResult(
                claimed=False,
                outbox=None,
                reason="outbox_claim_lost",
            )
        return EscalationOutboxClaimResult(
            claimed=(
                claimed.status is EscalationOutboxStatus.PUBLISHING
                and claimed.publisher_id == publisher_id
                and claimed.claim_id == claim_id
                and claimed.republish_count == next_republish_count
            ),
            outbox=claimed,
            reason=None
            if claimed.status is EscalationOutboxStatus.PUBLISHING
            else f"outbox_not_publishable:{claimed.status.value}",
        )

    async def mark_outbox_published(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        expected_tenant_id: str,
    ) -> EscalationOutboxRecord:
        _require_nonempty(expected_tenant_id, "expected_tenant_id")
        _require_nonempty(claim_id, "claim_id")
        return await self._escalations.mark_escalation_outbox_published(
            outbox_id=outbox_id,
            claim_id=claim_id,
            published_at=datetime.now(timezone.utc),
            expected_tenant_id=expected_tenant_id,
        )

    async def mark_outbox_failed(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        error: str,
        expected_tenant_id: str,
        dead_letter: bool = False,
    ) -> EscalationOutboxRecord:
        _require_nonempty(expected_tenant_id, "expected_tenant_id")
        _require_nonempty(claim_id, "claim_id")
        return await self._escalations.mark_escalation_outbox_failed(
            outbox_id=outbox_id,
            claim_id=claim_id,
            error=error,
            failed_at=datetime.now(timezone.utc),
            dead_letter=dead_letter,
            expected_tenant_id=expected_tenant_id,
        )

    async def reconcile_stale_outbox_records(
        self,
        *,
        stale_before: datetime,
        expected_tenant_id: str | None = None,
        limit: int = 100,
    ) -> EscalationOutboxReconcileSweepResult:
        """Return stuck publishing rows to pending for re-publication."""

        page = await self._escalations.list_escalation_outbox(
            EscalationOutboxQuery(
                status=EscalationOutboxStatus.PUBLISHING,
                claimed_before_or_at=stale_before,
                limit=limit,
            ),
            expected_tenant_id=expected_tenant_id,
        )
        requeued: list[EscalationOutboxRecord] = []
        now = datetime.now(timezone.utc)
        for outbox in page.items:
            recovered = await self._escalations.requeue_stale_escalation_outbox(
                outbox_id=outbox.outbox_id,
                stale_before=stale_before,
                requeued_at=now,
                reason="stale_publishing_claim",
                expected_tenant_id=expected_tenant_id,
            )
            if recovered is not None:
                _logger.warning(
                    "stale_escalation_outbox_requeued",
                    extra={
                        "outbox_id": recovered.outbox_id,
                        "escalation_id": recovered.escalation_id,
                        "tenant_id": recovered.tenant_id,
                    },
                )
                requeued.append(recovered)
        return EscalationOutboxReconcileSweepResult(requeued=tuple(requeued))

    async def approve_escalation(
        self,
        *,
        escalation_id: str,
        resolution: str,
        resolved_by: str,
        expected_tenant_id: str,
    ) -> EscalationRecord:
        """Approve a pending escalation and create override provenance."""

        _require_nonempty(resolution, "resolution")
        _require_nonempty(resolved_by, "resolved_by")
        record = await self._require_record(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record.status == EscalationStatus.APPROVED.value:
            return record
        _ensure_resolvable(record)
        denied = await self._require_source_denial(
            record,
            expected_tenant_id=expected_tenant_id,
        )
        override_decision_id = await self._record_governance_override(
            record=record,
            denied=denied,
            resolution=resolution,
            resolved_by=resolved_by,
        )
        now = datetime.now(timezone.utc)
        updated = replace(
            record,
            status=EscalationStatus.APPROVED.value,
            resolved_at=now.isoformat(),
            resolution=resolution,
            resolved_by=resolved_by,
            metadata={
                **dict(record.metadata),
                "resolution_status": EscalationStatus.APPROVED.value,
                "governance_override_decision_id": str(override_decision_id),
                "resolved_by": resolved_by,
                "resolved_at": now.isoformat(),
                "resolution": resolution,
            },
        )
        await self._escalations.update_escalation(
            updated,
            expected_tenant_id=expected_tenant_id,
        )
        return updated

    async def reject_escalation(
        self,
        *,
        escalation_id: str,
        resolution: str,
        resolved_by: str,
        expected_tenant_id: str,
    ) -> EscalationRecord:
        """Reject a pending escalation without changing governance lineage."""

        _require_nonempty(resolution, "resolution")
        _require_nonempty(resolved_by, "resolved_by")
        record = await self._require_record(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record.status == EscalationStatus.REJECTED.value:
            return record
        _ensure_resolvable(record)
        await self._require_source_denial(
            record,
            expected_tenant_id=expected_tenant_id,
        )
        now = datetime.now(timezone.utc)
        updated = replace(
            record,
            status=EscalationStatus.REJECTED.value,
            resolved_at=now.isoformat(),
            resolution=resolution,
            resolved_by=resolved_by,
            metadata={
                **dict(record.metadata),
                "resolution_status": EscalationStatus.REJECTED.value,
                "denial_lineage_intact": True,
                "resolved_by": resolved_by,
                "resolved_at": now.isoformat(),
                "resolution": resolution,
            },
        )
        await self._escalations.update_escalation(
            updated,
            expected_tenant_id=expected_tenant_id,
        )
        return updated

    async def _require_record(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str,
    ) -> EscalationRecord:
        record = await self._escalations.get_escalation(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise EscalationNotFoundError(
                f"unknown escalation: {escalation_id}"
            )
        return record

    async def _require_source_denial(
        self,
        record: EscalationRecord,
        *,
        expected_tenant_id: str,
    ) -> GovernanceDecisionRecord:
        decision = await self._governance.get_decision(
            record.governance_decision_id,
            expected_tenant_id=expected_tenant_id,
        )
        if decision is None:
            raise EscalationRuntimeError(
                "source governance denial is absent or tenant-invisible"
            )
        if decision.decision != Decision.DENY.value:
            raise EscalationRuntimeError(
                "source governance decision is no longer a DENY record"
            )
        return decision

    async def _record_governance_override(
        self,
        *,
        record: EscalationRecord,
        denied: GovernanceDecisionRecord,
        resolution: str,
        resolved_by: str,
    ) -> str:
        override_decision_id = str(
            derive_escalation_override_decision_id(
                escalation_id=record.escalation_id,
                governance_decision_id=record.governance_decision_id,
                tenant_id=record.tenant_id,
            )
        )
        existing = await self._governance.get_decision(
            override_decision_id,
            expected_tenant_id=record.tenant_id,
        )
        if existing is not None:
            return override_decision_id

        now = datetime.now(timezone.utc)
        metadata = {
            "override_authority": "human_manager",
            "override": True,
            "escalation_id": record.escalation_id,
            "source_governance_decision_id": denied.decision_id,
            "source_decision": denied.decision,
            "source_policy_chain_id": denied.policy_chain_id,
            "session_id": record.session_id,
            "resolved_by": resolved_by,
            "resolution": resolution,
            "tenant_authority_source": "human_manager",
        }
        decision_record = GovernanceDecisionRecord(
            decision_id=override_decision_id,
            decision=Decision.ALLOW.value,
            stage=denied.stage,
            policy_chain_id=_OVERRIDE_POLICY_CHAIN_ID,
            reason=resolution,
            decided_at=now.isoformat(),
            correlation_id=denied.correlation_id,
            request_id=denied.request_id,
            tenant_id=record.tenant_id,
            subject_kind="escalation",
            governance_version="phase-3-c.manager-override.v1",
            evaluated_rules=(
                PolicyEvaluationResultRecord(
                    policy_name=_OVERRIDE_POLICY_NAME,
                    rule_id=_OVERRIDE_RULE_ID,
                    decision=Decision.ALLOW.value,
                    severity=10,
                    reason=resolution,
                    evaluated_at=now.isoformat(),
                    metadata=metadata,
                    policy_version="phase-3-c.manager-override.v1",
                ),
            ),
            metadata=metadata,
        )
        trace_record = GovernanceTraceRecord(
            decision_id=override_decision_id,
            request_id=denied.request_id,
            correlation_id=denied.correlation_id,
            stage=denied.stage,
            action="escalation:approve",
            resource=f"escalation:{record.escalation_id}",
            actor=resolved_by,
            tenant_id=record.tenant_id,
            subject_kind="escalation",
            started_at=now.isoformat(),
            ended_at=now.isoformat(),
            latency_ms=0.0,
            status="ok",
            final_decision=Decision.ALLOW.value,
            policy_chain_id=_OVERRIDE_POLICY_CHAIN_ID,
            rule_count=1,
            violation_count=0,
            restriction_count=0,
            enforcement_handler=_OVERRIDE_HANDLER,
            enforcement_status="applied",
            enforcement_latency_ms=0.0,
            metadata=metadata,
        )
        action_record = EnforcementActionRecord(
            action_id=str(
                derive_escalation_override_action_id(
                    escalation_id=record.escalation_id,
                    override_decision_id=override_decision_id,
                    tenant_id=record.tenant_id,
                )
            ),
            handler_name=_OVERRIDE_HANDLER,
            decision_id=override_decision_id,
            outcome="applied",
            applied_at=now.isoformat(),
            detail=resolution,
            metadata=metadata,
        )
        await self._governance.record_decision(decision_record)
        await self._governance.record_trace(trace_record)
        await self._governance.record_enforcement_action(action_record)
        return override_decision_id


def _session_id_from_metadata(metadata: Mapping[str, Any]) -> str | None:
    for key in _SESSION_METADATA_KEYS:
        value = metadata.get(key)
        if value is not None:
            text = str(value)
            if text:
                return text
    return None


def _ensure_resolvable(record: EscalationRecord) -> None:
    if record.status not in {
        EscalationStatus.PENDING.value,
        EscalationStatus.REVIEWED.value,
    }:
        raise EscalationResolutionError(
            "only pending or reviewed escalations can be resolved"
        )


def _require_nonempty(value: str, name: str) -> None:
    if not value or not value.strip():
        raise EscalationRuntimeError(f"{name} is required")


__all__ = ["EscalationAgentRuntime"]
