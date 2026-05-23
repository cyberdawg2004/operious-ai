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
from app.execution import PostgresExecutionPersistence
from app.governance.persistence import PostgresGovernanceRepository
from app.session.persistence import PostgresSessionPersistence
from app.supervisor.evaluators.builtin import build_default_evaluator_registry
from app.supervisor.persistence import PostgresSupervisorRepository
from app.supervisor.runtime import SupervisorRuntime
from app.workers.celery_app import celery_app
from app.workers.qa_tasks import score_supervisor_inspection

_T = TypeVar("_T")


@celery_app.task(name="evaluate_session_supervisor", bind=True, ignore_result=True)  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
def evaluate_session_supervisor(
    _self: Any,
    session_id: str,
) -> dict[str, object]:
    """Evaluate one closed session through supervisor persistence."""

    return _run_async(
        evaluate_session_supervisor_runtime(session_id=session_id)
    )


async def evaluate_session_supervisor_runtime(
    *,
    session_id: str,
) -> dict[str, object]:
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
        qa_scoring_queued = _queue_qa_scoring(inspection.inspection_id, inspection.tenant_id)
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


def _queue_qa_scoring(inspection_id: str, tenant_id: str | None) -> bool:
    if tenant_id is None or not tenant_id:
        return False
    cast(Any, score_supervisor_inspection).delay(inspection_id, tenant_id)
    return True


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

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
