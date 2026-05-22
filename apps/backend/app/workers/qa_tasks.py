"""QA scoring worker tasks.

Celery is transport only. The task accepts supervisor-inspection
lineage and constructs the persistence-backed QA runtime inside the
worker boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from threading import Thread
from typing import Any, TypeVar, cast

from app.db.session import get_session_factory
from app.qa.persistence import PostgresQAPersistence
from app.qa.persistence.records import QAScoreRecord
from app.qa.runtime import QAAgentRuntime
from app.supervisor.persistence import PostgresSupervisorRepository
from app.workers.celery_app import celery_app
from app.workers.sop_intelligence_tasks import (
    propose_sop_intelligence_change,
)

_T = TypeVar("_T")
_SOP_INTELLIGENCE_CONFIDENCE_THRESHOLD = 0.85


@celery_app.task(name="score_supervisor_inspection", bind=True)  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
def score_supervisor_inspection(
    _self: Any,
    inspection_id: str,
    tenant_id: str,
) -> dict[str, object]:
    """Score one persisted supervisor inspection through QA."""

    return _run_async(
        score_supervisor_inspection_runtime(
            inspection_id=inspection_id,
            tenant_id=tenant_id,
        )
    )


async def score_supervisor_inspection_runtime(
    *,
    inspection_id: str,
    tenant_id: str,
) -> dict[str, object]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        runtime = QAAgentRuntime(
            supervisor_repository=PostgresSupervisorRepository(session),
            qa_persistence=PostgresQAPersistence(session),
        )
        score = await runtime.score_inspection(
            inspection_id,
            expected_tenant_id=tenant_id,
        )
        await session.commit()
        sop_intelligence_queued = _queue_sop_intelligence(score)
        return {
            "status": "completed",
            "inspection_id": inspection_id,
            "score_id": score.score_id,
            "execution_id": score.execution_id,
            "tenant_id": score.tenant_id,
            "overall_score": score.overall_score,
            "sop_intelligence_queued": sop_intelligence_queued,
        }


def _queue_sop_intelligence(score: QAScoreRecord) -> bool:
    """Queue low-priority SOP proposal after high-confidence QA."""

    if score.overall_score < _SOP_INTELLIGENCE_CONFIDENCE_THRESHOLD:
        return False
    session_id = score.metadata.get("session_id")
    if session_id is None:
        session_id = score.metadata.get("source_session_id")
    if session_id is None:
        return False
    cast(Any, propose_sop_intelligence_change).apply_async(
        args=(str(session_id), score.tenant_id, score.inspection_id),
        queue="low_priority",
        priority=9,
    )
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
        raise RuntimeError("QA scoring coroutine returned no result")
    return results[0]


__all__ = [
    "score_supervisor_inspection",
    "score_supervisor_inspection_runtime",
]
