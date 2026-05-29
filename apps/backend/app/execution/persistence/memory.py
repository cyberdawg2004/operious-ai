"""In-memory execution persistence backend."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import Any, Mapping

from app.execution.envelope import ExecutionResultEnvelope
from app.execution.enums import (
    ExecutionAttemptState,
    ExecutionKind,
    ExecutionOutboxState,
    ExecutionState,
)
from app.execution.exceptions import (
    ExecutionPersistenceError,
    ExecutionStateError,
)
from app.execution.identity import (
    ExecutionAttemptId,
    ExecutionId,
    ExecutionOutboxClaimId,
    ExecutionOutboxId,
    derive_attempt_id,
)
from app.execution.persistence.models import (
    ExecutionAttemptPage,
    ExecutionAttemptQuery,
    ExecutionPage,
    ExecutionQuery,
    OutboxPage,
    OutboxQuery,
)
from app.execution.persistence.records import (
    ExecutionAttemptRecord,
    ExecutionClaimLost,
    ExecutionClaimRecord,
    ExecutionOutboxClaimLost,
    ExecutionOutboxRecord,
    ExecutionOutboxTransitionResult,
    ExecutionRecord,
    ExecutionTransitionResult,
)
from app.execution.persistence.repository import (
    ExecutionPersistenceProtocol,
)


class InMemoryExecutionPersistence(ExecutionPersistenceProtocol):
    """Async-safe reference implementation."""

    def __init__(self) -> None:
        self._executions: dict[ExecutionId, ExecutionRecord] = {}
        self._attempts: dict[ExecutionAttemptId, ExecutionAttemptRecord] = {}
        self._attempts_by_execution: dict[
            ExecutionId, list[ExecutionAttemptId]
        ] = {}
        self._outbox: dict[object, ExecutionOutboxRecord] = {}
        self._outbox_by_execution: dict[ExecutionId, ExecutionOutboxId] = {}
        self._by_dispatch: dict[
            tuple[str, str, ExecutionKind], ExecutionId
        ] = {}
        self._lock = asyncio.Lock()

    async def request_execution(
        self,
        *,
        execution: ExecutionRecord,
        outbox: ExecutionOutboxRecord,
    ) -> ExecutionRecord:
        async with self._lock:
            key = (
                execution.tenant_id,
                execution.dispatch_id,
                execution.kind,
            )
            existing_id = self._by_dispatch.get(key)
            if existing_id is not None:
                existing = self._executions.get(existing_id)
                if existing is None:
                    raise ExecutionPersistenceError(
                        "execution dispatch index points at missing row"
                    )
                return existing
            if execution.execution_id in self._executions:
                raise ExecutionPersistenceError(
                    f"duplicate execution_id: {execution.execution_id}"
                )
            self._executions[execution.execution_id] = execution
            self._by_dispatch[key] = execution.execution_id
            self._outbox[outbox.outbox_id] = outbox
            self._outbox_by_execution[outbox.execution_id] = outbox.outbox_id
            return execution

    async def get_execution(
        self,
        execution_id: ExecutionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionRecord | None:
        record = self._executions.get(execution_id)
        if record is None:
            return None
        if (
            expected_tenant_id is not None
            and record.tenant_id != expected_tenant_id
        ):
            return None
        return record

    async def get_execution_by_dispatch(
        self,
        *,
        dispatch_id: str,
        kind: ExecutionKind,
        expected_tenant_id: str,
    ) -> ExecutionRecord | None:
        execution_id = self._by_dispatch.get(
            (expected_tenant_id, dispatch_id, kind)
        )
        if execution_id is None:
            return None
        return await self.get_execution(
            execution_id, expected_tenant_id=expected_tenant_id
        )

    async def get_attempt(
        self,
        attempt_id: ExecutionAttemptId,
    ) -> ExecutionAttemptRecord | None:
        return self._attempts.get(attempt_id)

    async def claim_execution(
        self,
        *,
        execution_id: ExecutionId,
        worker_id: str,
        claimed_at: datetime,
    ) -> ExecutionClaimRecord | None:
        async with self._lock:
            record = self._executions.get(execution_id)
            if record is None:
                return None
            if record.state is not ExecutionState.REQUESTED:
                return None
            attempt_number = record.attempt_count + 1
            previous_attempt_id = self._latest_attempt_id(execution_id)
            attempt_id = derive_attempt_id(
                execution_id=execution_id,
                attempt_number=attempt_number,
            )
            updated = replace(
                record,
                state=ExecutionState.CLAIMED,
                attempt_count=attempt_number,
                claimed_at=claimed_at,
                worker_id=worker_id,
            )
            attempt = ExecutionAttemptRecord(
                attempt_id=attempt_id,
                execution_id=execution_id,
                attempt_number=attempt_number,
                state=ExecutionAttemptState.RUNNING,
                worker_id=worker_id,
                started_at=claimed_at,
                previous_attempt_id=previous_attempt_id,
            )
            self._executions[execution_id] = updated
            self._attempts[attempt_id] = attempt
            self._attempts_by_execution.setdefault(execution_id, []).append(
                attempt_id
            )
            return ExecutionClaimRecord(execution=updated, attempt=attempt)

    async def complete_execution(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        result: Mapping[str, Any],
        completed_at: datetime,
        worker_id: str,
    ) -> ExecutionTransitionResult:
        async with self._lock:
            record = self._require(execution_id)
            attempt = self._load_attempt_for_transition(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                current=record,
            )
            if isinstance(attempt, ExecutionClaimLost):
                return attempt
            if record.state is ExecutionState.COMPLETED:
                if attempt.state is ExecutionAttemptState.COMPLETED:
                    return record
                return self._execution_claim_lost(
                    execution_id=execution_id,
                    attempt_id=attempt_id,
                    worker_id=worker_id,
                    reason="execution_not_claimed:completed",
                    current=record,
                )
            lost = self._transition_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                current=record,
                attempt=attempt,
            )
            if lost is not None:
                return lost
            result_envelope = ExecutionResultEnvelope.from_dict(result)
            self._attempts[attempt.attempt_id] = replace(
                attempt,
                state=ExecutionAttemptState.COMPLETED,
                completed_at=completed_at,
                result=result_envelope,
            )
            updated = replace(
                record,
                state=ExecutionState.COMPLETED,
                completed_at=completed_at,
                result=result_envelope,
            )
            self._executions[execution_id] = updated
            return updated

    async def fail_execution(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        error: str,
        failed_at: datetime,
        retry_requested: bool,
        worker_id: str,
        result: Mapping[str, Any],
    ) -> ExecutionTransitionResult:
        async with self._lock:
            record = self._require(execution_id)
            attempt = self._load_attempt_for_transition(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                current=record,
            )
            if isinstance(attempt, ExecutionClaimLost):
                return attempt
            lost = self._transition_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                current=record,
                attempt=attempt,
            )
            if lost is not None:
                return lost
            result_envelope = ExecutionResultEnvelope.from_dict(result)
            self._attempts[attempt.attempt_id] = replace(
                attempt,
                state=ExecutionAttemptState.FAILED,
                failed_at=failed_at,
                retry_requested=retry_requested,
                result=result_envelope,
                error=error,
            )
            updated = replace(
                record,
                state=(
                    ExecutionState.REQUESTED
                    if retry_requested
                    else ExecutionState.FAILED
                ),
                failed_at=failed_at,
                result=result_envelope,
                error=error,
            )
            self._executions[execution_id] = updated
            return updated

    async def dead_letter_execution(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        error: str,
        dead_lettered_at: datetime,
        worker_id: str,
        result: Mapping[str, Any],
    ) -> ExecutionTransitionResult:
        async with self._lock:
            record = self._require(execution_id)
            attempt = self._load_attempt_for_transition(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                current=record,
            )
            if isinstance(attempt, ExecutionClaimLost):
                return attempt
            lost = self._transition_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                current=record,
                attempt=attempt,
            )
            if lost is not None:
                return lost
            result_envelope = ExecutionResultEnvelope.from_dict(result)
            self._attempts[attempt.attempt_id] = replace(
                attempt,
                state=ExecutionAttemptState.DEAD_LETTERED,
                failed_at=dead_lettered_at,
                retry_requested=False,
                result=result_envelope,
                error=error,
            )
            updated = replace(
                record,
                state=ExecutionState.DEAD_LETTERED,
                failed_at=dead_lettered_at,
                result=result_envelope,
                error=error,
            )
            self._executions[execution_id] = updated
            return updated

    async def recover_stale_execution(
        self,
        *,
        execution_id: ExecutionId,
        stale_before: datetime,
        recovered_at: datetime,
        reason: str,
    ) -> ExecutionClaimRecord | None:
        async with self._lock:
            record = self._executions.get(execution_id)
            if record is None:
                return None
            if record.state is not ExecutionState.CLAIMED:
                return None
            if record.claimed_at is None or record.claimed_at > stale_before:
                return None
            attempt = self._resolve_running_attempt(
                execution_id=execution_id,
                attempt_id=None,
                worker_id=record.worker_id,
                current=record,
            )
            recovered_attempt = replace(
                attempt,
                state=ExecutionAttemptState.FAILED,
                failed_at=recovered_at,
                retry_requested=True,
                error=reason,
                metadata={
                    **dict(attempt.metadata),
                    "recovery.reason": reason,
                    "recovery.recovered_at": recovered_at.isoformat(),
                },
            )
            self._attempts[attempt.attempt_id] = recovered_attempt
            updated = replace(
                record,
                state=ExecutionState.REQUESTED,
                claimed_at=None,
                worker_id=None,
                failed_at=recovered_at,
                error=reason,
                metadata={
                    **dict(record.metadata),
                    "recovery.reason": reason,
                    "recovery.recovered_at": recovered_at.isoformat(),
                    "recovery.attempt_id": str(attempt.attempt_id),
                    "recovery.worker_id": attempt.worker_id,
                },
            )
            self._executions[execution_id] = updated
            return ExecutionClaimRecord(
                execution=updated,
                attempt=recovered_attempt,
            )

    async def get_outbox(
        self,
        outbox_id: ExecutionOutboxId,
    ) -> ExecutionOutboxRecord | None:
        return self._outbox.get(outbox_id)

    async def get_outbox_by_execution(
        self,
        execution_id: ExecutionId,
    ) -> ExecutionOutboxRecord | None:
        outbox_id = self._outbox_by_execution.get(execution_id)
        if outbox_id is None:
            return None
        return self._outbox.get(outbox_id)

    async def claim_outbox_for_execution(
        self,
        *,
        execution_id: ExecutionId,
        publisher_id: str,
        claim_id: ExecutionOutboxClaimId,
        claimed_at: datetime,
    ) -> ExecutionOutboxRecord | None:
        async with self._lock:
            outbox = await self.get_outbox_by_execution(execution_id)
            if outbox is None:
                return None
            if outbox.state is not ExecutionOutboxState.PENDING:
                return None
            updated = replace(
                outbox,
                state=ExecutionOutboxState.PUBLISHING,
                claimed_at=claimed_at,
                publisher_id=publisher_id,
                claim_id=claim_id,
                publish_attempt_count=outbox.publish_attempt_count + 1,
                last_error=None,
            )
            self._outbox[outbox.outbox_id] = updated
            return updated

    async def mark_outbox_published(
        self,
        *,
        outbox_id: ExecutionOutboxId,
        claim_id: ExecutionOutboxClaimId,
        published_at: datetime,
    ) -> ExecutionOutboxTransitionResult:
        async with self._lock:
            outbox = self._require_outbox(outbox_id)
            if outbox.state is ExecutionOutboxState.PUBLISHED:
                if outbox.claim_id == claim_id:
                    return outbox
                return ExecutionOutboxClaimLost(
                    outbox_id=outbox_id,
                    claim_id=claim_id,
                    reason="outbox_already_published",
                    current=outbox,
                )
            if outbox.state is not ExecutionOutboxState.PUBLISHING:
                return ExecutionOutboxClaimLost(
                    outbox_id=outbox_id,
                    claim_id=claim_id,
                    reason=f"outbox_not_publishable:{outbox.state.value}",
                    current=outbox,
                )
            if outbox.claim_id != claim_id:
                return ExecutionOutboxClaimLost(
                    outbox_id=outbox_id,
                    claim_id=claim_id,
                    reason="outbox_claim_lost",
                    current=outbox,
                )
            updated = replace(
                outbox,
                state=ExecutionOutboxState.PUBLISHED,
                published_at=published_at,
                last_error=None,
            )
            self._outbox[outbox_id] = updated
            return updated

    async def mark_outbox_failed(
        self,
        *,
        outbox_id: ExecutionOutboxId,
        claim_id: ExecutionOutboxClaimId,
        error: str,
        failed_at: datetime,
    ) -> ExecutionOutboxTransitionResult:
        async with self._lock:
            outbox = self._require_outbox(outbox_id)
            if outbox.state is ExecutionOutboxState.PUBLISHED:
                return ExecutionOutboxClaimLost(
                    outbox_id=outbox_id,
                    claim_id=claim_id,
                    reason="outbox_already_published",
                    current=outbox,
                )
            if outbox.state is not ExecutionOutboxState.PUBLISHING:
                return ExecutionOutboxClaimLost(
                    outbox_id=outbox_id,
                    claim_id=claim_id,
                    reason=f"outbox_not_publishable:{outbox.state.value}",
                    current=outbox,
                )
            if outbox.claim_id != claim_id:
                return ExecutionOutboxClaimLost(
                    outbox_id=outbox_id,
                    claim_id=claim_id,
                    reason="outbox_claim_lost",
                    current=outbox,
                )
            updated = replace(
                outbox,
                state=ExecutionOutboxState.FAILED,
                published_at=None,
                last_error=error,
                metadata={**dict(outbox.metadata), "failed_at": failed_at.isoformat()},
            )
            self._outbox[outbox_id] = updated
            return updated

    async def requeue_stale_outbox(
        self,
        *,
        outbox_id: ExecutionOutboxId,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
    ) -> ExecutionOutboxRecord | None:
        del requeued_at
        async with self._lock:
            outbox = self._outbox.get(outbox_id)
            if outbox is None:
                return None
            if outbox.state is not ExecutionOutboxState.PUBLISHING:
                return None
            if outbox.claimed_at is None or outbox.claimed_at > stale_before:
                return None
            updated = replace(
                outbox,
                state=ExecutionOutboxState.PENDING,
                claimed_at=None,
                publisher_id=None,
                claim_id=None,
                last_error=reason,
                metadata={
                    **dict(outbox.metadata),
                    "reconciler.reason": reason,
                },
            )
            self._outbox[outbox_id] = updated
            return updated

    async def list_retryable_failed_outbox_records(
        self,
        *,
        tenant_id: str | None,
        failed_before_or_at: datetime,
        max_publish_attempts: int,
        limit: int,
    ) -> OutboxPage:
        rows: list[ExecutionOutboxRecord] = []
        for outbox in self._outbox.values():
            execution = self._executions.get(outbox.execution_id)
            if execution is None:
                continue
            if tenant_id is not None and execution.tenant_id != tenant_id:
                continue
            if execution.state in _TERMINAL_OUTBOX_RETRY_EXECUTION_STATES:
                continue
            if outbox.state is not ExecutionOutboxState.FAILED:
                continue
            if outbox.publish_attempt_count >= max_publish_attempts:
                continue
            failed_at = _outbox_failed_at(outbox)
            if failed_at is None or failed_at > failed_before_or_at:
                continue
            rows.append(outbox)
        rows.sort(key=lambda row: (row.created_at, str(row.outbox_id)))
        sliced = rows[:limit]
        return OutboxPage(records=tuple(sliced), total=len(rows), offset=0)

    async def requeue_failed_outbox(
        self,
        *,
        outbox_id: ExecutionOutboxId,
        failed_before_or_at: datetime,
        requeued_at: datetime,
        reason: str,
        max_publish_attempts: int,
        expected_tenant_id: str | None = None,
    ) -> ExecutionOutboxRecord | None:
        async with self._lock:
            outbox = self._outbox.get(outbox_id)
            if outbox is None:
                return None
            execution = self._executions.get(outbox.execution_id)
            if execution is None:
                return None
            if (
                expected_tenant_id is not None
                and execution.tenant_id != expected_tenant_id
            ):
                return None
            if execution.state in _TERMINAL_OUTBOX_RETRY_EXECUTION_STATES:
                return None
            if outbox.state is not ExecutionOutboxState.FAILED:
                return None
            if outbox.publish_attempt_count >= max_publish_attempts:
                return None
            failed_at = _outbox_failed_at(outbox)
            if failed_at is None or failed_at > failed_before_or_at:
                return None
            metadata = dict(outbox.metadata)
            retry_count = _metadata_int(
                metadata.get("failed_recovery.retry_attempt_count")
            )
            updated = replace(
                outbox,
                state=ExecutionOutboxState.PENDING,
                claimed_at=None,
                publisher_id=None,
                claim_id=None,
                published_at=None,
                last_error=reason,
                metadata={
                    **metadata,
                    "failed_recovery.previous_failure_reason": outbox.last_error,
                    "failed_recovery.retry_attempt_count": retry_count + 1,
                    "failed_recovery.last_recovered_at": requeued_at.isoformat(),
                    "failed_recovery.reason": reason,
                },
            )
            self._outbox[outbox_id] = updated
            return updated

    async def list_executions(
        self,
        query: ExecutionQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionPage:
        rows = list(self._executions.values())
        if expected_tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == expected_tenant_id]
        if query.execution_id is not None:
            rows = [r for r in rows if r.execution_id == query.execution_id]
        if query.kind is not None:
            rows = [r for r in rows if r.kind is query.kind]
        if query.dispatch_id is not None:
            rows = [r for r in rows if r.dispatch_id == query.dispatch_id]
        if query.session_id is not None:
            rows = [r for r in rows if r.session_id == query.session_id]
        if query.tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == query.tenant_id]
        if query.state is not None:
            rows = [r for r in rows if r.state is query.state]
        if query.requested_after_or_at is not None:
            rows = [
                r
                for r in rows
                if r.requested_at >= query.requested_after_or_at
            ]
        if query.failed_after_or_at is not None:
            rows = [
                r
                for r in rows
                if r.failed_at is not None
                and r.failed_at >= query.failed_after_or_at
            ]
        if query.claimed_before_or_at is not None:
            rows = [
                r
                for r in rows
                if r.claimed_at is not None
                and r.claimed_at <= query.claimed_before_or_at
            ]
        rows.sort(key=lambda r: (r.requested_at, str(r.execution_id)))
        total = len(rows)
        sliced = rows[query.offset : query.offset + query.limit]
        return ExecutionPage(
            executions=tuple(sliced),
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    async def list_attempts(
        self,
        query: ExecutionAttemptQuery,
    ) -> ExecutionAttemptPage:
        rows = list(self._attempts.values())
        if query.attempt_id is not None:
            rows = [r for r in rows if r.attempt_id == query.attempt_id]
        if query.execution_id is not None:
            rows = [r for r in rows if r.execution_id == query.execution_id]
        if query.state is not None:
            rows = [r for r in rows if r.state is query.state]
        rows.sort(key=lambda r: (r.started_at, r.attempt_number))
        total = len(rows)
        sliced = rows[query.offset : query.offset + query.limit]
        return ExecutionAttemptPage(
            attempts=tuple(sliced), total=total, offset=query.offset
        )

    async def list_outbox(
        self,
        query: OutboxQuery,
    ) -> OutboxPage:
        rows = list(self._outbox.values())
        if query.execution_id is not None:
            rows = [r for r in rows if r.execution_id == query.execution_id]
        if query.tenant_id is not None:
            rows = [
                r
                for r in rows
                if (
                    self._executions.get(r.execution_id) is not None
                    and self._executions[r.execution_id].tenant_id == query.tenant_id
                )
            ]
        if query.state is not None:
            rows = [r for r in rows if r.state is query.state]
        rows.sort(key=lambda r: (r.created_at, str(r.outbox_id)))
        total = len(rows)
        sliced = rows[query.offset : query.offset + query.limit]
        return OutboxPage(records=tuple(sliced), total=total, offset=query.offset)

    def _require(self, execution_id: ExecutionId) -> ExecutionRecord:
        record = self._executions.get(execution_id)
        if record is None:
            raise ExecutionPersistenceError(
                f"execution not found: {execution_id}"
            )
        return record

    def _latest_attempt_id(
        self, execution_id: ExecutionId
    ) -> ExecutionAttemptId | None:
        ids = self._attempts_by_execution.get(execution_id, [])
        if not ids:
            return None
        return ids[-1]

    def _execution_claim_lost(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        worker_id: str | None,
        reason: str,
        current: ExecutionRecord | None = None,
    ) -> ExecutionClaimLost:
        return ExecutionClaimLost(
            execution_id=execution_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            reason=reason,
            current=current,
        )

    def _load_attempt_for_transition(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        worker_id: str,
        current: ExecutionRecord,
    ) -> ExecutionAttemptRecord | ExecutionClaimLost:
        if attempt_id is None:
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=None,
                worker_id=worker_id,
                reason="attempt_id_required",
                current=current,
            )
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                reason="attempt_not_found",
                current=current,
            )
        if attempt.execution_id != execution_id:
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                reason="attempt_execution_mismatch",
                current=current,
            )
        if attempt.worker_id != worker_id:
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                reason="worker_mismatch:attempt",
                current=current,
            )
        return attempt

    def _transition_claim_lost(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        worker_id: str,
        current: ExecutionRecord,
        attempt: ExecutionAttemptRecord,
    ) -> ExecutionClaimLost | None:
        if current.state is not ExecutionState.CLAIMED:
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                reason=f"execution_not_claimed:{current.state.value}",
                current=current,
            )
        if current.worker_id != worker_id:
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                reason="worker_mismatch:execution",
                current=current,
            )
        if attempt.attempt_number != current.attempt_count:
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                reason="attempt_not_current",
                current=current,
            )
        if attempt.state is not ExecutionAttemptState.RUNNING:
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                reason=f"attempt_not_running:{attempt.state.value}",
                current=current,
            )
        return None

    def _resolve_running_attempt(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        worker_id: str | None = None,
        current: ExecutionRecord | None = None,
    ) -> ExecutionAttemptRecord:
        if attempt_id is None:
            attempt_id = self._latest_attempt_id(execution_id)
        if attempt_id is None:
            raise ExecutionPersistenceError(
                f"execution has no attempt: {execution_id}"
            )
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            raise ExecutionPersistenceError(
                f"attempt not found: {attempt_id}"
            )
        if attempt.execution_id != execution_id:
            raise ExecutionStateError(
                "attempt does not belong to execution"
            )
        if attempt.state is not ExecutionAttemptState.RUNNING:
            raise ExecutionStateError(
                "only running attempts can be completed or failed"
            )
        if current is not None and attempt.attempt_number != current.attempt_count:
            raise ExecutionStateError("attempt is no longer current")
        if worker_id is not None:
            if attempt.worker_id != worker_id:
                raise ExecutionStateError("worker does not own attempt")
            if current is not None and current.worker_id != worker_id:
                raise ExecutionStateError("worker does not own execution")
        return attempt

    def _require_outbox(
        self, outbox_id: ExecutionOutboxId
    ) -> ExecutionOutboxRecord:
        record = self._outbox.get(outbox_id)
        if record is None:
            raise ExecutionPersistenceError(f"outbox not found: {outbox_id}")
        return record


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


def _metadata_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


__all__ = ["InMemoryExecutionPersistence"]
