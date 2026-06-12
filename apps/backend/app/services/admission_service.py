"""Service-layer admission control wrapper."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker

from app.db.models.admission import AdmissionRecordRow
from app.hardening.admission import (
    AdmissionDecision,
    AdmissionGate,
    AdmissionOutcome,
)
from app.hardening.observability import get_metrics_collector
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class AdmissionService(BaseService):
    """Evaluate admission and persist actionable admission decisions durably."""

    def __init__(
        self,
        *,
        gate: AdmissionGate,
        session_factory: async_sessionmaker[AsyncSession],
        db_pool_wait_provider: Callable[[], Awaitable[float | None]] | None = None,
    ) -> None:
        super().__init__()
        self._gate = gate
        self._session_factory = session_factory
        self._db_pool_wait_provider = db_pool_wait_provider

    async def evaluate_and_persist(
        self,
        *,
        queue_name: str | None = None,
        queue_names: Sequence[str] | None = None,
        tenant_id: str | None = None,
        channel: str | None = None,
        request_correlation_id: str | None = None,
    ) -> AdmissionDecision:
        db_pool_wait_ms = await self._measure_db_pool_wait()
        decision = await self._gate.evaluate(
            queue_name=queue_name,
            queue_names=queue_names,
            tenant_id=tenant_id,
            channel=channel,
            request_correlation_id=request_correlation_id,
            db_pool_wait_ms=db_pool_wait_ms,
        )
        should_record = (
            decision.outcome is not AdmissionOutcome.ADMIT
            or decision.telemetry_unavailable
        )
        if not should_record:
            return decision
        self._emit_admission_decision(
            decision=decision,
            tenant_id=tenant_id,
            channel=channel,
        )
        if decision.telemetry_unavailable:
            self._log_telemetry_unavailable(
                decision=decision,
                tenant_id=tenant_id,
                channel=channel,
            )
        await self._persist_decision(
            decision=decision,
            tenant_id=tenant_id,
            channel=channel,
        )
        return decision

    async def _persist_decision(
        self,
        *,
        decision: AdmissionDecision,
        tenant_id: str | None,
        channel: str | None,
    ) -> None:
        try:
            async with self._session_factory() as session:
                session.add(
                    AdmissionRecordRow(
                        decision_id=decision.decision_id,
                        tenant_id=tenant_id,
                        outcome=decision.outcome.value,
                        reason=(
                            decision.reason.value
                            if decision.reason is not None
                            else None
                        ),
                        queue_name=decision.queue_name,
                        queue_depth=decision.queue_depth,
                        queue_age_seconds=decision.queue_age_seconds,
                        redis_memory_pct=decision.redis_memory_pct,
                        db_pool_wait_ms=decision.db_pool_wait_ms,
                        retry_after_seconds=decision.retry_after_seconds,
                        channel=channel,
                        channel_class=decision.channel_class.value,
                        queue_depth_available=decision.queue_depth_available,
                        queue_age_available=decision.queue_age_available,
                        redis_memory_available=decision.redis_memory_available,
                        telemetry_unavailable=decision.telemetry_unavailable,
                        unavailable_reasons=list(decision.unavailable_reasons),
                        evaluated_at=decision.evaluated_at,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - enforcement must not depend on audit.
            logger.exception(
                "admission_decision_persist_failed",
                extra={"decision_id": str(decision.decision_id)},
            )

    def _emit_admission_decision(
        self,
        *,
        decision: AdmissionDecision,
        tenant_id: str | None,
        channel: str | None,
    ) -> None:
        try:
            collector = get_metrics_collector()
            if collector is None:
                return
            collector.emit_admission_decision(
                tenant_id=tenant_id,
                channel=channel,
                decision=decision.outcome.value,
                queue_name=decision.queue_name,
                reason=(
                    decision.reason.value
                    if decision.reason is not None
                    else None
                ),
                admission_telemetry_unavailable=decision.telemetry_unavailable,
                channel_class=decision.channel_class.value,
                unavailable_reasons=decision.unavailable_reasons,
                final_decision=decision.outcome.value,
            )
        except Exception:  # noqa: BLE001 - metrics must not affect admission.
            logger.warning(
                "admission_metrics_emit_failed",
                extra={"decision_id": str(decision.decision_id)},
            )

    def _log_telemetry_unavailable(
        self,
        *,
        decision: AdmissionDecision,
        tenant_id: str | None,
        channel: str | None,
    ) -> None:
        logger.warning(
            "admission_telemetry_unavailable",
            extra={
                "decision_id": str(decision.decision_id),
                "tenant_id": tenant_id,
                "channel": channel,
                "admission_telemetry_unavailable": True,
                "channel_class": decision.channel_class.value,
                "queue_name": decision.queue_name,
                "unavailable_reasons": decision.unavailable_reasons,
                "final_decision": decision.outcome.value,
            },
        )

    async def _measure_db_pool_wait(self) -> float | None:
        if self._db_pool_wait_provider is None:
            return None
        try:
            return await self._db_pool_wait_provider()
        except Exception:  # noqa: BLE001 - DB pressure probe must fail open.
            logger.warning("admission_db_pool_wait_check_failed")
            return None


async def measure_db_pool_wait_ms(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    timeout_seconds: float = 1.0,
) -> float:
    """Estimate DB pool saturation from local engine statistics without network I/O."""

    del timeout_seconds
    engine = _resolve_engine(session_factory)
    if engine is None:
        return 0.0
    pool = getattr(engine, "pool", None)
    if pool is None:
        return 0.0
    checked_out = _safe_pool_int(pool, "checkedout")
    size = _safe_pool_int(pool, "size")
    overflow = _safe_pool_int(pool, "overflow")
    if checked_out is None or size is None or overflow is None:
        return 0.0
    capacity = max(size + overflow, 1)
    if checked_out <= 0:
        return 0.0
    utilization = checked_out / capacity
    if utilization >= 1.0:
        return 1000.0
    if utilization >= 0.75:
        return 500.0
    if utilization >= 0.5:
        return 250.0
    return round(utilization * 100, 2)


def _resolve_engine(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncEngine | object | None:
    bind = getattr(session_factory, "bind", None)
    if bind is None and hasattr(session_factory, "kw"):
        bind = getattr(session_factory.kw, "get", lambda *_: None)("bind")
    if bind is None:
        return None
    if hasattr(bind, "pool"):
        return bind
    if isinstance(bind, AsyncEngine):
        return bind
    sync_engine = getattr(bind, "sync_engine", None)
    if hasattr(sync_engine, "pool"):
        return sync_engine
    return sync_engine if isinstance(sync_engine, AsyncEngine) else None


def _safe_pool_int(pool: object, method_name: str) -> int | None:
    method = getattr(pool, method_name, None)
    if method is None:
        return None
    try:
        value = method()
    except Exception:  # noqa: BLE001 - pool introspection must be tolerant.
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return None


__all__ = ["AdmissionService", "measure_db_pool_wait_ms"]
