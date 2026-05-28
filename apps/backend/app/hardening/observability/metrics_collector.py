"""Structured operational metrics emitted through project logging."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol


class _MetricsLogger(Protocol):
    def info(self, msg: str, *args: object, **kwargs: object) -> None: ...

    def warning(self, msg: str, *args: object, **kwargs: object) -> None: ...


class OperationalMetricsCollector:
    """Fire-and-forget structured metrics collector.

    Observability must never be allowed to crash task execution or block
    request handling, so every emit path swallows logging failures.
    """

    def __init__(self, *, logger: _MetricsLogger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def emit_task_started(
        self,
        *,
        task_id: str,
        task_name: str,
        queue: str,
        tenant_id: str | None,
        enqueued_at: datetime | None,
    ) -> None:
        now = _utc_now()
        queue_wait_ms = (
            _duration_ms(started_at=enqueued_at, ended_at=now)
            if enqueued_at is not None
            else None
        )
        self._emit(
            "task.started",
            {
                "task_id": task_id,
                "task_name": task_name,
                "queue": queue,
                "tenant_id": tenant_id,
                "enqueued_at": _iso_or_none(enqueued_at),
                "started_at": now.isoformat(),
                "queue_wait_ms": queue_wait_ms,
            },
        )

    def emit_task_completed(
        self,
        *,
        task_id: str,
        task_name: str,
        queue: str,
        tenant_id: str | None,
        started_at: datetime | None,
        outcome: str,
    ) -> None:
        now = _utc_now()
        self._emit(
            "task.completed",
            {
                "task_id": task_id,
                "task_name": task_name,
                "queue": queue,
                "tenant_id": tenant_id,
                "started_at": _iso_or_none(started_at),
                "completed_at": now.isoformat(),
                "processing_duration_ms": (
                    _duration_ms(started_at=started_at, ended_at=now)
                    if started_at is not None
                    else None
                ),
                "outcome": outcome,
            },
        )

    def emit_task_failed(
        self,
        *,
        task_id: str,
        task_name: str,
        queue: str,
        tenant_id: str | None,
        error_class: str,
        started_at: datetime | None,
    ) -> None:
        now = _utc_now()
        self._emit(
            "task.failed",
            {
                "task_id": task_id,
                "task_name": task_name,
                "queue": queue,
                "tenant_id": tenant_id,
                "error_class": error_class,
                "started_at": _iso_or_none(started_at),
                "failed_at": now.isoformat(),
                "processing_duration_ms": (
                    _duration_ms(started_at=started_at, ended_at=now)
                    if started_at is not None
                    else None
                ),
            },
        )

    def emit_task_retried(
        self,
        *,
        task_id: str,
        task_name: str,
        queue: str,
        tenant_id: str | None,
        retry_number: int,
        error_class: str,
    ) -> None:
        self._emit(
            "task.retried",
            {
                "task_id": task_id,
                "task_name": task_name,
                "queue": queue,
                "tenant_id": tenant_id,
                "retry_number": retry_number,
                "error_class": error_class,
            },
        )

    def emit_admission_decision(
        self,
        *,
        tenant_id: str | None,
        channel: str | None,
        decision: str,
        queue_name: str | None,
        reason: str | None,
        admission_telemetry_unavailable: bool = False,
        channel_class: str | None = None,
        unavailable_reasons: tuple[str, ...] = (),
        final_decision: str | None = None,
    ) -> None:
        self._emit(
            "admission.decision",
            {
                "tenant_id": tenant_id,
                "channel": channel,
                "decision": decision,
                "queue_name": queue_name,
                "reason": reason,
                "admission_telemetry_unavailable": admission_telemetry_unavailable,
                "channel_class": channel_class,
                "unavailable_reasons": unavailable_reasons,
                "final_decision": final_decision or decision,
            },
        )

    def emit_queue_depth_snapshot(
        self,
        *,
        depths: dict[str, int],
        snapshot_at: datetime,
    ) -> None:
        self._emit(
            "queue.depth_snapshot",
            {
                "depths": dict(depths),
                "snapshot_at": _as_utc(snapshot_at).isoformat(),
            },
        )

    def emit_provider_call(
        self,
        *,
        tenant_id: str | None,
        provider: str,
        model: str,
        duration_ms: int,
        outcome: str,
        tokens_used: int | None,
    ) -> None:
        self._emit(
            "provider.call_completed",
            {
                "tenant_id": tenant_id,
                "provider": provider,
                "model": model,
                "duration_ms": duration_ms,
                "outcome": outcome,
                "tokens_used": tokens_used,
            },
        )

    def _emit(self, event_key: str, fields: dict[str, object]) -> None:
        try:
            self._logger.info(event_key, extra=fields)
        except Exception as exc:  # noqa: BLE001 - metrics never propagate.
            try:
                self._logger.warning(
                    "operational_metrics_emit_failed",
                    extra={
                        "metric_event": event_key,
                        "error": exc.__class__.__name__,
                    },
                )
            except Exception:
                return


_collector: OperationalMetricsCollector | None = None


def initialize_metrics_collector(
    collector: OperationalMetricsCollector,
) -> None:
    global _collector
    _collector = collector


def get_metrics_collector() -> OperationalMetricsCollector | None:
    return _collector


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat()


def _duration_ms(*, started_at: datetime, ended_at: datetime) -> int:
    elapsed = _as_utc(ended_at) - _as_utc(started_at)
    return max(0, int(elapsed.total_seconds() * 1000))


__all__ = [
    "OperationalMetricsCollector",
    "get_metrics_collector",
    "initialize_metrics_collector",
]
