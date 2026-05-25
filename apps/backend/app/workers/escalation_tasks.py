"""Escalation worker tasks.

Celery is transport only. The task accepts governance denial lineage
and composes the persistence-backed escalation runtime inside the
worker boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from threading import Thread
from typing import Any, TypeVar

from app.db.session import get_session_factory
from app.db.tenant_context import set_current_tenant
from app.escalation.persistence import PostgresEscalationPersistence
from app.escalation.runtime import EscalationAgentRuntime
from app.governance.persistence import PostgresGovernanceRepository
from app.session.persistence import PostgresSessionPersistence
from app.workers.celery_app import celery_app
from app.workers.queue_admission import clear_worker_queue_age
from app.queues import QUEUE_ESCALATION

_T = TypeVar("_T")


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="create_governance_escalation",
    queue=QUEUE_ESCALATION,
    bind=True,
    ignore_result=True,
    max_retries=2,
    default_retry_delay=30,
)
def create_governance_escalation(
    _self: Any,
    governance_decision_id: str,
    tenant_id: str,
    session_id: str | None = None,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Create a pending escalation for one governance DENY decision."""
    del _enqueued_at

    set_current_tenant(tenant_id)
    try:
        return _run_async(
            create_governance_escalation_runtime(
                governance_decision_id=governance_decision_id,
                tenant_id=tenant_id,
                session_id=session_id,
            ),
            tenant_id=tenant_id,
        )
    finally:
        set_current_tenant(None)


async def create_governance_escalation_runtime(
    *,
    governance_decision_id: str,
    tenant_id: str,
    session_id: str | None = None,
) -> dict[str, object]:
    set_current_tenant(tenant_id)
    try:
        await clear_worker_queue_age(
            queue_name=QUEUE_ESCALATION,
            member_id=governance_decision_id,
        )
        session_factory = get_session_factory()
        async with session_factory() as session:
            runtime = EscalationAgentRuntime(
                escalation_persistence=PostgresEscalationPersistence(session),
                governance_repository=PostgresGovernanceRepository(session),
                session_persistence=PostgresSessionPersistence(session),
            )
            prepared = await runtime.prepare_governance_denial_outbox(
                governance_decision_id=governance_decision_id,
                expected_tenant_id=tenant_id,
                session_id=session_id,
            )
            await session.commit()
            return {
                "status": "completed",
                "governance_decision_id": governance_decision_id,
                "escalation_id": prepared.escalation.escalation_id,
                "session_id": prepared.escalation.session_id,
                "tenant_id": prepared.escalation.tenant_id,
                "queue_status": prepared.escalation.status,
                "outbox_id": prepared.outbox.outbox_id,
                "outbox_status": prepared.outbox.status.value,
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
        raise RuntimeError("escalation coroutine returned no result")
    return results[0]


__all__ = [
    "create_governance_escalation",
    "create_governance_escalation_runtime",
]
