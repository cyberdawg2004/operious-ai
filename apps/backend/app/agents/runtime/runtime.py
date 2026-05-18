"""Agent runtime — apex orchestrator.

One method (`execute`) drives one agent execution end-to-end:

    AgentRuntime.execute(agent_id, request, …)
        → resolve agent
        → build identity + per-execution context
        → drive state machine: CREATED → READY → RUNNING
        → run agent.run(request, context, session)
        → on success: RUNNING → COMPLETED
        → on failure: RUNNING → FAILED
        → fold every tool envelope + governance envelope
        → emit one `AgentExecutionEnvelope`

The runtime is the **single** producer of `AgentExecutionEnvelope`.
It is the only place that:

* threads identity (`runtime_instance_id`, `execution_id`,
  `correlation_id`, `parent_execution_id`),
* drives the state machine,
* records `StateTransition` entries,
* collects lineage from the tool session,
* attributes terminal state.

The runtime NEVER raises. Every failure mode produces an envelope:

* unknown agent       → CREATED → FAILED, error attached
* state-machine error → CREATED/READY → FAILED, error attached
* agent.run() raise   → RUNNING → FAILED, error attached, partial
                         envelopes preserved

Replay invariant: a saved `AgentExecutionEnvelope` is sufficient to
reconstruct the full execution lineage — every state transition,
every tool envelope, every governance decision id, the causality
chain. Combined with deterministic agent implementations, the
substrate is bit-for-bit replayable end-to-end.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from app.agents.capabilities import CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.envelopes import AgentExecutionEnvelope
from app.agents.enums import ExecutionState
from app.agents.exceptions import (
    AgentNotFoundError,
    StateTransitionError,
)
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import AgentExecutionResult
from app.agents.runtime.registry import AgentRegistry
from app.agents.state_machine import assert_transition
from app.agents.tools.invoker import ToolInvoker
from app.agents.tools.session import AgentToolSession
from app.agents.tracing import AgentExecutionTrace
from app.agents.value_objects import CausalityMetadata, StateTransition
from app.observability.context import get_request_id


class AgentRuntime:
    """Apex agent runtime orchestrator. Produces one envelope per call."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        tool_invoker: ToolInvoker,
    ) -> None:
        self._agents = agent_registry
        self._invoker = tool_invoker
        self._instance_id = uuid.uuid4()

    # ─── Inspection ───────────────────────────────────────────────────

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._instance_id

    def known_agents(self) -> tuple[str, ...]:
        return self._agents.names()

    # ─── Public API ───────────────────────────────────────────────────

    async def execute(
        self,
        agent_id: str,
        request: Mapping[str, Any],
        *,
        parent_execution_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        request_id: str | None = None,
        capabilities: CapabilitySet | None = None,
        constraints: ExecutionConstraints | None = None,
        causality: CausalityMetadata | None = None,
        tenant_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentExecutionEnvelope:
        """Run one agent end-to-end. Never raises."""
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()
        execution_id = uuid.uuid4()
        rid = request_id if request_id is not None else get_request_id()

        # 1. Resolve agent (failed lookup → fast-fail envelope).
        try:
            agent = self._agents.get(agent_id)
        except AgentNotFoundError as exc:
            return self._fail_fast_envelope(
                execution_id=execution_id,
                agent_id=agent_id,
                correlation_id=correlation_id,
                parent_execution_id=parent_execution_id,
                request_id=rid,
                tenant_id=tenant_id,
                started_at=started_at,
                loop_start=loop_start,
                error=exc,
                from_state=ExecutionState.CREATED,
            )

        # 2. Build identity + context.
        identity = AgentIdentity(
            agent_id=agent_id,
            runtime_instance_id=self._instance_id,
        )
        execution_identity = ExecutionIdentity(
            execution_id=execution_id,
            correlation_id=correlation_id,
            parent_execution_id=parent_execution_id,
            request_id=rid,
        )
        cap_set = (
            capabilities
            if capabilities is not None
            else CapabilitySet(capabilities=tuple(agent.declared_capabilities))
        )
        ctx_constraints = constraints or ExecutionConstraints()
        ctx_causality = _extend_causality(causality, parent_execution_id)
        context = AgentExecutionContext(
            identity=identity,
            execution=execution_identity,
            capabilities=cap_set,
            constraints=ctx_constraints,
            causality=ctx_causality,
            tenant_id=tenant_id,
            metadata=dict(metadata or {}),
        )

        # 3. Drive the state machine.
        transitions: list[StateTransition] = []
        current = ExecutionState.CREATED
        try:
            current = self._record_transition(
                transitions, current, ExecutionState.READY, "context_built"
            )
            current = self._record_transition(
                transitions, current, ExecutionState.RUNNING, "agent_started"
            )
        except StateTransitionError as exc:
            # Genuinely unreachable for the table the substrate ships
            # — but this is the substrate; we never trust transitions
            # to be free.
            return self._fail_fast_envelope(
                execution_id=execution_id,
                agent_id=agent_id,
                correlation_id=correlation_id,
                parent_execution_id=parent_execution_id,
                request_id=rid,
                tenant_id=tenant_id,
                started_at=started_at,
                loop_start=loop_start,
                error=exc,
                from_state=current,
                transitions=tuple(transitions),
                runtime_instance_id=self._instance_id,
                parent_chain=ctx_causality.parent_chain,
                metadata=dict(metadata or {}),
            )

        # 4. Run the agent.
        session = AgentToolSession(invoker=self._invoker, context=context)
        agent_error: BaseException | None = None
        result: AgentExecutionResult | None = None
        try:
            result = await agent.run(request, context, session)
        except Exception as exc:
            agent_error = exc

        # 5. Final transition.
        if agent_error is None and result is not None:
            current = self._record_transition(
                transitions, current, ExecutionState.COMPLETED, "agent_returned"
            )
        else:
            current = self._record_transition(
                transitions, current, ExecutionState.FAILED, "agent_raised"
            )

        # 6. Build the trace + envelope.
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        tool_envelopes = session.envelopes
        governance_envelopes = tuple(
            e.governance_envelope
            for e in tool_envelopes
            if e.governance_envelope is not None
        )
        governance_decision_ids = tuple(
            e.trace.governance_decision_id
            for e in tool_envelopes
            if e.trace.governance_decision_id is not None
        )
        tool_invocation_ids = tuple(
            e.trace.invocation_id for e in tool_envelopes
        )
        trace = AgentExecutionTrace(
            execution_id=execution_id,
            runtime_instance_id=self._instance_id,
            agent_id=agent_id,
            correlation_id=correlation_id,
            parent_execution_id=parent_execution_id,
            parent_chain=ctx_causality.parent_chain,
            request_id=rid,
            tenant_id=tenant_id,
            state_transitions=tuple(transitions),
            final_state=current,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            tool_invocation_count=len(tool_envelopes),
            tool_invocation_ids=tool_invocation_ids,
            governance_decision_ids=governance_decision_ids,
            error=(
                None
                if agent_error is None
                else f"{type(agent_error).__name__}: {agent_error}"
            ),
            metadata={
                "initiator": ctx_causality.initiator,
                "cause": ctx_causality.cause,
                **(dict(metadata or {})),
            },
        )
        return AgentExecutionEnvelope(
            trace=trace,
            result=result,
            error=agent_error,
            tool_envelopes=tool_envelopes,
            governance_envelopes=governance_envelopes,
        )

    # ─── Internals ────────────────────────────────────────────────────

    def _record_transition(
        self,
        transitions: list[StateTransition],
        current: ExecutionState,
        target: ExecutionState,
        reason: str,
    ) -> ExecutionState:
        assert_transition(current, target)
        transitions.append(
            StateTransition(
                from_state=current,
                to_state=target,
                reason=reason,
            )
        )
        return target

    def _fail_fast_envelope(
        self,
        *,
        execution_id: uuid.UUID,
        agent_id: str,
        correlation_id: uuid.UUID | None,
        parent_execution_id: uuid.UUID | None,
        request_id: str | None,
        tenant_id: str | None,
        started_at: datetime,
        loop_start: float,
        error: BaseException,
        from_state: ExecutionState,
        transitions: tuple[StateTransition, ...] = (),
        runtime_instance_id: uuid.UUID | None = None,
        parent_chain: tuple[uuid.UUID, ...] = (),
        metadata: dict | None = None,
    ) -> AgentExecutionEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        # Synthesize the FAILED transition (always legal from any
        # non-terminal state per the table).
        failed_transitions = list(transitions) + [
            StateTransition(
                from_state=from_state,
                to_state=ExecutionState.FAILED,
                reason="fast_fail",
            )
        ]
        trace = AgentExecutionTrace(
            execution_id=execution_id,
            runtime_instance_id=runtime_instance_id or self._instance_id,
            agent_id=agent_id,
            correlation_id=correlation_id,
            parent_execution_id=parent_execution_id,
            parent_chain=parent_chain,
            request_id=request_id,
            tenant_id=tenant_id,
            state_transitions=tuple(failed_transitions),
            final_state=ExecutionState.FAILED,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            tool_invocation_count=0,
            error=f"{type(error).__name__}: {error}",
            metadata=metadata or {},
        )
        return AgentExecutionEnvelope(trace=trace, error=error)


def _extend_causality(
    causality: CausalityMetadata | None,
    parent_execution_id: uuid.UUID | None,
) -> CausalityMetadata:
    """Return a CausalityMetadata with the parent_chain extended.

    The chain represents the full ancestor lineage. If the caller
    passed a `parent_execution_id` AND a `causality` whose
    `parent_chain` does NOT yet include it, append it. This is the
    foundational "build the lineage" step for sub-execution scenarios
    (Sprint K supervisor-driven multi-agent flows).
    """
    if causality is None:
        if parent_execution_id is None:
            return CausalityMetadata()
        return CausalityMetadata(parent_chain=(parent_execution_id,))
    if parent_execution_id is None:
        return causality
    if parent_execution_id in causality.parent_chain:
        return causality
    extended = causality.parent_chain + (parent_execution_id,)
    return CausalityMetadata(
        initiator=causality.initiator,
        cause=causality.cause,
        parent_chain=extended,
        metadata=dict(causality.metadata),
    )


__all__ = ["AgentRuntime"]
