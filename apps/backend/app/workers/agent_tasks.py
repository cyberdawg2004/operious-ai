"""Agent execution worker tasks."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
import uuid
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Thread
from typing import Any, ParamSpec, Protocol, TypeVar, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.diagnostic_agent import DiagnosticAgent, DiagnosticResult
from app.agents.enums import CapabilityScope
from app.agents.identity import (
    AgentIdentity,
    ExecutionIdentity,
    derive_agent_runtime_instance_id,
)
from app.agents.runtime.quota_runtime import (
    get_quota_runtime as get_initialized_quota_runtime,
)
from app.agents.runtime.retry_policy import RetryPolicy, get_policy
from app.agents.tools import ToolInvoker
from app.agents.tools.action_governance import (
    build_action_tool_governance_runtime,
)
from app.agents.tools.actions import build_action_tool_registry
from app.agents.tools.approvals import PostgresActionApprovalRepository
from app.agents.tools.grants import PostgresAgentActionGrantRepository
from app.agents.tools.orchestration import ActionOrchestrationRuntime
from app.agents.value_objects import CausalityMetadata
from app.cognition import (
    AnthropicMessagesClient,
    DeterministicDiagnosticLLMClient,
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
    DiagnosticLLMClient,
    DiagnosticLLMMessage,
    DiagnosticReasoningResult,
    DiagnosticReasoningSnapshot,
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
from app.cognition.models import DiagnosticLLMCompletion
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    CoordinationRecord,
    PostgresCoordinationPersistence,
)
from app.boundary.translation import (
    IdentityTranslationProvider,
    InMemoryTranslationPersistence,
    TranslationEgressRuntime,
    TranslationIngressRuntime,
    TranslationRuntime,
)
from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.db.session import dispose_engine, get_session_factory, reset_engine_state
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.execution import (
    ExecutionClaimLost,
    ExecutionResultEnvelope,
    ExecutionRuntime,
    PostgresExecutionPersistence,
)
from app.governance.persistence import PostgresGovernanceRepository
from app.governance.capability.runtime import build_capability_governance_runtime
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import PostgresKnowledgeRepository
from app.resolution.persistence import PostgresResolutionProposalPersistence
from app.runtime.resolution_governance_gate import (
    ResolutionGovernanceGate,
    build_resolution_governance_runtime,
)
from app.runtime.resolution_runtime import (
    ResolutionOutboundDraftRuntime,
    ResolutionProposalRequest,
    ResolutionRuntime,
    resolution_outbound_draft_timeline_payload,
    resolution_proposal_timeline_payload,
    resolution_proposal_is_send_eligible,
)
from app.runtime.timeline_runtime import TimelineRuntime
from app.runtime.provider_circuit_breaker import (
    ProviderCircuitBreaker,
    ProviderCircuitSnapshot,
)
from app.workers.execution_completion_events import (
    WorkerExecutionCompletionEventSink,
)
from app.session.contracts.requests import AppendEventRequest
from app.session.contracts.results import AppendEventResult
from app.session.conversation import (
    derive_conversation_turn_id,
    publish_conversation_event,
)
from app.session.enums import SessionContinuityMode, SessionEventKind
from app.session.identity import as_session_id
from app.session.lifecycle.classifier import is_terminal as is_terminal_session
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionPersistenceProtocol,
)
from app.session.runtime import SessionRuntime
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.workers.celery_app import celery_app, enqueued_at_iso
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
_P = ParamSpec("_P")


class _CeleryTaskDecorator(Protocol):
    def __call__(
        self,
        *args: object,
        **kwargs: object,
    ) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
        ...


_celery_task = cast(_CeleryTaskDecorator, getattr(celery_app, "task"))
_STARTED = "diagnostic_execution_started"
_COMPLETED = "diagnostic_analysis_completed"
_FAILED = "diagnostic_execution_failed"
_RESOLUTION_CREATED = "resolution_proposal_created"
_RESOLUTION_DRAFT_CREATED = "resolution_outbound_draft_created"
_RESOLUTION_FAILED = "resolution_proposal_failed"
_MAX_EXECUTION_ATTEMPTS = 5
_DIAGNOSTIC_RETRY_BASE_DELAY_SECONDS = 30

logger = logging.getLogger(__name__)


@_celery_task(
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
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Run one bounded DiagnosticAgent execution."""
    del _enqueued_at
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
                worker_id=worker_id,
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
    source_language: str = "en"
    conversation_turn_id: str | None = None


