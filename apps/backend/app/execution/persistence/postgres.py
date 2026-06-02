"""Postgres execution persistence backend."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from typing import Any, Mapping, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from app.execution.envelope import ExecutionResultEnvelope
from app.execution.db.models import (
    ExecutionAttemptRow,
    ExecutionOutboxRow,
    ExecutionRow,
)
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
from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page


class PostgresExecutionPersistence(BaseRepository):
    """Postgres-backed execution authority persistence."""

    async def request_execution(
        self,
        *,
        execution: ExecutionRecord,
        outbox: ExecutionOutboxRecord,
    ) -> ExecutionRecord:
        try:
            async with self.session.begin_nested():
                self.session.add(_execution_to_row(execution))
                await self.session.flush()
                self.session.add(_outbox_to_row(outbox))
        except IntegrityError:
            existing = await self.get_execution_by_dispatch(
                dispatch_id=execution.dispatch_id,
                kind=execution.kind,
                expected_tenant_id=execution.tenant_id,
            )
            if existing is not None:
                return existing
            raise ExecutionPersistenceError(
                "execution request collided but no existing record "
                "could be loaded"
            )
        return execution

    async def get_execution(
        self,
        execution_id: ExecutionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionRecord | None:
        stmt = select(ExecutionRow).where(
            ExecutionRow.execution_id == execution_id
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(ExecutionRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_execution(row)

    async def get_execution_by_dispatch(
        self,
        *,
        dispatch_id: str,
        kind: ExecutionKind,
        expected_tenant_id: str,
    ) -> ExecutionRecord | None:
        stmt = select(ExecutionRow).where(
            ExecutionRow.tenant_id == expected_tenant_id,
            ExecutionRow.dispatch_id == dispatch_id,
            ExecutionRow.kind == kind.value,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_execution(row)

    async def get_attempt(
        self,
        attempt_id: ExecutionAttemptId,
    ) -> ExecutionAttemptRecord | None:
        stmt = select(ExecutionAttemptRow).where(
            ExecutionAttemptRow.attempt_id == attempt_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_attempt(row)

    async def claim_execution(
        self,
        *,
        execution_id: ExecutionId,
        worker_id: str,
        claimed_at: datetime,
    ) -> ExecutionClaimRecord | None:
        stmt = (
            update(ExecutionRow)
            .where(
                ExecutionRow.execution_id == execution_id,
                ExecutionRow.state == ExecutionState.REQUESTED.value,
            )
            .values(
                state=ExecutionState.CLAIMED.value,
                attempt_count=ExecutionRow.attempt_count + 1,
                claimed_at=claimed_at,
                worker_id=worker_id,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        record = await self.get_execution(execution_id)
        if record is None:
            raise ExecutionPersistenceError(
                f"claimed execution disappeared: {execution_id}"
            )
        previous_attempt_id = await self._latest_attempt_id(execution_id)
        attempt = ExecutionAttemptRecord(
            attempt_id=derive_attempt_id(
                execution_id=execution_id,
                attempt_number=record.attempt_count,
            ),
            execution_id=execution_id,
            attempt_number=record.attempt_count,
            state=ExecutionAttemptState.RUNNING,
            worker_id=worker_id,
            started_at=claimed_at,
            previous_attempt_id=previous_attempt_id,
        )
        self.session.add(_attempt_to_row(attempt))
        return ExecutionClaimRecord(execution=record, attempt=attempt)

    async def complete_execution(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        result: Mapping[str, Any],
        completed_at: datetime,
        worker_id: str,
        diagnostic_category: str | None = None,
        diagnostic_confidence: float | None = None,
    ) -> ExecutionTransitionResult:
        existing = await self.get_execution(execution_id)
        if existing is None:
            raise ExecutionPersistenceError(
                f"execution not found: {execution_id}"
            )
        attempt = await self._load_attempt_for_transition(
            execution_id=execution_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            current=existing,
        )
        if isinstance(attempt, ExecutionClaimLost):
            return attempt
        if existing.state is ExecutionState.COMPLETED:
            if attempt.state is ExecutionAttemptState.COMPLETED:
                return existing
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                reason="execution_not_claimed:completed",
                current=existing,
            )
        lost = self._transition_claim_lost(
            execution_id=execution_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            current=existing,
            attempt=attempt,
        )
        if lost is not None:
            return lost
        result_envelope = ExecutionResultEnvelope.from_dict(result)
        category = diagnostic_category or result_envelope.diagnostic_category
        confidence = (
            diagnostic_confidence
            if diagnostic_confidence is not None
            else result_envelope.diagnostic_confidence
        )
        result_payload = result_envelope.to_dict()
        async with self.session.begin_nested():
            stmt = (
                update(ExecutionRow)
                .where(
                    ExecutionRow.execution_id == execution_id,
                    ExecutionRow.state == ExecutionState.CLAIMED.value,
                    ExecutionRow.attempt_count == attempt.attempt_number,
                    ExecutionRow.worker_id == worker_id,
                )
                .values(
                    state=ExecutionState.COMPLETED.value,
                    completed_at=completed_at,
                    diagnostic_category=category,
                    diagnostic_confidence=confidence,
                    result=result_payload,
                )
            )
            execution_result = cast(
                CursorResult[Any], await self.session.execute(stmt)
            )
            if execution_result.rowcount != 1:
                return await self._refreshed_execution_claim_lost(
                    execution_id=execution_id,
                    attempt_id=attempt_id,
                    worker_id=worker_id,
                    reason="execution_claim_lost",
                )
            attempt_stmt = (
                update(ExecutionAttemptRow)
                .where(
                    ExecutionAttemptRow.attempt_id == attempt.attempt_id,
                    ExecutionAttemptRow.execution_id == execution_id,
                    ExecutionAttemptRow.state
                    == ExecutionAttemptState.RUNNING.value,
                    ExecutionAttemptRow.attempt_number == attempt.attempt_number,
                    ExecutionAttemptRow.worker_id == worker_id,
                )
                .values(
                    state=ExecutionAttemptState.COMPLETED.value,
                    completed_at=completed_at,
                    result=result_payload,
                )
            )
            attempt_result = cast(
                CursorResult[Any], await self.session.execute(attempt_stmt)
            )
            if attempt_result.rowcount != 1:
                raise ExecutionPersistenceError(
                    "execution completion attempt CAS failed after authority CAS"
                )
        updated = await self.get_execution(execution_id)
        if updated is None:
            raise ExecutionPersistenceError(
                f"completed execution disappeared: {execution_id}"
            )
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
        existing = await self.get_execution(execution_id)
        if existing is None:
            raise ExecutionPersistenceError(
                f"execution not found: {execution_id}"
            )
        attempt = await self._load_attempt_for_transition(
            execution_id=execution_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            current=existing,
        )
        if isinstance(attempt, ExecutionClaimLost):
            return attempt
        lost = self._transition_claim_lost(
            execution_id=execution_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            current=existing,
            attempt=attempt,
        )
        if lost is not None:
            return lost
        result_envelope = ExecutionResultEnvelope.from_dict(result).to_dict()
        next_state = (
            ExecutionState.REQUESTED
            if retry_requested
            else ExecutionState.FAILED
        )
        async with self.session.begin_nested():
            stmt = (
                update(ExecutionRow)
                .where(
                    ExecutionRow.execution_id == execution_id,
                    ExecutionRow.state == ExecutionState.CLAIMED.value,
                    ExecutionRow.attempt_count == attempt.attempt_number,
                    ExecutionRow.worker_id == worker_id,
                )
                .values(
                    state=next_state.value,
                    failed_at=failed_at,
                    result=result_envelope,
                    error=error,
                )
            )
            execution_result = cast(
                CursorResult[Any], await self.session.execute(stmt)
            )
            if execution_result.rowcount != 1:
                return await self._refreshed_execution_claim_lost(
                    execution_id=execution_id,
                    attempt_id=attempt_id,
                    worker_id=worker_id,
                    reason="execution_claim_lost",
                )
            attempt_stmt = (
                update(ExecutionAttemptRow)
                .where(
                    ExecutionAttemptRow.attempt_id == attempt.attempt_id,
                    ExecutionAttemptRow.execution_id == execution_id,
                    ExecutionAttemptRow.state
                    == ExecutionAttemptState.RUNNING.value,
                    ExecutionAttemptRow.attempt_number == attempt.attempt_number,
                    ExecutionAttemptRow.worker_id == worker_id,
                )
                .values(
                    state=ExecutionAttemptState.FAILED.value,
                    failed_at=failed_at,
                    retry_requested=retry_requested,
                    result=result_envelope,
                    error=error,
                )
            )
            attempt_result = cast(
                CursorResult[Any], await self.session.execute(attempt_stmt)
            )
            if attempt_result.rowcount != 1:
                raise ExecutionPersistenceError(
                    "execution failure attempt CAS failed after authority CAS"
                )
        updated = await self.get_execution(execution_id)
        if updated is None:
            raise ExecutionPersistenceError(
                f"failed execution disappeared: {execution_id}"
            )
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
        existing = await self.get_execution(execution_id)
        if existing is None:
            raise ExecutionPersistenceError(
                f"execution not found: {execution_id}"
            )
        attempt = await self._load_attempt_for_transition(
            execution_id=execution_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            current=existing,
        )
        if isinstance(attempt, ExecutionClaimLost):
            return attempt
        lost = self._transition_claim_lost(
            execution_id=execution_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            current=existing,
            attempt=attempt,
        )
        if lost is not None:
            return lost
        result_envelope = ExecutionResultEnvelope.from_dict(result).to_dict()
        async with self.session.begin_nested():
            stmt = (
                update(ExecutionRow)
                .where(
                    ExecutionRow.execution_id == execution_id,
                    ExecutionRow.state == ExecutionState.CLAIMED.value,
                    ExecutionRow.attempt_count == attempt.attempt_number,
                    ExecutionRow.worker_id == worker_id,
                )
                .values(
                    state=ExecutionState.DEAD_LETTERED.value,
                    failed_at=dead_lettered_at,
                    result=result_envelope,
                    error=error,
                )
            )
            execution_result = cast(
                CursorResult[Any], await self.session.execute(stmt)
            )
            if execution_result.rowcount != 1:
                return await self._refreshed_execution_claim_lost(
                    execution_id=execution_id,
                    attempt_id=attempt_id,
                    worker_id=worker_id,
                    reason="execution_claim_lost",
                )
            attempt_stmt = (
                update(ExecutionAttemptRow)
                .where(
                    ExecutionAttemptRow.attempt_id == attempt.attempt_id,
                    ExecutionAttemptRow.execution_id == execution_id,
                    ExecutionAttemptRow.state
                    == ExecutionAttemptState.RUNNING.value,
                    ExecutionAttemptRow.attempt_number == attempt.attempt_number,
                    ExecutionAttemptRow.worker_id == worker_id,
                )
                .values(
                    state=ExecutionAttemptState.DEAD_LETTERED.value,
                    failed_at=dead_lettered_at,
                    retry_requested=False,
                    result=result_envelope,
                    error=error,
                )
            )
            attempt_result = cast(
                CursorResult[Any], await self.session.execute(attempt_stmt)
            )
            if attempt_result.rowcount != 1:
                raise ExecutionPersistenceError(
                    "execution dead-letter attempt CAS failed after authority CAS"
                )
        updated = await self.get_execution(execution_id)
        if updated is None:
            raise ExecutionPersistenceError(
                f"dead-lettered execution disappeared: {execution_id}"
            )
        return updated

    async def recover_stale_execution(
        self,
        *,
        execution_id: ExecutionId,
        stale_before: datetime,
        recovered_at: datetime,
        reason: str,
    ) -> ExecutionClaimRecord | None:
        existing = await self.get_execution(execution_id)
        if existing is None:
            return None
        if existing.state is not ExecutionState.CLAIMED:
            return None
        if existing.claimed_at is None or existing.claimed_at > stale_before:
            return None
        attempt = await self._resolve_running_attempt(
            execution_id=execution_id,
            attempt_id=None,
            worker_id=existing.worker_id,
            current=existing,
        )
        stmt = (
            update(ExecutionRow)
            .where(
                ExecutionRow.execution_id == execution_id,
                ExecutionRow.state == ExecutionState.CLAIMED.value,
                ExecutionRow.claimed_at <= stale_before,
            )
            .values(
                state=ExecutionState.REQUESTED.value,
                claimed_at=None,
                worker_id=None,
                failed_at=recovered_at,
                error=reason,
                metadata_json={
                    **dict(existing.metadata),
                    "recovery.reason": reason,
                    "recovery.recovered_at": recovered_at.isoformat(),
                    "recovery.attempt_id": str(attempt.attempt_id),
                    "recovery.worker_id": attempt.worker_id,
                },
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        await self.session.execute(
            update(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.attempt_id == attempt.attempt_id)
            .values(
                state=ExecutionAttemptState.FAILED.value,
                failed_at=recovered_at,
                retry_requested=True,
                error=reason,
                metadata_json={
                    **dict(attempt.metadata),
                    "recovery.reason": reason,
                    "recovery.recovered_at": recovered_at.isoformat(),
                },
            )
        )
        updated = await self.get_execution(execution_id)
        recovered_attempt = await self.get_attempt(attempt.attempt_id)
        if updated is None or recovered_attempt is None:
            raise ExecutionPersistenceError(
                f"recovered execution disappeared: {execution_id}"
            )
        return ExecutionClaimRecord(
            execution=updated,
            attempt=recovered_attempt,
        )

    async def get_outbox(
        self,
        outbox_id: ExecutionOutboxId,
    ) -> ExecutionOutboxRecord | None:
        stmt = select(ExecutionOutboxRow).where(
            ExecutionOutboxRow.outbox_id == outbox_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_outbox(row)

    async def get_outbox_by_execution(
        self,
        execution_id: ExecutionId,
    ) -> ExecutionOutboxRecord | None:
        stmt = select(ExecutionOutboxRow).where(
            ExecutionOutboxRow.execution_id == execution_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_outbox(row)

    async def claim_outbox_for_execution(
        self,
        *,
        execution_id: ExecutionId,
        publisher_id: str,
        claim_id: ExecutionOutboxClaimId,
        claimed_at: datetime,
    ) -> ExecutionOutboxRecord | None:
        stmt = (
            update(ExecutionOutboxRow)
            .where(
                ExecutionOutboxRow.execution_id == execution_id,
                ExecutionOutboxRow.state
                == ExecutionOutboxState.PENDING.value,
            )
            .values(
                state=ExecutionOutboxState.PUBLISHING.value,
                claimed_at=claimed_at,
                publisher_id=publisher_id,
                claim_id=claim_id,
                publish_attempt_count=(
                    ExecutionOutboxRow.publish_attempt_count + 1
                ),
                last_error=None,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        record = await self.get_outbox_by_execution(execution_id)
        if record is None:
            raise ExecutionPersistenceError(
                f"claimed outbox disappeared for execution: {execution_id}"
            )
        return record

    async def mark_outbox_published(
        self,
        *,
        outbox_id: ExecutionOutboxId,
        claim_id: ExecutionOutboxClaimId,
        published_at: datetime,
    ) -> ExecutionOutboxTransitionResult:
        existing = await self.get_outbox(outbox_id)
        if existing is None:
            raise ExecutionPersistenceError(f"outbox not found: {outbox_id}")
        if existing.state is ExecutionOutboxState.PUBLISHED:
            if existing.claim_id == claim_id:
                return existing
            return ExecutionOutboxClaimLost(
                outbox_id=outbox_id,
                claim_id=claim_id,
                reason="outbox_already_published",
                current=existing,
            )
        if existing.state is not ExecutionOutboxState.PUBLISHING:
            return ExecutionOutboxClaimLost(
                outbox_id=outbox_id,
                claim_id=claim_id,
                reason=f"outbox_not_publishable:{existing.state.value}",
                current=existing,
            )
        stmt = (
            update(ExecutionOutboxRow)
            .where(
                ExecutionOutboxRow.outbox_id == outbox_id,
                ExecutionOutboxRow.state == ExecutionOutboxState.PUBLISHING.value,
                ExecutionOutboxRow.claim_id == claim_id,
            )
            .values(
                state=ExecutionOutboxState.PUBLISHED.value,
                published_at=published_at,
                last_error=None,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return ExecutionOutboxClaimLost(
                outbox_id=outbox_id,
                claim_id=claim_id,
                reason="outbox_claim_lost",
                current=await self.get_outbox(outbox_id),
            )
        updated = await self.get_outbox(outbox_id)
        if updated is None:
            raise ExecutionPersistenceError(
                f"published outbox disappeared: {outbox_id}"
            )
        return updated

    async def mark_outbox_failed(
        self,
        *,
        outbox_id: ExecutionOutboxId,
        claim_id: ExecutionOutboxClaimId,
        error: str,
        failed_at: datetime,
    ) -> ExecutionOutboxTransitionResult:
        existing = await self.get_outbox(outbox_id)
        if existing is None:
            raise ExecutionPersistenceError(f"outbox not found: {outbox_id}")
        if existing.state is ExecutionOutboxState.PUBLISHED:
            return ExecutionOutboxClaimLost(
                outbox_id=outbox_id,
                claim_id=claim_id,
                reason="outbox_already_published",
                current=existing,
            )
        if existing.state is not ExecutionOutboxState.PUBLISHING:
            return ExecutionOutboxClaimLost(
                outbox_id=outbox_id,
                claim_id=claim_id,
                reason=f"outbox_not_publishable:{existing.state.value}",
                current=existing,
            )
        stmt = (
            update(ExecutionOutboxRow)
            .where(
                ExecutionOutboxRow.outbox_id == outbox_id,
                ExecutionOutboxRow.state == ExecutionOutboxState.PUBLISHING.value,
                ExecutionOutboxRow.claim_id == claim_id,
            )
            .values(
                state=ExecutionOutboxState.FAILED.value,
                published_at=None,
                last_error=error,
                metadata_json={
                    **dict(existing.metadata),
                    "failed_at": failed_at.isoformat(),
                },
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return ExecutionOutboxClaimLost(
                outbox_id=outbox_id,
                claim_id=claim_id,
                reason="outbox_claim_lost",
                current=await self.get_outbox(outbox_id),
            )
        updated = await self.get_outbox(outbox_id)
        if updated is None:
            raise ExecutionPersistenceError(
                f"failed outbox disappeared: {outbox_id}"
            )
        return updated

    async def requeue_stale_outbox(
        self,
        *,
        outbox_id: ExecutionOutboxId,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
    ) -> ExecutionOutboxRecord | None:
        existing = await self.get_outbox(outbox_id)
        if existing is None:
            return None
        stmt = (
            update(ExecutionOutboxRow)
            .where(
                ExecutionOutboxRow.outbox_id == outbox_id,
                ExecutionOutboxRow.state == ExecutionOutboxState.PUBLISHING.value,
                ExecutionOutboxRow.claimed_at.is_not(None),
                ExecutionOutboxRow.claimed_at <= stale_before,
            )
            .values(
                state=ExecutionOutboxState.PENDING.value,
                claimed_at=None,
                publisher_id=None,
                claim_id=None,
                last_error=reason,
                metadata_json={
                    **dict(existing.metadata),
                    "reconciler.reason": reason,
                    "reconciler.requeued_at": requeued_at.isoformat(),
                },
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_outbox(outbox_id)

    async def list_retryable_failed_outbox_records(
        self,
        *,
        tenant_id: str | None,
        failed_before_or_at: datetime,
        max_publish_attempts: int,
        limit: int,
    ) -> OutboxPage:
        stmt = (
            select(ExecutionOutboxRow)
            .join(
                ExecutionRow,
                ExecutionRow.execution_id == ExecutionOutboxRow.execution_id,
            )
            .where(
                ExecutionOutboxRow.state == ExecutionOutboxState.FAILED.value,
                ExecutionOutboxRow.publish_attempt_count < max_publish_attempts,
                ExecutionRow.state.not_in(
                    _TERMINAL_OUTBOX_RETRY_EXECUTION_STATE_VALUES
                ),
            )
            .order_by(ExecutionOutboxRow.created_at, ExecutionOutboxRow.outbox_id)
            .limit(max(limit * 4, limit))
        )
        if tenant_id is not None:
            stmt = stmt.where(ExecutionRow.tenant_id == tenant_id)
        rows = (await self.session.execute(stmt)).scalars().all()  # bounded-load-ok
        records: list[ExecutionOutboxRecord] = []
        for row in rows:
            record = _row_to_outbox(row)
            failed_at = _outbox_failed_at(record)
            if failed_at is None or failed_at > failed_before_or_at:
                continue
            records.append(record)
            if len(records) >= limit:
                break
        return OutboxPage(
            records=tuple(records),
            total=len(records),
            limit=limit,
            offset=0,
        )

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
        existing = await self.get_outbox(outbox_id)
        if existing is None:
            return None
        if existing.state is not ExecutionOutboxState.FAILED:
            return None
        if existing.publish_attempt_count >= max_publish_attempts:
            return None
        failed_at = _outbox_failed_at(existing)
        if failed_at is None or failed_at > failed_before_or_at:
            return None
        parent_stmt = select(ExecutionRow.execution_id).where(
            ExecutionRow.execution_id == ExecutionOutboxRow.execution_id,
            ExecutionRow.state.not_in(
                _TERMINAL_OUTBOX_RETRY_EXECUTION_STATE_VALUES
            ),
        )
        if expected_tenant_id is not None:
            parent_stmt = parent_stmt.where(
                ExecutionRow.tenant_id == expected_tenant_id
            )
        metadata = dict(existing.metadata)
        retry_count = _metadata_int(
            metadata.get("failed_recovery.retry_attempt_count")
        )
        stmt = (
            update(ExecutionOutboxRow)
            .where(
                ExecutionOutboxRow.outbox_id == outbox_id,
                ExecutionOutboxRow.state == ExecutionOutboxState.FAILED.value,
                ExecutionOutboxRow.publish_attempt_count < max_publish_attempts,
                ExecutionOutboxRow.execution_id.in_(parent_stmt),
            )
            .values(
                state=ExecutionOutboxState.PENDING.value,
                claimed_at=None,
                publisher_id=None,
                claim_id=None,
                published_at=None,
                last_error=reason,
                metadata_json={
                    **metadata,
                    "failed_recovery.previous_failure_reason": (
                        existing.last_error
                    ),
                    "failed_recovery.retry_attempt_count": retry_count + 1,
                    "failed_recovery.last_recovered_at": (
                        requeued_at.isoformat()
                    ),
                    "failed_recovery.reason": reason,
                },
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_outbox(outbox_id)

    async def list_executions(
        self,
        query: ExecutionQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionPage:
        stmt = select(ExecutionRow)
        if expected_tenant_id is not None:
            stmt = stmt.where(ExecutionRow.tenant_id == expected_tenant_id)
        if query.execution_id is not None:
            stmt = stmt.where(ExecutionRow.execution_id == query.execution_id)
        if query.kind is not None:
            stmt = stmt.where(ExecutionRow.kind == query.kind.value)
        if query.dispatch_id is not None:
            stmt = stmt.where(ExecutionRow.dispatch_id == query.dispatch_id)
        if query.session_id is not None:
            stmt = stmt.where(ExecutionRow.session_id == query.session_id)
        if query.tenant_id is not None:
            stmt = stmt.where(ExecutionRow.tenant_id == query.tenant_id)
        if query.state is not None:
            stmt = stmt.where(ExecutionRow.state == query.state.value)
        if query.requested_after_or_at is not None:
            stmt = stmt.where(
                ExecutionRow.requested_at >= query.requested_after_or_at
            )
        if query.failed_after_or_at is not None:
            stmt = stmt.where(
                ExecutionRow.failed_at.is_not(None),
                ExecutionRow.failed_at >= query.failed_after_or_at,
            )
        if query.claimed_before_or_at is not None:
            stmt = stmt.where(
                ExecutionRow.claimed_at.is_not(None),
                ExecutionRow.claimed_at <= query.claimed_before_or_at,
            )
        stmt = stmt.order_by(ExecutionRow.requested_at, ExecutionRow.execution_id)
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return ExecutionPage(
            executions=tuple(_row_to_execution(r) for r in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_attempts(
        self,
        query: ExecutionAttemptQuery,
    ) -> ExecutionAttemptPage:
        stmt = select(ExecutionAttemptRow)
        if query.attempt_id is not None:
            stmt = stmt.where(
                ExecutionAttemptRow.attempt_id == query.attempt_id
            )
        if query.execution_id is not None:
            stmt = stmt.where(
                ExecutionAttemptRow.execution_id == query.execution_id
            )
        if query.state is not None:
            stmt = stmt.where(
                ExecutionAttemptRow.state == query.state.value
            )
        stmt = stmt.order_by(
            ExecutionAttemptRow.started_at,
            ExecutionAttemptRow.attempt_number,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return ExecutionAttemptPage(
            attempts=tuple(_row_to_attempt(r) for r in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_outbox(
        self,
        query: OutboxQuery,
    ) -> OutboxPage:
        stmt = select(ExecutionOutboxRow)
        if query.execution_id is not None:
            stmt = stmt.where(
                ExecutionOutboxRow.execution_id == query.execution_id
            )
        if query.tenant_id is not None:
            stmt = stmt.join(
                ExecutionRow,
                ExecutionRow.execution_id == ExecutionOutboxRow.execution_id,
            ).where(ExecutionRow.tenant_id == query.tenant_id)
        if query.state is not None:
            stmt = stmt.where(ExecutionOutboxRow.state == query.state.value)
        stmt = stmt.order_by(
            ExecutionOutboxRow.created_at, ExecutionOutboxRow.outbox_id
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return OutboxPage(
            records=tuple(_row_to_outbox(r) for r in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def _latest_attempt_id(
        self,
        execution_id: ExecutionId,
    ) -> ExecutionAttemptId | None:
        stmt = (
            select(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.execution_id == execution_id)
            .order_by(ExecutionAttemptRow.attempt_number.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return ExecutionAttemptId(row.attempt_id)

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

    async def _refreshed_execution_claim_lost(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        worker_id: str | None,
        reason: str,
    ) -> ExecutionClaimLost:
        return self._execution_claim_lost(
            execution_id=execution_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            reason=reason,
            current=await self.get_execution(execution_id),
        )

    async def _load_attempt_for_transition(
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
        stmt = select(ExecutionAttemptRow).where(
            ExecutionAttemptRow.attempt_id == attempt_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return self._execution_claim_lost(
                execution_id=execution_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                reason="attempt_not_found",
                current=current,
            )
        attempt = _row_to_attempt(row)
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

    async def _resolve_running_attempt(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        worker_id: str | None = None,
        current: ExecutionRecord | None = None,
    ) -> ExecutionAttemptRecord:
        if attempt_id is None:
            attempt_id = await self._latest_attempt_id(execution_id)
        if attempt_id is None:
            raise ExecutionPersistenceError(
                f"execution has no attempt: {execution_id}"
            )
        stmt = select(ExecutionAttemptRow).where(
            ExecutionAttemptRow.attempt_id == attempt_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ExecutionPersistenceError(
                f"attempt not found: {attempt_id}"
            )
        attempt = _row_to_attempt(row)
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


def _execution_to_row(record: ExecutionRecord) -> ExecutionRow:
    metadata = dict(record.metadata)
    if record.governance_decision_id is not None:
        metadata["governance.decision_id"] = str(record.governance_decision_id)
    if record.execution_governance_evaluation_id is not None:
        metadata["execution_governance.evaluation_id"] = str(
            record.execution_governance_evaluation_id
        )
    if record.governance_admitted_at is not None:
        metadata["execution_governance.admitted_at"] = (
            record.governance_admitted_at.isoformat()
        )
    if record.execution_governance_config_id is not None:
        metadata["execution_governance.config_id"] = str(
            record.execution_governance_config_id
        )
    if record.execution_governance_config_version is not None:
        metadata["execution_governance.version"] = (
            record.execution_governance_config_version
        )
    if record.execution_governance_config_sha256 is not None:
        metadata["execution_governance.content_sha256"] = (
            record.execution_governance_config_sha256
        )
    return ExecutionRow(
        execution_id=record.execution_id,
        kind=record.kind.value,
        dispatch_id=record.dispatch_id,
        session_id=record.session_id,
        tenant_id=record.tenant_id,
        state=record.state.value,
        attempt_count=record.attempt_count,
        requested_at=record.requested_at,
        claimed_at=record.claimed_at,
        completed_at=record.completed_at,
        failed_at=record.failed_at,
        worker_id=record.worker_id,
        diagnostic_category=record.diagnostic_category,
        diagnostic_confidence=record.diagnostic_confidence,
        result=record.result.to_dict(),
        error=record.error,
        metadata_json=metadata,
    )


def _attempt_to_row(record: ExecutionAttemptRecord) -> ExecutionAttemptRow:
    return ExecutionAttemptRow(
        attempt_id=record.attempt_id,
        execution_id=record.execution_id,
        attempt_number=record.attempt_number,
        state=record.state.value,
        worker_id=record.worker_id,
        started_at=record.started_at,
        completed_at=record.completed_at,
        failed_at=record.failed_at,
        previous_attempt_id=record.previous_attempt_id,
        retry_requested=record.retry_requested,
        result=record.result.to_dict(),
        error=record.error,
        metadata_json=dict(record.metadata),
    )


def _row_to_attempt(row: ExecutionAttemptRow) -> ExecutionAttemptRecord:
    return ExecutionAttemptRecord(
        attempt_id=ExecutionAttemptId(row.attempt_id),
        execution_id=ExecutionId(row.execution_id),
        attempt_number=row.attempt_number,
        state=ExecutionAttemptState(row.state),
        worker_id=row.worker_id,
        started_at=row.started_at,
        completed_at=row.completed_at,
        failed_at=row.failed_at,
        previous_attempt_id=(
            ExecutionAttemptId(row.previous_attempt_id)
            if row.previous_attempt_id is not None
            else None
        ),
        retry_requested=row.retry_requested,
        result=ExecutionResultEnvelope.from_dict(row.result or {}),
        error=row.error,
        metadata=dict(row.metadata_json or {}),
    )


def _row_to_execution(row: ExecutionRow) -> ExecutionRecord:
    metadata = dict(row.metadata_json or {})
    return ExecutionRecord(
        execution_id=ExecutionId(row.execution_id),
        kind=ExecutionKind(row.kind),
        dispatch_id=row.dispatch_id,
        session_id=row.session_id,
        tenant_id=row.tenant_id,
        state=ExecutionState(row.state),
        attempt_count=row.attempt_count,
        requested_at=row.requested_at,
        governance_decision_id=_optional_uuid(
            metadata.get("governance.decision_id")
        ),
        execution_governance_evaluation_id=_optional_uuid(
            metadata.get("execution_governance.evaluation_id")
        ),
        governance_admitted_at=_optional_datetime(
            metadata.get("execution_governance.admitted_at")
        ),
        execution_governance_config_id=_optional_uuid(
            metadata.get("execution_governance.config_id")
        ),
        execution_governance_config_version=_optional_int(
            metadata.get("execution_governance.version")
        ),
        execution_governance_config_sha256=_optional_str(
            metadata.get("execution_governance.content_sha256")
        ),
        claimed_at=row.claimed_at,
        completed_at=row.completed_at,
        failed_at=row.failed_at,
        worker_id=row.worker_id,
        diagnostic_category=row.diagnostic_category,
        diagnostic_confidence=row.diagnostic_confidence,
        result=ExecutionResultEnvelope.from_dict(row.result or {}),
        error=row.error,
        metadata=metadata,
    )


def _outbox_to_row(record: ExecutionOutboxRecord) -> ExecutionOutboxRow:
    return ExecutionOutboxRow(
        outbox_id=record.outbox_id,
        execution_id=record.execution_id,
        state=record.state.value,
        created_at=record.created_at,
        claimed_at=record.claimed_at,
        published_at=record.published_at,
        publisher_id=record.publisher_id,
        claim_id=record.claim_id,
        publish_attempt_count=record.publish_attempt_count,
        last_error=record.last_error,
        metadata_json=dict(record.metadata),
    )


def _row_to_outbox(row: ExecutionOutboxRow) -> ExecutionOutboxRecord:
    from app.execution.identity import ExecutionOutboxId

    return ExecutionOutboxRecord(
        outbox_id=ExecutionOutboxId(row.outbox_id),
        execution_id=ExecutionId(row.execution_id),
        state=ExecutionOutboxState(row.state),
        created_at=row.created_at,
        claimed_at=row.claimed_at,
        published_at=row.published_at,
        publisher_id=row.publisher_id,
        claim_id=(
            ExecutionOutboxClaimId(row.claim_id)
            if row.claim_id is not None
            else None
        ),
        publish_attempt_count=row.publish_attempt_count,
        last_error=row.last_error,
        metadata=dict(row.metadata_json or {}),
    )


def _optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


_TERMINAL_OUTBOX_RETRY_EXECUTION_STATE_VALUES = (
    ExecutionState.COMPLETED.value,
    ExecutionState.FAILED.value,
    ExecutionState.DEAD_LETTERED.value,
)


def _outbox_failed_at(outbox: ExecutionOutboxRecord) -> datetime | None:
    failed_at = _optional_datetime(outbox.metadata.get("failed_at"))
    if failed_at is None or failed_at.tzinfo is None:
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


__all__ = ["PostgresExecutionPersistence"]
