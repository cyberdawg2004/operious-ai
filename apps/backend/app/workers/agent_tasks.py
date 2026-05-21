"""Agent execution worker tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from threading import Thread
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.diagnostic_agent import DiagnosticAgent
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    CoordinationRecord,
    PostgresCoordinationPersistence,
)
from app.db.session import get_session_factory
from app.runtime.timeline_runtime import TimelineRuntime
from app.session.identity import as_session_id
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionPersistenceProtocol,
)
from app.workers.celery_app import celery_app

_T = TypeVar("_T")
_STARTED = "diagnostic_execution_started"
_COMPLETED = "diagnostic_analysis_completed"
_FAILED = "diagnostic_execution_failed"


@celery_app.task(
    name="execute_diagnostic_agent",
    bind=True,
    max_retries=3,
)
def execute_diagnostic_agent(
    _self: Any,
    dispatch_id: str,
    session_id: str,
    tenant_id: str,
) -> dict[str, object]:
    """Run one bounded DiagnosticAgent execution."""
    return _run_async(
        execute_diagnostic_agent_runtime(
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
        )
    )


async def execute_diagnostic_agent_runtime(
    *,
    dispatch_id: str,
    session_id: str,
    tenant_id: str,
) -> dict[str, object]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        session_repo = PostgresSessionPersistence(session)
        coordination_repo = PostgresCoordinationPersistence(session)
        timeline = TimelineRuntime(persistence=session_repo)
        try:
            await timeline.append_event(
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
                event_type=_STARTED,
                payload={},
            )
            await session.commit()

            content = await _load_dispatch_content(
                coordination_repo=coordination_repo,
                session_repo=session_repo,
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
            )
            result = await DiagnosticAgent().execute(
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
                content=content,
            )
            await timeline.append_event(
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
                event_type=_COMPLETED,
                payload=result.model_dump(),
            )
            await session.commit()
            return {
                "dispatch_id": dispatch_id,
                "session_id": session_id,
                "tenant_id": tenant_id,
                "status": "completed",
                "summary": result.summary,
                "category": result.category,
                "confidence": result.confidence,
            }
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            failure = _bounded_failure_metadata(exc)
            failure_event_persisted = await _append_failure_event(
                session=session,
                timeline=timeline,
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
                failure=failure,
            )
            return {
                "dispatch_id": dispatch_id,
                "session_id": session_id,
                "tenant_id": tenant_id,
                "status": "failed",
                "failure_event_persisted": failure_event_persisted,
                **failure,
            }


async def _load_dispatch_content(
    *,
    coordination_repo: CoordinationPersistenceProtocol,
    session_repo: SessionPersistenceProtocol,
    dispatch_id: str,
    session_id: str,
    tenant_id: str,
) -> str:
    session_record = await session_repo.get_session(
        as_session_id(session_id),
        expected_tenant_id=tenant_id,
    )
    if session_record is None:
        raise DiagnosticExecutionError(
            "session context not found for diagnostic execution"
        )
    dispatch = await coordination_repo.get_envelope(
        dispatch_id,
        expected_tenant_id=tenant_id,
    )
    if dispatch is None:
        raise DiagnosticExecutionError(
            "dispatch context not found for diagnostic execution"
        )
    return _extract_content(dispatch)


def _extract_content(dispatch: CoordinationRecord) -> str:
    body = dispatch.payload_body
    canonical_payload = body.get("canonical_payload")
    if isinstance(canonical_payload, Mapping):
        extracted = _extract_text(canonical_payload)
        if extracted:
            return extracted
    return _extract_text(body)


def _extract_text(payload: Mapping[str, Any]) -> str:
    for key in (
        "comment",
        "subject",
        "text",
        "message",
        "description",
        "transcript",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    text_values = [
        value.strip()
        for value in payload.values()
        if isinstance(value, str) and value.strip()
    ]
    return " ".join(text_values)


async def _append_failure_event(
    *,
    session: AsyncSession,
    timeline: TimelineRuntime,
    dispatch_id: str,
    session_id: str,
    tenant_id: str,
    failure: Mapping[str, object],
) -> bool:
    try:
        await timeline.append_event(
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
            event_type=_FAILED,
            payload=failure,
        )
        await session.commit()
        return True
    except Exception:  # noqa: BLE001
        await session.rollback()
        return False


def _bounded_failure_metadata(exc: BaseException) -> dict[str, object]:
    message = str(exc)
    if len(message) > 240:
        message = f"{message[:237]}..."
    return {
        "error_type": exc.__class__.__name__,
        "message": message,
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
        raise RuntimeError("diagnostic worker coroutine returned no result")
    return results[0]


class DiagnosticExecutionError(RuntimeError):
    """Raised when worker context is unavailable or invalid."""


__all__ = [
    "execute_diagnostic_agent",
    "execute_diagnostic_agent_runtime",
]
