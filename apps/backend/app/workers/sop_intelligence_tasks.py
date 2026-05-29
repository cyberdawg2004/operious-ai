"""SOP intelligence proposal worker tasks.

Celery is transport only. The task accepts primitive lineage and
composes the persistence-backed SOP Intelligence Agent runtime inside
the worker boundary.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Any, TypeVar

from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.session import get_owner_session_factory, get_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.governance.persistence import PostgresGovernanceRepository
from app.qa.persistence import PostgresQAPersistence
from app.runtime import make_postgres_sop_approval_event_projector
from app.session.persistence import PostgresSessionPersistence
from app.sop_intelligence.exceptions import SOPIntelligenceError
from app.sop_intelligence.persistence import PostgresSOPApprovalPersistence
from app.sop_intelligence.runtime import SOPIntelligenceRuntime
from app.supervisor.persistence import PostgresSupervisorRepository
from app.tenant.db.models import TenantRow
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.trainer.persistence import (
    PostgresTrainingRecommendationRepository,
    TrainingFailurePattern,
)
from app.workers.celery_app import celery_app
from app.workers.queue_admission import clear_worker_queue_age
from app.queues import QUEUE_SOP_INTELLIGENCE

_T = TypeVar("_T")
logger = logging.getLogger(__name__)

# PRIVILEGED_PATH: the scheduled gap scanner enumerates tenant IDs under
# an owner session, then reinstates app.current_tenant_id before every
# tenant-scoped read/write.


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="propose_sop_intelligence_change",
    queue=QUEUE_SOP_INTELLIGENCE,
    bind=True,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=30,
)
def propose_sop_intelligence_change(
    _self: Any,
    session_id: str,
    tenant_id: str,
    inspection_id: str | None = None,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Create a pending SOP approval proposal for one session."""
    del _enqueued_at

    set_current_tenant(tenant_id)
    try:
        return _run_async(
            propose_sop_intelligence_change_runtime(
                session_id=session_id,
                tenant_id=tenant_id,
                inspection_id=inspection_id,
            ),
            tenant_id=tenant_id,
        )
    finally:
        set_current_tenant(None)


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="scan_training_recommendation_gaps",
    queue=QUEUE_SOP_INTELLIGENCE,
    bind=True,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=30,
)
def scan_training_recommendation_gaps(_self: Any) -> dict[str, object]:
    """Scan pending trainer recommendations for repeated SOP gaps."""

    return _run_async(
        scan_training_recommendation_gaps_runtime(),
        tenant_id="maintenance",
    )


async def propose_sop_intelligence_change_runtime(
    *,
    session_id: str,
    tenant_id: str,
    inspection_id: str | None = None,
) -> dict[str, object]:
    set_current_tenant(tenant_id)
    try:
        await clear_worker_queue_age(
            queue_name=QUEUE_SOP_INTELLIGENCE,
            member_id=session_id,
        )
        session_factory = get_session_factory()
        async with session_factory() as session:
            approval_persistence = PostgresSOPApprovalPersistence(session)
            runtime = SOPIntelligenceRuntime(
                approval_persistence=approval_persistence,
                session_persistence=PostgresSessionPersistence(session),
                supervisor_repository=PostgresSupervisorRepository(session),
                qa_persistence=PostgresQAPersistence(session),
                governance_repository=PostgresGovernanceRepository(session),
                tenant_configuration_repository=(
                    PostgresTenantConfigurationRepository(session)
                ),
            )
            record = await runtime.propose_for_session(
                session_id=session_id,
                expected_tenant_id=tenant_id,
                inspection_id=inspection_id,
            )
            projection = await make_postgres_sop_approval_event_projector(
                session,
                approval_persistence=approval_persistence,
            ).project_approval(
                record.approval_id,
                expected_tenant_id=tenant_id,
            )
            await session.commit()
            return {
                "status": "completed",
                "session_id": session_id,
                "tenant_id": record.tenant_id,
                "approval_id": record.approval_id,
                "operational_event_id": projection.operational_event.event_id,
                "document_id": record.document_id,
                "queue_status": record.status,
                "confidence": record.confidence,
            }
    finally:
        set_current_tenant(None)


