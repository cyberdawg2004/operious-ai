"""Execution persistence query/page value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.execution.enums import (
    ExecutionAttemptState,
    ExecutionKind,
    ExecutionOutboxState,
    ExecutionState,
)
from app.execution.identity import ExecutionAttemptId, ExecutionId
from app.execution.persistence.records import (
    ExecutionAttemptRecord,
    ExecutionOutboxRecord,
    ExecutionRecord,
)


@dataclass(frozen=True, slots=True)
class ExecutionQuery:
    execution_id: ExecutionId | None = None
    kind: ExecutionKind | None = None
    dispatch_id: str | None = None
    session_id: str | None = None
    tenant_id: str | None = None
    state: ExecutionState | None = None
    claimed_before_or_at: datetime | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OutboxQuery:
    execution_id: ExecutionId | None = None
    tenant_id: str | None = None
    state: ExecutionOutboxState | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ExecutionAttemptQuery:
    attempt_id: ExecutionAttemptId | None = None
    execution_id: ExecutionId | None = None
    state: ExecutionAttemptState | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ExecutionPage:
    executions: tuple[ExecutionRecord, ...]
    total: int
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OutboxPage:
    records: tuple[ExecutionOutboxRecord, ...]
    total: int
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ExecutionAttemptPage:
    attempts: tuple[ExecutionAttemptRecord, ...]
    total: int
    offset: int = 0


__all__ = [
    "ExecutionAttemptPage",
    "ExecutionAttemptQuery",
    "ExecutionPage",
    "ExecutionQuery",
    "OutboxPage",
    "OutboxQuery",
]
