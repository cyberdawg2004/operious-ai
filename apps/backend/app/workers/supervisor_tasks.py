"""Supervisor evaluation worker tasks.

Celery is transport only. The task accepts a ``session_id`` and then
constructs the persisted-evidence supervisor runtime inside the worker
boundary; no live runtime objects are passed into supervisor
evaluation.

MVP-8: Also hosts the autonomous supervisor pattern detection task,
which runs asynchronously (not in the approval path) and detects
cross-ticket patterns that individual gates miss.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine, Iterable, Mapping
from datetime import datetime, timezone
from threading import Thread
from typing import Any, TypeVar, cast

from app.agents.governed.autonomous_supervisor import (
    AutonomousSupervisorAgent,
    SupervisorPatternFinding,
    apply_supervisor_finding_action,
)
from app.agents.governed.base import AgentInput
from app.agents.governed.proposal import AgentProposalStatus
from app.cognition.llm_factory import build_llm_client
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.db.tenant_context import set_current_tenant
from app.execution import PostgresExecutionPersistence
from app.governance.persistence import PostgresGovernanceRepository
from app.session.persistence import PostgresSessionPersistence
from app.supervisor.evaluators.builtin import build_default_evaluator_registry
from app.supervisor.persistence import PostgresSupervisorRepository
from app.supervisor.runtime import SupervisorRuntime
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.workers.celery_app import celery_app, enqueued_at_iso
from app.workers.queue_admission import (
    admit_qa_publish,
    clear_worker_queue_age,
    record_worker_queue_age,
)
from app.queues import QUEUE_QA, QUEUE_SUPERVISOR
from app.workers.qa_tasks import score_supervisor_inspection

_T = TypeVar("_T")

_logger = logging.getLogger(__name__)

_SUPERVISOR_AGENT_NAMESPACE = uuid.UUID("8b2e4f6a-1c3d-5e7f-9a0b-2d4e6f8a0c1e")

# Allowlist of structured signal fields that are safe to pass to the supervisor
# LLM. Any field not in this set is stripped before the signals list reaches
# AgentInput — prevents free-text fields (note, reason, message, etc.) from
# carrying prompt-injection payloads that could cause the model to output
# severity=critical + trigger_circuit_breaker (H-2 pre-pilot hardening item).
_SAFE_SIGNAL_FIELDS: frozenset[str] = frozenset({
    "type",
    "session_id",
    "execution_id",
    "tenant_id",
    "timestamp",
    "category",
    "pattern_kind",
    # numeric quality/rate signals
    "compliance_score",
    "escalation_rate",
    "severity_score",
    "qa_score",
    "count",
    "duration_seconds",
    "amount_cents",
    # boolean flags
    "escalated",
    "flagged",
    "is_anomaly",
})


def _sanitize_signals(signals: Iterable[object]) -> list[dict[str, Any]]:
    """Strip free-text fields from signal dicts before LLM ingestion.

    Keeps only _SAFE_SIGNAL_FIELDS — structured, typed fields that carry no
    prose content an attacker could embed instructions in.
    """
    sanitized: list[dict[str, Any]] = []
    for raw in signals:
        if not isinstance(raw, Mapping):
            continue
        clean = {
            k: v
            for k, v in raw.items()
            if isinstance(k, str) and k in _SAFE_SIGNAL_FIELDS
        }
        if clean:
            sanitized.append(clean)
    return sanitized


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
    # Write the sentinel before the task is dispatchable: if a worker
    # could dequeue and clear it first, the later write would orphan
    # the member permanently.
    await record_worker_queue_age(
        queue_name=QUEUE_QA,
        member_id=inspection_id,
    )
    try:
        cast(Any, score_supervisor_inspection).apply_async(
            args=(inspection_id, tenant_id),
            kwargs={"_enqueued_at": enqueued_at_iso()},
            queue=QUEUE_QA,
        )
    except Exception:
        await clear_worker_queue_age(
            queue_name=QUEUE_QA,
            member_id=inspection_id,
        )
        raise
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


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="run_supervisor_pattern_detection",
    queue=QUEUE_SUPERVISOR,
    bind=True,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=60,
)
def run_supervisor_pattern_detection(
    _self: Any,
    tenant_id: str,
    category: str,
    session_ids: list[str],
    signals: list[dict[str, Any]],
    window_hours: int = 24,
    escalation_rate: float | None = None,
    avg_compliance: float | None = None,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Run autonomous supervisor pattern detection for a tenant/category."""
    del _enqueued_at

    set_current_tenant(tenant_id)
    try:
        return _run_async(
            run_supervisor_pattern_detection_runtime(
                tenant_id=tenant_id,
                category=category,
                session_ids=session_ids,
                signals=signals,
                window_hours=window_hours,
                escalation_rate=escalation_rate,
                avg_compliance=avg_compliance,
            ),
            tenant_id=tenant_id,
        )
    finally:
        set_current_tenant(None)