async def scan_training_recommendation_gaps_runtime(
    *,
    tenant_ids: tuple[str, ...] | None = None,
    session: Any | None = None,
) -> dict[str, object]:
    settings = get_settings()
    threshold = settings.SOP_REPEATED_FAILURE_THRESHOLD
    since = datetime.now(timezone.utc) - timedelta(
        days=settings.SOP_REPEATED_FAILURE_LOOKBACK_DAYS
    )
    try:
        if session is not None:
            return await _scan_training_recommendation_gaps_with_session(
                session=session,
                tenant_ids=tenant_ids,
                since=since,
                threshold=threshold,
            )

        session_factory = get_owner_session_factory()
        async with session_factory() as owned_session:
            return await _scan_training_recommendation_gaps_with_session(
                session=owned_session,
                tenant_ids=tenant_ids,
                since=since,
                threshold=threshold,
            )
    finally:
        set_current_tenant(None)


async def _scan_training_recommendation_gaps_with_session(
    *,
    session: Any,
    tenant_ids: tuple[str, ...] | None,
    since: datetime,
    threshold: int,
) -> dict[str, object]:
    approval_persistence = PostgresSOPApprovalPersistence(session)
    trainer_repository = PostgresTrainingRecommendationRepository(session)
    runtime = SOPIntelligenceRuntime(
        approval_persistence=approval_persistence,
        session_persistence=PostgresSessionPersistence(session),
        supervisor_repository=PostgresSupervisorRepository(session),
        qa_persistence=PostgresQAPersistence(session),
        governance_repository=PostgresGovernanceRepository(session),
        tenant_configuration_repository=(
            PostgresTenantConfigurationRepository(session)
        ),
    )
    tenants = (
        tenant_ids
        if tenant_ids is not None
        else await _tenant_ids_for_gap_scan(session)
    )
    if not tenants and get_current_tenant():
        tenants = (str(get_current_tenant()),)

    patterns: list[TrainingFailurePattern] = []
    for tenant_id in tenants:
        set_current_tenant(tenant_id)
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": tenant_id},
        )
        patterns.extend(
            await trainer_repository.list_failure_patterns(
                expected_tenant_id=tenant_id,
                since=since,
                threshold=threshold,
            )
        )
    if not patterns:
        patterns.extend(
            await trainer_repository.list_all_failure_patterns(
                since=since,
                threshold=threshold,
            )
        )

    proposed: list[str] = []
    skipped: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for pattern in patterns:
        key = (pattern.tenant_id, pattern.category)
        if key in seen:
            continue
        seen.add(key)
        set_current_tenant(pattern.tenant_id)
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": pattern.tenant_id},
        )
        try:
            record = await runtime.propose_from_failure_pattern(
                tenant_id=pattern.tenant_id,
                expected_tenant_id=pattern.tenant_id,
                category=pattern.category,
                recommendation_count=pattern.recommendation_count,
            )
            projection = await make_postgres_sop_approval_event_projector(
                session,
                approval_persistence=approval_persistence,
            ).project_approval(
                record.approval_id,
                expected_tenant_id=pattern.tenant_id,
            )
            proposed.append(record.approval_id)
            logger.info(
                "sop_failure_pattern_proposed",
                extra={
                    "tenant_id": pattern.tenant_id,
                    "category": pattern.category,
                    "recommendation_count": pattern.recommendation_count,
                    "approval_id": record.approval_id,
                    "operational_event_id": str(
                        projection.operational_event.event_id
                    ),
                },
            )
        except SOPIntelligenceError as exc:
            skipped.append(
                {
                    "tenant_id": pattern.tenant_id,
                    "category": pattern.category,
                    "reason": exc.__class__.__name__,
                }
            )
    await session.commit()
    return {
        "status": "completed",
        "patterns_seen": len(patterns),
        "proposals_created": len(proposed),
        "approval_ids": proposed,
        "skipped": skipped,
    }


async def _tenant_ids_for_gap_scan(session: Any) -> tuple[str, ...]:
    rows = (await session.execute(select(TenantRow.tenant_id))).scalars().all()
    return tuple(str(row) for row in rows)


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
        raise RuntimeError("SOP intelligence coroutine returned no result")
    return results[0]


__all__ = [
    "propose_sop_intelligence_change",
    "propose_sop_intelligence_change_runtime",
    "scan_training_recommendation_gaps",
    "scan_training_recommendation_gaps_runtime",
]
