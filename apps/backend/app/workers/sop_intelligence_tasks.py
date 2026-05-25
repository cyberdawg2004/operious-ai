"""SOP intelligence proposal worker tasks.

Celery is transport only. The task accepts primitive lineage and
composes the persistence-backed SOP Intelligence Agent runtime inside
the worker boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from threading import Thread
from typing import Any, TypeVar

from app.db.session import get_session_factory
from app.db.tenant_context import set_current_tenant
from app.governance.persistence import PostgresGovernanceRepository
from app.qa.persistence import PostgresQAPersistence
from app.runtime import make_postgres_sop_approval_event_projector
from app.session.persistence import PostgresSessionPersistence
from app.sop_intelligence.persistence import PostgresSOPApprovalPersistence
from app.sop_intelligence.runtime import SOPIntelligenceRuntime
from app.supervisor.persistence import PostgresSupervisorRepository
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.workers.celery_app import celery_app
from app.workers.queue_admission import clear_worker_queue_age
from app.queues import QUEUE_SOP_INTELLIGENCE

_T = TypeVar("_T")


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
) -> dict[str, object]:
    """Create a pending SOP approval proposal for one session."""

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
]
