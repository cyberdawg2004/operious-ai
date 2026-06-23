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

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.db.tenant_context import set_current_tenant
from app.qa.persistence import PostgresQAPersistence
from app.qa.persistence.records import QAScoreRecord
from app.qa.runtime import QAAgentRuntime
from app.supervisor.persistence import PostgresSupervisorRepository
from app.trainer.persistence import PostgresTrainingRecommendationRepository
from app.trainer.runtime import TrainerAgentRuntime
from app.workers.celery_app import celery_app, enqueued_at_iso
from app.workers.queue_admission import (
    admit_sop_intelligence_publish,
    clear_worker_queue_age,
    record_worker_queue_age,
)
from app.queues import QUEUE_QA, QUEUE_SOP_INTELLIGENCE
from app.workers.sop_intelligence_tasks import (
    propose_sop_intelligence_change,
)

_T = TypeVar("_T")
_SOP_INTELLIGENCE_CONFIDENCE_THRESHOLD = 0.85
_TRAINER_THRESHOLD = get_settings().TRAINER_RECOMMENDATION_THRESHOLD


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="score_supervisor_inspection",
    queue=QUEUE_QA,
    bind=True,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=30,
)
def score_supervisor_inspection(
    _self: Any,
    inspection_id: str,
    tenant_id: str,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Score one persisted supervisor inspection through QA."""
    del _enqueued_at

    set_current_tenant(tenant_id)
    try:
        return _run_async(
            score_supervisor_inspection_runtime(
                inspection_id=inspection_id,
                tenant_id=tenant_id,
            ),
            tenant_id=tenant_id,
        )
    finally:
        set_current_tenant(None)


async def score_supervisor_inspection_runtime(
    *,
    inspection_id: str,
    tenant_id: str,
) -> dict[str, object]:
    set_current_tenant(tenant_id)
    try:
        await clear_worker_queue_age(
            queue_name=QUEUE_QA,
            member_id=inspection_id,
        )
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
            sop_intelligence_queued = await _queue_sop_intelligence(score)
            training_recommendation_count = 0
            if _should_generate_training_recommendations(score):
                trainer_runtime = TrainerAgentRuntime(
                    recommendation_repository=(
                        PostgresTrainingRecommendationRepository(session)
                    )
                )
                recommendations = await trainer_runtime.generate_and_persist(
                    qa_score=score,
                    tenant_id=tenant_id,
                    expected_tenant_id=tenant_id,
                )
                training_recommendation_count = len(recommendations)
                await session.commit()
            return {
                "status": "completed",
                "inspection_id": inspection_id,
                "score_id": score.score_id,
                "execution_id": score.execution_id,
                "tenant_id": score.tenant_id,
                "overall_score": score.overall_score,
                "sop_intelligence_queued": sop_intelligence_queued,
                "training_recommendation_count": training_recommendation_count,
            }
    finally:
        set_current_tenant(None)


async def _queue_sop_intelligence(score: QAScoreRecord) -> bool:
    """Queue low-priority SOP proposal after high-confidence QA."""

    if score.overall_score < _SOP_INTELLIGENCE_CONFIDENCE_THRESHOLD:
        return False
    session_id = score.metadata.get("session_id")
    if session_id is None:
        session_id = score.metadata.get("source_session_id")
    if session_id is None:
        return False
    await admit_sop_intelligence_publish(tenant_id=score.tenant_id)
    # Write the sentinel before the task is dispatchable: if a worker
    # could dequeue and clear it first, the later write would orphan
    # the member permanently.
    await record_worker_queue_age(
        queue_name=QUEUE_SOP_INTELLIGENCE,
        member_id=str(session_id),
    )
    try:
        cast(Any, propose_sop_intelligence_change).apply_async(
            args=(str(session_id), score.tenant_id, score.inspection_id),
            kwargs={"_enqueued_at": enqueued_at_iso()},
            queue=QUEUE_SOP_INTELLIGENCE,
            priority=9,
        )
    except Exception:
        await clear_worker_queue_age(
            queue_name=QUEUE_SOP_INTELLIGENCE,
            member_id=str(session_id),
        )
        raise
    return True


def _should_generate_training_recommendations(score: QAScoreRecord) -> bool:
    return (
        score.overall_score < _TRAINER_THRESHOLD
        or score.escalation_count > 0
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
        raise RuntimeError("QA scoring coroutine returned no result")
    return results[0]


__all__ = [
    "score_supervisor_inspection",
    "score_supervisor_inspection_runtime",
]
