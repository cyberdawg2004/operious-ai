"""Scheduled SOP failure-pattern detection tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from threading import Thread
from typing import Any, Protocol, TypeVar

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_owner_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.events.persistence import OperationalEventPersistenceProtocol
from app.governance.persistence import PostgresGovernanceRepository
from app.qa.persistence import PostgresQAPersistence
from app.queues import QUEUE_SOP_INTELLIGENCE
from app.runtime.failure_pattern_runtime import (
    FailurePattern,
    FailurePatternDetectionRuntime,
)
from app.session.persistence import PostgresSessionPersistence
from app.sop_intelligence.persistence import PostgresSOPApprovalPersistence
from app.sop_intelligence.runtime import SOPIntelligenceRuntime
from app.supervisor.persistence import PostgresSupervisorRepository
from app.tenant.db.models import TenantRow
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.workers.celery_app import celery_app

_T = TypeVar("_T")
logger = logging.getLogger(__name__)


class SOPFailurePatternProposalProtocol(Protocol):
    def propose_from_failure_pattern(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        category: str,
        recommendation_count: int,
    ) -> Coroutine[Any, Any, Any]: ...


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="detect_sop_failure_patterns",
    queue=QUEUE_SOP_INTELLIGENCE,
    bind=True,
    ignore_result=True,
    max_retries=2,
    default_retry_delay=120,
)
def detect_sop_failure_patterns(_self: Any) -> dict[str, object]:
    """PRIVILEGED_PATH: scan all tenants for DLQ/admission SOP gaps."""

    return _run_async(
        detect_sop_failure_patterns_runtime(),
        tenant_id="maintenance",
    )


async def detect_sop_failure_patterns_runtime(
    *,
    tenant_ids: tuple[str, ...] | None = None,
    session: AsyncSession | None = None,
    sop_runtime: SOPFailurePatternProposalProtocol | None = None,
    event_persistence: OperationalEventPersistenceProtocol | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    settings = get_settings()
    window_hours = settings.SOP_FAILURE_PATTERN_DLQ_WINDOW_HOURS
    dlq_threshold = settings.SOP_FAILURE_PATTERN_DLQ_THRESHOLD
    admission_threshold = settings.SOP_FAILURE_PATTERN_ADMISSION_THRESHOLD
    if session is not None:
        return await _detect_sop_failure_patterns_with_session(
            session=session,
            tenant_ids=tenant_ids,
            sop_runtime=sop_runtime,
            event_persistence=event_persistence,
            now=now,
            window_hours=window_hours,
            dlq_threshold=dlq_threshold,
            admission_threshold=admission_threshold,
        )

    session_factory = get_owner_session_factory()
    async with session_factory() as owned_session:
        return await _detect_sop_failure_patterns_with_session(
            session=owned_session,
            tenant_ids=tenant_ids,
            sop_runtime=sop_runtime,
            event_persistence=event_persistence,
            now=now,
            window_hours=window_hours,
            dlq_threshold=dlq_threshold,
            admission_threshold=admission_threshold,
        )


async def _detect_sop_failure_patterns_with_session(
    *,
    session: AsyncSession,
    tenant_ids: tuple[str, ...] | None,
    sop_runtime: SOPFailurePatternProposalProtocol | None,
    event_persistence: OperationalEventPersistenceProtocol | None,
    now: Callable[[], datetime] | None,
    window_hours: int,
    dlq_threshold: int,
    admission_threshold: int,
) -> dict[str, object]:
    tenants = (
        tenant_ids
        if tenant_ids is not None
        else await _tenant_ids_for_failure_pattern_scan(session)
    )
    if not tenants and get_current_tenant():
        tenants = (str(get_current_tenant()),)

    detector = FailurePatternDetectionRuntime(
        session=session,
        event_persistence=event_persistence,
        now=now,
    )
    proposer = sop_runtime or _sop_runtime(session)
    detected: list[dict[str, object]] = []
    inserted: list[str] = []
    proposed: list[str] = []
    proposal_failed: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []

    for tenant_id in tenants:
        set_current_tenant(tenant_id)
        await _set_db_tenant_context(session, tenant_id)
        try:
            async with session.begin_nested():
                patterns = await _detect_patterns_for_tenant(
                    detector=detector,
                    tenant_id=tenant_id,
                    window_hours=window_hours,
                    dlq_threshold=dlq_threshold,
                    admission_threshold=admission_threshold,
                )
                for pattern in patterns:
                    threshold = (
                        admission_threshold
                        if pattern.pattern_source == "admission"
                        else dlq_threshold
                    )
                    detected.append(_pattern_payload(pattern))
                    recorded = await detector.record_detected_pattern(
                        pattern=pattern,
                        expected_tenant_id=tenant_id,
                        window_hours=window_hours,
                        threshold=threshold,
                    )
                    if not recorded.inserted:
                        continue
                    inserted.append(str(recorded.pattern_id))
                    try:
                        record = await proposer.propose_from_failure_pattern(
                            tenant_id=pattern.tenant_id,
                            expected_tenant_id=pattern.tenant_id,
                            category=pattern.category,
                            recommendation_count=pattern.failure_count,
                        )
                        approval_id = str(getattr(record, "approval_id"))
                        await detector.mark_pattern_proposed(
                            pattern_id=recorded.pattern_id,
                            expected_tenant_id=tenant_id,
                            proposal_id=approval_id,
                        )
                        proposed.append(approval_id)
                    except Exception as exc:  # noqa: BLE001 - retry next scan.
                        proposal_failed.append(
                            {
                                "tenant_id": tenant_id,
                                "category": pattern.category,
                                "reason": exc.__class__.__name__,
                            }
                        )
                        logger.warning(
                            "sop_failure_pattern_proposal_failed",
                            extra={
                                "tenant_id": tenant_id,
                                "category": pattern.category,
                                "error_class": exc.__class__.__name__,
                            },
                        )
        except Exception as exc:  # noqa: BLE001 - fail open per tenant.
            failed.append(
                {
                    "tenant_id": tenant_id,
                    "reason": exc.__class__.__name__,
                }
            )
            logger.exception(
                "sop_failure_pattern_scan_tenant_failed",
                extra={"tenant_id": tenant_id},
            )

    await session.commit()
    set_current_tenant(None)
    return {
        "status": "completed",
        "tenants_scanned": len(tenants),
        "patterns_detected": len(detected),
        "patterns_inserted": len(inserted),
        "patterns_proposed": len(proposed),
        "pattern_ids": inserted,
        "approval_ids": proposed,
        "detected": detected,
        "proposal_failed": proposal_failed,
        "failed": failed,
    }


async def _detect_patterns_for_tenant(
    *,
    detector: FailurePatternDetectionRuntime,
    tenant_id: str,
    window_hours: int,
    dlq_threshold: int,
    admission_threshold: int,
) -> list[FailurePattern]:
    patterns = await detector.detect_dlq_patterns(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
        window_hours=window_hours,
        threshold=dlq_threshold,
    )
    patterns.extend(
        await detector.detect_admission_patterns(
            tenant_id=tenant_id,
            expected_tenant_id=tenant_id,
            window_hours=window_hours,
            threshold=admission_threshold,
        )
    )
    return patterns


def _pattern_payload(pattern: FailurePattern) -> dict[str, object]:
    return {
        "tenant_id": pattern.tenant_id,
        "category": pattern.category,
        "failure_count": pattern.failure_count,
        "pattern_source": pattern.pattern_source,
        "window_start": pattern.window_start.isoformat(),
        "window_end": pattern.window_end.isoformat(),
    }


def _sop_runtime(session: AsyncSession) -> SOPIntelligenceRuntime:
    return SOPIntelligenceRuntime(
        approval_persistence=PostgresSOPApprovalPersistence(session),
        session_persistence=PostgresSessionPersistence(session),
        supervisor_repository=PostgresSupervisorRepository(session),
        qa_persistence=PostgresQAPersistence(session),
        governance_repository=PostgresGovernanceRepository(session),
        tenant_configuration_repository=PostgresTenantConfigurationRepository(
            session
        ),
    )


async def _tenant_ids_for_failure_pattern_scan(
    session: AsyncSession,
) -> tuple[str, ...]:
    rows = (await session.execute(select(TenantRow.tenant_id))).scalars().all()
    return tuple(str(row) for row in rows)


async def _set_db_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "postgresql":
        return
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": tenant_id},
    )


def _run_async(coro: Coroutine[Any, Any, _T], *, tenant_id: str) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        set_current_tenant(tenant_id)
        try:
            return asyncio.run(coro)
        finally:
            set_current_tenant(None)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        set_current_tenant(tenant_id)
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            set_current_tenant(None)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not results:
        raise RuntimeError("failure pattern coroutine returned no result")
    return results[0]


__all__ = [
    "detect_sop_failure_patterns",
    "detect_sop_failure_patterns_runtime",
]
