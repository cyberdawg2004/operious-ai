"""Agent execution worker tasks."""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass
from threading import Thread
from typing import Any, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.diagnostic_agent import DiagnosticAgent, DiagnosticResult
from app.agents.runtime.quota_runtime import (
    get_quota_runtime as get_initialized_quota_runtime,
)
from app.agents.runtime.retry_policy import RetryPolicy, get_policy
from app.cognition import (
    AnthropicMessagesClient,
    DeterministicDiagnosticLLMClient,
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
)
from app.cognition.exceptions import (
    CognitionGovernanceRejectionError,
    CognitionLLMProviderError,
    CognitionParsingFailureError,
    CognitionPersistenceError,
    CognitionPersistenceFailureError,
    CognitionSemanticRejectionError,
    CognitionSemanticValidationError,
    GovernanceDenyError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderTransientError,
)
from app.cognition.persistence import PostgresCognitionUsagePersistence
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    CoordinationRecord,
    PostgresCoordinationPersistence,
)
from app.core.config import get_settings
from app.db.session import dispose_engine, get_session_factory, reset_engine_state
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.execution import ExecutionRuntime, PostgresExecutionPersistence
from app.governance.persistence import PostgresGovernanceRepository
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import PostgresKnowledgeRepository
from app.runtime.timeline_runtime import TimelineRuntime
from app.runtime.provider_circuit_breaker import ProviderCircuitBreaker
from app.session.identity import as_session_id
from app.session.lifecycle.classifier import is_terminal as is_terminal_session
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionPersistenceProtocol,
)
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.workers.celery_app import celery_app
from app.workers.dead_letter_persistence import record_dead_letter_task
from app.workers.queue_admission import (
    admit_supervisor_publish,
    clear_worker_queue_age,
    record_worker_queue_age,
)
from app.queues import (
    QUEUE_DEAD_LETTER,
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_DIAGNOSTIC_RETRY,
    QUEUE_SUPERVISOR,
)
from app.workers.supervisor_tasks import evaluate_session_supervisor

_T = TypeVar("_T")
_STARTED = "diagnostic_execution_started"
_COMPLETED = "diagnostic_analysis_completed"
_FAILED = "diagnostic_execution_failed"
_MAX_EXECUTION_ATTEMPTS = 5
_DIAGNOSTIC_RETRY_BASE_DELAY_SECONDS = 30


@celery_app.task(
    name="execute_diagnostic_agent",
    queue=QUEUE_DIAGNOSTIC_NORMAL,
    bind=True,
    max_retries=4,
    default_retry_delay=_DIAGNOSTIC_RETRY_BASE_DELAY_SECONDS,
    ignore_result=True,
)
def execute_diagnostic_agent(
    self: Any,
    execution_id: str,
    tenant_id: str,
) -> dict[str, object]:
    """Run one bounded DiagnosticAgent execution."""
    previous_tenant = get_current_tenant()
    set_current_tenant(tenant_id)
    try:
        reset_engine_state()
        worker_id = _worker_id(self)
        result = _run_async(
            execute_diagnostic_agent_runtime(
                execution_id=execution_id,
                tenant_id=tenant_id,
                worker_id=worker_id,
                max_attempts=_max_execution_attempts(self),
                task_name="execute_diagnostic_agent",
                task_id=_task_id(self),
                retry_count=_task_retries(self),
            ),
            tenant_id=tenant_id,
        )
        if result.get("status") == "retry_requested":
            raise self.retry(
                exc=DiagnosticExecutionRetry(str(result.get("message") or result)),
                countdown=_retry_countdown_from_result(self, result),
                queue=_retry_queue_from_result(result),
            )
        if result.get("status") == "dead_lettered":
            raise DiagnosticExecutionDeadLettered(
                str(result.get("message") or result)
            )
        return result
    finally:
        set_current_tenant(previous_tenant)


