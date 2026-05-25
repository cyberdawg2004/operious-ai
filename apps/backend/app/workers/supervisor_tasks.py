"""Supervisor evaluation worker tasks.

Celery is transport only. The task accepts a ``session_id`` and then
constructs the persisted-evidence supervisor runtime inside the worker
boundary; no live runtime objects are passed into supervisor
evaluation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from threading import Thread
from typing import Any, TypeVar, cast

from app.db.session import get_session_factory
from app.db.tenant_context import set_current_tenant
from app.execution import PostgresExecutionPersistence
from app.governance.persistence import PostgresGovernanceRepository
from app.session.persistence import PostgresSessionPersistence
from app.supervisor.evaluators.builtin import build_default_evaluator_registry
from app.supervisor.persistence import PostgresSupervisorRepository
from app.supervisor.runtime import SupervisorRuntime
from app.workers.celery_app import celery_app, enqueued_at_iso
from app.workers.queue_admission import (
    admit_qa_publish,
    clear_worker_queue_age,
    record_worker_queue_age,
)
from app.queues import QUEUE_QA, QUEUE_SUPERVISOR
from app.workers.qa_tasks import score_supervisor_inspection

_T = TypeVar("_T")


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="evaluate_session_supervisor",
    queue=QUEUE_SUPERVISOR,
    bind=True,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=30,
)
def evaluate_session_supervisor(
    _self: Any,
    session_id: str,
    tenant_id: str,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Evaluate one closed session through supervisor persistence."""
    del _enqueued_at

    set_current_tenant(tenant_id)
    try:
        return _run_async(
            evaluate_session_supervisor_runtime(
                session_id=session_id,
                tenant_id=tenant_id,
            ),
            tenant_id=tenant_id,
        )
    finally:
        set_current_tenant(None)


async def evaluate_session_supervisor_runtime(
    *,
    session_id: str,
    tenant_id: str,
) -> dict[str, object]:
    set_current_tenant(tenant_id)
    try:
        await clear_worker_queue_age(
            queue_name=QUEUE_SUPERVISOR,
            member_id=session_id,
        )
        session_factory = get_session_factory()
        async with session_factory() as session:
            supervisor_repository = PostgresSupervisorRepository(session)
            runtime = SupervisorRuntime(
                evaluator_registry=build_default_evaluator_registry(),
                supervisor_repository=supervisor_repository,
                session_persistence=PostgresSessionPersistence(session),
                execution_persistence=PostgresExecutionPersistence(session),
                governance_repository=PostgresGovernanceRepository(session),
            )
            inspection = await runtime.evaluate_session(session_id)
            await session.commit()
            qa_scoring_queued = await _queue_qa_scoring(
                inspection.inspection_id,
                inspection.tenant_id,
            )
            return {
                "status": "completed",
                "session_id": session_id,
                "inspection_id": inspection.inspection_id,
                "execution_id": inspection.execution_id,
                "tenant_id": inspection.tenant_id,
                "decision_kind": inspection.decision.kind,
                "compliance_score": inspection.compliance_score,
                "qa_scoring_queued": qa_scoring_queued,
            }
    finally:
        set_current_tenant(None)


async def _queue_qa_scoring(inspection_id: str, tenant_id: str | None) -> bool:
    if tenant_id is None or not tenant_id:
        return False
    await admit_qa_publish(tenant_id=tenant_id)
    cast(Any, score_supervisor_inspection).apply_async(
        args=(inspection_id, tenant_id),
        kwargs={"_enqueued_at": enqueued_at_iso()},
        queue=QUEUE_QA,
    )
    await record_worker_queue_age(
        queue_name=QUEUE_QA,
        member_id=inspection_id,
    )
    return True


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
        raise RuntimeError("supervisor evaluation coroutine returned no result")
    return results[0]


__all__ = [
    "evaluate_session_supervisor",
    "evaluate_session_supervisor_runtime",
]
