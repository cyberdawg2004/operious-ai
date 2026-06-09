"""Transport contracts for queue operations surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict

from app.services.queue_operations_service import (
    DeadLetterItemRecord,
    DeadLetterListPage,
    DeadLetterReplayRecord,
    QueueDepthItemRecord,
    QueueStatusRecord,
)


QueueOperationStatus = Literal["ok", "warn", "critical", "unknown"]


class QueueDepthItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    queue_name: str
    depth: int
    oldest_age_seconds: float | None
    status: QueueOperationStatus
    error: str | None = None
    messages_ready: int | None = None
    messages_unacknowledged: int | None = None
    messages: int | None = None

    @classmethod
    def from_record(cls, record: QueueDepthItemRecord) -> "QueueDepthItem":
        return cls(
            queue_name=record.queue_name,
            depth=record.depth,
            oldest_age_seconds=record.oldest_age_seconds,
            status=cast(QueueOperationStatus, record.status),
            error=record.error,
            messages_ready=record.messages_ready,
            messages_unacknowledged=record.messages_unacknowledged,
            messages=record.messages,
        )


class QueueStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    queues: dict[str, QueueDepthItem]
    snapshot_at: datetime

    @classmethod
    def from_record(cls, record: QueueStatusRecord) -> "QueueStatusResponse":
        return cls(
            queues={
                name: QueueDepthItem.from_record(item)
                for name, item in record.queues.items()
            },
            snapshot_at=record.snapshot_at,
        )


class DeadLetterItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    task_name: str
    queue: str
    error_class: str
    error_message: str
    attempt_count: int
    task_payload: dict[str, Any]
    created_at: datetime
    replayed: bool
    replay_state: str
    replayed_at: datetime | None
    replayed_by: str | None

    @classmethod
    def from_record(cls, record: DeadLetterItemRecord) -> "DeadLetterItem":
        return cls(
            id=record.id,
            tenant_id=record.tenant_id,
            task_name=record.task_name,
            queue=record.queue,
            error_class=record.error_class,
            error_message=record.error_message,
            attempt_count=record.attempt_count,
            task_payload=dict(record.task_payload),
            created_at=record.created_at,
            replayed=record.replayed,
            replay_state=record.replay_state,
            replayed_at=record.replayed_at,
            replayed_by=record.replayed_by,
        )


class DeadLetterListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    limit: int
    offset: int
    items: list[DeadLetterItem]

    @classmethod
    def from_page(cls, page: DeadLetterListPage) -> "DeadLetterListResponse":
        return cls(
            total=page.total,
            limit=page.limit,
            offset=page.offset,
            items=[DeadLetterItem.from_record(item) for item in page.items],
        )


class DeadLetterReplayResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    status: Literal["replayed"]
    replayed_at: datetime

    @classmethod
    def from_record(
        cls,
        record: DeadLetterReplayRecord,
    ) -> "DeadLetterReplayResponse":
        return cls(
            id=record.id,
            status="replayed",
            replayed_at=record.replayed_at,
        )


__all__ = [
    "DeadLetterItem",
    "DeadLetterListResponse",
    "DeadLetterReplayResponse",
    "QueueDepthItem",
    "QueueOperationStatus",
    "QueueStatusResponse",
]
