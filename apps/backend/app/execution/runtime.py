"""ExecutionRuntime: durable execution authority boundary."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping, cast

from app.execution.enums import (
    ExecutionAttemptState,
    ExecutionKind,
    ExecutionOutboxState,
    ExecutionState,
)
from app.execution.admission import GovernanceAdmissionToken
from app.execution.envelope import ExecutionResultEnvelope
from app.execution.exceptions import ExecutionNotClaimableError
from app.execution.exceptions import ExecutionAdmissionError
from app.execution.identity import (
    ExecutionAttemptId,
    ExecutionId,
    ExecutionOutboxClaimId,
    ExecutionOutboxId,
    as_attempt_id,
    as_execution_id,
    as_outbox_claim_id,
    as_outbox_id,
    derive_execution_id,
    derive_outbox_claim_id,
    derive_outbox_id,
)
from app.execution.persistence import (
    ExecutionAttemptPage,
    ExecutionAttemptQuery,
    ExecutionAttemptRecord,
    ExecutionClaimLost,
    ExecutionPage,
    ExecutionOutboxClaimLost,
    ExecutionOutboxRecord,
    ExecutionOutboxTransitionResult,
    ExecutionPersistenceProtocol,
    ExecutionQuery,
    ExecutionRecord,
    ExecutionTransitionResult,
    OutboxPage,
    OutboxQuery,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExecutionRequestResult:
    """Result of admitting an execution intent."""

    execution: ExecutionRecord


@dataclass(frozen=True, slots=True)
class ExecutionClaimResult:
    """Result of a worker claim attempt."""

    claimed: bool
    execution: ExecutionRecord | None
    attempt: ExecutionAttemptRecord | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionOutboxClaimResult:
    """Result of claiming a durable transport intent."""

    claimed: bool
    outbox: ExecutionOutboxRecord | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionOutboxReconcileResult:
    """Result of one stale outbox reconciliation attempt."""

    reconciled: bool
    outbox: ExecutionOutboxRecord | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionOutboxReconcileSweepResult:
    """Inspectable result of one stale outbox reconciliation sweep."""

    scanned: int
    reconciled: tuple[ExecutionOutboxReconcileResult, ...]
    refused: tuple[ExecutionOutboxReconcileResult, ...] = ()

    @property
    def reconciled_count(self) -> int:
        return len(self.reconciled)

    @property
    def refused_count(self) -> int:
        return len(self.refused)


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryResult:
    """Result of reopening a stale worker claim."""

    recovered: bool
    execution: ExecutionRecord | None
    attempt: ExecutionAttemptRecord | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionRecoverySweepResult:
    """Inspectable result of one stale-claim recovery sweep."""

    scanned: int
    recovered: tuple[ExecutionRecoveryResult, ...]
    refused: tuple[ExecutionRecoveryResult, ...] = ()

    @property
    def recovered_count(self) -> int:
        return len(self.recovered)

    @property
    def refused_count(self) -> int:
        return len(self.refused)


@dataclass(frozen=True, slots=True)
class ExecutionWorkerLegitimacyResult:
    """Read-only verdict for a worker attempting side effects."""

    legitimate: bool
    execution: ExecutionRecord | None
    attempt: ExecutionAttemptRecord | None = None
    reason: str | None = None


class ExecutionRuntime:
    """Apex execution authority.

    This runtime does not execute agents and does not publish transport
    messages. It owns the durable right to execute and the state
    transitions around that right.
    """

    def __init__(
        self,
        *,
        persistence: ExecutionPersistenceProtocol,
    ) -> None:
        self._persistence = persistence

    @property
    def persistence(self) -> ExecutionPersistenceProtocol:
        return self._persistence

    async def get_execution(
        self,
        execution_id: ExecutionId | str,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionRecord | None:
        """Read an execution through the runtime authority boundary."""

        _validate_optional_tenant_id(expected_tenant_id)
        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        return await self._persistence.get_execution(
            eid,
            expected_tenant_id=expected_tenant_id,
        )

    async def get_execution_by_dispatch(
        self,
        *,
        dispatch_id: str,
        kind: ExecutionKind,
        expected_tenant_id: str,
    ) -> ExecutionRecord | None:
        """Read an execution intent by dispatch identity and tenant."""

        if not dispatch_id:
            raise ValueError("dispatch_id must be non-empty")
        if not expected_tenant_id:
            raise ValueError("expected_tenant_id must be non-empty")
        return await self._persistence.get_execution_by_dispatch(
            dispatch_id=dispatch_id,
            kind=kind,
            expected_tenant_id=expected_tenant_id,
        )

    async def get_attempt(
        self,
        attempt_id: ExecutionAttemptId | str,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionAttemptRecord | None:
        """Read an execution attempt, optionally scoped by parent tenant."""

        _validate_optional_tenant_id(expected_tenant_id)
        aid = (
            attempt_id
            if not isinstance(attempt_id, str)
            else as_attempt_id(attempt_id)
        )
        attempt = await self._persistence.get_attempt(aid)
        if attempt is None or expected_tenant_id is None:
            return attempt
        parent = await self._persistence.get_execution(
            attempt.execution_id,
            expected_tenant_id=expected_tenant_id,
        )
        if parent is None:
            return None
        return attempt

    async def get_outbox(
        self,
        outbox_id: ExecutionOutboxId | str,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionOutboxRecord | None:
        """Read an outbox transport intent, optionally tenant scoped."""

        _validate_optional_tenant_id(expected_tenant_id)
        oid = (
            outbox_id
            if not isinstance(outbox_id, str)
            else as_outbox_id(outbox_id)
        )
        outbox = await self._persistence.get_outbox(oid)
        if outbox is None or expected_tenant_id is None:
            return outbox
        parent = await self._persistence.get_execution(
            outbox.execution_id,
            expected_tenant_id=expected_tenant_id,
        )
        if parent is None:
            return None
        return outbox

    async def get_outbox_by_execution(
        self,
        execution_id: ExecutionId | str,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionOutboxRecord | None:
        """Read the durable transport intent for one execution."""

        _validate_optional_tenant_id(expected_tenant_id)
        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        if expected_tenant_id is not None:
            parent = await self._persistence.get_execution(
                eid,
                expected_tenant_id=expected_tenant_id,
            )
            if parent is None:
                return None
        return await self._persistence.get_outbox_by_execution(eid)

    async def list_executions(
        self,
        query: ExecutionQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionPage:
        """List executions through the runtime authority boundary."""

        _validate_optional_tenant_id(expected_tenant_id)
        return await self._persistence.list_executions(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_attempts(
        self,
        query: ExecutionAttemptQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionAttemptPage:
        """List execution attempts without creating timeline authority."""

        _validate_optional_tenant_id(expected_tenant_id)
        if expected_tenant_id is None:
            return await self._persistence.list_attempts(query)
        if query.execution_id is None:
            raise ValueError(
                "tenant-scoped attempt reads require execution_id"
            )
        parent = await self._persistence.get_execution(
            query.execution_id,
            expected_tenant_id=expected_tenant_id,
        )
        if parent is None:
            return ExecutionAttemptPage(
                attempts=(),
                total=0,
                offset=query.offset,
            )
        return await self._persistence.list_attempts(query)

    async def list_outbox(
        self,
        query: OutboxQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> OutboxPage:
        """List outbox transport intents through execution authority."""

        _validate_optional_tenant_id(expected_tenant_id)
        if (
            expected_tenant_id is not None
            and query.tenant_id is not None
            and query.tenant_id != expected_tenant_id
        ):
            return OutboxPage(records=(), total=0, offset=query.offset)
        if (
            expected_tenant_id is not None
            and query.tenant_id is None
            and query.execution_id is None
        ):
            raise ValueError(
                "tenant-scoped outbox reads require execution_id or tenant_id"
            )
        if expected_tenant_id is not None and query.tenant_id is None:
            query = replace(query, tenant_id=expected_tenant_id)
        return await self._persistence.list_outbox(query)

    async def request_diagnostic_execution(
        self,
        *,
        dispatch_id: str,
        session_id: str,
        tenant_id: str,
        admission_token: GovernanceAdmissionToken,
        requested_at: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionRequestResult:
        """Create or retrieve the durable diagnostic execution intent."""

        if not tenant_id:
            raise ValueError("execution request requires tenant_id")
        admission = cast(GovernanceAdmissionToken | None, admission_token)
        if admission is None:
            raise ExecutionAdmissionError(
                "diagnostic execution requires governance admission"
            )
        if admission.tenant_id != tenant_id:
            raise ExecutionAdmissionError(
                "governance admission token tenant does not match execution tenant"
            )
        ts = requested_at or datetime.now(tz=timezone.utc)
        request_metadata = dict(metadata or {})
        request_metadata.setdefault(
            "governance.decision_id",
            str(admission.governance_decision_id),
        )
        request_metadata["execution_governance.evaluation_id"] = str(
            admission.execution_governance_evaluation_id
        )
        request_metadata["execution_governance.admitted_at"] = (
            admission.admitted_at.isoformat()
        )
        execution_id = derive_execution_id(
            kind=ExecutionKind.DIAGNOSTIC_AGENT.value,
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
        )
        execution = ExecutionRecord(
            execution_id=execution_id,
            kind=ExecutionKind.DIAGNOSTIC_AGENT,
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
            state=ExecutionState.REQUESTED,
            attempt_count=0,
            requested_at=ts,
            governance_decision_id=admission.governance_decision_id,
            execution_governance_evaluation_id=(
                admission.execution_governance_evaluation_id
            ),
            governance_admitted_at=admission.admitted_at,
            metadata=request_metadata,
        )
        outbox = ExecutionOutboxRecord(
            outbox_id=derive_outbox_id(execution_id=execution_id),
            execution_id=execution_id,
            state=ExecutionOutboxState.PENDING,
            created_at=ts,
            metadata={
                "execution.kind": ExecutionKind.DIAGNOSTIC_AGENT.value,
                **request_metadata,
            },
        )
        persisted = await self._persistence.request_execution(
            execution=execution,
            outbox=outbox,
        )
        return ExecutionRequestResult(execution=persisted)

    async def claim_execution(
        self,
        *,
        execution_id: ExecutionId | str,
        worker_id: str,
        claimed_at: datetime | None = None,
    ) -> ExecutionClaimResult:
        """Atomically claim an execution before worker logic runs."""

        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        claimed = await self._persistence.claim_execution(
            execution_id=eid,
            worker_id=worker_id,
            claimed_at=claimed_at or datetime.now(tz=timezone.utc),
        )
        if claimed is not None:
            return ExecutionClaimResult(
                claimed=True,
                execution=claimed.execution,
                attempt=claimed.attempt,
            )
        current = await self._persistence.get_execution(eid)
        if current is None:
            return ExecutionClaimResult(
                claimed=False, execution=None, reason="execution_not_found"
            )
        return ExecutionClaimResult(
            claimed=False,
            execution=current,
            reason=f"execution_not_claimable:{current.state.value}",
        )

    async def complete_execution(
        self,
        *,
        execution_id: ExecutionId | str,
        attempt_id: ExecutionAttemptId | str | None = None,
        worker_id: str,
        result: Mapping[str, Any],
        completed_at: datetime | None = None,
    ) -> ExecutionTransitionResult:
        _validate_worker_id(worker_id)
        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        aid = (
            None
            if attempt_id is None
            else (
                attempt_id
                if not isinstance(attempt_id, str)
                else as_attempt_id(attempt_id)
            )
        )
        outcome = await self._persistence.complete_execution(
            execution_id=eid,
            attempt_id=aid,
            result=ExecutionResultEnvelope.from_dict(result).to_dict(),
            completed_at=completed_at or datetime.now(tz=timezone.utc),
            worker_id=worker_id,
        )
        if isinstance(outcome, ExecutionClaimLost):
            _log_execution_claim_lost(outcome, operation="complete")
        return outcome

    async def fail_execution(
        self,
        *,
        execution_id: ExecutionId | str,
        attempt_id: ExecutionAttemptId | str | None = None,
        worker_id: str,
        error: str,
        failed_at: datetime | None = None,
        retry_requested: bool = False,
        result: Mapping[str, Any] | None = None,
    ) -> ExecutionTransitionResult:
        _validate_worker_id(worker_id)
        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        aid = (
            None
            if attempt_id is None
            else (
                attempt_id
                if not isinstance(attempt_id, str)
                else as_attempt_id(attempt_id)
            )
        )
        outcome = await self._persistence.fail_execution(
            execution_id=eid,
            attempt_id=aid,
            error=error,
            failed_at=failed_at or datetime.now(tz=timezone.utc),
            retry_requested=retry_requested,
            worker_id=worker_id,
            result=(
                ExecutionResultEnvelope.from_dict(result).to_dict()
                if result is not None
                else ExecutionResultEnvelope(
                    error_code="execution_failed",
                    error_message=error,
                ).to_dict()
            ),
        )
        if isinstance(outcome, ExecutionClaimLost):
            _log_execution_claim_lost(outcome, operation="fail")
        return outcome

    async def dead_letter_execution(
        self,
        *,
        execution_id: ExecutionId | str,
        attempt_id: ExecutionAttemptId | str | None = None,
        worker_id: str,
        error: str,
        dead_lettered_at: datetime | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> ExecutionTransitionResult:
        _validate_worker_id(worker_id)
        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        aid = (
            None
            if attempt_id is None
            else (
                attempt_id
                if not isinstance(attempt_id, str)
                else as_attempt_id(attempt_id)
            )
        )
        outcome = await self._persistence.dead_letter_execution(
            execution_id=eid,
            attempt_id=aid,
            error=error,
            dead_lettered_at=dead_lettered_at or datetime.now(tz=timezone.utc),
            worker_id=worker_id,
            result=(
                ExecutionResultEnvelope.from_dict(result).to_dict()
                if result is not None
                else ExecutionResultEnvelope(
                    error_code="execution_dead_lettered",
                    error_message=error,
                ).to_dict()
            ),
        )
        if isinstance(outcome, ExecutionClaimLost):
            _log_execution_claim_lost(outcome, operation="dead_letter")
        return outcome

    async def recover_stale_execution(
        self,
        *,
        execution_id: ExecutionId | str,
        stale_before: datetime,
        recovered_at: datetime | None = None,
        reason: str = "execution claim expired",
    ) -> ExecutionRecoveryResult:
        """Reopen an expired claimed execution without creating an attempt.

        Recovery marks the current running attempt as failed with
        ``retry_requested=True`` and returns the execution to
        ``REQUESTED``. The next legitimate worker claim creates the
        next deterministic attempt id.
        """

        if stale_before.tzinfo is None:
            raise ValueError("stale_before must be timezone-aware")
        if recovered_at is not None and recovered_at.tzinfo is None:
            raise ValueError("recovered_at must be timezone-aware")
        if not reason:
            raise ValueError("recovery reason must be non-empty")
        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        recovered = await self._persistence.recover_stale_execution(
            execution_id=eid,
            stale_before=stale_before,
            recovered_at=recovered_at or datetime.now(tz=timezone.utc),
            reason=reason,
        )
        if recovered is not None:
            return ExecutionRecoveryResult(
                recovered=True,
                execution=recovered.execution,
                attempt=recovered.attempt,
            )
        current = await self._persistence.get_execution(eid)
        if current is None:
            return ExecutionRecoveryResult(
                recovered=False,
                execution=None,
                reason="execution_not_found",
            )
        if current.state is not ExecutionState.CLAIMED:
            return ExecutionRecoveryResult(
                recovered=False,
                execution=current,
                reason=f"execution_not_claimed:{current.state.value}",
            )
        return ExecutionRecoveryResult(
            recovered=False,
            execution=current,
            reason="execution_not_stale",
        )

    async def recover_stale_executions(
        self,
        *,
        stale_before: datetime,
        recovered_at: datetime | None = None,
        reason: str = "execution claim expired",
        limit: int = 100,
        tenant_id: str | None = None,
    ) -> ExecutionRecoverySweepResult:
        """Recover a bounded page of stale claimed executions.

        This is the execution-owned reaper primitive. It selects only
        claimed executions older than ``stale_before`` and delegates
        each transition to ``recover_stale_execution`` so the same
        state machine and attempt lineage rules apply everywhere.
        """

        if stale_before.tzinfo is None:
            raise ValueError("stale_before must be timezone-aware")
        if recovered_at is not None and recovered_at.tzinfo is None:
            raise ValueError("recovered_at must be timezone-aware")
        if limit < 1:
            raise ValueError("limit must be positive")
        if not reason:
            raise ValueError("recovery reason must be non-empty")
        page = await self._persistence.list_executions(
            ExecutionQuery(
                tenant_id=tenant_id,
                state=ExecutionState.CLAIMED,
                claimed_before_or_at=stale_before,
                limit=limit,
            ),
            expected_tenant_id=tenant_id,
        )
        ts = recovered_at or datetime.now(tz=timezone.utc)
        recovered_results: list[ExecutionRecoveryResult] = []
        refused_results: list[ExecutionRecoveryResult] = []
        for execution in page.executions:
            result = await self.recover_stale_execution(
                execution_id=execution.execution_id,
                stale_before=stale_before,
                recovered_at=ts,
                reason=reason,
            )
            if result.recovered:
                recovered_results.append(result)
            else:
                refused_results.append(result)
        return ExecutionRecoverySweepResult(
            scanned=len(page.executions),
            recovered=tuple(recovered_results),
            refused=tuple(refused_results),
        )

    async def validate_worker_legitimacy(
        self,
        *,
        execution_id: ExecutionId | str,
        attempt_id: ExecutionAttemptId | str,
        worker_id: str,
    ) -> ExecutionWorkerLegitimacyResult:
        """Read-only worker ownership check before side effects."""

        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        aid = (
            attempt_id
            if not isinstance(attempt_id, str)
            else as_attempt_id(attempt_id)
        )
        execution = await self._persistence.get_execution(eid)
        if execution is None:
            return ExecutionWorkerLegitimacyResult(
                legitimate=False,
                execution=None,
                reason="execution_not_found",
            )
        attempt = await self._persistence.get_attempt(aid)
        if attempt is None:
            return ExecutionWorkerLegitimacyResult(
                legitimate=False,
                execution=execution,
                reason="attempt_not_found",
            )
        reason = _worker_legitimacy_violation(
            execution=execution,
            attempt=attempt,
            worker_id=worker_id,
        )
        return ExecutionWorkerLegitimacyResult(
            legitimate=reason is None,
            execution=execution,
            attempt=attempt,
            reason=reason,
        )

    async def claim_outbox_for_execution(
        self,
        *,
        execution_id: ExecutionId | str,
        publisher_id: str,
        claimed_at: datetime | None = None,
    ) -> ExecutionOutboxClaimResult:
        """Atomically claim the pending transport intent for an execution."""

        if not publisher_id:
            raise ValueError("publisher_id must be non-empty")
        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        current = await self._persistence.get_outbox_by_execution(eid)
        if current is None:
            return ExecutionOutboxClaimResult(
                claimed=False,
                outbox=None,
                reason="outbox_not_found",
            )
        if current.state is not ExecutionOutboxState.PENDING:
            return ExecutionOutboxClaimResult(
                claimed=False,
                outbox=current,
                reason=f"outbox_not_publishable:{current.state.value}",
            )
        claim_id = derive_outbox_claim_id(
            outbox_id=current.outbox_id,
            publisher_id=publisher_id,
            publish_attempt_count=current.publish_attempt_count + 1,
        )
        claimed = await self._persistence.claim_outbox_for_execution(
            execution_id=eid,
            publisher_id=publisher_id,
            claim_id=claim_id,
            claimed_at=claimed_at or datetime.now(tz=timezone.utc),
        )
        if claimed is not None:
            return ExecutionOutboxClaimResult(
                claimed=True,
                outbox=claimed,
            )
        current = await self._persistence.get_outbox_by_execution(eid)
        return ExecutionOutboxClaimResult(
            claimed=False,
            outbox=current,
            reason=(
                "outbox_not_found"
                if current is None
                else f"outbox_not_publishable:{current.state.value}"
            ),
        )

    async def mark_outbox_published(
        self,
        *,
        outbox_id: ExecutionOutboxId | str,
        claim_id: ExecutionOutboxClaimId | str,
        published_at: datetime | None = None,
    ) -> ExecutionOutboxTransitionResult:
        oid = (
            outbox_id
            if not isinstance(outbox_id, str)
            else as_outbox_id(outbox_id)
        )
        cid = (
            claim_id
            if not isinstance(claim_id, str)
            else as_outbox_claim_id(claim_id)
        )
        outcome = await self._persistence.mark_outbox_published(
            outbox_id=oid,
            claim_id=cid,
            published_at=published_at or datetime.now(tz=timezone.utc),
        )
        if isinstance(outcome, ExecutionOutboxClaimLost):
            _log_outbox_claim_lost(outcome, operation="published")
        return outcome

    async def mark_outbox_failed(
        self,
        *,
        outbox_id: ExecutionOutboxId | str,
        claim_id: ExecutionOutboxClaimId | str,
        error: str,
        failed_at: datetime | None = None,
    ) -> ExecutionOutboxTransitionResult:
        oid = (
            outbox_id
            if not isinstance(outbox_id, str)
            else as_outbox_id(outbox_id)
        )
        cid = (
            claim_id
            if not isinstance(claim_id, str)
            else as_outbox_claim_id(claim_id)
        )
        outcome = await self._persistence.mark_outbox_failed(
            outbox_id=oid,
            claim_id=cid,
            error=error,
            failed_at=failed_at or datetime.now(tz=timezone.utc),
        )
        if isinstance(outcome, ExecutionOutboxClaimLost):
            _log_outbox_claim_lost(outcome, operation="failed")
        return outcome

    async def reconcile_stale_outbox(
        self,
        *,
        outbox_id: ExecutionOutboxId | str,
        stale_before: datetime,
        requeued_at: datetime | None = None,
        expected_tenant_id: str | None = None,
        reason: str = "publisher lease expired",
    ) -> ExecutionOutboxReconcileResult:
        """Requeue one stale publishing outbox row through execution authority."""

        _validate_optional_tenant_id(expected_tenant_id)
        if stale_before.tzinfo is None:
            raise ValueError("stale_before must be timezone-aware")
        if requeued_at is not None and requeued_at.tzinfo is None:
            raise ValueError("requeued_at must be timezone-aware")
        if not reason:
            raise ValueError("requeue reason must be non-empty")
        oid = (
            outbox_id
            if not isinstance(outbox_id, str)
            else as_outbox_id(outbox_id)
        )
        current = await self.get_outbox(
            oid,
            expected_tenant_id=expected_tenant_id,
        )
        if current is None:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=None,
                reason="outbox_not_found",
            )
        if current.state is not ExecutionOutboxState.PUBLISHING:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=current,
                reason=f"outbox_not_publishable:{current.state.value}",
            )
        if current.claimed_at is None or current.claimed_at > stale_before:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=current,
                reason="outbox_not_stale",
            )
        updated = await self._persistence.requeue_stale_outbox(
            outbox_id=oid,
            stale_before=stale_before,
            requeued_at=requeued_at or datetime.now(tz=timezone.utc),
            reason=reason,
        )
        if updated is None:
            refreshed = await self.get_outbox(
                oid,
                expected_tenant_id=expected_tenant_id,
            )
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=refreshed,
                reason="outbox_not_stale",
            )
        return ExecutionOutboxReconcileResult(reconciled=True, outbox=updated)

    async def reconcile_stale_outbox_records(
        self,
        *,
        stale_before: datetime,
        requeued_at: datetime | None = None,
        tenant_id: str | None = None,
        reason: str = "publisher lease expired",
        limit: int = 100,
    ) -> ExecutionOutboxReconcileSweepResult:
        """Requeue a bounded tenant-scoped page of stale outbox rows."""

        if stale_before.tzinfo is None:
            raise ValueError("stale_before must be timezone-aware")
        if requeued_at is not None and requeued_at.tzinfo is None:
            raise ValueError("requeued_at must be timezone-aware")
        if limit < 1:
            raise ValueError("limit must be positive")
        page = await self._persistence.list_outbox(
            OutboxQuery(
                tenant_id=tenant_id,
                state=ExecutionOutboxState.PUBLISHING,
                limit=limit,
            )
        )
        ts = requeued_at or datetime.now(tz=timezone.utc)
        reconciled: list[ExecutionOutboxReconcileResult] = []
        refused: list[ExecutionOutboxReconcileResult] = []
        for outbox in page.records:
            result = await self.reconcile_stale_outbox(
                outbox_id=outbox.outbox_id,
                stale_before=stale_before,
                requeued_at=ts,
                expected_tenant_id=tenant_id,
                reason=reason,
            )
            if result.reconciled:
                reconciled.append(result)
            else:
                refused.append(result)
        return ExecutionOutboxReconcileSweepResult(
            scanned=len(page.records),
            reconciled=tuple(reconciled),
            refused=tuple(refused),
        )

    async def reconcile_failed_execution_outbox(
        self,
        *,
        outbox_id: ExecutionOutboxId | str,
        failed_before_or_at: datetime,
        requeued_at: datetime | None = None,
        expected_tenant_id: str | None = None,
        reason: str = "failed publisher retry",
        max_publish_attempts: int = 3,
    ) -> ExecutionOutboxReconcileResult:
        """Requeue one retryable failed outbox row to the normal pending path."""

        _validate_optional_tenant_id(expected_tenant_id)
        if failed_before_or_at.tzinfo is None:
            raise ValueError("failed_before_or_at must be timezone-aware")
        if requeued_at is not None and requeued_at.tzinfo is None:
            raise ValueError("requeued_at must be timezone-aware")
        if max_publish_attempts < 1:
            raise ValueError("max_publish_attempts must be positive")
        if not reason:
            raise ValueError("requeue reason must be non-empty")
        oid = (
            outbox_id
            if not isinstance(outbox_id, str)
            else as_outbox_id(outbox_id)
        )
        current = await self.get_outbox(
            oid,
            expected_tenant_id=expected_tenant_id,
        )
        if current is None:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=None,
                reason="outbox_not_found",
            )
        if current.state is not ExecutionOutboxState.FAILED:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=current,
                reason=f"outbox_not_publishable:{current.state.value}",
            )
        if current.publish_attempt_count >= max_publish_attempts:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=current,
                reason="failed_outbox_retry_budget_exhausted",
            )
        failed_at = _outbox_failed_at(current)
        if failed_at is None:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=current,
                reason="failed_outbox_missing_failed_at",
            )
        if failed_at > failed_before_or_at:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=current,
                reason="failed_outbox_cooldown_active",
            )
        execution = await self._persistence.get_execution(
            current.execution_id,
            expected_tenant_id=expected_tenant_id,
        )
        if execution is None:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=current,
                reason="execution_not_found",
            )
        if execution.state in _TERMINAL_OUTBOX_RETRY_EXECUTION_STATES:
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=current,
                reason=f"execution_terminal:{execution.state.value}",
            )
        updated = await self._persistence.requeue_failed_outbox(
            outbox_id=oid,
            failed_before_or_at=failed_before_or_at,
            requeued_at=requeued_at or datetime.now(tz=timezone.utc),
            reason=reason,
            max_publish_attempts=max_publish_attempts,
            expected_tenant_id=expected_tenant_id,
        )
        if updated is None:
            refreshed = await self.get_outbox(
                oid,
                expected_tenant_id=expected_tenant_id,
            )
            return ExecutionOutboxReconcileResult(
                reconciled=False,
                outbox=refreshed,
                reason="failed_outbox_not_retryable",
            )
        return ExecutionOutboxReconcileResult(reconciled=True, outbox=updated)

    async def reconcile_failed_execution_outbox_records(
        self,
        *,
        failed_before_or_at: datetime,
        requeued_at: datetime | None = None,
        tenant_id: str | None = None,
        reason: str = "failed publisher retry",
        max_publish_attempts: int = 3,
        limit: int = 100,
    ) -> ExecutionOutboxReconcileSweepResult:
        """Requeue a bounded page of retryable failed outbox rows."""

        if failed_before_or_at.tzinfo is None:
            raise ValueError("failed_before_or_at must be timezone-aware")
        if requeued_at is not None and requeued_at.tzinfo is None:
            raise ValueError("requeued_at must be timezone-aware")
        if limit < 1:
            raise ValueError("limit must be positive")
        if max_publish_attempts < 1:
            raise ValueError("max_publish_attempts must be positive")
        if not reason:
            raise ValueError("requeue reason must be non-empty")
        page = await self._persistence.list_retryable_failed_outbox_records(
            tenant_id=tenant_id,
            failed_before_or_at=failed_before_or_at,
            max_publish_attempts=max_publish_attempts,
            limit=limit,
        )
        ts = requeued_at or datetime.now(tz=timezone.utc)
        reconciled: list[ExecutionOutboxReconcileResult] = []
        refused: list[ExecutionOutboxReconcileResult] = []
        for outbox in page.records:
            result = await self.reconcile_failed_execution_outbox(
                outbox_id=outbox.outbox_id,
                failed_before_or_at=failed_before_or_at,
                requeued_at=ts,
                expected_tenant_id=tenant_id,
                reason=reason,
                max_publish_attempts=max_publish_attempts,
            )
            if result.reconciled:
                reconciled.append(result)
            else:
                refused.append(result)
        return ExecutionOutboxReconcileSweepResult(
            scanned=len(page.records),
            reconciled=tuple(reconciled),
            refused=tuple(refused),
        )

    async def require_claim(
        self,
        *,
        execution_id: ExecutionId | str,
        worker_id: str,
    ) -> ExecutionRecord:
        claim = await self.claim_execution(
            execution_id=execution_id, worker_id=worker_id
        )
        if claim.claimed and claim.execution is not None:
            return claim.execution
        raise ExecutionNotClaimableError(claim.reason or "claim refused")


__all__ = [
    "ExecutionClaimResult",
    "ExecutionOutboxClaimResult",
    "ExecutionOutboxReconcileResult",
    "ExecutionOutboxReconcileSweepResult",
    "ExecutionRecoveryResult",
    "ExecutionRecoverySweepResult",
    "ExecutionRequestResult",
    "ExecutionRuntime",
    "ExecutionWorkerLegitimacyResult",
]


def _validate_worker_id(worker_id: str) -> None:
    if not worker_id:
        raise ValueError("worker_id must be non-empty")


def _validate_optional_tenant_id(tenant_id: str | None) -> None:
    if tenant_id is not None and not tenant_id:
        raise ValueError("expected_tenant_id must be non-empty when supplied")


def _worker_legitimacy_violation(
    *,
    execution: ExecutionRecord,
    attempt: ExecutionAttemptRecord,
    worker_id: str,
) -> str | None:
    if execution.state is not ExecutionState.CLAIMED:
        return f"execution_not_claimed:{execution.state.value}"
    if execution.worker_id != worker_id:
        return "worker_mismatch:execution"
    if attempt.execution_id != execution.execution_id:
        return "attempt_execution_mismatch"
    if attempt.worker_id != worker_id:
        return "worker_mismatch:attempt"
    if attempt.state is not ExecutionAttemptState.RUNNING:
        return f"attempt_not_running:{attempt.state.value}"
    if attempt.attempt_number != execution.attempt_count:
        return "attempt_not_current"
    return None


def _log_execution_claim_lost(
    outcome: ExecutionClaimLost,
    *,
    operation: str,
) -> None:
    logger.info(
        "execution_claim_lost",
        extra={
            "operation": operation,
            "execution_id": str(outcome.execution_id),
            "attempt_id": (
                None
                if outcome.attempt_id is None
                else str(outcome.attempt_id)
            ),
            "worker_id": outcome.worker_id,
            "reason": outcome.reason,
        },
    )


def _log_outbox_claim_lost(
    outcome: ExecutionOutboxClaimLost,
    *,
    operation: str,
) -> None:
    logger.info(
        "execution_outbox_claim_lost",
        extra={
            "operation": operation,
            "outbox_id": str(outcome.outbox_id),
            "claim_id": (
                None if outcome.claim_id is None else str(outcome.claim_id)
            ),
            "reason": outcome.reason,
        },
    )


_TERMINAL_OUTBOX_RETRY_EXECUTION_STATES = frozenset(
    {
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.DEAD_LETTERED,
    }
)


def _outbox_failed_at(outbox: ExecutionOutboxRecord) -> datetime | None:
    value = outbox.metadata.get("failed_at")
    if value is None:
        return None
    try:
        failed_at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if failed_at.tzinfo is None:
        return None
    return failed_at
