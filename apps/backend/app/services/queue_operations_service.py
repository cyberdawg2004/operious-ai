"""Queue operations service for Command Center operators."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.admission import admission_thresholds_from_settings
from app.core.config import Settings, get_settings
from app.core.queue_depth import (
    QueueDepthProvider,
    RedisQueueDepthProvider,
    get_queue_depth_provider,
)
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

DEAD_LETTER_REPLAY_NONE = "none"
DEAD_LETTER_REPLAY_CLAIMED = "claimed"
DEAD_LETTER_REPLAY_PUBLISHED = "published"
DEAD_LETTER_REPLAY_FAILED = "failed"

_DLQ_REPLAY_CLAIM_NAMESPACE = uuid.UUID(
    "d71c7001-0001-4001-8001-000000000001"
)


@dataclass(frozen=True, slots=True)
class QueueDepthItemRecord:
    queue_name: str
    depth: int
    oldest_age_seconds: float | None
    status: str
    error: str | None = None
    messages_ready: int | None = None
    messages_unacknowledged: int | None = None
    messages: int | None = None


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
    replay_state: str
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


@dataclass(frozen=True, slots=True)
class DeadLetterReplayRecoveryRecord:
    scanned: int
    recovered_count: int
    recovered_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DeadLetterReplayClaim:
    dlq_id: uuid.UUID
    queue_name: str
    kwargs: dict[str, Any]
    task_name: str
    replayed_at: datetime
    replayed_by: str
    claim_id: uuid.UUID


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
        queue_depth_provider: QueueDepthProvider | None = None,
        queue_depth_provider_factory: Callable[[], QueueDepthProvider] | None = None,
        replay_publisher: DeadLetterReplayPublisher | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._redis_provider = redis_provider
        if queue_depth_provider_factory is not None:
            self._queue_depth_provider_factory = queue_depth_provider_factory
        elif queue_depth_provider is not None:
            self._queue_depth_provider_factory = lambda: queue_depth_provider
        elif redis_provider is not get_redis_client:
            self._queue_depth_provider_factory = (
                lambda: RedisQueueDepthProvider(self._redis_provider())
            )
        else:
            self._queue_depth_provider_factory = get_queue_depth_provider
        self._replay_publisher = (
            replay_publisher or CeleryDeadLetterReplayPublisher()
        )
        self._settings = settings or get_settings()

    async def get_queue_status(self) -> QueueStatusRecord:
        """Return depth and oldest age for every physical queue."""

        snapshot_at = datetime.now(timezone.utc)
        queues: dict[str, QueueDepthItemRecord] = {}
        redis_client = cast(AdmissionRedisClient, self._redis_provider())
        queue_depth_provider = self._queue_depth_provider_factory()
        gate = AdmissionGate(
            redis_client=redis_client,
            thresholds=admission_thresholds_from_settings(self._settings),
            queue_depth_provider=queue_depth_provider,
        )
        for queue_name in ALL_QUEUES:
            queues[queue_name] = await self._queue_status_item(
                queue_name=queue_name,
                queue_depth_provider=queue_depth_provider,
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
                connection = await self._session.connection()
                await self._set_replay_tenant(tenant_id)
                claim = await self._claim_dead_letter_replay(
                    parsed_id=parsed_id,
                    tenant_id=tenant_id,
                    replayed_by=replayed_by,
                )
                await self._session.commit()
                if _should_commit_external_transaction(
                    session=self._session,
                    connection=connection,
                ):
                    await connection.commit()
            except Exception:
                if self._session.in_transaction():
                    await self._session.rollback()
                raise

            try:
                self._replay_publisher.publish(
                    task_name=claim.task_name,
                    kwargs=claim.kwargs,
                    queue=claim.queue_name,
                )
            except Exception as exc:
                try:
                    connection = await self._session.connection()
                    await self._set_replay_tenant(tenant_id)
                    await self._mark_dead_letter_replay_failed(
                        claim=claim,
                        failed_at=datetime.now(timezone.utc),
                        error=_bounded_replay_error(exc),
                    )
                    await self._session.commit()
                    if _should_commit_external_transaction(
                        session=self._session,
                        connection=connection,
                    ):
                        await connection.commit()
                except Exception:
                    if self._session.in_transaction():
                        await self._session.rollback()
                    raise
                raise

            published_at = datetime.now(timezone.utc)
            try:
                connection = await self._session.connection()
                await self._set_replay_tenant(tenant_id)
                published = await self._mark_dead_letter_replay_published(
                    claim=claim,
                    published_at=published_at,
                )
                await self._session.commit()
                if _should_commit_external_transaction(
                    session=self._session,
                    connection=connection,
                ):
                    await connection.commit()
            except Exception:
                if self._session.in_transaction():
                    await self._session.rollback()
                raise
            if not published:
                raise DeadLetterAlreadyReplayedError(
                    "dead-letter replay claim lost"
                )
            return DeadLetterReplayRecord(
                id=str(parsed_id),
                status="replayed",
                replayed_at=published_at,
            )
        finally:
            set_current_tenant(previous_tenant)

    async def recover_dead_letter_replays(
        self,
        *,
        claimed_before_or_at: datetime,
        tenant_id: str | None = None,
        limit: int = 100,
        reason: str = "dead-letter replay recovery",
    ) -> DeadLetterReplayRecoveryRecord:
        """Make failed or stale claimed replay rows retryable again."""

        if claimed_before_or_at.tzinfo is None:
            raise ValueError("claimed_before_or_at must be timezone-aware")
        if limit < 1:
            raise ValueError("limit must be positive")
        if not reason:
            raise ValueError("recovery reason must be non-empty")

        previous_tenant = get_current_tenant()
        if tenant_id is not None:
            set_current_tenant(tenant_id)
        try:
            stmt = (
                select(DeadLetterTaskRow)
                .where(
                    DeadLetterTaskRow.replayed.is_(False),
                    or_(
                        DeadLetterTaskRow.replay_state
                        == DEAD_LETTER_REPLAY_FAILED,
                        and_(
                            DeadLetterTaskRow.replay_state
                            == DEAD_LETTER_REPLAY_CLAIMED,
                            DeadLetterTaskRow.replay_claimed_at.is_not(None),
                            DeadLetterTaskRow.replay_claimed_at
                            <= claimed_before_or_at,
                        ),
                    ),
                )
                .order_by(
                    DeadLetterTaskRow.created_at,
                    DeadLetterTaskRow.dead_letter_task_id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            if tenant_id is not None:
                stmt = stmt.where(DeadLetterTaskRow.tenant_id == tenant_id)
            rows = (await self._session.execute(stmt)).scalars().all()
            recovered_ids: list[str] = []
            recovered_at = datetime.now(timezone.utc)
            for row in rows:
                metadata = dict(row.metadata_json or {})
                row.replay_state = DEAD_LETTER_REPLAY_FAILED
                row.replay_claim_id = None
                row.replay_claimed_at = None
                row.replay_last_error = reason
                row.metadata_json = {
                    **metadata,
                    "replay_recovery.reason": reason,
                    "replay_recovery.recovered_at": recovered_at.isoformat(),
                }
                recovered_ids.append(str(row.dead_letter_task_id))
            await self._session.flush()
            return DeadLetterReplayRecoveryRecord(
                scanned=len(rows),
                recovered_count=len(recovered_ids),
                recovered_ids=tuple(recovered_ids),
            )
        finally:
            set_current_tenant(previous_tenant)

    async def _claim_dead_letter_replay(
        self,
        *,
        parsed_id: uuid.UUID,
        tenant_id: str,
        replayed_by: str,
    ) -> _DeadLetterReplayClaim:
        row = (
            await self._session.execute(
                select(DeadLetterTaskRow)
                .where(
                    DeadLetterTaskRow.dead_letter_task_id == parsed_id,
                    DeadLetterTaskRow.tenant_id == tenant_id,
                    DeadLetterTaskRow.replayed.is_(False),
                    DeadLetterTaskRow.replay_state.in_(
                        (
                            DEAD_LETTER_REPLAY_NONE,
                            DEAD_LETTER_REPLAY_FAILED,
                        )
                    ),
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            existing_id = (
                await self._session.execute(
                    select(DeadLetterTaskRow.dead_letter_task_id).where(
                        DeadLetterTaskRow.dead_letter_task_id == parsed_id,
                        DeadLetterTaskRow.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if existing_id is None:
                raise DeadLetterNotFoundError("dead-letter record not found")
            raise DeadLetterAlreadyReplayedError(
                "dead-letter replay already in progress"
            )

        queue_name = _queue_for_row(row)
        kwargs = _replay_kwargs_for_row(row)
        replayed_at = datetime.now(timezone.utc)
        next_attempt_count = row.replay_attempt_count + 1
        claim_id = _derive_replay_claim_id(
            dlq_id=row.dead_letter_task_id,
            tenant_id=row.tenant_id,
            replay_attempt_count=next_attempt_count,
        )
        metadata = dict(row.metadata_json or {})
        result = cast(
            Any,
            await self._session.execute(
                update(DeadLetterTaskRow)
                .where(
                    DeadLetterTaskRow.dead_letter_task_id
                    == row.dead_letter_task_id,
                    DeadLetterTaskRow.tenant_id == tenant_id,
                    DeadLetterTaskRow.replayed.is_(False),
                    DeadLetterTaskRow.replay_state.in_(
                        (
                            DEAD_LETTER_REPLAY_NONE,
                            DEAD_LETTER_REPLAY_FAILED,
                        )
                    ),
                    DeadLetterTaskRow.replay_attempt_count
                    == row.replay_attempt_count,
                )
                .values(
                    replay_state=DEAD_LETTER_REPLAY_CLAIMED,
                    replay_claim_id=claim_id,
                    replay_attempt_count=next_attempt_count,
                    replay_claimed_at=replayed_at,
                    replay_last_error=None,
                    replayed=False,
                    replayed_at=None,
                    replayed_by=replayed_by,
                    metadata_json={
                        **metadata,
                        "replay.claimed_at": replayed_at.isoformat(),
                        "replay.claim_id": str(claim_id),
                    },
                )
            ),
        )
        if result.rowcount != 1:
            raise DeadLetterAlreadyReplayedError(
                "dead-letter replay already in progress"
            )
        return _DeadLetterReplayClaim(
            dlq_id=row.dead_letter_task_id,
            queue_name=queue_name,
            kwargs=kwargs,
            task_name=row.task_name,
            replayed_at=replayed_at,
            replayed_by=replayed_by,
            claim_id=claim_id,
        )

    async def _set_replay_tenant(self, tenant_id: str) -> None:
        await self._session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )

    async def _mark_dead_letter_replay_published(
        self,
        *,
        claim: _DeadLetterReplayClaim,
        published_at: datetime,
    ) -> bool:
        result = cast(
            Any,
            await self._session.execute(
                update(DeadLetterTaskRow)
                .where(
                    DeadLetterTaskRow.dead_letter_task_id == claim.dlq_id,
                    DeadLetterTaskRow.replay_state
                    == DEAD_LETTER_REPLAY_CLAIMED,
                    DeadLetterTaskRow.replay_claim_id == claim.claim_id,
                    DeadLetterTaskRow.replayed.is_(False),
                )
                .values(
                    replay_state=DEAD_LETTER_REPLAY_PUBLISHED,
                    replayed=True,
                    replayed_at=published_at,
                    replayed_by=claim.replayed_by,
                    replay_last_error=None,
                    metadata_json=DeadLetterTaskRow.metadata_json.op("||")(
                        {
                            "replay.published_at": published_at.isoformat(),
                        }
                    ),
                )
            ),
        )
        if result.rowcount == 1:
            return True
        logger.info(
            "dead_letter_replay_claim_lost",
            extra={
                "dlq_id": str(claim.dlq_id),
                "claim_id": str(claim.claim_id),
                "operation": "published",
            },
        )
        return False

    async def _mark_dead_letter_replay_failed(
        self,
        *,
        claim: _DeadLetterReplayClaim,
        failed_at: datetime,
        error: str,
    ) -> None:
        result = cast(
            Any,
            await self._session.execute(
                update(DeadLetterTaskRow)
                .where(
                    DeadLetterTaskRow.dead_letter_task_id == claim.dlq_id,
                    DeadLetterTaskRow.replay_state
                    == DEAD_LETTER_REPLAY_CLAIMED,
                    DeadLetterTaskRow.replay_claim_id == claim.claim_id,
                    DeadLetterTaskRow.replayed.is_(False),
                )
                .values(
                    replay_state=DEAD_LETTER_REPLAY_FAILED,
                    replay_last_error=error,
                    replayed=False,
                    replayed_at=None,
                    replayed_by=claim.replayed_by,
                    metadata_json=DeadLetterTaskRow.metadata_json.op("||")(
                        {
                            "replay.failed_at": failed_at.isoformat(),
                            "replay.failure": error,
                        }
                    ),
                )
            ),
        )
        if result.rowcount != 1:
            logger.info(
                "dead_letter_replay_claim_lost",
                extra={
                    "dlq_id": str(claim.dlq_id),
                    "claim_id": str(claim.claim_id),
                    "operation": "failed",
                },
            )

    async def _queue_status_item(
        self,
        *,
        queue_name: str,
        queue_depth_provider: QueueDepthProvider,
        gate: AdmissionGate,
    ) -> QueueDepthItemRecord:
        try:
            sample = await queue_depth_provider.get_queue_depth(queue_name)
            depth = sample.depth
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
                error=_queue_depth_error_name(queue_depth_provider),
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
            messages_ready=sample.messages_ready,
            messages_unacknowledged=sample.messages_unacknowledged,
            messages=sample.messages,
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


def _queue_depth_error_name(provider: QueueDepthProvider) -> str:
    backend = getattr(provider, "backend", None)
    if backend == "redis":
        return "redis_unavailable"
    if backend == "rabbitmq":
        return "rabbitmq_unavailable"
    return "queue_depth_unavailable"


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
        replay_state=row.replay_state,
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


def _derive_replay_claim_id(
    *,
    dlq_id: uuid.UUID,
    tenant_id: str,
    replay_attempt_count: int,
) -> uuid.UUID:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if replay_attempt_count < 1:
        raise ValueError("replay_attempt_count must be >= 1")
    return uuid.uuid5(
        _DLQ_REPLAY_CLAIM_NAMESPACE,
        f"{dlq_id}|{tenant_id}|{replay_attempt_count}",
    )


def _bounded_replay_error(exc: BaseException) -> str:
    message = f"{exc.__class__.__name__}: {exc}"
    if len(message) > 240:
        return f"{message[:237]}..."
    return message


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


def _should_commit_external_transaction(
    *,
    session: AsyncSession,
    connection: AsyncConnection,
) -> bool:
    return (
        connection.in_transaction()
        and session.sync_session.join_transaction_mode != "create_savepoint"
    )


__all__ = [
    "DeadLetterAlreadyReplayedError",
    "DeadLetterCannotReplayUnknownTaskError",
    "DeadLetterItemRecord",
    "DeadLetterListPage",
    "DeadLetterNotFoundError",
    "DeadLetterReplayRecoveryRecord",
    "DeadLetterReplayRecord",
    "DEAD_LETTER_REPLAY_CLAIMED",
    "DEAD_LETTER_REPLAY_FAILED",
    "DEAD_LETTER_REPLAY_NONE",
    "DEAD_LETTER_REPLAY_PUBLISHED",
    "QueueDepthItemRecord",
    "QueueOperationsService",
    "QueueStatusRecord",
    "TASK_DEFAULT_QUEUES",
]