@dataclass(frozen=True, slots=True)
class _DispatchContentContext:
    content: str
    source_language: str


@dataclass(frozen=True, slots=True)
class _ResolutionAppendResult:
    success: bool
    customer_reply: str | None = None
    governance_decision_id: str | None = None
    proposal_id: str | None = None
    draft_id: str | None = None


@dataclass(frozen=True, slots=True)
class _ConversationPhaseBEvent:
    turn_id: str
    content: str
    governance_decision_id: str
    execution_id: str


@dataclass(frozen=True, slots=True)
class _DiagnosticReasoningDraft:
    snapshot: DiagnosticReasoningSnapshot
    completion: DiagnosticLLMCompletion


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
        conversation_turn_id = _metadata_text(
            dict(execution.metadata).get("conversation.turn_id")
        )
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

        content_context = await _load_dispatch_content(
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
            content=content_context.content,
            source_language=content_context.source_language,
            conversation_turn_id=conversation_turn_id,
        )


async def _generate_diagnostic_reasoning_for_work_item(
    *,
    session_factory: Any,
    work_item: _DiagnosticExecutionWorkItem,
    worker_id: str,
) -> _DiagnosticReasoningDraft:
    snapshot = await _load_diagnostic_reasoning_snapshot(
        session_factory=session_factory,
        work_item=work_item,
        worker_id=worker_id,
    )
    try:
        completion = await _complete_diagnostic_reasoning_snapshot(snapshot)
    except Exception as exc:
        await _record_provider_circuit_outcome(
            session_factory=session_factory,
            snapshot=snapshot,
            error=exc,
        )
        await _persist_diagnostic_reasoning_failure_forensics(
            session_factory=session_factory,
            snapshot=snapshot,
            exc=exc,
        )
        raise

    await _record_provider_circuit_outcome(
        session_factory=session_factory,
        snapshot=snapshot,
        completion=completion,
    )
    return _DiagnosticReasoningDraft(
        snapshot=snapshot,
        completion=completion,
    )


async def _load_diagnostic_reasoning_snapshot(
    *,
    session_factory: Any,
    work_item: _DiagnosticExecutionWorkItem,
    worker_id: str,
) -> DiagnosticReasoningSnapshot:
    previous_tenant = get_current_tenant()
    set_current_tenant(work_item.tenant_id)
    try:
        async with session_factory() as session:
            try:
                await _set_transaction_tenant(session, work_item.tenant_id)
                cognition_runtime = _diagnostic_cognition_runtime(session)
                snapshot = await cognition_runtime.load_reasoning_snapshot(
                    tenant_id=work_item.tenant_id,
                    execution_id=work_item.execution_id,
                    dispatch_id=work_item.dispatch_id,
                    session_id=work_item.session_id,
                    content=work_item.content,
                    attempt_id=work_item.attempt_id,
                    attempt_number=work_item.attempt_number,
                    worker_id=worker_id,
                    source_language=work_item.source_language,
                )
                circuit_snapshot = await ProviderCircuitBreaker(
                    session=session,
                ).before_request(
                    tenant_id=snapshot.tenant_id,
                    provider_name=snapshot.provider_name,
                )
                snapshot = snapshot.with_provider_circuit_state(
                    _provider_circuit_state_payload(circuit_snapshot)
                )
                await session.commit()
                return snapshot
            except Exception:
                await session.rollback()
                raise
    finally:
        set_current_tenant(previous_tenant)


async def _set_transaction_tenant(
    session: AsyncSession,
    tenant_id: str,
) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


def _provider_circuit_state_payload(
    snapshot: ProviderCircuitSnapshot,
) -> dict[str, object]:
    return {
        "state": snapshot.state.value,
        "consecutive_failures": snapshot.consecutive_failures,
        "retry_count": snapshot.retry_count,
        "open_until": (
            snapshot.open_until.isoformat()
            if snapshot.open_until is not None
            else None
        ),
        "half_open_trial_started_at": (
            snapshot.half_open_trial_started_at.isoformat()
            if snapshot.half_open_trial_started_at is not None
            else None
        ),
    }


