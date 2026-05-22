"""Storage-agnostic execution persistence contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable

from app.execution.enums import ExecutionKind
from app.execution.identity import (
    ExecutionAttemptId,
    ExecutionId,
    ExecutionOutboxId,
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
    ExecutionClaimRecord,
    ExecutionOutboxRecord,
    ExecutionRecord,
)


@runtime_checkable
class ExecutionPersistenceProtocol(Protocol):
    """Durable execution authority store.

    Implementations must make ``request_execution`` idempotent by
    ``(tenant_id, dispatch_id, kind)``. A duplicate request returns the
    existing execution record instead of creating a second authority.
    """

    async def request_execution(
        self,
        *,
        execution: ExecutionRecord,
        outbox: ExecutionOutboxRecord,
    ) -> ExecutionRecord: ...

    async def get_execution(
        self,
        execution_id: ExecutionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionRecord | None: ...

    async def get_execution_by_dispatch(
        self,
        *,
        dispatch_id: str,
        kind: ExecutionKind,
        expected_tenant_id: str,
    ) -> ExecutionRecord | None: ...

    async def get_attempt(
        self,
        attempt_id: ExecutionAttemptId,
    ) -> ExecutionAttemptRecord | None: ...

    async def claim_execution(
        self,
        *,
        execution_id: ExecutionId,
        worker_id: str,
        claimed_at: datetime,
    ) -> ExecutionClaimRecord | None: ...

    async def complete_execution(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        result: Mapping[str, Any],
        completed_at: datetime,
        worker_id: str | None = None,
    ) -> ExecutionRecord: ...

    async def fail_execution(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        error: str,
        failed_at: datetime,
        retry_requested: bool,
        worker_id: str | None = None,
    ) -> ExecutionRecord: ...

    async def dead_letter_execution(
        self,
        *,
        execution_id: ExecutionId,
        attempt_id: ExecutionAttemptId | None,
        error: str,
        dead_lettered_at: datetime,
        worker_id: str | None = None,
    ) -> ExecutionRecord: ...

    async def recover_stale_execution(
        self,
        *,
        execution_id: ExecutionId,
        stale_before: datetime,
        recovered_at: datetime,
        reason: str,
    ) -> ExecutionClaimRecord | None: ...

    async def get_outbox(
        self,
        outbox_id: ExecutionOutboxId,
    ) -> ExecutionOutboxRecord | None: ...

    async def get_outbox_by_execution(
        self,
        execution_id: ExecutionId,
    ) -> ExecutionOutboxRecord | None: ...

    async def claim_outbox_for_execution(
        self,
        *,
        execution_id: ExecutionId,
        publisher_id: str,
        claimed_at: datetime,
    ) -> ExecutionOutboxRecord | None: ...

    async def mark_outbox_published(
        self,
        *,
        outbox_id: ExecutionOutboxId,
        published_at: datetime,
    ) -> ExecutionOutboxRecord: ...

    async def mark_outbox_failed(
        self,
        *,
        outbox_id: ExecutionOutboxId,
        error: str,
        failed_at: datetime,
    ) -> ExecutionOutboxRecord: ...

    async def list_executions(
        self,
        query: ExecutionQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> ExecutionPage: ...

    async def list_attempts(
        self,
        query: ExecutionAttemptQuery,
    ) -> ExecutionAttemptPage: ...

    async def list_outbox(
        self,
        query: OutboxQuery,
    ) -> OutboxPage: ...


__all__ = ["ExecutionPersistenceProtocol"]
