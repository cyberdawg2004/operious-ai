"""Queue operations service for Command Center operators."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from inspect import isawaitable
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admission import admission_thresholds_from_settings
from app.core.config import Settings, get_settings
from app.core.queue_admission import queue_depth_status
from app.core.redis import get_redis_client
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.hardening.admission import AdmissionGate
from app.hardening.admission.gate import AdmissionRedisClient
from app.queue_operations import (
    CeleryDeadLetterReplayPublisher,
    DeadLetterReplayPublisher,
    TASK_DEFAULT_QUEUES,
    celery_kwargs_for_task,
)
from app.queues import ALL_QUEUES
from app.repositories.pagination import fetch_scalar_page
from app.runtime.db.models import DeadLetterTaskRow

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueueDepthItemRecord:
    queue_name: str
    depth: int
    oldest_age_seconds: float | None
    status: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class QueueStatusRecord:
    queues: dict[str, QueueDepthItemRecord]
    snapshot_at: datetime


@dataclass(frozen=True, slots=True)
class DeadLetterItemRecord:
    id: str
    tenant_id: str
    task_name: str
    queue: str
    error_class: str
    error_message: str
    attempt_count: int
    task_payload: Mapping[str, Any]
    created_at: datetime
    replayed: bool
    replayed_at: datetime | None
    replayed_by: str | None


@dataclass(frozen=True, slots=True)
class DeadLetterListPage:
    total: int
    limit: int
    offset: int
    items: tuple[DeadLetterItemRecord, ...]


@dataclass(frozen=True, slots=True)
class DeadLetterReplayRecord:
    id: str
    status: str
    replayed_at: datetime


class QueueOperationsError(RuntimeError):
    """Base error for queue operation failures."""


class DeadLetterNotFoundError(QueueOperationsError):
    """Raised when a DLQ record is not visible in the tenant scope."""


class DeadLetterAlreadyReplayedError(QueueOperationsError):
    """Raised when an operator replays an already replayed DLQ record."""


class DeadLetterCannotReplayUnknownTaskError(QueueOperationsError):
    """Raised when no replay kwargs can be reconstructed for a task."""


class QueueOperationsService:
    """Application service for queue status, DLQ reads, and DLQ replay."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        redis_provider: Callable[[], Redis] = get_redis_client,
        replay_publisher: DeadLetterReplayPublisher | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._redis_provider = redis_provider
        self._replay_publisher = (
            replay_publisher or CeleryDeadLetterReplayPublisher()
        )
        self._settings = settings or get_settings()

    async def get_queue_status(self) -> QueueStatusRecord:
        """Return depth and oldest age for every physical queue."""

        snapshot_at = datetime.now(timezone.utc)
        queues: dict[str, QueueDepthItemRecord] = {}
        redis_client = cast(AdmissionRedisClient, self._redis_provider())
        gate = AdmissionGate(
            redis_client=redis_client,
            thresholds=admission_thresholds_from_settings(self._settings),
        )
        for queue_name in ALL_QUEUES:
            queues[queue_name] = await self._queue_status_item(
                queue_name=queue_name,
                redis_client=redis_client,
                gate=gate,
            )
        return QueueStatusRecord(queues=queues, snapshot_at=snapshot_at)

    async def list_dead_letters(
        self,
        *,
        tenant_id: str,
        queue: str | None = None,
        error_class: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DeadLetterListPage:
        """Return tenant-scoped dead-letter task rows."""

        previous_tenant = get_current_tenant()
        set_current_tenant(tenant_id)
        try:
            stmt = (
                select(DeadLetterTaskRow)
                .where(DeadLetterTaskRow.tenant_id == tenant_id)
                .order_by(
                    DeadLetterTaskRow.created_at.desc(),
                    DeadLetterTaskRow.dead_letter_task_id,
                )
            )
            if queue is not None:
                stmt = stmt.where(_queue_filter(queue))
            if error_class is not None:
                stmt = stmt.where(
                    text("metadata ->> 'error_class' = :error_class")
                ).params(error_class=error_class)
            page = await fetch_scalar_page(
                self._session,
                stmt,
                limit=limit,
                offset=offset,
            )
            return DeadLetterListPage(
                total=page.total,
                limit=page.limit,
                offset=page.offset,
                items=tuple(_item_from_row(row) for row in page.items),
            )
        finally:
            set_current_tenant(previous_tenant)

    async def replay_dead_letter(
        self,
        *,
        dlq_id: str,
        tenant_id: str,
        replayed_by: str,
    ) -> DeadLetterReplayRecord:
        """Replay one tenant-scoped dead-letter task."""

        parsed_id = _parse_dlq_id(dlq_id)
        previous_tenant = get_current_tenant()
        set_current_tenant(tenant_id)
        try:
            try:
                existing = (
                    await self._session.execute(
                        select(DeadLetterTaskRow).where(
                            DeadLetterTaskRow.dead_letter_task_id == parsed_id,
                            DeadLetterTaskRow.tenant_id == tenant_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    raise DeadLetterNotFoundError("dead-letter record not found")
                row = (
                    await self._session.execute(
                        select(DeadLetterTaskRow)
                        .where(
                            DeadLetterTaskRow.dead_letter_task_id == parsed_id,
                            DeadLetterTaskRow.tenant_id == tenant_id,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).scalar_one_or_none()
                if row is None:
                    raise DeadLetterAlreadyReplayedError(
                        "dead-letter replay already in progress"
                    )
                if row.replayed:
                    raise DeadLetterAlreadyReplayedError(
                        "dead-letter record already replayed"
                    )
                queue_name = _queue_for_row(row)
                kwargs = _replay_kwargs_for_row(row)
                task_name = row.task_name
                replayed_at = datetime.now(timezone.utc)
                row.replayed = True
                row.replayed_at = replayed_at
                row.replayed_by = replayed_by
                await self._session.commit()
            except Exception:
                await self._session.rollback()
                raise

            self._replay_publisher.publish(
                task_name=task_name,
                kwargs=kwargs,
                queue=queue_name,
            )
            return DeadLetterReplayRecord(
                id=str(parsed_id),
                status="replayed",
                replayed_at=replayed_at,
            )
        finally:
            set_current_tenant(previous_tenant)

    async def _queue_status_item(
        self,
        *,
        queue_name: str,
        redis_client: AdmissionRedisClient,
        gate: AdmissionGate,
    ) -> QueueDepthItemRecord:
        try:
            depth = int(await _resolve(redis_client.llen(queue_name)) or 0)
        except Exception as exc:  # noqa: BLE001 - endpoint degrades per queue.
            logger.warning(
                "queue_status_depth_unavailable",
                extra={
                    "queue_name": queue_name,
                    "error": exc.__class__.__name__,
                },
            )
            return QueueDepthItemRecord(
                queue_name=queue_name,
                depth=0,
                oldest_age_seconds=None,
                status="unknown",
                error="redis_unavailable",
            )
        oldest_age_seconds = await gate.queue_age_seconds(queue_name=queue_name)
        return QueueDepthItemRecord(
            queue_name=queue_name,
            depth=depth,
            oldest_age_seconds=oldest_age_seconds,
            status=_queue_item_status(
                depth=depth,
                oldest_age_seconds=oldest_age_seconds,
                settings=self._settings,
            ),
        )


def _queue_filter(queue: str) -> Any:
    fallback_task_names = tuple(
        task_name
        for task_name, default_queue in TASK_DEFAULT_QUEUES.items()
        if default_queue == queue
    )
    if not fallback_task_names:
        return DeadLetterTaskRow.queue == queue
    return or_(
        DeadLetterTaskRow.queue == queue,
        and_(
            DeadLetterTaskRow.queue.is_(None),
            DeadLetterTaskRow.task_name.in_(fallback_task_names),
        ),
    )


def _queue_item_status(
    *,
    depth: int,
    oldest_age_seconds: float | None,
    settings: Settings,
) -> str:
    depth_status = queue_depth_status(
        depth=depth,
        warn_depth=settings.ADMISSION_QUEUE_DEPTH_WARN,
        critical_depth=settings.ADMISSION_QUEUE_DEPTH_REJECT,
    )
    if (
        oldest_age_seconds is not None
        and oldest_age_seconds >= settings.ADMISSION_QUEUE_AGE_REJECT_SECONDS
    ):
        return "critical"
    if depth_status == "critical":
        return "critical"
    if (
        oldest_age_seconds is not None
        and oldest_age_seconds >= settings.ADMISSION_QUEUE_AGE_WARN_SECONDS
    ):
        return "warn"
    return depth_status


def _item_from_row(row: DeadLetterTaskRow) -> DeadLetterItemRecord:
    metadata = dict(row.metadata_json or {})
    return DeadLetterItemRecord(
        id=str(row.dead_letter_task_id),
        tenant_id=row.tenant_id,
        task_name=row.task_name,
        queue=_queue_for_row(row),
        error_class=_metadata_str(metadata, "error_class")
        or _metadata_str(metadata, "error_type")
        or "UnknownError",
        error_message=_metadata_str(metadata, "error_message") or row.reason,
        attempt_count=_metadata_int(metadata, "attempt_count") or row.retry_count,
        task_payload=_metadata_dict(metadata, "task_payload"),
        created_at=row.created_at,
        replayed=row.replayed,
        replayed_at=row.replayed_at,
        replayed_by=row.replayed_by,
    )


def _queue_for_row(row: DeadLetterTaskRow) -> str:
    if row.queue:
        return row.queue
    queue = TASK_DEFAULT_QUEUES.get(row.task_name)
    if queue is None:
        raise DeadLetterCannotReplayUnknownTaskError(
            "cannot_replay_unknown_task"
        )
    return queue


def _replay_kwargs_for_row(row: DeadLetterTaskRow) -> dict[str, Any]:
    kwargs = celery_kwargs_for_task(
        task_name=row.task_name,
        metadata=dict(row.metadata_json or {}),
    )
    if kwargs is None:
        raise DeadLetterCannotReplayUnknownTaskError(
            "cannot_replay_unknown_task"
        )
    return kwargs


def _parse_dlq_id(dlq_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(dlq_id)
    except ValueError as exc:
        raise DeadLetterNotFoundError("dead-letter record not found") from exc


def _metadata_str(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _metadata_int(metadata: Mapping[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    return value if isinstance(value, int) else None


def _metadata_dict(metadata: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = metadata.get(key)
    if not isinstance(value, Mapping):
        return {}
    return _mapping_to_dict(cast(Mapping[Any, Any], value))


def _mapping_to_dict(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


async def _resolve(value: Awaitable[Any] | Any) -> Any:
    if isawaitable(value):
        return await value
    return value


__all__ = [
    "DeadLetterAlreadyReplayedError",
    "DeadLetterCannotReplayUnknownTaskError",
    "DeadLetterItemRecord",
    "DeadLetterListPage",
    "DeadLetterNotFoundError",
    "DeadLetterReplayRecord",
    "QueueDepthItemRecord",
    "QueueOperationsService",
    "QueueStatusRecord",
    "TASK_DEFAULT_QUEUES",
]