async def execute_diagnostic_agent_runtime(
    *,
    execution_id: str,
    tenant_id: str,
    worker_id: str = "inline:diagnostic",
    max_attempts: int = 1,
    task_name: str = "execute_diagnostic_agent",
    task_id: str | None = None,
    retry_count: int = 0,
) -> dict[str, object]:
    previous_tenant = get_current_tenant()
    set_current_tenant(tenant_id)
    try:
        await clear_worker_queue_age(
            queue_name=QUEUE_DIAGNOSTIC_NORMAL,
            member_id=execution_id,
        )
        session_factory = get_session_factory()
        prepared = await _prepare_diagnostic_execution(
            session_factory=session_factory,
            execution_id=execution_id,
            worker_id=worker_id,
        )
        if isinstance(prepared, dict):
            return prepared

        try:
            result = await _generate_diagnostic_reasoning_for_work_item(
                session_factory=session_factory,
                work_item=prepared,
            )
        except Exception as exc:  # noqa: BLE001
            return await _persist_diagnostic_failure(
                session_factory=session_factory,
                work_item=prepared,
                worker_id=worker_id,
                max_attempts=max_attempts,
                task_name=task_name,
                task_id=task_id,
                retry_count=retry_count,
                exc=exc,
                last_traceback=traceback.format_exc(),
            )

        try:
            return await _persist_diagnostic_success(
                session_factory=session_factory,
                work_item=prepared,
                worker_id=worker_id,
                result=result,
            )
        except Exception as exc:  # noqa: BLE001
            return await _persist_diagnostic_failure(
                session_factory=session_factory,
                work_item=prepared,
                worker_id=worker_id,
                max_attempts=max_attempts,
                task_name=task_name,
                task_id=task_id,
                retry_count=retry_count,
                exc=CognitionPersistenceFailureError(
                    "diagnostic success persistence failed: "
                    f"{exc.__class__.__name__}: {_bounded_exception_message(exc)}"
                ),
                last_traceback=traceback.format_exc(),
            )
    finally:
        try:
            if not _running_under_pytest():
                await dispose_engine()
        finally:
            set_current_tenant(previous_tenant)


@dataclass(frozen=True, slots=True)
class _DiagnosticExecutionWorkItem:
    execution_id: str
    attempt_id: str
    attempt_number: int
    dispatch_id: str
    session_id: str
    tenant_id: str
    content: str


@dataclass(frozen=True, slots=True)
class _DiagnosticRetryDecision:
    error_class: str
    policy: RetryPolicy
    terminal: bool
    retry_requested: bool
    countdown_seconds: int
    queue: str


async def _prepare_diagnostic_execution(
    *,
    session_factory: Any,
    execution_id: str,
    worker_id: str,
) -> _DiagnosticExecutionWorkItem | dict[str, object]:
    async with session_factory() as session:
        execution_runtime = ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        )
        session_repo = PostgresSessionPersistence(session)
        coordination_repo = PostgresCoordinationPersistence(session)
        timeline = TimelineRuntime(persistence=session_repo)
        claim = await execution_runtime.claim_execution(
            execution_id=execution_id,
            worker_id=worker_id,
        )
        if not claim.claimed or claim.execution is None:
            return {
                "execution_id": execution_id,
                "status": "claim_refused",
                "reason": claim.reason or "not_claimable",
            }
        execution = claim.execution
        attempt = claim.attempt
        if attempt is None:
            raise DiagnosticExecutionError(
                "execution claim did not produce attempt lineage"
            )
        await session.commit()
        execution_id_text = str(execution.execution_id)
        attempt_id_text = str(attempt.attempt_id)
        attempt_number = attempt.attempt_number
        dispatch_id = execution.dispatch_id
        session_id = execution.session_id
        tenant_id = execution.tenant_id
        claim_lost = await _claim_lost_payload(
            execution_runtime=execution_runtime,
            execution_id=execution_id_text,
            attempt_id=attempt_id_text,
            worker_id=worker_id,
        )
        if claim_lost is not None:
            return {
                **claim_lost,
                "dispatch_id": dispatch_id,
                "session_id": session_id,
                "tenant_id": tenant_id,
            }
        await timeline.append_event(
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
            event_type=_STARTED,
            payload={
                "execution_id": execution_id_text,
                "attempt_id": attempt_id_text,
                "attempt_number": attempt_number,
            },
            idempotency_key=_timeline_idempotency_key(
                execution_id=execution_id_text,
                attempt_id=attempt_id_text,
                event_type=_STARTED,
            ),
        )
        await session.commit()

        content = await _load_dispatch_content(
            coordination_repo=coordination_repo,
            session_repo=session_repo,
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
        )
        await session.commit()
        return _DiagnosticExecutionWorkItem(
            execution_id=execution_id_text,
            attempt_id=attempt_id_text,
            attempt_number=attempt_number,
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
            content=content,
        )


