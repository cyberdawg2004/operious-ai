"""Alert evaluator for operational hardening signals."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from inspect import isawaitable
from typing import Any, Protocol, cast

import sentry_sdk
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AlertSettings(Protocol):
    ALERT_QUEUE_AGE_CRITICAL_SECONDS: int
    ALERT_DLQ_SPIKE_THRESHOLD: int
    ALERT_REDIS_MEMORY_PCT: float
    ALERT_DB_POOL_UTILIZATION: float
    DB_USE_NULLPOOL: bool


class AlertAdmissionGate(Protocol):
    async def queue_age_seconds(self, *, queue_name: str) -> float | None: ...

    async def redis_memory_pct(self) -> float | None: ...


@dataclass(frozen=True, slots=True)
class AlertCondition:
    name: str
    severity: str
    cooldown_seconds: int


@dataclass(frozen=True, slots=True)
class AlertResult:
    condition_name: str
    fired: bool
    severity: str
    message: str
    resource: str
    dedup_key: str
    metadata: dict[str, Any]


class AlertEvaluator:
    """Evaluate hardening alert conditions without owning a substrate."""

    CONDITIONS: list[AlertCondition] = [
        AlertCondition(
            name="queue_age_slo_breach",
            severity="warning",
            cooldown_seconds=300,
        ),
        AlertCondition(
            name="dlq_spike",
            severity="critical",
            cooldown_seconds=600,
        ),
        AlertCondition(
            name="provider_circuit_open",
            severity="critical",
            cooldown_seconds=120,
        ),
        AlertCondition(
            name="redis_memory_pressure",
            severity="warning",
            cooldown_seconds=300,
        ),
        AlertCondition(
            name="db_pool_exhaustion",
            severity="critical",
            cooldown_seconds=60,
        ),
        AlertCondition(
            name="replay_mismatch",
            severity="warning",
            cooldown_seconds=600,
        ),
    ]

    def __init__(
        self,
        *,
        settings: AlertSettings,
        redis_provider: Callable[[], Any],
        admission_gate_factory: Callable[[], AlertAdmissionGate],
        owner_session_context_factory: Callable[
            [],
            AbstractAsyncContextManager[Any],
        ],
        engine_provider: Callable[[], Any],
        queue_names: Sequence[str],
        dead_letter_task_row: Any,
        provider_circuit_state_row: Any,
        execution_row: Any,
        provider_open_state: str,
    ) -> None:
        self._settings = settings
        self._redis_provider = redis_provider
        self._admission_gate_factory = admission_gate_factory
        self._owner_session_context_factory = owner_session_context_factory
        self._engine_provider = engine_provider
        self._queue_names = tuple(queue_names)
        self._dead_letter_task_row = dead_letter_task_row
        self._provider_circuit_state_row = provider_circuit_state_row
        self._execution_row = execution_row
        self._provider_open_state = provider_open_state

    async def evaluate_all(
        self,
        session: AsyncSession,
    ) -> list[AlertResult]:
        """Evaluate all conditions, isolating failures per condition."""

        checks: tuple[
            tuple[AlertCondition, Callable[[], Awaitable[list[AlertResult]]]],
            ...,
        ] = (
            (self.CONDITIONS[0], self._check_queue_age_slo),
            (self.CONDITIONS[1], lambda: self._check_dlq_spike(session)),
            (self.CONDITIONS[2], lambda: self._check_provider_circuits(session)),
            (self.CONDITIONS[3], self._check_redis_memory),
            (self.CONDITIONS[4], self._check_db_pool),
            (self.CONDITIONS[5], lambda: self._check_replay_mismatch(session)),
        )
        fired: list[AlertResult] = []
        for condition, check in checks:
            try:
                fired.extend(await check())
            except Exception as exc:  # noqa: BLE001 - alert checks are isolated.
                logger.warning(
                    "alert_condition_evaluation_failed",
                    extra={
                        "condition_name": condition.name,
                        "error_class": exc.__class__.__name__,
                        "error": str(exc),
                    },
                )
        return fired

    async def _check_queue_age_slo(self) -> list[AlertResult]:
        gate = self._admission_gate()
        threshold = self._settings.ALERT_QUEUE_AGE_CRITICAL_SECONDS
        results: list[AlertResult] = []
        for queue_name in self._queue_names:
            age_seconds = await gate.queue_age_seconds(queue_name=queue_name)
            if age_seconds is None or age_seconds < threshold:
                continue
            results.append(
                AlertResult(
                    condition_name="queue_age_slo_breach",
                    fired=True,
                    severity="warning",
                    message=(
                        f"queue age SLO breach for {queue_name}: "
                        f"{age_seconds}s >= {threshold}s"
                    ),
                    resource=queue_name,
                    dedup_key=f"queue_age:{queue_name}",
                    metadata={
                        "queue_name": queue_name,
                        "age_seconds": age_seconds,
                        "threshold_seconds": threshold,
                    },
                )
            )
        return results

    async def _check_dlq_spike(
        self,
        session: AsyncSession,
    ) -> list[AlertResult]:
        del session
        # PRIVILEGED_PATH: cross-tenant DLQ spike detection.
        async with self._owner_session_context_factory() as owner_session:
            current_count = int(
                (
                    await owner_session.execute(
                        text(
                            "SELECT COUNT(*) FROM dead_letter_tasks "
                            "WHERE created_at > NOW() - INTERVAL '1 hour'"
                        )
                    )
                ).scalar_one()
                or 0
            )

        baseline_value = await self._get_redis_string("alert:dlq_baseline")
        if baseline_value is None:
            await self._set_redis_string("alert:dlq_baseline", str(current_count))
            return []
        try:
            baseline_count = int(baseline_value)
        except ValueError:
            await self._set_redis_string("alert:dlq_baseline", str(current_count))
            return []

        delta = current_count - baseline_count
        await self._set_redis_string("alert:dlq_baseline", str(current_count))
        if delta < self._settings.ALERT_DLQ_SPIKE_THRESHOLD:
            return []
        return [
            AlertResult(
                condition_name="dlq_spike",
                fired=True,
                severity="critical",
                message=(
                    "DLQ spike detected: "
                    f"{delta} new records in the last hour"
                ),
                resource="dead_letter_tasks",
                dedup_key="dlq_spike",
                metadata={
                    "current_count": current_count,
                    "baseline_count": baseline_count,
                    "delta": delta,
                    "threshold": self._settings.ALERT_DLQ_SPIKE_THRESHOLD,
                    "window_seconds": 3600,
                },
            )
        ]

    async def _check_provider_circuits(
        self,
        session: AsyncSession,
    ) -> list[AlertResult]:
        del session
        now = datetime.now(timezone.utc)
        row_type = self._provider_circuit_state_row
        # PRIVILEGED_PATH: cross-tenant circuit state inspection.
        async with self._owner_session_context_factory() as owner_session:
            rows = tuple(
                (
                    await owner_session.execute(
                        select(row_type).where(
                            row_type.state == self._provider_open_state,
                            or_(
                                row_type.open_until.is_(None),
                                row_type.open_until > now,
                            ),
                        )
                    )
                ).scalars()
            )
        return [
            AlertResult(
                condition_name="provider_circuit_open",
                fired=True,
                severity="critical",
                message=(
                    "provider circuit open for "
                    f"{row.tenant_id}/{row.provider_name}"
                ),
                resource=f"{row.tenant_id}:{row.provider_name}",
                dedup_key=f"circuit_open:{row.tenant_id}:{row.provider_name}",
                metadata={
                    "tenant_id": row.tenant_id,
                    "provider_name": row.provider_name,
                    "state": row.state,
                    "opened_at": _iso_or_none(row.opened_at),
                    "open_until": _iso_or_none(row.open_until),
                    "last_failure_reason": row.last_failure_reason,
                },
            )
            for row in rows
        ]

    async def _check_redis_memory(self) -> list[AlertResult]:
        memory_pct = await self._admission_gate().redis_memory_pct()
        threshold = self._settings.ALERT_REDIS_MEMORY_PCT
        if memory_pct is None or memory_pct < threshold:
            return []
        return [
            AlertResult(
                condition_name="redis_memory_pressure",
                fired=True,
                severity="warning",
                message=f"Redis memory pressure: {memory_pct}% >= {threshold}%",
                resource="redis",
                dedup_key="redis_memory",
                metadata={
                    "memory_pct": memory_pct,
                    "threshold_pct": threshold,
                },
            )
        ]

    async def _check_db_pool(self) -> list[AlertResult]:
        if self._settings.DB_USE_NULLPOOL:
            return []
        try:
            pool = self._engine_provider().sync_engine.pool
            checked_out = int(pool.checkedout())
            capacity = int(pool.size()) + int(pool.overflow())
            if capacity <= 0:
                return []
            utilization = checked_out / capacity
        except Exception as exc:  # noqa: BLE001 - DB pool alert is best-effort.
            logger.warning(
                "alert_db_pool_status_unavailable",
                extra={
                    "error_class": exc.__class__.__name__,
                    "error": str(exc),
                },
            )
            return []

        threshold = self._settings.ALERT_DB_POOL_UTILIZATION
        if utilization < threshold:
            return []
        return [
            AlertResult(
                condition_name="db_pool_exhaustion",
                fired=True,
                severity="critical",
                message=(
                    "DB pool utilization high: "
                    f"{utilization:.2f} >= {threshold:.2f}"
                ),
                resource="database",
                dedup_key="db_pool",
                metadata={
                    "checked_out": checked_out,
                    "capacity": capacity,
                    "utilization": round(utilization, 6),
                    "threshold": threshold,
                },
            )
        ]

    async def _check_replay_mismatch(
        self,
        session: AsyncSession,
    ) -> list[AlertResult]:
        del session
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        dead_letter_row = self._dead_letter_task_row
        execution_row = self._execution_row
        # PRIVILEGED_PATH: cross-tenant replay verification.
        async with self._owner_session_context_factory() as owner_session:
            rows = tuple(
                (
                    await owner_session.execute(
                        select(dead_letter_row)
                        .where(
                            dead_letter_row.replayed.is_(True),
                            dead_letter_row.replayed_at.is_not(None),
                            dead_letter_row.replayed_at > cutoff,
                        )
                        .order_by(
                            dead_letter_row.replayed_at.desc(),
                            dead_letter_row.dead_letter_task_id,
                        )
                    )
                ).scalars()
            )
            results: list[AlertResult] = []
            rows_with_execution_id: list[tuple[Any, str, uuid.UUID]] = []
            for row in rows:
                execution_id = _execution_id_from_metadata(row.metadata_json)
                execution_uuid = _uuid_or_none(execution_id)
                if execution_id is not None and execution_uuid is not None:
                    rows_with_execution_id.append((row, execution_id, execution_uuid))
            if not rows_with_execution_id:
                return []

            execution_ids = [
                execution_uuid
                for _row, _execution_id, execution_uuid in rows_with_execution_id
            ]
            existing_ids = {
                str(value)
                for value in (
                    await owner_session.execute(
                        select(execution_row.execution_id).where(
                            execution_row.execution_id.in_(execution_ids)
                        )
                    )
                ).scalars()
            }

            for row, execution_id, execution_uuid in rows_with_execution_id:
                if str(execution_uuid) in existing_ids:
                    continue
                dlq_id = str(row.dead_letter_task_id)
                results.append(
                    AlertResult(
                        condition_name="replay_mismatch",
                        fired=True,
                        severity="warning",
                        message=(
                            "DLQ replay mismatch: execution record not found "
                            f"for dead-letter task {dlq_id}"
                        ),
                        resource=dlq_id,
                        dedup_key=f"replay_mismatch:{dlq_id}",
                        metadata={
                            "dead_letter_task_id": dlq_id,
                            "tenant_id": row.tenant_id,
                            "task_name": row.task_name,
                            "task_id": row.task_id,
                            "execution_id": execution_id,
                            "replayed_at": _iso_or_none(row.replayed_at),
                        },
                    )
                )
        return results

    async def _is_in_cooldown(
        self,
        dedup_key: str,
    ) -> bool:
        try:
            redis_client = self._redis_provider()
            value = await _resolve(
                redis_client.exists(f"alert:cooldown:{dedup_key}")
            )
            return bool(value)
        except Exception:  # noqa: BLE001 - cooldown fails open.
            return False

    async def _set_cooldown(
        self,
        dedup_key: str,
        cooldown_seconds: int,
    ) -> None:
        try:
            redis_client = self._redis_provider()
            await _resolve(
                redis_client.set(
                    f"alert:cooldown:{dedup_key}",
                    "1",
                    ex=cooldown_seconds,
                )
            )
        except Exception:  # noqa: BLE001 - cooldown persistence is best-effort.
            return

    async def fire_alert(
        self,
        result: AlertResult,
        session: AsyncSession,
    ) -> None:
        await self._fire_alert(result, session)

    async def _fire_alert(
        self,
        result: AlertResult,
        session: AsyncSession,
    ) -> None:
        del session
        if await self._is_in_cooldown(result.dedup_key):
            return
        condition = self._condition(result.condition_name)
        await self._set_cooldown(result.dedup_key, condition.cooldown_seconds)
        level = "error" if result.severity == "critical" else "warning"
        try:
            sentry_sdk.capture_message(
                f"[{result.severity}] {result.message}",
                level=level,
            )
        except Exception as exc:  # noqa: BLE001 - alerting must not crash tasks.
            logger.warning(
                "alert_sentry_capture_failed",
                extra={
                    "condition_name": result.condition_name,
                    "error_class": exc.__class__.__name__,
                },
            )
        logger.warning(
            "alert.fired",
            extra={
                "condition_name": result.condition_name,
                "severity": result.severity,
                "resource": result.resource,
                "dedup_key": result.dedup_key,
                "alert_message": result.message,
                "alert_metadata": dict(result.metadata),
            },
        )

    def _admission_gate(self) -> AlertAdmissionGate:
        return self._admission_gate_factory()

    def _condition(self, name: str) -> AlertCondition:
        for condition in self.CONDITIONS:
            if condition.name == name:
                return condition
        return AlertCondition(name=name, severity="warning", cooldown_seconds=300)

    async def _get_redis_string(self, key: str) -> str | None:
        try:
            value = await _resolve(self._redis_provider().get(key))
        except Exception:  # noqa: BLE001 - baseline reads fail open.
            return None
        return value if isinstance(value, str) else None

    async def _set_redis_string(self, key: str, value: str) -> None:
        try:
            await _resolve(self._redis_provider().set(key, value))
        except Exception:  # noqa: BLE001 - baseline writes are best-effort.
            return


_evaluator: AlertEvaluator | None = None


def initialize_alert_evaluator(evaluator: AlertEvaluator) -> None:
    global _evaluator
    _evaluator = evaluator


def get_alert_evaluator() -> AlertEvaluator | None:
    return _evaluator


async def _resolve(value: Awaitable[Any] | Any) -> Any:
    if isawaitable(value):
        return await value
    return value


def _execution_id_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    if not isinstance(metadata, Mapping):
        return None
    celery_kwargs = metadata.get("celery_kwargs")
    if not isinstance(celery_kwargs, Mapping):
        return None
    value = cast(Mapping[Any, Any], celery_kwargs).get("execution_id")
    return value if isinstance(value, str) and value else None


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


__all__ = [
    "AlertCondition",
    "AlertEvaluator",
    "AlertResult",
    "get_alert_evaluator",
    "initialize_alert_evaluator",
]
