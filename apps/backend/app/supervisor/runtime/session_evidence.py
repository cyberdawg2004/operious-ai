"""Persisted session evidence reconstruction for supervisor evaluation.

This module is deliberately read-only. It consumes persistence
protocols and produces replay records for ``SupervisorRuntime.inspect``.
It does not import live runtimes and does not mutate session,
execution, or governance state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, cast

from app.agents.enums import ExecutionState as AgentExecutionState
from app.agents.persistence.records import (
    AgentExecutionRecord,
    StateTransitionRecord,
    ToolInvocationRecord,
)
from app.execution.enums import ExecutionState as DurableExecutionState
from app.execution.persistence import (
    ExecutionPersistenceProtocol,
    ExecutionQuery,
    ExecutionRecord,
)
from app.governance.persistence import (
    BaseGovernanceRepository,
    GovernanceDecisionRecord,
)
from app.session.identity import SessionId, as_session_id
from app.session.lifecycle.classifier import is_terminal
from app.session.persistence import (
    SessionEventQuery,
    SessionEventRecord,
    SessionPersistenceProtocol,
    SessionRecord,
)
from app.supervisor.exceptions import SupervisorEvaluationError


_REPLAY_RUNTIME_NAMESPACE = uuid.UUID(
    "2b5f4c7a-59f7-4af4-9f76-3f9d6ac1c301"
)


@dataclass(frozen=True, slots=True)
class SessionInspectionEvidence:
    """All persisted evidence needed to inspect one closed session."""

    session: SessionRecord
    timeline_events: tuple[SessionEventRecord, ...]
    execution: ExecutionRecord
    recorded_execution: AgentExecutionRecord
    recorded_tool_invocations: tuple[ToolInvocationRecord, ...]
    governance_decisions: tuple[GovernanceDecisionRecord, ...]

    @property
    def tenant_id(self) -> str:
        tenant_id = self.session.tenant_id
        if not tenant_id:
            raise SupervisorEvaluationError(
                "supervisor evaluation requires a tenant-scoped session"
            )
        return tenant_id

    def metadata(self) -> dict[str, object]:
        return {
            "session_id": str(self.session.session_id),
            "session_lifecycle_phase": self.session.lifecycle_phase.value,
            "session_revision": self.session.revision,
            "session_sequence_head": self.session.sequence_head,
            "timeline_event_count": len(self.timeline_events),
            "execution_id": str(self.execution.execution_id),
            "execution_state": self.execution.state.value,
            "governance_decision_ids": [
                decision.decision_id for decision in self.governance_decisions
            ],
            "evidence_source": "persisted_session_records",
        }


async def load_session_inspection_evidence(
    *,
    session_id: str,
    session_persistence: SessionPersistenceProtocol,
    execution_persistence: ExecutionPersistenceProtocol,
    governance_repository: BaseGovernanceRepository | None,
) -> SessionInspectionEvidence:
    """Reconstruct supervisor evidence using persistence only."""

    sid = as_session_id(session_id)
    session = await _load_tenant_scoped_session(
        sid, session_persistence=session_persistence
    )
    tenant_id = session.tenant_id
    if tenant_id is None:
        raise SupervisorEvaluationError(
            "supervisor evaluation requires a tenant-scoped session"
        )
    if not is_terminal(session.lifecycle_phase):
        raise SupervisorEvaluationError(
            "supervisor evaluation requires a closed session"
        )

    events = await _load_timeline_events(
        sid,
        tenant_id=tenant_id,
        session_persistence=session_persistence,
    )
    execution = await _select_terminal_execution(
        session=session,
        execution_persistence=execution_persistence,
    )
    governance_decisions = await _load_governance_decisions(
        execution=execution,
        session=session,
        events=events,
        tenant_id=tenant_id,
        governance_repository=governance_repository,
    )
    recorded_execution = execution_record_to_agent_replay_record(
        execution=execution,
        session=session,
        governance_decisions=governance_decisions,
    )
    return SessionInspectionEvidence(
        session=session,
        timeline_events=events,
        execution=execution,
        recorded_execution=recorded_execution,
        recorded_tool_invocations=(),
        governance_decisions=governance_decisions,
    )


def execution_record_to_agent_replay_record(
    *,
    execution: ExecutionRecord,
    session: SessionRecord,
    governance_decisions: Iterable[GovernanceDecisionRecord] = (),
) -> AgentExecutionRecord:
    """Project durable execution authority into supervisor replay shape."""

    started_at = execution.requested_at
    ended_at = _execution_terminal_at(execution)
    final_state = _agent_final_state(execution.state)
    transitions = _state_transitions_for_execution(
        execution=execution,
        final_state=final_state,
    )
    governance_ids = tuple(
        decision.decision_id for decision in governance_decisions
    )
    return AgentExecutionRecord(
        execution_id=str(execution.execution_id),
        runtime_instance_id=str(
            uuid.uuid5(_REPLAY_RUNTIME_NAMESPACE, str(execution.execution_id))
        ),
        agent_id=execution.kind.value,
        correlation_id=None,
        parent_execution_id=None,
        parent_chain=(),
        request_id=execution.dispatch_id,
        tenant_id=execution.tenant_id,
        final_state=final_state.value,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        latency_ms=(ended_at - started_at).total_seconds() * 1000.0,
        state_transitions=transitions,
        tool_invocation_count=0,
        tool_invocation_ids=(),
        governance_decision_ids=governance_ids,
        error=execution.error,
        metadata={
            **dict(execution.metadata),
            "session_id": str(session.session_id),
            "dispatch_id": execution.dispatch_id,
            "durable_execution_state": execution.state.value,
            "durable_attempt_count": execution.attempt_count,
        },
    )


async def _load_tenant_scoped_session(
    session_id: SessionId,
    *,
    session_persistence: SessionPersistenceProtocol,
) -> SessionRecord:
    bootstrap = await session_persistence.get_session(session_id)
    if bootstrap is None:
        raise SupervisorEvaluationError("session not found")
    if bootstrap.tenant_id is None:
        raise SupervisorEvaluationError(
            "supervisor evaluation requires a tenant-scoped session"
        )
    session = await session_persistence.get_session(
        session_id,
        expected_tenant_id=bootstrap.tenant_id,
    )
    if session is None:
        raise SupervisorEvaluationError(
            "tenant-scoped session read failed during supervisor evaluation"
        )
    return session


async def _load_timeline_events(
    session_id: SessionId,
    *,
    tenant_id: str,
    session_persistence: SessionPersistenceProtocol,
) -> tuple[SessionEventRecord, ...]:
    page = await session_persistence.list_events(
        SessionEventQuery(session_id=session_id),
        expected_tenant_id=tenant_id,
    )
    return tuple(page.events)


async def _select_terminal_execution(
    *,
    session: SessionRecord,
    execution_persistence: ExecutionPersistenceProtocol,
) -> ExecutionRecord:
    tenant_id = session.tenant_id
    if tenant_id is None:
        raise SupervisorEvaluationError(
            "supervisor evaluation requires a tenant-scoped session"
        )
    page = await execution_persistence.list_executions(
        ExecutionQuery(
            session_id=str(session.session_id),
            tenant_id=tenant_id,
            limit=100,
        ),
        expected_tenant_id=tenant_id,
    )
    terminal = [
        execution
        for execution in page.executions
        if _is_terminal_execution(execution)
    ]
    if not terminal:
        raise SupervisorEvaluationError(
            "supervisor evaluation requires a terminal execution"
        )
    return sorted(
        terminal,
        key=lambda execution: (
            _execution_terminal_at(execution),
            str(execution.execution_id),
        ),
    )[-1]


async def _load_governance_decisions(
    *,
    execution: ExecutionRecord,
    session: SessionRecord,
    events: tuple[SessionEventRecord, ...],
    tenant_id: str,
    governance_repository: BaseGovernanceRepository | None,
) -> tuple[GovernanceDecisionRecord, ...]:
    if governance_repository is None:
        return ()
    records: list[GovernanceDecisionRecord] = []
    seen: set[str] = set()
    for decision_id in _governance_decision_ids(
        execution=execution,
        session=session,
        events=events,
    ):
        if decision_id in seen:
            continue
        seen.add(decision_id)
        record = await governance_repository.get_decision(
            decision_id,
            expected_tenant_id=tenant_id,
        )
        if record is not None:
            records.append(record)
    return tuple(records)


def _governance_decision_ids(
    *,
    execution: ExecutionRecord,
    session: SessionRecord,
    events: tuple[SessionEventRecord, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    _append_metadata_id(values, execution.metadata)
    _append_metadata_id(values, session.metadata)
    for event in events:
        if event.governance_decision_id is not None:
            values.append(str(event.governance_decision_id))
        _append_metadata_id(values, event.metadata)
        _append_payload_id(values, event.payload)
    return tuple(values)


def _append_metadata_id(values: list[str], metadata: object) -> None:
    if not isinstance(metadata, dict):
        return
    metadata_map = cast(dict[str, object], metadata)
    candidate = metadata_map.get("governance.decision_id")
    if candidate:
        values.append(str(candidate))


def _append_payload_id(values: list[str], payload: object) -> None:
    if not isinstance(payload, dict):
        return
    payload_map = cast(dict[str, object], payload)
    for key in ("governance_decision_id", "governance.decision_id"):
        candidate = payload_map.get(key)
        if candidate:
            values.append(str(candidate))


def _state_transitions_for_execution(
    *,
    execution: ExecutionRecord,
    final_state: AgentExecutionState,
) -> tuple[StateTransitionRecord, ...]:
    transitions: list[StateTransitionRecord] = [
        StateTransitionRecord(
            from_state=AgentExecutionState.CREATED.value,
            to_state=AgentExecutionState.READY.value,
            transitioned_at=execution.requested_at.isoformat(),
            reason="durable execution requested",
        )
    ]
    running_started = execution.claimed_at
    if running_started is not None:
        transitions.append(
            StateTransitionRecord(
                from_state=AgentExecutionState.READY.value,
                to_state=AgentExecutionState.RUNNING.value,
                transitioned_at=running_started.isoformat(),
                reason="durable execution claimed",
            )
        )
        terminal_from = AgentExecutionState.RUNNING
    else:
        terminal_from = AgentExecutionState.READY
    if final_state is not terminal_from:
        transitions.append(
            StateTransitionRecord(
                from_state=terminal_from.value,
                to_state=final_state.value,
                transitioned_at=_execution_terminal_at(execution).isoformat(),
                reason=f"durable execution {execution.state.value}",
            )
        )
    return tuple(transitions)


def _agent_final_state(
    state: DurableExecutionState,
) -> AgentExecutionState:
    if state is DurableExecutionState.COMPLETED:
        return AgentExecutionState.COMPLETED
    if state in {
        DurableExecutionState.FAILED,
        DurableExecutionState.DEAD_LETTERED,
    }:
        return AgentExecutionState.FAILED
    if state is DurableExecutionState.CLAIMED:
        return AgentExecutionState.RUNNING
    return AgentExecutionState.READY


def _is_terminal_execution(execution: ExecutionRecord) -> bool:
    return execution.state in {
        DurableExecutionState.COMPLETED,
        DurableExecutionState.FAILED,
        DurableExecutionState.DEAD_LETTERED,
    }


def _execution_terminal_at(execution: ExecutionRecord) -> datetime:
    if execution.completed_at is not None:
        return execution.completed_at
    if execution.failed_at is not None:
        return execution.failed_at
    if execution.claimed_at is not None:
        return execution.claimed_at
    return execution.requested_at


__all__ = [
    "SessionInspectionEvidence",
    "execution_record_to_agent_replay_record",
    "load_session_inspection_evidence",
]