async def _generate_diagnostic_reasoning_for_work_item(
    *,
    session_factory: Any,
    work_item: _DiagnosticExecutionWorkItem,
) -> DiagnosticResult:
    session = session_factory()
    try:
        result = await _generate_diagnostic_reasoning_draft(
            cognition_runtime=_diagnostic_cognition_runtime(session),
            dispatch_id=work_item.dispatch_id,
            session_id=work_item.session_id,
            tenant_id=work_item.tenant_id,
            content=work_item.content,
            execution_id=work_item.execution_id,
            attempt_id=work_item.attempt_id,
        )
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _persist_diagnostic_success(
    *,
    session_factory: Any,
    work_item: _DiagnosticExecutionWorkItem,
    worker_id: str,
    result: DiagnosticResult,
) -> dict[str, object]:
    async with session_factory() as session:
        execution_runtime = ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        )
        session_repo = PostgresSessionPersistence(session)
        timeline = TimelineRuntime(persistence=session_repo)
        claim_lost = await _claim_lost_payload(
            execution_runtime=execution_runtime,
            execution_id=work_item.execution_id,
            attempt_id=work_item.attempt_id,
            worker_id=worker_id,
        )
        if claim_lost is not None:
            return {
                **claim_lost,
                "dispatch_id": work_item.dispatch_id,
                "session_id": work_item.session_id,
                "tenant_id": work_item.tenant_id,
            }
        await timeline.append_event(
            dispatch_id=work_item.dispatch_id,
            session_id=work_item.session_id,
            tenant_id=work_item.tenant_id,
            event_type=_COMPLETED,
            payload=result.model_dump(),
            idempotency_key=_timeline_idempotency_key(
                execution_id=work_item.execution_id,
                attempt_id=work_item.attempt_id,
                event_type=_COMPLETED,
            ),
        )
        completed_payload = result.model_dump()
        await execution_runtime.complete_execution(
            execution_id=work_item.execution_id,
            attempt_id=work_item.attempt_id,
            worker_id=worker_id,
            result=completed_payload,
        )
        await session.commit()
        supervisor_queued = await _queue_supervisor_if_closed(
            session_repo=session_repo,
            session_id=work_item.session_id,
            tenant_id=work_item.tenant_id,
            dispatch_id=work_item.dispatch_id,
        )
        return {
            "execution_id": work_item.execution_id,
            "attempt_id": work_item.attempt_id,
            "attempt_number": work_item.attempt_number,
            "dispatch_id": work_item.dispatch_id,
            "session_id": work_item.session_id,
            "tenant_id": work_item.tenant_id,
            "status": "completed",
            "supervisor_evaluation_queued": supervisor_queued,
            "summary": result.summary,
            "category": result.category,
            "confidence": result.confidence,
        }


