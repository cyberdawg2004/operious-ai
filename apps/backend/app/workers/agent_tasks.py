"""Agent execution worker tasks."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Coroutine, Mapping
from threading import Thread
from typing import Any, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.diagnostic_agent import DiagnosticAgent, DiagnosticResult
from app.cognition import (
    AnthropicMessagesClient,
    DeterministicDiagnosticLLMClient,
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
)
from app.cognition.persistence import PostgresCognitionUsagePersistence
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    CoordinationRecord,
    PostgresCoordinationPersistence,
)
from app.core.config import get_settings
from app.db.session import get_session_factory
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
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.workers.celery_app import celery_app
from app.workers.supervisor_tasks import evaluate_session_supervisor

_T = TypeVar("_T")
_STARTED = "diagnostic_execution_started"
_COMPLETED = "diagnostic_analysis_completed"
_FAILED = "diagnostic_execution_failed"
_MAX_EXECUTION_ATTEMPTS = 4


@celery_app.task(
    name="execute_diagnostic_agent",
    bind=True,
    max_retries=3,
)
def execute_diagnostic_agent(
    self: Any,
    execution_id: str,
) -> dict[str, object]:
    """Run one bounded DiagnosticAgent execution."""
    worker_id = _worker_id(self)
    result = _run_async(
        execute_diagnostic_agent_runtime(
            execution_id=execution_id,
            worker_id=worker_id,
            max_attempts=_max_execution_attempts(self),
        )
    )
    if result.get("status") == "retry_requested":
        raise self.retry(
            exc=DiagnosticExecutionRetry(str(result.get("message") or result))
        )
    return result


async def execute_diagnostic_agent_runtime(
    *,
    execution_id: str,
    worker_id: str = "inline:diagnostic",
    max_attempts: int = 1,
) -> dict[str, object]:
    session_factory = get_session_factory()
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
        dispatch_id = execution.dispatch_id
        session_id = execution.session_id
        tenant_id = execution.tenant_id
        try:
            claim_lost = await _claim_lost_payload(
                execution_runtime=execution_runtime,
                execution_id=str(execution.execution_id),
                attempt_id=str(attempt.attempt_id),
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
                    "execution_id": str(execution.execution_id),
                    "attempt_id": str(attempt.attempt_id),
                    "attempt_number": attempt.attempt_number,
                },
                idempotency_key=_timeline_idempotency_key(
                    execution_id=str(execution.execution_id),
                    attempt_id=str(attempt.attempt_id),
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
            result = await DiagnosticAgent(
                cognition_runtime=_diagnostic_cognition_runtime(session)
            ).execute(
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
                content=content,
                execution_id=str(execution.execution_id),
            )
            claim_lost = await _claim_lost_payload(
                execution_runtime=execution_runtime,
                execution_id=str(execution.execution_id),
                attempt_id=str(attempt.attempt_id),
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
                event_type=_COMPLETED,
                payload=result.model_dump(),
                idempotency_key=_timeline_idempotency_key(
                    execution_id=str(execution.execution_id),
                    attempt_id=str(attempt.attempt_id),
                    event_type=_COMPLETED,
                ),
            )
            completed_payload = result.model_dump()
            await execution_runtime.complete_execution(
                execution_id=execution.execution_id,
                attempt_id=attempt.attempt_id,
                worker_id=worker_id,
                result=completed_payload,
            )
            await session.commit()
            supervisor_queued = await _queue_supervisor_if_closed(
                session_repo=session_repo,
                session_id=session_id,
                tenant_id=tenant_id,
            )
            return {
                "execution_id": str(execution.execution_id),
                "attempt_id": str(attempt.attempt_id),
                "attempt_number": attempt.attempt_number,
                "dispatch_id": dispatch_id,
                "session_id": session_id,
                "tenant_id": tenant_id,
                "status": "completed",
                "supervisor_evaluation_queued": supervisor_queued,
                "summary": result.summary,
                "category": result.category,
                "confidence": result.confidence,
            }
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            terminal = attempt.attempt_number >= max(1, max_attempts)
            failure = _bounded_failure_metadata(
                exc,
                execution_id=str(execution.execution_id),
                attempt_id=str(attempt.attempt_id),
                attempt_number=attempt.attempt_number,
                retry_requested=not terminal,
            )
            claim_lost = await _claim_lost_payload(
                execution_runtime=execution_runtime,
                execution_id=str(execution.execution_id),
                attempt_id=str(attempt.attempt_id),
                worker_id=worker_id,
            )
            if claim_lost is not None:
                return {
                    **claim_lost,
                    "dispatch_id": dispatch_id,
                    "session_id": session_id,
                    "tenant_id": tenant_id,
                    **failure,
                }
            failure_event_persisted = await _append_failure_event(
                session=session,
                timeline=timeline,
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
                failure=failure,
            )
            if terminal:
                execution_failed = await _dead_letter_execution_record(
                    execution_runtime=execution_runtime,
                    session=session,
                    execution_id=execution.execution_id,
                    attempt_id=attempt.attempt_id,
                    worker_id=worker_id,
                    failure=failure,
                )
                status = "dead_lettered"
            else:
                execution_failed = await _fail_execution_record(
                    execution_runtime=execution_runtime,
                    session=session,
                    execution_id=execution.execution_id,
                    attempt_id=attempt.attempt_id,
                    worker_id=worker_id,
                    failure=failure,
                    retry_requested=True,
                )
                status = "retry_requested"
            return {
                "execution_id": str(execution.execution_id),
                "attempt_id": str(attempt.attempt_id),
                "attempt_number": attempt.attempt_number,
                "dispatch_id": dispatch_id,
                "session_id": session_id,
                "tenant_id": tenant_id,
                "status": status,
                "failure_event_persisted": failure_event_persisted,
                "execution_failed": execution_failed,
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
) -> DiagnosticResult:
    return await DiagnosticAgent(
        cognition_runtime=cognition_runtime
    ).execute(
        dispatch_id=dispatch_id,
        session_id=session_id,
        tenant_id=tenant_id,
        content=content,
        execution_id=execution_id,
    )


async def _queue_supervisor_if_closed(
    *,
    session_repo: SessionPersistenceProtocol,
    session_id: str,
    tenant_id: str,
) -> bool:
    session = await session_repo.get_session(
        as_session_id(session_id),
        expected_tenant_id=tenant_id,
    )
    if session is None or not is_terminal_session(session.lifecycle_phase):
        return False
    cast(Any, evaluate_session_supervisor).delay(session_id)
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


def _bounded_failure_metadata(
    exc: BaseException,
    *,
    execution_id: str,
    attempt_id: str,
    attempt_number: int,
    retry_requested: bool,
) -> dict[str, object]:
    message = str(exc)
    if len(message) > 240:
        message = f"{message[:237]}..."
    return {
        "execution_id": execution_id,
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "error_type": exc.__class__.__name__,
        "message": message,
        "retry_requested": retry_requested,
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


def _max_execution_attempts(task_self: Any) -> int:
    max_retries = getattr(task_self, "max_retries", None)
    if isinstance(max_retries, int) and max_retries >= 0:
        return max_retries + 1
    return _MAX_EXECUTION_ATTEMPTS


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
        usage_persistence=PostgresCognitionUsagePersistence(session),
        governance_repository=PostgresGovernanceRepository(session),
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


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def _timeline_idempotency_key(
    *,
    execution_id: str,
    attempt_id: str,
    event_type: str,
) -> str:
    return f"execution.{execution_id}.attempt.{attempt_id}.event.{event_type}"


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


class DiagnosticExecutionRetry(RuntimeError):
    """Raised to ask Celery transport for another delivery."""


__all__ = [
    "execute_diagnostic_agent",
    "execute_diagnostic_agent_runtime",
    "_generate_diagnostic_reasoning_draft",
]
