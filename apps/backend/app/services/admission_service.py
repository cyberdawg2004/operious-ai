"""Service-layer admission control wrapper."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    """Evaluate admission and persist non-ADMIT decisions durably."""

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
        if decision.outcome is AdmissionOutcome.ADMIT:
            return decision
        self._emit_admission_decision(
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
            )
        except Exception:  # noqa: BLE001 - metrics must not affect admission.
            logger.warning(
                "admission_metrics_emit_failed",
                extra={"decision_id": str(decision.decision_id)},
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
    """Measure wait to acquire and execute a tiny DB round-trip."""

    async def _probe() -> float:
        started = time.perf_counter()
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return round((time.perf_counter() - started) * 1000, 2)

    try:
        return await asyncio.wait_for(_probe(), timeout=timeout_seconds)
    except TimeoutError:
        return round(timeout_seconds * 1000, 2)


__all__ = ["AdmissionService", "measure_db_pool_wait_ms"]