async def _persist_diagnostic_failure(
    *,
    session_factory: Any,
    work_item: _DiagnosticExecutionWorkItem,
    worker_id: str,
    max_attempts: int,
    task_name: str,
    task_id: str | None,
    retry_count: int,
    exc: BaseException,
    last_traceback: str,
) -> dict[str, object]:
    async with session_factory() as session:
        execution_runtime = ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        )
        session_repo = PostgresSessionPersistence(session)
        timeline = TimelineRuntime(persistence=session_repo)
        retry_decision = _diagnostic_retry_decision(
            exc,
            retry_count=retry_count,
        )
        terminal = retry_decision.terminal or _diagnostic_failure_is_terminal(
            exc,
            attempt_number=work_item.attempt_number,
            max_attempts=max_attempts,
        )
        retry_requested = retry_decision.retry_requested and not terminal
        retry_queue = QUEUE_DEAD_LETTER if terminal else retry_decision.queue
        retry_countdown_seconds = 0 if terminal else retry_decision.countdown_seconds
        failure = _bounded_failure_metadata(
            exc,
            execution_id=work_item.execution_id,
            attempt_id=work_item.attempt_id,
            attempt_number=work_item.attempt_number,
            error_class=retry_decision.error_class,
            retry_requested=retry_requested,
            retry_queue=retry_queue,
            retry_countdown_seconds=retry_countdown_seconds,
            last_traceback=last_traceback,
        )
        claim_lost = await _claim_lost_payload(
            execution_runtime=execution_runtime,
            execution_id=work_item.execution_id,
            attempt_id=work_item.attempt_id,
            worker_id=worker_id,
        )
        if claim_lost is not None:
            return {
                **claim_lost,
                "dispatch_id": work_item.dispatch_id,
                "session_id": work_item.session_id,
                "tenant_id": work_item.tenant_id,
                **failure,
            }
        failure_event_persisted = await _append_failure_event(
            session=session,
            timeline=timeline,
            dispatch_id=work_item.dispatch_id,
            session_id=work_item.session_id,
            tenant_id=work_item.tenant_id,
            failure=failure,
        )
        if terminal:
            execution_failed = await _dead_letter_execution_record(
                execution_runtime=execution_runtime,
                session=session,
                execution_id=work_item.execution_id,
                attempt_id=work_item.attempt_id,
                worker_id=worker_id,
                failure=failure,
            )
            dead_letter_task_recorded = await _record_dead_letter_task(
                session=session,
                tenant_id=work_item.tenant_id,
                task_name=task_name,
                task_id=(
                    task_id
                    or _fallback_task_id(
                        task_name=task_name,
                        execution_id=work_item.execution_id,
                        attempt_id=work_item.attempt_id,
                    )
                ),
                execution_id=work_item.execution_id,
                attempt_id=work_item.attempt_id,
                dispatch_id=work_item.dispatch_id,
                session_id=work_item.session_id,
                retry_count=retry_count,
                task_payload=_dead_letter_task_payload(work_item),
                failure=failure,
            )
            status = "dead_lettered"
        else:
            execution_failed = await _fail_execution_record(
                execution_runtime=execution_runtime,
                session=session,
                execution_id=work_item.execution_id,
                attempt_id=work_item.attempt_id,
                worker_id=worker_id,
                failure=failure,
                retry_requested=retry_requested,
            )
            dead_letter_task_recorded = False
            status = "retry_requested"
        return {
            "execution_id": work_item.execution_id,
            "attempt_id": work_item.attempt_id,
            "attempt_number": work_item.attempt_number,
            "dispatch_id": work_item.dispatch_id,
            "session_id": work_item.session_id,
            "tenant_id": work_item.tenant_id,
            "status": status,
            "failure_event_persisted": failure_event_persisted,
            "execution_failed": execution_failed,
            "dead_letter_task_recorded": dead_letter_task_recorded,
            "retry_queue": retry_queue,
            "retry_countdown_seconds": retry_countdown_seconds,
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
        extracted = _extract_text(cast(Mapping[str, Any], canonical_payload))
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


async def _generate_diagnostic_reasoning_draft(
    *,
    cognition_runtime: DiagnosticCognitionRuntime,
    dispatch_id: str,
    session_id: str,
    tenant_id: str,
    content: str,
    execution_id: str,
    attempt_id: str,
) -> DiagnosticResult:
    return await DiagnosticAgent(
        cognition_runtime=cognition_runtime
    ).execute(
        dispatch_id=dispatch_id,
        session_id=session_id,
        tenant_id=tenant_id,
        content=content,
        execution_id=execution_id,
        attempt_id=attempt_id,
    )


async def _queue_supervisor_if_closed(
    *,
    session_repo: SessionPersistenceProtocol,
    session_id: str,
    tenant_id: str,
    dispatch_id: str | None = None,
) -> bool:
    session = await session_repo.get_session(
        as_session_id(session_id),
        expected_tenant_id=tenant_id,
    )
    if session is None or not is_terminal_session(session.lifecycle_phase):
        return False
    await admit_supervisor_publish(tenant_id=tenant_id, dispatch_id=dispatch_id)
    cast(Any, evaluate_session_supervisor).apply_async(
        args=(session_id, tenant_id),
        queue=QUEUE_SUPERVISOR,
    )
    await record_worker_queue_age(
        queue_name=QUEUE_SUPERVISOR,
        member_id=session_id,
    )
    return True


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
            idempotency_key=_timeline_idempotency_key(
                execution_id=str(failure.get("execution_id") or "unknown"),
                attempt_id=str(failure.get("attempt_id") or "unknown"),
                event_type=_FAILED,
            ),
        )
        await session.commit()
        return True
    except Exception:  # noqa: BLE001
        await session.rollback()
        return False


