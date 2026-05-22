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
from app.escalation.persistence import PostgresEscalationPersistence
from app.escalation.runtime import EscalationAgentRuntime
from app.governance.persistence import PostgresGovernanceRepository
from app.session.persistence import PostgresSessionPersistence
from app.workers.celery_app import celery_app

_T = TypeVar("_T")


@celery_app.task(name="create_governance_escalation", bind=True)  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
def create_governance_escalation(
    _self: Any,
    governance_decision_id: str,
    tenant_id: str,
    session_id: str | None = None,
) -> dict[str, object]:
    """Create a pending escalation for one governance DENY decision."""

    return _run_async(
        create_governance_escalation_runtime(
            governance_decision_id=governance_decision_id,
            tenant_id=tenant_id,
            session_id=session_id,
        )
    )


async def create_governance_escalation_runtime(
    *,
    governance_decision_id: str,
    tenant_id: str,
    session_id: str | None = None,
) -> dict[str, object]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        runtime = EscalationAgentRuntime(
            escalation_persistence=PostgresEscalationPersistence(session),
            governance_repository=PostgresGovernanceRepository(session),
            session_persistence=PostgresSessionPersistence(session),
        )
        record = await runtime.create_for_governance_denial(
            governance_decision_id=governance_decision_id,
            expected_tenant_id=tenant_id,
            session_id=session_id,
        )
        await session.commit()
        return {
            "status": "completed",
            "governance_decision_id": governance_decision_id,
            "escalation_id": record.escalation_id,
            "session_id": record.session_id,
            "tenant_id": record.tenant_id,
            "queue_status": record.status,
        }


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
        raise RuntimeError("escalation coroutine returned no result")
    return results[0]


__all__ = [
    "create_governance_escalation",
    "create_governance_escalation_runtime",
]
