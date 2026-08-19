"""Transactional, synthetic-only Northstar recording fixture seeder.

This module contains no connector, worker, task, outbox, or provider call.
It is deliberately an operator-invoked local command surface, not a route.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Awaitable
from typing import Callable, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from app.agents.tools.approvals import (
    PostgresActionApprovalRepository,
    build_pending_action_approval,
)
from app.events import PostgresOperationalEventPersistence
from app.events.appender import OperationalEventAppender
from app.governance.persistence import (
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    PostgresGovernanceRepository,
)
from app.qa.persistence import PostgresQAPersistence, QAScoreRecord
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import as_resolution_proposal_id
from app.resolution.persistence import (
    PostgresResolutionProposalPersistence,
    ResolutionProposalRecord,
)
from app.runtime.resolution_runtime import resolution_proposal_timeline_payload
from app.services.tenant_lifecycle_service import TenantLifecycleService
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import SessionEventId, SessionId, SessionLineageId
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionEventRecord,
    SessionRecord,
)
from app.supervisor.persistence import (
    InspectionRecord,
    PostgresSupervisorRepository,
    SupervisorDecisionRecord,
)
from app.tenant.lifecycle import PostgresTenantLifecycleRepository

from .manifest import (
    MANIFEST,
    NorthstarDemoManifest,
    SEEDED_SESSION_SEQUENCE_HEAD,
    stable_id,
)
from .locking import (
    NORTHSTAR_SEED_LOCK_TIMEOUT_MILLISECONDS,
    acquire_northstar_seed_transaction_lock,
    is_postgres_lock_timeout,
)
from .verifier import (
    NorthstarVerificationClassification,
    verify_northstar_fixture,
)


class NorthstarSeedSafetyError(RuntimeError):
    """Raised when fixture state is not exactly absent or exactly complete."""


class NorthstarSeedFailurePhase(StrEnum):
    """The only transaction-owner failure phases exposed by the seed path."""

    PRECOMMIT_FAILURE = "PRECOMMIT_FAILURE"
    COMMIT_OUTCOME_UNKNOWN = "COMMIT_OUTCOME_UNKNOWN"


class NorthstarPreDurableCommitRejected(NorthstarSeedSafetyError):
    """A locally known rejection before the driver has been asked to commit."""

    phase = NorthstarSeedFailurePhase.PRECOMMIT_FAILURE

    def __init__(self) -> None:
        super().__init__("Northstar seed rejected before durable commit")


class NorthstarCommitOutcomeUnknown(NorthstarSeedSafetyError):
    """The commit request raised; durable PostgreSQL outcome is unknowable here."""

    phase = NorthstarSeedFailurePhase.COMMIT_OUTCOME_UNKNOWN

    def __init__(self) -> None:
        # Deliberately do not retain or expose a database-driver exception.
        super().__init__("Northstar seed commit outcome is unknown")


class NorthstarConcurrentExecutionBusy(NorthstarSeedSafetyError):
    """The transaction-local PostgreSQL advisory lock did not become free."""

    def __init__(self) -> None:
        super().__init__("Northstar seed is already executing for this tenant")


class SeedStage(StrEnum):
    TENANT_AND_LIFECYCLE = "tenant_and_lifecycle"
    SESSION = "session"
    TIMELINE_SESSION_OPENED = "timeline_session_opened"
    TIMELINE_CUSTOMER_MESSAGE = "timeline_customer_message"
    TIMELINE_RESOLUTION_PROPOSAL_CREATED = "timeline_resolution_proposal_created"
    GOVERNANCE_DECISION = "governance_decision"
    GOVERNANCE_TRACE = "governance_trace"
    HELD_RESOLUTION_PROPOSAL = "held_resolution_proposal"
    PENDING_REPLACEMENT_APPROVAL = "pending_replacement_approval"
    SUPERVISOR_INSPECTION = "supervisor_inspection"
    QA_SCORE = "qa_score"
    FINAL_FLUSH = "final_flush"
    FINAL_COMPLETE_MATCH_VERIFICATION = "final_complete_match_verification"
    IMMEDIATELY_BEFORE_COMMIT = "immediately_before_commit"


class SeedInjectedFailure(RuntimeError):
    """Synthetic test-only failure raised at a fixed seed stage."""


SeedFailureInjector = Callable[[SeedStage], bool]
PreDurableCommitHook = Callable[[], Awaitable[None]]
PostLockBarrier = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class NorthstarSeedVerification:
    state: Literal["absent", "complete"]
    tenant_id: str
    session_id: str


class NorthstarDemoSeedService:
    """Creates the fixed synthetic fixture in one caller-owned transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        manifest: NorthstarDemoManifest = MANIFEST,
        failure_injector: SeedFailureInjector | None = None,
        pre_durable_commit_hook: PreDurableCommitHook | None = None,
        serialize_execution: bool = False,
        post_lock_barrier: PostLockBarrier | None = None,
        lock_timeout_milliseconds: int = NORTHSTAR_SEED_LOCK_TIMEOUT_MILLISECONDS,
    ) -> None:
        self._session = session
        self._manifest = manifest
        self._failure_injector = failure_injector
        self._pre_durable_commit_hook = pre_durable_commit_hook
        self._serialize_execution = serialize_execution
        self._post_lock_barrier = post_lock_barrier
        self._lock_timeout_milliseconds = lock_timeout_milliseconds

    async def verify(self) -> NorthstarSeedVerification:
        """Map the canonical verifier into the legacy seed-state contract."""
        # Tenant registry is platform-gated; this only scopes the current
        # transaction and never writes a tenant row.
        await self._session.execute(
            text("SELECT set_config('app.platform_tenant_admin', 'true', true)")
        )
        await self._set_tenant_context()
        result = await verify_northstar_fixture(
            self._session, manifest=self._manifest
        )
        if result.classification is NorthstarVerificationClassification.ABSENT:
            return NorthstarSeedVerification("absent", self._manifest.tenant_id, str(self._manifest.session_id))
        if result.classification is not NorthstarVerificationClassification.COMPLETE_MATCH:
            raise NorthstarSeedSafetyError("Northstar demo state does not match immutable manifest")
        return NorthstarSeedVerification("complete", self._manifest.tenant_id, str(self._manifest.session_id))

    async def seed(self) -> NorthstarSeedVerification:
        """Commit the entire fixture once, or leave no partial fixture rows."""
        if self._session.in_transaction():
            raise NorthstarSeedSafetyError(
                "seed service requires a fresh session so it can own one atomic transaction"
            )
        transaction = await self._session.begin()
        try:
            if self._serialize_execution:
                try:
                    await acquire_northstar_seed_transaction_lock(
                        self._session,
                        tenant_id=self._manifest.tenant_id,
                        timeout_milliseconds=self._lock_timeout_milliseconds,
                    )
                except Exception as exc:
                    if is_postgres_lock_timeout(exc):
                        raise NorthstarConcurrentExecutionBusy() from None
                    raise
                if self._post_lock_barrier is not None:
                    await self._post_lock_barrier()
            state = await self.verify()
            if state.state == "complete":
                await self._attempt_durable_commit(transaction)
                return state
            lifecycle = TenantLifecycleService(
                repository=PostgresTenantLifecycleRepository(self._session),
                event_appender=OperationalEventAppender(
                    persistence=PostgresOperationalEventPersistence(self._session)
                ),
                session=self._session,
            )
            await lifecycle.create_tenant_in_transaction(
                tenant_id=self._manifest.tenant_id, created_by="northstar-demo-seed"
            )
            self._checkpoint(SeedStage.TENANT_AND_LIFECYCLE)
            await self._set_tenant_context()
            await self._write_session()
            await self._write_governance()
            await self._write_proposal_and_inert_review()
            await self._write_supervisor_and_qa()
            await self._session.flush()
            self._checkpoint(SeedStage.FINAL_FLUSH)
            result = await verify_northstar_fixture(
                self._session, manifest=self._manifest
            )
            if result.classification is not NorthstarVerificationClassification.COMPLETE_MATCH:
                raise NorthstarSeedSafetyError("Northstar demo state does not match immutable manifest")
            self._checkpoint(SeedStage.FINAL_COMPLETE_MATCH_VERIFICATION)
            self._checkpoint(SeedStage.IMMEDIATELY_BEFORE_COMMIT)
            await self._attempt_durable_commit(transaction)
        except NorthstarCommitOutcomeUnknown:
            # The transaction must be discarded by the caller.  Rolling it
            # back here could incorrectly imply that no durable commit won.
            raise
        except Exception:
            if transaction.is_active:
                await transaction.rollback()
            raise
        return NorthstarSeedVerification("complete", self._manifest.tenant_id, str(self._manifest.session_id))

    async def _attempt_durable_commit(
        self, transaction: AsyncSessionTransaction
    ) -> None:
        """Cross the durable boundary once, preserving ambiguity on driver error."""

        if self._pre_durable_commit_hook is not None:
            await self._pre_durable_commit_hook()
        try:
            await transaction.commit()
        except Exception as exc:
            del exc
            raise NorthstarCommitOutcomeUnknown() from None

    def _checkpoint(self, stage: SeedStage) -> None:
        if self._failure_injector is not None and self._failure_injector(stage):
            raise SeedInjectedFailure(stage.value)

    async def _set_tenant_context(self) -> None:
        await self._session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": self._manifest.tenant_id},
        )

    async def _write_session(self) -> None:
        repository = PostgresSessionPersistence(self._session)
        session_id = SessionId(self._manifest.session_id)
        await repository.save_session(SessionRecord(
            session_id=session_id, scope=SessionScope.TENANT,
            external_handle="northstar-clueso-demo-maya-chen",
            tenant_id=self._manifest.tenant_id, principal_id="northstar-demo-seed",
            opened_at=self._manifest.opened_at, lifecycle_phase=SessionLifecyclePhase.DORMANT,
            lifecycle_recorded_at=self._manifest.inspection_at,
            lifecycle_reason="synthetic demo held for human review",
            lineage_id=SessionLineageId(self._manifest.session_id), root_session_id=session_id,
            parent_session_id=None, ancestor_session_ids=(), lineage_depth=0,
            sequence_head=SEEDED_SESSION_SEQUENCE_HEAD, revision=1, context_environment="synthetic-demo",
            context_labels=("synthetic", "northstar", "clueso"),
            context_attributes={"customer_name": self._manifest.customer_name, "customer_email": self._manifest.customer_email},
            metadata={"synthetic": True, "inert": True},
        ))
        self._checkpoint(SeedStage.SESSION)
        events = (
            (0, SessionEventKind.SESSION_OPENED, self._manifest.opened_at, {"synthetic": True}),
            (1, SessionEventKind.CUSTOMER_MESSAGE, self._manifest.customer_message_at, {"author": "Maya Chen", "message": "My device arrived damaged. Can you help?", "synthetic": True}),
        )
        for sequence, kind, occurred_at, payload in events:
            await repository.save_event(SessionEventRecord(
                event_id=SessionEventId(stable_id(f"session-event-{sequence}")), session_id=session_id,
                sequence=sequence, kind=kind, continuity_mode=SessionContinuityMode.DEFERRED,
                occurred_at=occurred_at, recorded_at=occurred_at, payload=payload,
                idempotency_key=str(stable_id(f"session-event-idempotency-{sequence}")),
                metadata={"synthetic": True, "inert": True},
            ))
            self._checkpoint(
                SeedStage.TIMELINE_SESSION_OPENED
                if sequence == 0
                else SeedStage.TIMELINE_CUSTOMER_MESSAGE
            )

    async def _write_governance(self) -> None:
        repository = PostgresGovernanceRepository(self._session)
        decision_id = str(self._manifest.governance_decision_id)
        timestamp = self._manifest.governance_at.isoformat()
        await repository.record_decision(GovernanceDecisionRecord(
            decision_id=decision_id, decision="require_approval", stage="resolution_governance_gate",
            policy_chain_id="northstar-demo-synthetic-v1", reason="replacement is a goods commitment",
            decided_at=timestamp, tenant_id=self._manifest.tenant_id, subject_kind="agent_action",
            governance_version="synthetic-demo-v1", metadata={"synthetic": True, "inert": True},
        ))
        self._checkpoint(SeedStage.GOVERNANCE_DECISION)
        await repository.record_trace(GovernanceTraceRecord(
            decision_id=decision_id, request_id=str(self._manifest.session_id), correlation_id=None,
            stage="resolution_governance_gate", action="replacement.order", resource="synthetic-case",
            actor="northstar-demo-seed", tenant_id=self._manifest.tenant_id, subject_kind="agent_action",
            started_at=timestamp, ended_at=timestamp, latency_ms=0.0, status="completed",
            final_decision="require_approval", policy_chain_id="northstar-demo-synthetic-v1",
            rule_count=1, violation_count=0, restriction_count=1, enforcement_handler=None,
            enforcement_status=None, enforcement_latency_ms=None, metadata={"synthetic": True, "inert": True},
        ))
        self._checkpoint(SeedStage.GOVERNANCE_TRACE)

    async def _write_proposal_and_inert_review(self) -> None:
        proposal = ResolutionProposalRecord(
                proposal_id=as_resolution_proposal_id(self._manifest.proposal_id), tenant_id=self._manifest.tenant_id,
                session_id=str(self._manifest.session_id), execution_id=None,
                dispatch_id=str(stable_id("synthetic-dispatch")), diagnostic_event_id=None,
                proposed_customer_reply="I’m sorry the device arrived damaged. A replacement has been proposed for human review.",
                resolution_category="synthetic_demo", confidence=1.0,
                supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
                governance_verdict=ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
                autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
                status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
                created_at=self._manifest.proposal_at, updated_at=self._manifest.proposal_at,
                governance_decision_id=self._manifest.governance_decision_id,
                recommended_actions=({"type": "replacement.order", "label": "Review proposed replacement", "requires_execution": True},),
                evidence=({"source": "synthetic_case", "customer": "Maya Chen"},),
                metadata={"synthetic": True, "inert": True, "gate_reasons": ["goods_commitment_requires_human_approval"]},
            )
        await PostgresResolutionProposalPersistence(self._session).create_resolution_proposal(
            proposal, expected_tenant_id=self._manifest.tenant_id,
        )
        self._checkpoint(SeedStage.HELD_RESOLUTION_PROPOSAL)
        await self._append_proposal_timeline_event(proposal)
        self._checkpoint(SeedStage.TIMELINE_RESOLUTION_PROPOSAL_CREATED)
        # This approval is review-only: no worker queries action approvals, the
        # recorder cannot approve actions, and the empty tenant has no configured tool.
        approval = build_pending_action_approval(
            tenant_id=self._manifest.tenant_id, session_id=str(self._manifest.session_id), execution_id=None,
            tool_name="replacement.order", idempotency_key=str(self._manifest.approval_idempotency_key),
            payload_json={"synthetic": True, "review_only": True},
            governance_decision_id=str(self._manifest.governance_decision_id),
            metadata={"synthetic": True, "simulation": True, "inert": True, "no_connector": True},
            proposed_by="northstar-demo-seed",
        )
        if str(approval.approval_id) != str(self._manifest.approval_id):
            raise NorthstarSeedSafetyError("approval identifier derivation drifted")
        await PostgresActionApprovalRepository(self._session).create_pending_approval(
            approval, expected_tenant_id=self._manifest.tenant_id
        )
        self._checkpoint(SeedStage.PENDING_REPLACEMENT_APPROVAL)

    async def _append_proposal_timeline_event(
        self, proposal: ResolutionProposalRecord
    ) -> None:
        """Append the canonical production-style proposal timeline envelope."""
        payload = {
            "session_id": str(self._manifest.session_id),
            "dispatch_id": proposal.dispatch_id,
            "tenant_id": self._manifest.tenant_id,
            "event_type": "resolution_proposal_created",
            "timestamp": self._manifest.proposal_at.isoformat(),
            "payload": resolution_proposal_timeline_payload(proposal),
        }
        await PostgresSessionPersistence(self._session).save_event(
            SessionEventRecord(
                event_id=SessionEventId(stable_id("session-event-2")),
                session_id=SessionId(self._manifest.session_id), sequence=2,
                kind=SessionEventKind.OPERATIONAL_OBSERVATION,
                continuity_mode=SessionContinuityMode.DEFERRED,
                occurred_at=self._manifest.proposal_at,
                recorded_at=self._manifest.proposal_at, payload=payload,
                annotation="resolution_proposal_created",
                idempotency_key=str(stable_id("session-event-idempotency-2")),
                governance_decision_id=self._manifest.governance_decision_id,
                governance_chain_id="northstar-demo-synthetic-v1",
                metadata={"synthetic": True, "inert": True},
            )
        )

    async def _write_supervisor_and_qa(self) -> None:
        inspection_id = str(self._manifest.inspection_id)
        timestamp = self._manifest.inspection_at.isoformat()
        decision = SupervisorDecisionRecord(
            decision_id=str(stable_id("supervisor-decision")), kind="needs_human_review", aggregate_score=1.0,
            finding_ids=(), escalation_ids=(), reason="synthetic replacement remains held", decided_at=timestamp,
            metadata={"synthetic": True, "inert": True},
        )
        await PostgresSupervisorRepository(self._session).record_inspection(InspectionRecord(
            inspection_id=inspection_id, execution_id=str(self._manifest.execution_id),
            runtime_instance_id=str(stable_id("supervisor-runtime")), correlation_id=str(self._manifest.session_id),
            request_id=str(self._manifest.session_id), tenant_id=self._manifest.tenant_id,
            inspection_mode="synthetic_demo", decision=decision, evaluator_names=("synthetic-demo-qa",),
            started_at=timestamp, ended_at=timestamp, latency_ms=0.0,
            tenant_authority_source="explicit", metadata={"synthetic": True, "inert": True},
        ))
        self._checkpoint(SeedStage.SUPERVISOR_INSPECTION)
        await PostgresQAPersistence(self._session).record_score(QAScoreRecord(
            score_id=str(self._manifest.qa_score_id), inspection_id=inspection_id,
            execution_id=str(self._manifest.execution_id), tenant_id=self._manifest.tenant_id,
            tenant_authority_source="explicit", diagnostic_accuracy=1.0, policy_compliance=1.0,
            timeline_integrity=1.0, resolution_quality=1.0, overall_score=1.0,
            supervisor_decision_kind="needs_human_review", finding_count=0, evaluation_count=0,
            escalation_count=0, scored_at=timestamp, metadata={"synthetic": True, "inert": True},
        ), expected_tenant_id=self._manifest.tenant_id)
        self._checkpoint(SeedStage.QA_SCORE)