async def _fail_execution_record(
    *,
    execution_runtime: ExecutionRuntime,
    session: AsyncSession,
    execution_id: object,
    attempt_id: object,
    worker_id: str,
    failure: Mapping[str, object],
    retry_requested: bool,
) -> bool:
    try:
        await execution_runtime.fail_execution(
            execution_id=str(execution_id),
            attempt_id=str(attempt_id),
            worker_id=worker_id,
            error=str(failure.get("message") or failure),
            retry_requested=retry_requested,
        )
        await session.commit()
        return True
    except Exception:  # noqa: BLE001
        await session.rollback()
        return False


async def _dead_letter_execution_record(
    *,
    execution_runtime: ExecutionRuntime,
    session: AsyncSession,
    execution_id: object,
    attempt_id: object,
    worker_id: str,
    failure: Mapping[str, object],
) -> bool:
    try:
        await execution_runtime.dead_letter_execution(
            execution_id=str(execution_id),
            attempt_id=str(attempt_id),
            worker_id=worker_id,
            error=str(failure.get("message") or failure),
        )
        await session.commit()
        return True
    except Exception:  # noqa: BLE001
        await session.rollback()
        return False


async def _record_dead_letter_task(
    *,
    session: AsyncSession,
    tenant_id: str,
    task_name: str,
    task_id: str,
    execution_id: str,
    attempt_id: str,
    dispatch_id: str,
    session_id: str,
    retry_count: int,
    task_payload: Mapping[str, object],
    failure: Mapping[str, object],
) -> bool:
    try:
        await record_dead_letter_task(
            session=session,
            tenant_id=tenant_id,
            task_name=task_name,
            task_id=task_id,
            execution_id=execution_id,
            session_id=session_id,
            attempt_count=retry_count,
            reason=str(failure.get("message") or failure),
            retry_count=retry_count,
            metadata={
                "execution_id": execution_id,
                "attempt_id": attempt_id,
                "dispatch_id": dispatch_id,
                "session_id": session_id,
                "tenant_id": tenant_id,
                "attempt_count": retry_count,
                "error_type": failure.get("error_type"),
                "error_class": failure.get("error_class"),
                "error_message": failure.get("error_message"),
                "last_traceback": failure.get("last_traceback"),
                "attempt_number": failure.get("attempt_number"),
                "task_payload": dict(task_payload),
            },
        )
        await session.commit()
        return True
    except Exception:  # noqa: BLE001
        await session.rollback()
        return False