async def _record_provider_circuit_outcome(
    *,
    session_factory: Any,
    snapshot: DiagnosticReasoningSnapshot,
    completion: DiagnosticLLMCompletion | None = None,
    error: BaseException | None = None,
) -> None:
    del completion
    previous_tenant = get_current_tenant()
    set_current_tenant(snapshot.tenant_id)
    try:
        async with session_factory() as session:
            try:
                await _set_transaction_tenant(session, snapshot.tenant_id)
                breaker = ProviderCircuitBreaker(session=session)
                if error is None:
                    await breaker.record_success(
                        tenant_id=snapshot.tenant_id,
                        provider_name=snapshot.provider_name,
                    )
                elif isinstance(error, ProviderRateLimitError):
                    retry_after = getattr(error, "retry_after_seconds", None)
                    await breaker.record_http_status(
                        tenant_id=snapshot.tenant_id,
                        provider_name=snapshot.provider_name,
                        status_code=429,
                        retry_after=(
                            str(retry_after)
                            if isinstance(retry_after, int)
                            else None
                        ),
                    )
                elif isinstance(error, ProviderTransientError):
                    await breaker.record_transient_failure(
                        tenant_id=snapshot.tenant_id,
                        provider_name=snapshot.provider_name,
                        reason=error.__class__.__name__,
                    )
                elif isinstance(error, CognitionLLMProviderError):
                    status_code = _provider_status_code_from_error(error)
                    if status_code is None:
                        await breaker.record_transient_failure(
                            tenant_id=snapshot.tenant_id,
                            provider_name=snapshot.provider_name,
                            reason=error.__class__.__name__,
                        )
                    else:
                        await breaker.record_http_status(
                            tenant_id=snapshot.tenant_id,
                            provider_name=snapshot.provider_name,
                            status_code=status_code,
                        )
                else:
                    await breaker.record_transient_failure(
                        tenant_id=snapshot.tenant_id,
                        provider_name=snapshot.provider_name,
                        reason=error.__class__.__name__,
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        set_current_tenant(previous_tenant)


def _provider_status_code_from_error(error: BaseException) -> int | None:
    marker = "HTTPStatusError:"
    message = str(error)
    marker_index = message.find(marker)
    if marker_index == -1:
        return None
    start = marker_index + len(marker)
    digits: list[str] = []
    for char in message[start:]:
        if not char.isdigit():
            break
        digits.append(char)
    if not digits:
        return None
    return int("".join(digits))


def _diagnostic_result_from_reasoning(
    result: DiagnosticReasoningResult,
) -> DiagnosticResult:
    cognition_audit_id = result.metadata.get("cognition_audit_id")
    return DiagnosticResult(
        summary=result.summary,
        category=result.category,
        confidence=result.confidence,
        provider=result.provider,
        model=result.model,
        citations=result.citations,
        usage_id=str(result.usage_id),
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        estimated_cost_micro_usd=result.estimated_cost_micro_usd,
        governance_decision_id=result.governance_decision_id,
        cognition_audit_id=(
            str(cognition_audit_id)
            if cognition_audit_id is not None
            else None
        ),
        retrieved_citations=result.retrieved_citations,
    )


async def _diagnostic_usage_exists(
    *,
    session: AsyncSession,
    snapshot: DiagnosticReasoningSnapshot,
) -> bool:
    existing = await PostgresCognitionUsagePersistence(
        session,
        audit_encryptor=_cognition_audit_encryptor(),
    ).get_llm_usage(
        snapshot.usage_id,
        expected_tenant_id=snapshot.tenant_id,
    )
    return existing is not None


def _log_diagnostic_claim_lost(
    claim_lost: Mapping[str, object],
    *,
    work_item: _DiagnosticExecutionWorkItem,
    worker_id: str,
) -> None:
    logger.info(
        "diagnostic_claim_lost_after_llm",
        extra={
            "execution_id": work_item.execution_id,
            "attempt_id": work_item.attempt_id,
            "attempt_number": work_item.attempt_number,
            "worker_id": worker_id,
            "reason": str(claim_lost.get("reason") or "claim_lost"),
        },
    )


async def _complete_diagnostic_reasoning_snapshot(
    snapshot: DiagnosticReasoningSnapshot,
) -> DiagnosticLLMCompletion:
    client = _diagnostic_llm_client()
    try:
        return await client.complete(
            system_prompt=snapshot.system_prompt,
            messages=tuple(
                DiagnosticLLMMessage(
                    role=message.role,
                    content=message.content,
                )
                for message in snapshot.messages
            ),
            max_output_tokens=snapshot.max_output_tokens,
            temperature=snapshot.temperature,
            tenant_id=snapshot.tenant_id,
        )
    except TypeError as exc:
        if "tenant_id" not in str(exc):
            raise
        return await client.complete(
            system_prompt=snapshot.system_prompt,
            messages=snapshot.messages,
            max_output_tokens=snapshot.max_output_tokens,
            temperature=snapshot.temperature,
        )


async def _persist_diagnostic_reasoning_failure_forensics(
    *,
    session_factory: Any,
    snapshot: DiagnosticReasoningSnapshot,
    exc: BaseException,
) -> None:
    previous_tenant = get_current_tenant()
    set_current_tenant(snapshot.tenant_id)
    try:
        async with session_factory() as session:
            try:
                await _set_transaction_tenant(session, snapshot.tenant_id)
                await _diagnostic_cognition_runtime(
                    session
                ).persist_reasoning_failure(
                    snapshot=snapshot,
                    error=exc,
                    failed=not isinstance(
                        exc,
                        (
                            CognitionLLMProviderError,
                            ProviderQuotaExceededError,
                            ProviderRateLimitError,
                            ProviderTransientError,
                        ),
                    ),
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        set_current_tenant(previous_tenant)


async def _persist_diagnostic_success(
    *,
    session_factory: Any,
    work_item: _DiagnosticExecutionWorkItem,
    worker_id: str,
    result: _DiagnosticReasoningDraft,
) -> dict[str, object]:
    draft = result
    previous_tenant = get_current_tenant()
    set_current_tenant(work_item.tenant_id)
    try:
        async with session_factory() as session:
            try:
                await _set_transaction_tenant(session, work_item.tenant_id)
                execution_runtime = ExecutionRuntime(
                    persistence=PostgresExecutionPersistence(session),
                    completion_event_sink=WorkerExecutionCompletionEventSink(
                        session=session
                    ),
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
                    if not await _diagnostic_usage_exists(
                        session=session,
                        snapshot=draft.snapshot,
                    ):
                        await _diagnostic_cognition_runtime(
                            session
                        ).persist_reasoning_result(
                            snapshot=draft.snapshot,
                            completion=draft.completion,
                            allow_existing_governance=True,
                        )
                    await session.commit()
                    _log_diagnostic_claim_lost(
                        claim_lost,
                        work_item=work_item,
                        worker_id=worker_id,
                    )
                    return {
                        **claim_lost,
                        "dispatch_id": work_item.dispatch_id,
                        "session_id": work_item.session_id,
                        "tenant_id": work_item.tenant_id,
                    }

                # GovernanceRuntime is constructed fresh per task invocation.
                # Policies are current as of this task's start time. The
                # staleness window within a running diagnostic task is the
                # task duration, typically < 90s. Crisis policies and new
                # governance rules take effect on the next task that starts
                # after deployment; in-flight tasks at deployment time see
                # the prior policy. This is acceptable for the pilot; see
                # docs/slo.md.
                cognition_result = await _diagnostic_cognition_runtime(
                    session
                ).persist_reasoning_result(
                    snapshot=draft.snapshot,
                    completion=draft.completion,
                    allow_existing_governance=True,
                )
                result_payload = _diagnostic_result_from_reasoning(
                    cognition_result
                )
                authority_tx = await session.begin_nested()
                try:
                    diagnostic_event = await timeline.append_event(
                        dispatch_id=work_item.dispatch_id,
                        session_id=work_item.session_id,
                        tenant_id=work_item.tenant_id,
                        event_type=_COMPLETED,
                        payload=result_payload.model_dump(),
                        idempotency_key=_timeline_idempotency_key(
                            execution_id=work_item.execution_id,
                            attempt_id=work_item.attempt_id,
                            event_type=_COMPLETED,
                        ),
                    )
                    resolution_append = (
                        await _append_resolution_proposal_after_diagnostic(
                            session=session,
                            timeline=timeline,
                            work_item=work_item,
                            result=result_payload,
                            diagnostic_event_id=diagnostic_event.timeline_event_id,
                        )
                    )
                    phase_b_event = await _append_conversation_phase_b_turn(
                        session=session,
                        session_repo=session_repo,
                        work_item=work_item,
                        resolution_append=resolution_append,
                    )
                    result_metadata = result_payload.model_dump(
                        exclude={
                            "category",
                            "confidence",
                            "summary",
                            "governance_decision_id",
                        }
                    )
                    completed_envelope = ExecutionResultEnvelope(
                        diagnostic_category=result_payload.category,
                        diagnostic_confidence=result_payload.confidence,
                        diagnostic_summary=result_payload.summary,
                        governance_decision_id=(
                            result_payload.governance_decision_id
                            or resolution_append.governance_decision_id
                        ),
                        resolution_proposal_id=resolution_append.proposal_id,
                        resolution_draft_id=resolution_append.draft_id,
                        metadata=result_metadata,
                    )
                    completed_payload = completed_envelope.to_dict()
                    completed = await execution_runtime.complete_execution(
                        execution_id=work_item.execution_id,
                        attempt_id=work_item.attempt_id,
                        worker_id=worker_id,
                        result=completed_payload,
                        diagnostic_category=(
                            completed_envelope.diagnostic_category
                        ),
                        diagnostic_confidence=(
                            completed_envelope.diagnostic_confidence
                        ),
                    )
                    if isinstance(completed, ExecutionClaimLost):
                        await authority_tx.rollback()
                        await session.commit()
                        claim_lost_payload: dict[str, object] = {
                            "execution_id": work_item.execution_id,
                            "attempt_id": work_item.attempt_id,
                            "worker_id": worker_id,
                            "dispatch_id": work_item.dispatch_id,
                            "session_id": work_item.session_id,
                            "tenant_id": work_item.tenant_id,
                            "status": "claim_lost",
                            "reason": completed.reason,
                        }
                        _log_diagnostic_claim_lost(
                            claim_lost_payload,
                            work_item=work_item,
                            worker_id=worker_id,
                        )
                        return claim_lost_payload
                    await authority_tx.commit()
                except Exception:
                    if authority_tx.is_active:
                        await authority_tx.rollback()
                    raise
                await session.commit()
                await _publish_conversation_phase_b(
                    work_item=work_item,
                    phase_b_event=phase_b_event,
                )
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
                    "summary": result_payload.summary,
                    "category": result_payload.category,
                    "confidence": result_payload.confidence,
                }
            except Exception:
                await session.rollback()
                raise
    finally:
        set_current_tenant(previous_tenant)


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
                queue=QUEUE_DIAGNOSTIC_NORMAL,
                task_payload=_dead_letter_task_payload(work_item),
                celery_kwargs={
                    "execution_id": work_item.execution_id,
                    "tenant_id": work_item.tenant_id,
                },
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
) -> _DispatchContentContext:
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


def _extract_content(dispatch: CoordinationRecord) -> _DispatchContentContext:
    body = dispatch.payload_body
    source_language = _extract_source_language(body)
    canonical_payload = body.get("canonical_payload")
    if isinstance(canonical_payload, Mapping):
        extracted = _extract_text(cast(Mapping[str, Any], canonical_payload))
        if extracted:
            return _DispatchContentContext(
                content=extracted,
                source_language=source_language,
            )
    return _DispatchContentContext(
        content=_extract_text(body),
        source_language=source_language,
    )


def _extract_source_language(body: Mapping[str, Any]) -> str:
    language = body.get("source_language")
    if isinstance(language, str) and language.strip():
        return language.strip().lower()
    canonical_payload = body.get("canonical_payload")
    if isinstance(canonical_payload, Mapping):
        payload = cast(Mapping[str, Any], canonical_payload)
        payload_language = payload.get("source_language")
        if isinstance(payload_language, str) and payload_language.strip():
            return payload_language.strip().lower()
    return "en"


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


async def _append_resolution_proposal_after_diagnostic(
    *,
    session: AsyncSession,
    timeline: TimelineRuntime,
    work_item: _DiagnosticExecutionWorkItem,
    result: DiagnosticResult,
    diagnostic_event_id: str,
) -> _ResolutionAppendResult:
    try:
        async with session.begin_nested():
            resolution_persistence = PostgresResolutionProposalPersistence(session)
            proposal = await ResolutionRuntime(
                persistence=resolution_persistence,
                governance_gate=ResolutionGovernanceGate(
                    # Per-task runtime construction bounds policy staleness
                    # to the current task; new tasks pick up new composition.
                    governance_runtime=build_resolution_governance_runtime(
                        persistence=PostgresGovernanceRepository(session)
                    )
                ),
            ).create_proposal(
                ResolutionProposalRequest(
                    tenant_id=work_item.tenant_id,
                    session_id=work_item.session_id,
                    execution_id=work_item.execution_id,
                    dispatch_id=work_item.dispatch_id,
                    diagnostic_event_id=diagnostic_event_id,
                    diagnostic_summary=result.summary,
                    diagnostic_category=result.category,
                    diagnostic_confidence=result.confidence,
                    original_content=work_item.content,
                    source_language=work_item.source_language,
                    retrieved_citations=result.retrieved_citations,
                )
            )
            await timeline.append_event(
                dispatch_id=work_item.dispatch_id,
                session_id=work_item.session_id,
                tenant_id=work_item.tenant_id,
                event_type=_RESOLUTION_CREATED,
                payload=resolution_proposal_timeline_payload(proposal),
                idempotency_key=_timeline_idempotency_key(
                    execution_id=work_item.execution_id,
                    attempt_id=work_item.attempt_id,
                    event_type=_RESOLUTION_CREATED,
                ),
            )
            draft = await ResolutionOutboundDraftRuntime(
                persistence=resolution_persistence,
                translation_runtime=_translation_runtime(session),
            ).create_draft_for_proposal(proposal)
            await timeline.append_event(
                dispatch_id=work_item.dispatch_id,
                session_id=work_item.session_id,
                tenant_id=work_item.tenant_id,
                event_type=_RESOLUTION_DRAFT_CREATED,
                payload=resolution_outbound_draft_timeline_payload(
                    draft=draft,
                    proposal=proposal,
                ),
                idempotency_key=_timeline_idempotency_key(
                    execution_id=work_item.execution_id,
                    attempt_id=work_item.attempt_id,
                    event_type=_RESOLUTION_DRAFT_CREATED,
                ),
            )
            if resolution_proposal_is_send_eligible(proposal):
                await _action_orchestration_runtime(
                    session=session,
                    timeline=timeline,
                ).execute_proposal_actions(
                    proposal=proposal,
                    execution_context=_action_execution_context(work_item),
                    expected_tenant_id=work_item.tenant_id,
                )
        if (
            resolution_proposal_is_send_eligible(proposal)
            and proposal.governance_decision_id is not None
        ):
            return _ResolutionAppendResult(
                success=True,
                customer_reply=draft.draft_body,
                governance_decision_id=str(proposal.governance_decision_id),
                proposal_id=str(proposal.proposal_id),
                draft_id=str(draft.draft_id),
            )
        return _ResolutionAppendResult(
            success=True,
            governance_decision_id=(
                str(proposal.governance_decision_id)
                if proposal.governance_decision_id is not None
                else None
            ),
            proposal_id=str(proposal.proposal_id),
            draft_id=str(draft.draft_id),
        )
    except Exception as exc:  # noqa: BLE001
        await _append_resolution_failure_event(
            session=session,
            timeline=timeline,
            work_item=work_item,
            diagnostic_event_id=diagnostic_event_id,
            exc=exc,
        )
        return _ResolutionAppendResult(success=False)


def _action_orchestration_runtime(
    *,
    session: AsyncSession,
    timeline: TimelineRuntime,
) -> ActionOrchestrationRuntime:
    return ActionOrchestrationRuntime(
        tool_invoker=ToolInvoker(
            tool_registry=build_action_tool_registry(),
            # Per-task runtime construction bounds policy staleness to the
            # current task; new tasks pick up new composition.
            governance_runtime=build_action_tool_governance_runtime(
                persistence=PostgresGovernanceRepository(session),
                redis_client=get_redis_client(),
            ),
            grant_repository=PostgresAgentActionGrantRepository(session),
            redis_client=get_redis_client(),
            pre_approved_decision_ttl_seconds=(
                get_settings().AGENT_PRE_APPROVED_DECISION_TTL_SECONDS
            ),
        ),
        approval_repository=PostgresActionApprovalRepository(session),
        timeline_runtime=timeline,
    )


def _translation_runtime(session: AsyncSession) -> TranslationRuntime:
    persistence = InMemoryTranslationPersistence()
    provider = IdentityTranslationProvider()
    # Per-task runtime construction bounds policy staleness to the current
    # task; new tasks pick up new composition.
    governance = build_capability_governance_runtime(
        persistence=PostgresGovernanceRepository(session)
    )
    return TranslationRuntime(
        ingress=TranslationIngressRuntime(
            provider=provider,
            persistence=persistence,
            capability_governance=governance,
        ),
        egress=TranslationEgressRuntime(
            provider=provider,
            persistence=persistence,
            capability_governance=governance,
        ),
    )


def _action_execution_context(
    work_item: _DiagnosticExecutionWorkItem,
) -> AgentExecutionContext:
    tool_names = (
        "warranty.claim",
        "replacement.order",
        "refund.request",
        "warehouse.repair.report",
    )
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="diagnostic-action-orchestrator",
            runtime_instance_id=derive_agent_runtime_instance_id(
                agent_ids=("diagnostic-action-orchestrator",)
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.UUID(work_item.execution_id),
            request_id=f"action-orchestration:{work_item.execution_id}",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.warranty.claim",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.replacement.order",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.refund.request",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.warehouse.repair",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(allowed_tools=tool_names),
        causality=CausalityMetadata(
            initiator="diagnostic_agent",
            cause="resolution_send_eligible_action_tools",
        ),
        tenant_id=work_item.tenant_id,
        metadata={
            "session_id": work_item.session_id,
            "dispatch_id": work_item.dispatch_id,
            "attempt_id": work_item.attempt_id,
        },
    )


async def _append_conversation_phase_b_turn(
    *,
    session: AsyncSession,
    session_repo: SessionPersistenceProtocol,
    work_item: _DiagnosticExecutionWorkItem,
    resolution_append: _ResolutionAppendResult,
) -> _ConversationPhaseBEvent | None:
    del session
    if work_item.conversation_turn_id is None:
        return None
    if (
        not resolution_append.success
        or resolution_append.customer_reply is None
        or resolution_append.governance_decision_id is None
    ):
        return None
    session_record = await session_repo.get_session(
        as_session_id(work_item.session_id),
        expected_tenant_id=work_item.tenant_id,
    )
    if session_record is None:
        return None
    turn_id = derive_conversation_turn_id(
        session_id=work_item.session_id,
        sequence=session_record.sequence_head + 1,
    )
    envelope = await SessionRuntime(persistence=session_repo).append_event(
        AppendEventRequest(
            session_id=as_session_id(work_item.session_id),
            kind=SessionEventKind.ASSISTANT_RESPONSE,
            occurred_at=datetime.now(timezone.utc),
            continuity_mode=SessionContinuityMode.SYNCHRONOUS,
            payload={
                "content": resolution_append.customer_reply,
                "phase": "B",
                "turn_id": turn_id,
                "governance_decision_id": (
                    resolution_append.governance_decision_id
                ),
                "execution_id": work_item.execution_id,
            },
            annotation="assistant_response_phase_b",
            correlation_id=work_item.dispatch_id,
            request_id=work_item.dispatch_id,
            idempotency_key=(
                "conversation.phase_b:"
                f"{work_item.execution_id}:{work_item.attempt_id}"
            ),
        )
    )
    if not envelope.is_ok or envelope.result is None:
        return None
    result = envelope.result
    if not isinstance(result, AppendEventResult) or result.event is None:
        return None
    payload = dict(result.event.payload)
    return _ConversationPhaseBEvent(
        turn_id=str(payload.get("turn_id") or turn_id),
        content=str(payload.get("content") or resolution_append.customer_reply),
        governance_decision_id=str(
            payload.get("governance_decision_id")
            or resolution_append.governance_decision_id
        ),
        execution_id=str(payload.get("execution_id") or work_item.execution_id),
    )


async def _publish_conversation_phase_b(
    *,
    work_item: _DiagnosticExecutionWorkItem,
    phase_b_event: _ConversationPhaseBEvent | None,
) -> None:
    if work_item.conversation_turn_id is None:
        return
    try:
        redis_client = get_redis_client()
        if phase_b_event is not None:
            await publish_conversation_event(
                redis_client=redis_client,
                session_id=work_item.session_id,
                event={
                    "type": "turn",
                    "role": "assistant",
                    "phase": "B",
                    "turn_id": phase_b_event.turn_id,
                    "content": phase_b_event.content,
                    "governance_decision_id": (
                        phase_b_event.governance_decision_id
                    ),
                    "execution_id": phase_b_event.execution_id,
                    "tenant_id": work_item.tenant_id,
                    "session_id": work_item.session_id,
                },
            )
        await publish_conversation_event(
            redis_client=redis_client,
            session_id=work_item.session_id,
            event={
                "type": "status",
                "phase": "complete",
                "tenant_id": work_item.tenant_id,
                "session_id": work_item.session_id,
                "execution_id": work_item.execution_id,
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "conversation_stream_publish_failed",
            extra={
                "session_id": work_item.session_id,
                "execution_id": work_item.execution_id,
            },
        )


async def _append_resolution_failure_event(
    *,
    session: AsyncSession,
    timeline: TimelineRuntime,
    work_item: _DiagnosticExecutionWorkItem,
    diagnostic_event_id: str,
    exc: BaseException,
) -> bool:
    try:
        async with session.begin_nested():
            await timeline.append_event(
                dispatch_id=work_item.dispatch_id,
                session_id=work_item.session_id,
                tenant_id=work_item.tenant_id,
                event_type=_RESOLUTION_FAILED,
                payload={
                    "execution_id": work_item.execution_id,
                    "attempt_id": work_item.attempt_id,
                    "diagnostic_event_id": diagnostic_event_id,
                    "error_type": exc.__class__.__name__,
                    "message": _bounded_exception_message(exc),
                },
                idempotency_key=_timeline_idempotency_key(
                    execution_id=work_item.execution_id,
                    attempt_id=work_item.attempt_id,
                    event_type=_RESOLUTION_FAILED,
                ),
            )
        return True
    except Exception:  # noqa: BLE001
        return False


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
        kwargs={"_enqueued_at": enqueued_at_iso()},
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
        failed = await execution_runtime.fail_execution(
            execution_id=str(execution_id),
            attempt_id=str(attempt_id),
            worker_id=worker_id,
            error=str(failure.get("message") or failure),
            retry_requested=retry_requested,
            result=ExecutionResultEnvelope(
                error_code=str(
                    failure.get("error_class") or "diagnostic_failed"
                ),
                error_message=str(failure.get("message") or failure),
                metadata=dict(failure),
            ).to_dict(),
        )
        if isinstance(failed, ExecutionClaimLost):
            await session.rollback()
            return False
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
        dead_lettered = await execution_runtime.dead_letter_execution(
            execution_id=str(execution_id),
            attempt_id=str(attempt_id),
            worker_id=worker_id,
            error=str(failure.get("message") or failure),
            result=ExecutionResultEnvelope(
                error_code=str(
                    failure.get("error_class")
                    or "diagnostic_dead_lettered"
                ),
                error_message=str(failure.get("message") or failure),
                metadata=dict(failure),
            ).to_dict(),
        )
        if isinstance(dead_lettered, ExecutionClaimLost):
            await session.rollback()
            return False
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
    queue: str,
    task_payload: Mapping[str, object],
    celery_kwargs: Mapping[str, object],
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
            queue=queue,
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
                "celery_kwargs": dict(celery_kwargs),
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
        "source_language": work_item.source_language,
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
    llm_client = _diagnostic_llm_client()
    return DiagnosticCognitionRuntime(
        knowledge_runtime=knowledge_runtime,
        llm_client=llm_client,
        usage_persistence=PostgresCognitionUsagePersistence(
            session,
            audit_encryptor=_cognition_audit_encryptor(),
        ),
        governance_repository=PostgresGovernanceRepository(session),
        redis_client=get_redis_client(),
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


def _diagnostic_llm_client() -> DiagnosticLLMClient:
    settings = get_settings()
    if _running_under_pytest() or not settings.ANTHROPIC_API_KEY.strip():
        return DeterministicDiagnosticLLMClient()
    return AnthropicMessagesClient(
        api_key=settings.ANTHROPIC_API_KEY,
        model=settings.ANTHROPIC_DEFAULT_MODEL,
        base_url=settings.ANTHROPIC_BASE_URL,
        anthropic_version=settings.ANTHROPIC_VERSION,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
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


def _metadata_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


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
