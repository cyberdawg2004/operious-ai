"""Tool invoker — single bridge between agent runtime and tool execution.

Every tool call goes through `ToolInvoker.invoke()`. This is the
**only** place that:

* resolves a tool by name,
* verifies capability requirements are satisfied,
* verifies the constraint allow-list permits the tool,
* runs the governance evaluation (when a `GovernanceRuntime` is wired),
* invokes the tool,
* records the `ToolInvocationTrace`,
* emits the `ToolInvocationEnvelope`.

Architectural rationale: keeping the bridge in one place means the
agent runtime (`runtime/runtime.py`) is unaware of governance, and
the governance substrate is unaware of tools. Composition lives in
the DI layer.

The invoker NEVER raises — every failure mode lands on a typed
envelope. Internal validation uses typed exceptions
(`CapabilityViolationError`, `ConstraintViolationError`,
`ToolNotFoundError`) for clarity, but they are caught here.

Governance integration uses `AgentActionGovernanceSubject` at the
`PRE_EXECUTION` stage. The action vocabulary is
`"agent.tool_invocation"`; the resource is the tool name. When no
`GovernanceRuntime` is wired the evaluation step is skipped and
`governance_decision_id` on the trace is ``None``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.agents.context import AgentExecutionContext
from app.agents.envelopes import ToolInvocationEnvelope
from app.agents.enums import ToolInvocationStatus
from app.agents.exceptions import (
    CapabilityViolationError,
    ConstraintViolationError,
    ToolNotFoundError,
)
from app.agents.results import ToolInvocationRequest
from app.agents.tools.base import BaseTool
from app.agents.tools.registry import ToolRegistry
from app.agents.tracing import ToolInvocationTrace
from app.agents.identity import derive_tool_invocation_id
from app.governance.context import GovernanceContext
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.envelopes import GovernanceEnvelope
from app.governance.enums import EnforcementStage
from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
from app.identity import TenantId


class ToolInvoker:
    """Single integration seam: tool registry + governance runtime."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        governance_runtime: GovernanceRuntime | None = None,
    ) -> None:
        self._tools = tool_registry
        self._governance = governance_runtime

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
        *,
        invocation_ordinal: int,
    ) -> ToolInvocationEnvelope:
        """Run the full pipeline. Never raises."""
        loop = asyncio.get_event_loop()
        invocation_id = derive_tool_invocation_id(
            execution_id=context.execution.execution_id,
            tool_name=request.tool_name,
            invocation_ordinal=invocation_ordinal,
            payload=request.payload,
            metadata=request.metadata,
        )
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()

        # 1. Resolve tool.
        try:
            tool = self._tools.get(request.tool_name)
        except ToolNotFoundError as exc:
            return self._denied_envelope(
                invocation_id=invocation_id,
                request=request,
                context=context,
                started_at=started_at,
                loop_start=loop_start,
                error=exc,
                reason="tool_not_found",
                governance_envelope=None,
            )

        # 2. Constraint allow-list (cheap, deterministic, no I/O).
        if not context.constraints.permits_tool(request.tool_name):
            return self._denied_envelope(
                invocation_id=invocation_id,
                request=request,
                context=context,
                started_at=started_at,
                loop_start=loop_start,
                error=ConstraintViolationError(
                    f"tool {request.tool_name!r} not in allowed_tools "
                    f"{tuple(context.constraints.allowed_tools)!r}"
                ),
                reason="constraint_blocked",
                governance_envelope=None,
            )

        # 3. Capability requirement.
        missing = context.capabilities.required(tool.required_capabilities)
        if missing:
            return self._denied_envelope(
                invocation_id=invocation_id,
                request=request,
                context=context,
                started_at=started_at,
                loop_start=loop_start,
                error=CapabilityViolationError(
                    f"tool {request.tool_name!r} requires capabilities "
                    f"{tuple(sorted(missing))!r}"
                ),
                reason="capability_violation",
                governance_envelope=None,
            )

        # 4. Governance gate (optional).
        governance_envelope: GovernanceEnvelope | None = None
        governance_decision_id: uuid.UUID | None = None
        if self._governance is not None:
            governance_envelope = await self._governance.evaluate(
                _build_governance_context(request, context, tool)
            )
            if not governance_envelope.is_ok:
                # Governance evaluation itself failed (configuration /
                # handler error). Treat as denied — fail-safe semantics.
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=governance_envelope.error
                    or RuntimeError("governance evaluation failed"),
                    reason="governance_evaluation_failed",
                    governance_envelope=governance_envelope,
                )
            decision = governance_envelope.unwrap()
            governance_decision_id = decision.decision_id
            if decision.is_blocking:
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=None,
                    reason="governance_denied",
                    extra_metadata={
                        "governance_decision": decision.decision.value,
                        "governance_reason": decision.reason,
                    },
                    governance_envelope=governance_envelope,
                    governance_decision_id=governance_decision_id,
                )

        # 5. Invoke the tool.
        try:
            result = await tool.invoke(request, context)
        except Exception as exc:
            ended_at = datetime.now(timezone.utc)
            latency_ms = round((loop.time() - loop_start) * 1000, 2)
            trace = ToolInvocationTrace(
                invocation_id=invocation_id,
                execution_id=context.execution.execution_id,
                tool_name=request.tool_name,
                status=ToolInvocationStatus.FAILED,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                governance_decision_id=governance_decision_id,
                error=f"{type(exc).__name__}: {exc}",
                metadata={"reason": "tool_raised"},
            )
            return ToolInvocationEnvelope(
                trace=trace,
                error=exc,
                governance_envelope=governance_envelope,
            )

        # 6. Success.
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        trace = ToolInvocationTrace(
            invocation_id=invocation_id,
            execution_id=context.execution.execution_id,
            tool_name=request.tool_name,
            status=ToolInvocationStatus.OK,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            governance_decision_id=governance_decision_id,
        )
        return ToolInvocationEnvelope(
            trace=trace,
            result=result,
            governance_envelope=governance_envelope,
        )

    # ─── Internals ────────────────────────────────────────────────────

    def _denied_envelope(
        self,
        *,
        invocation_id: uuid.UUID,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
        started_at: datetime,
        loop_start: float,
        error: BaseException | None,
        reason: str,
        governance_envelope: GovernanceEnvelope | None,
        governance_decision_id: uuid.UUID | None = None,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> ToolInvocationEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        metadata: dict[str, Any] = {"reason": reason}
        if extra_metadata:
            metadata.update(extra_metadata)
        trace = ToolInvocationTrace(
            invocation_id=invocation_id,
            execution_id=context.execution.execution_id,
            tool_name=request.tool_name,
            status=ToolInvocationStatus.DENIED,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            governance_decision_id=governance_decision_id,
            error=(None if error is None else f"{type(error).__name__}: {error}"),
            metadata=metadata,
        )
        return ToolInvocationEnvelope(
            trace=trace,
            error=error,
            governance_envelope=governance_envelope,
        )


def _build_governance_context(
    request: ToolInvocationRequest,
    context: AgentExecutionContext,
    tool: BaseTool,
) -> GovernanceContext:
    """Construct the typed governance context for one tool invocation.

    The action vocabulary is stable (``"agent.tool_invocation"``) so
    governance chains can be wired against tool calls without
    coupling to specific tool names. The resource is the tool name —
    callers can write tool-scoped policies against it.
    """
    capability_str = ",".join(sorted(tool.required_capabilities)) or ""
    target_resource = str(request.metadata.get("target_resource") or request.tool_name)
    subject = AgentActionGovernanceSubject(
        agent_id=context.identity.agent_id,
        capability=capability_str,
        tool_name=request.tool_name,
        target_resource=target_resource,
        execution_scope=(
            f"correlation:{context.execution.correlation_id}"
            if context.execution.correlation_id is not None
            else f"execution:{context.execution.execution_id}"
        ),
        request_id=context.execution.request_id,
        tenant_id=context.tenant_id,
        metadata=dict(request.metadata),
    )
    # Wedge 2.75-γ: project the full authority axis from the typed
    # ``AuthorityContext`` when present. Tool invocation is the
    # finest-grained operational act — dropping principal / org / env
    # here means agent-tool legality decisions are forensically
    # decoupled from the requesting principal.
    authority = context.authority
    return GovernanceContext(
        stage=EnforcementStage.PRE_EXECUTION,
        action="agent.tool_invocation",
        resource=f"tool:{request.tool_name}",
        actor=f"agent:{context.identity.agent_id}",
        # 2.5-F follow-up: ``GovernanceContext.tenant_id`` is now typed
        # as ``TenantId | None``. ``AgentExecutionContext.tenant_id``
        # is still the legacy ``str | None`` shape, so we project
        # through the typed alias here without mutating bytes.
        tenant_id=(
            TenantId(context.tenant_id)
            if context.tenant_id is not None
            else None
        ),
        request_id=context.execution.request_id,
        principal_id=(
            authority.principal_id if authority is not None else None
        ),
        organization_id=(
            authority.organization_id
            if authority is not None
            else None
        ),
        environment_id=(
            authority.environment_id
            if authority is not None
            else None
        ),
        authority=authority,
        subject=subject,
        correlation_id=context.execution.correlation_id,
        metadata={
            "execution_id": str(context.execution.execution_id),
            "runtime_instance_id": str(context.identity.runtime_instance_id),
        },
    )


__all__ = ["ToolInvoker"]