def _bounded_failure_metadata(
    exc: BaseException,
    *,
    execution_id: str,
    attempt_id: str,
    attempt_number: int,
    error_class: str | None = None,
    retry_requested: bool,
    retry_queue: str | None = None,
    retry_countdown_seconds: int | None = None,
    last_traceback: str,
) -> dict[str, object]:
    error_message = str(exc)
    message = (
        error_message
        if len(error_message) <= 240
        else f"{error_message[:237]}..."
    )
    error_type = exc.__class__.__name__
    failure: dict[str, object] = {
        "execution_id": execution_id,
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "attempt_count": attempt_number,
        "error_type": error_type,
        "error_class": error_class or error_type,
        "error_message": error_message,
        "last_traceback": last_traceback,
        "message": message,
        "retry_requested": retry_requested,
    }
    if retry_queue is not None:
        failure["retry_queue"] = retry_queue
    if retry_countdown_seconds is not None:
        failure["retry_countdown_seconds"] = retry_countdown_seconds
    return failure


def _dead_letter_task_payload(
    work_item: _DiagnosticExecutionWorkItem,
) -> dict[str, object]:
    return {
        "execution_id": work_item.execution_id,
        "attempt_id": work_item.attempt_id,
        "attempt_number": work_item.attempt_number,
        "dispatch_id": work_item.dispatch_id,
        "session_id": work_item.session_id,
        "tenant_id": work_item.tenant_id,
    }


async def _claim_lost_payload(
    *,
    execution_runtime: ExecutionRuntime,
    execution_id: str,
    attempt_id: str,
    worker_id: str,
) -> dict[str, object] | None:
    verdict = await execution_runtime.validate_worker_legitimacy(
        execution_id=execution_id,
        attempt_id=attempt_id,
        worker_id=worker_id,
    )
    if verdict.legitimate:
        return None
    return {
        "execution_id": execution_id,
        "attempt_id": attempt_id,
        "worker_id": worker_id,
        "status": "claim_lost",
        "reason": verdict.reason or "worker_not_legitimate",
    }


def _worker_id(task_self: Any) -> str:
    request = getattr(task_self, "request", None)
    task_id = getattr(request, "id", None)
    if isinstance(task_id, str) and task_id:
        return f"celery:{task_id}"
    return "celery:unknown"


def _task_id(task_self: Any) -> str | None:
    request = getattr(task_self, "request", None)
    task_id = getattr(request, "id", None)
    return task_id if isinstance(task_id, str) and task_id else None


def _task_retries(task_self: Any) -> int:
    request = getattr(task_self, "request", None)
    retries = getattr(request, "retries", None)
    return retries if isinstance(retries, int) and retries >= 0 else 0


def _retry_countdown(
    task_self: Any,
    *,
    base_seconds: int = _DIAGNOSTIC_RETRY_BASE_DELAY_SECONDS,
) -> int:
    return base_seconds * (2 ** _task_retries(task_self))


def _retry_countdown_from_result(
    task_self: Any,
    result: Mapping[str, object],
) -> int:
    countdown = result.get("retry_countdown_seconds")
    if isinstance(countdown, int) and countdown >= 0:
        return countdown
    return _retry_countdown(task_self)


def _retry_queue_from_result(result: Mapping[str, object]) -> str:
    queue = result.get("retry_queue")
    return queue if isinstance(queue, str) and queue else QUEUE_DIAGNOSTIC_RETRY


