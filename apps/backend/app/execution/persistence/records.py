"""Persistable execution substrate records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping
import uuid

from app.execution.enums import (
    ExecutionAttemptState,
    ExecutionKind,
    ExecutionOutboxState,
    ExecutionState,
)
from app.execution.identity import (
    ExecutionAttemptId,
    ExecutionId,
    ExecutionOutboxId,
)


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Durable authority record for one worker execution."""

    execution_id: ExecutionId
    kind: ExecutionKind
    dispatch_id: str
    session_id: str
    tenant_id: str
    state: ExecutionState
    attempt_count: int
    requested_at: datetime
    governance_decision_id: uuid.UUID | None = None
    execution_governance_evaluation_id: uuid.UUID | None = None
    governance_admitted_at: datetime | None = None
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    worker_id: str | None = None
    result: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionAttemptRecord:
    """Durable lineage record for one worker try."""

    attempt_id: ExecutionAttemptId
    execution_id: ExecutionId
    attempt_number: int
    state: ExecutionAttemptState
    worker_id: str
    started_at: datetime
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    previous_attempt_id: ExecutionAttemptId | None = None
    retry_requested: bool = False
    result: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionClaimRecord:
    """Atomic execution claim plus its attempt lineage row."""

    execution: ExecutionRecord
    attempt: ExecutionAttemptRecord


@dataclass(frozen=True, slots=True)
class ExecutionOutboxRecord:
    """Durable transport intent for one execution record."""

    outbox_id: ExecutionOutboxId
    execution_id: ExecutionId
    state: ExecutionOutboxState
    created_at: datetime
    claimed_at: datetime | None = None
    published_at: datetime | None = None
    publisher_id: str | None = None
    publish_attempt_count: int = 0
    last_error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "ExecutionAttemptRecord",
    "ExecutionClaimRecord",
    "ExecutionOutboxRecord",
    "ExecutionRecord",
]