async def run_supervisor_pattern_detection_runtime(
    *,
    tenant_id: str,
    category: str,
    session_ids: list[str],
    signals: list[dict[str, Any]],
    window_hours: int = 24,
    escalation_rate: float | None = None,
    avg_compliance: float | None = None,
) -> dict[str, object]:
    """Core async logic for autonomous supervisor pattern detection."""
    set_current_tenant(tenant_id)
    try:
        settings = get_settings()
        session_factory = get_session_factory()
        async with session_factory() as session:
            tenant_repo = PostgresTenantConfigurationRepository(session)
            llm_client = build_llm_client(settings)

            agent = AutonomousSupervisorAgent(
                llm_client=llm_client,
                tenant_configuration_repository=tenant_repo,
            )

            execution_id = str(uuid.uuid5(
                _SUPERVISOR_AGENT_NAMESPACE,
                f"supervisor_pattern:{tenant_id}:{category}:{datetime.now(timezone.utc).isoformat()}",
            ))

            agent_input = AgentInput(
                tenant_id=tenant_id,
                session_id=f"supervisor_pattern:{category}:{tenant_id}",
                execution_id=execution_id,
                content={
                    "category": category,
                    "signals": _sanitize_signals(signals),
                    "session_ids": session_ids,
                    "window_hours": window_hours,
                    "escalation_rate": escalation_rate,
                    "avg_compliance": avg_compliance,
                },
            )

            proposal = await agent.run(agent_input)

            if proposal.status != AgentProposalStatus.COMPLETED or proposal.output is None:
                _logger.warning(
                    "supervisor_pattern_detection_not_completed tenant=%s category=%s status=%s reason=%s",
                    tenant_id, category, proposal.status.value, proposal.reason,
                )
                return {
                    "status": "finding_requires_review",
                    "tenant_id": tenant_id,
                    "category": category,
                    "agent_status": proposal.status.value,
                    "reason": proposal.reason,
                }

            finding = SupervisorPatternFinding(
                finding_id=str(uuid.uuid5(
                    _SUPERVISOR_AGENT_NAMESPACE,
                    f"finding:{execution_id}:{category}",
                )),
                tenant_id=tenant_id,
                pattern_kind=proposal.output.get("pattern_kind", ""),
                severity=proposal.output.get("severity", "info"),
                affected_category=proposal.output.get("affected_category", category),
                confidence=proposal.output.get("confidence", 0.0),
                evidence_summary=proposal.output.get("evidence_summary", ""),
                recommended_action=proposal.output.get("recommended_action", "log"),
                affected_session_ids=tuple(
                    proposal.output.get("affected_session_ids") or []
                ),
                detected_at=datetime.now(timezone.utc).isoformat(),
                metadata={"execution_id": execution_id},
            )

            action_taken = await apply_supervisor_finding_action(
                finding=finding,
                tenant_configuration_repository=tenant_repo,
            )

            if action_taken == "circuit_breaker_tripped":
                await session.commit()

            _logger.info(
                "supervisor_pattern_finding tenant=%s category=%s severity=%s action=%s",
                tenant_id, category, finding.severity, action_taken,
            )

            return {
                "status": "completed",
                "tenant_id": tenant_id,
                "category": category,
                "finding": finding.to_dict(),
                "action_taken": action_taken,
            }
    finally:
        set_current_tenant(None)


__all__ = [
    "evaluate_session_supervisor",
    "evaluate_session_supervisor_runtime",
    "run_supervisor_pattern_detection",
    "run_supervisor_pattern_detection_runtime",
]