def _diagnostic_retry_decision(
    exc: BaseException,
    *,
    retry_count: int,
) -> _DiagnosticRetryDecision:
    error_class = _classify_diagnostic_exception(exc)
    policy = get_policy(error_class)
    exhausted = retry_count >= policy.max_retries
    terminal = (
        policy.terminal
        or exhausted
        or isinstance(exc, (DiagnosticExecutionError, DiagnosticNonRetryableError))
    )
    retry_requested = not terminal
    countdown_seconds = (
        0
        if terminal
        else _retry_countdown_for_policy(
            exc,
            policy=policy,
            retry_count=retry_count,
        )
    )
    return _DiagnosticRetryDecision(
        error_class=error_class,
        policy=policy,
        terminal=terminal,
        retry_requested=retry_requested,
        countdown_seconds=countdown_seconds,
        queue=QUEUE_DEAD_LETTER if terminal else policy.queue,
    )


def _retry_countdown_for_policy(
    exc: BaseException | None,
    *,
    policy: RetryPolicy,
    retry_count: int,
) -> int:
    retry_after = _retry_after_seconds(exc)
    base_seconds = retry_after if retry_after is not None else policy.base_delay_seconds
    return int(base_seconds * (policy.backoff_multiplier ** retry_count))


def _retry_after_seconds(exc: BaseException | None) -> int | None:
    retry_after = getattr(exc, "retry_after_seconds", None)
    if isinstance(retry_after, int) and retry_after > 0:
        return retry_after
    return None


def _fallback_task_id(
    *,
    task_name: str,
    execution_id: str,
    attempt_id: str,
) -> str:
    return f"{task_name}:{execution_id}:{attempt_id}"


def _max_execution_attempts(task_self: Any) -> int:
    max_retries = getattr(task_self, "max_retries", None)
    if isinstance(max_retries, int) and max_retries >= 0:
        return max_retries + 1
    return _MAX_EXECUTION_ATTEMPTS


def _diagnostic_failure_is_terminal(
    exc: BaseException,
    *,
    attempt_number: int,
    max_attempts: int,
) -> bool:
    if not _is_retryable_diagnostic_error(exc):
        return True
    policy = get_policy(_classify_diagnostic_exception(exc))
    return (
        policy.terminal
        or attempt_number >= max(1, max_attempts)
    )


def _is_retryable_diagnostic_error(exc: BaseException) -> bool:
    if isinstance(exc, (DiagnosticExecutionError, DiagnosticNonRetryableError)):
        return False
    return not get_policy(_classify_diagnostic_exception(exc)).terminal


def _classify_diagnostic_exception(exc: BaseException) -> str:
    if isinstance(exc, ProviderQuotaExceededError):
        return "QUOTA_EXCEEDED"
    if isinstance(exc, ProviderRateLimitError):
        return "PROVIDER_429"
    if isinstance(exc, ProviderTransientError):
        return "PROVIDER_5XX"
    if isinstance(exc, CognitionParsingFailureError):
        return "PARSING_FAILURE"
    if isinstance(exc, CognitionSemanticRejectionError):
        return "SEMANTIC_REJECTION"
    if isinstance(exc, GovernanceDenyError):
        return "GOVERNANCE_DENY"
    if isinstance(exc, CognitionPersistenceFailureError):
        return "PERSISTENCE_FAILURE"
    if isinstance(exc, CognitionPersistenceError):
        return "PERSISTENCE_FAILURE"
    if isinstance(exc, CognitionGovernanceRejectionError):
        return "GOVERNANCE_DENY"
    if isinstance(exc, CognitionSemanticValidationError):
        return "SEMANTIC_REJECTION"
    if isinstance(exc, CognitionLLMProviderError):
        message = str(exc).casefold()
        if (
            "invalid json" in message
            or "non-object json" in message
            or "schema validation" in message
        ):
            return "PARSING_FAILURE"
    return "PROVIDER_5XX"


def _diagnostic_cognition_runtime(
    session: AsyncSession,
) -> DiagnosticCognitionRuntime:
    settings = get_settings()
    tenant_repository = PostgresTenantConfigurationRepository(session)
    knowledge_runtime = KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(session),
        tenant_configuration_repository=tenant_repository,
        embedding_provider=DeterministicHashEmbeddingProvider(),
        chunker=DeterministicKnowledgeChunker(
            target_size=settings.CHUNK_TARGET_SIZE,
            overlap=settings.CHUNK_OVERLAP,
            min_size=settings.CHUNK_MIN_SIZE,
        ),
        vector_index_name=settings.VECTOR_DEFAULT_INDEX,
        default_context_token_budget=settings.RAG_DEFAULT_CONTEXT_TOKEN_BUDGET,
    )
    if _running_under_pytest() or not settings.ANTHROPIC_API_KEY.strip():
        llm_client = DeterministicDiagnosticLLMClient()
    else:
        llm_client = AnthropicMessagesClient(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.ANTHROPIC_DEFAULT_MODEL,
            base_url=settings.ANTHROPIC_BASE_URL,
            anthropic_version=settings.ANTHROPIC_VERSION,
            timeout_seconds=settings.AI_TIMEOUT_SECONDS,
            provider_circuit_breaker=ProviderCircuitBreaker(
                session=session,
                auto_commit=True,
            ),
        )
    return DiagnosticCognitionRuntime(
        knowledge_runtime=knowledge_runtime,
        llm_client=llm_client,
        usage_persistence=PostgresCognitionUsagePersistence(
            session,
            audit_encryptor=_cognition_audit_encryptor(),
        ),
        governance_repository=PostgresGovernanceRepository(session),
        quota_runtime=get_initialized_quota_runtime(),
        config=DiagnosticCognitionRuntimeConfig(
            max_output_tokens=settings.ANTHROPIC_MAX_OUTPUT_TOKENS,
            temperature=settings.ANTHROPIC_TEMPERATURE,
            context_top_k=settings.COGNITION_LLM_CONTEXT_TOP_K,
            context_token_budget=settings.COGNITION_LLM_CONTEXT_TOKEN_BUDGET,
            require_citations=settings.COGNITION_LLM_REQUIRE_CITATIONS,
            input_token_micro_usd=settings.COGNITION_LLM_INPUT_TOKEN_MICRO_USD,
            output_token_micro_usd=settings.COGNITION_LLM_OUTPUT_TOKEN_MICRO_USD,
        ),
    )


def _cognition_audit_encryptor() -> TenantCredentialEncryptor:
    key = get_settings().TENANT_CREDENTIAL_MASTER_KEY
    if key:
        return TenantCredentialEncryptor(platform_master_key=key)
    if _running_under_pytest():
        return TenantCredentialEncryptor(platform_master_key=b"0" * 32)
    raise RuntimeError("TENANT_CREDENTIAL_MASTER_KEY must be configured")


def _bounded_exception_message(exc: BaseException) -> str:
    message = str(exc)
    if len(message) <= 180:
        return message
    return f"{message[:177]}..."


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def _timeline_idempotency_key(
    *,
    execution_id: str,
    attempt_id: str,
    event_type: str,
) -> str:
    return f"execution.{execution_id}.attempt.{attempt_id}.event.{event_type}"


def _run_async(coro: Coroutine[Any, Any, _T], *, tenant_id: str) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        previous_tenant = get_current_tenant()
        set_current_tenant(tenant_id)
        try:
            return asyncio.run(coro)
        finally:
            set_current_tenant(previous_tenant)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        previous_tenant = get_current_tenant()
        set_current_tenant(tenant_id)
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            set_current_tenant(previous_tenant)

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


class DiagnosticExecutionRetry(RuntimeError):
    """Raised to ask Celery transport for another delivery."""


class DiagnosticExecutionDeadLettered(RuntimeError):
    """Raised after the worker persists terminal DLQ lineage."""


class DiagnosticNonRetryableError(RuntimeError):
    """Raised for diagnostic failures that should go straight to DLQ."""


__all__ = [
    "execute_diagnostic_agent",
    "execute_diagnostic_agent_runtime",
    "_generate_diagnostic_reasoning_draft",
]
