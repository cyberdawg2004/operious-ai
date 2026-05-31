"""Tool invoker — single bridge between agent runtime and tool execution.

Every tool call goes through `ToolInvoker.invoke()`. This is the
**only** place that:

* resolves a tool by name,
* verifies capability requirements are satisfied,
* verifies the constraint allow-list permits the tool,
* runs the governance evaluation (mandatory for action-capable tools),
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
`"agent.tool_invocation"`; the resource is the tool name. Read-only
registries may still omit a `GovernanceRuntime`; action-capable tools
require one and execute only on a persisted ALLOW decision.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Final

from app.agents.context import AgentExecutionContext
from app.agents.envelopes import ToolInvocationEnvelope
from app.agents.enums import ToolInvocationStatus
from app.agents.exceptions import (
    CapabilityViolationError,
    ConstraintViolationError,
    ToolConfigurationError,
    ToolNotFoundError,
)
from app.agents.results import ToolInvocationRequest
from app.agents.tools.base import BaseTool
from app.agents.tools.capability import ToolCapability
from app.agents.tools.registry import ToolRegistry
from app.agents.tracing import ToolInvocationTrace
from app.agents.identity import derive_tool_invocation_id
from app.governance.context import GovernanceContext
from app.governance.crisis import publish_crisis_intercept_event
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.envelopes import GovernanceEnvelope
from app.governance.enums import Decision, EnforcementStage
from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
from app.identity import TenantId

#: Metadata key under which the deterministic action binding fingerprint
#: is stamped on every agent-tool governance decision (S-05). The
#: fingerprint covers tenant + tool + action + target resource + payload
#: hash, so a persisted ALLOW decision can only be reused as a
#: ``pre_approved_decision_id`` for the EXACT request it authorised.
AGENT_ACTION_BINDING_KEY: Final[str] = "agent_action_binding"
_AGENT_ACTION: Final[str] = "agent.tool_invocation"
_DEFAULT_PRE_APPROVED_TTL_SECONDS: Final[int] = 3600


class ToolInvoker:
    """Single integration seam: tool registry + governance runtime."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        governance_runtime: GovernanceRuntime | None = None,
        redis_client: Any | None = None,
        pre_approved_decision_ttl_seconds: int = _DEFAULT_PRE_APPROVED_TTL_SECONDS,
    ) -> None:
        action_tool_names = tuple(
            tool.name
            for tool in tool_registry
            if _tool_capability(tool) is not ToolCapability.READ_ONLY
        )
        if action_tool_names and governance_runtime is None:
            raise ToolConfigurationError(
                "governance_runtime is required when action-capable tools "
                f"are registered: {action_tool_names!r}"
            )
        self._tools = tool_registry
        self._governance = governance_runtime
        self._redis_client = redis_client
        self._pre_approved_ttl_seconds = max(1, pre_approved_decision_ttl_seconds)

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
        *,
        invocation_ordinal: int,
        pre_approved_decision_id: str | None = None,
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

        # 4. Governance gate.
        requires_action_governance = (
            _tool_capability(tool) is not ToolCapability.READ_ONLY
        )
        governance_envelope: GovernanceEnvelope | None = None
        governance_decision_id: uuid.UUID | None = None
        if pre_approved_decision_id is not None:
            if self._governance is None:
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=ToolConfigurationError(
                        "governance_runtime is required for pre-approved actions"
                    ),
                    reason="governance_required",
                    governance_envelope=None,
                )
            try:
                governance_decision_id = uuid.UUID(pre_approved_decision_id)
            except ValueError as exc:
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=exc,
                    reason="pre_approved_decision_invalid",
                    governance_envelope=None,
                )
            persisted = await self._governance.get_persisted_decision(
                governance_decision_id,
                expected_tenant_id=context.tenant_id,
            )
            if persisted is None:
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=None,
                    reason="pre_approved_decision_not_found",
                    governance_envelope=None,
                    governance_decision_id=governance_decision_id,
                )
            if persisted.decision != Decision.ALLOW.value:
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=None,
                    reason="pre_approved_decision_not_allow",
                    extra_metadata={
                        "governance_decision": persisted.decision,
                        "governance_reason": persisted.reason,
                    },
                    governance_envelope=None,
                    governance_decision_id=governance_decision_id,
                )
            # S-05: the persisted ALLOW must be BOUND to this exact
            # request. A decision approved for a different tool / target /
            # payload cannot be replayed here.
            expected_binding = compute_agent_action_binding(
                tenant_id=context.tenant_id,
                tool_name=request.tool_name,
                target_resource=_target_resource_for(request),
                payload=request.payload,
            )
            persisted_binding = persisted.metadata.get(AGENT_ACTION_BINDING_KEY)
            if not isinstance(persisted_binding, str) or not hmac.compare_digest(
                persisted_binding, expected_binding
            ):
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=None,
                    reason="pre_approved_decision_binding_mismatch",
                    governance_envelope=None,
                    governance_decision_id=governance_decision_id,
                )
            # Expiry: a stale grant cannot be reused indefinitely.
            if self._pre_approved_decision_expired(persisted.decided_at):
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=None,
                    reason="pre_approved_decision_expired",
                    governance_envelope=None,
                    governance_decision_id=governance_decision_id,
                )
            # One-time consumption (best-effort; enforced when a Redis
            # client is configured). A grant may be redeemed at most once.
            if not await self._claim_pre_approved_decision(
                decision_id=governance_decision_id,
                tenant_id=context.tenant_id,
            ):
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=None,
                    reason="pre_approved_decision_already_consumed",
                    governance_envelope=None,
                    governance_decision_id=governance_decision_id,
                )
        elif self._governance is not None:
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
            if self._redis_client is not None and context.tenant_id is not None:
                await publish_crisis_intercept_event(
                    redis_client=self._redis_client,
                    tenant_id=context.tenant_id,
                    execution_id=str(context.execution.execution_id),
                    decision=decision,
                    category=_metadata_str(request.metadata, "issue_category"),
                )
            if requires_action_governance:
                if decision.decision is not Decision.ALLOW:
                    return self._denied_envelope(
                        invocation_id=invocation_id,
                        request=request,
                        context=context,
                        started_at=started_at,
                        loop_start=loop_start,
                        error=None,
                        reason="governance_not_allow",
                        extra_metadata={
                            "governance_decision": decision.decision.value,
                            "governance_reason": decision.reason,
                        },
                        governance_envelope=governance_envelope,
                        governance_decision_id=governance_decision_id,
                    )
                persisted = await self._governance.get_persisted_decision(
                    decision.decision_id,
                    expected_tenant_id=context.tenant_id,
                )
                if persisted is None or persisted.decision != Decision.ALLOW.value:
                    return self._denied_envelope(
                        invocation_id=invocation_id,
                        request=request,
                        context=context,
                        started_at=started_at,
                        loop_start=loop_start,
                        error=None,
                        reason="governance_decision_not_persisted",
                        extra_metadata={
                            "governance_decision": decision.decision.value,
                            "governance_reason": decision.reason,
                        },
                        governance_envelope=governance_envelope,
                        governance_decision_id=governance_decision_id,
                    )
            elif decision.is_blocking:
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
        elif requires_action_governance:
            return self._denied_envelope(
                invocation_id=invocation_id,
                request=request,
                context=context,
                started_at=started_at,
                loop_start=loop_start,
                error=ToolConfigurationError(
                    "governance_runtime is required for action-capable tools"
                ),
                reason="governance_required",
                governance_envelope=None,
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

    def _pre_approved_decision_expired(self, decided_at: str) -> bool:
        """Return ``True`` when a persisted grant is older than the TTL.

        A malformed / unparseable ``decided_at`` is treated as expired
        (fail-closed) — a grant we cannot date is not safe to honour.
        """
        try:
            decided = datetime.fromisoformat(decided_at)
        except (TypeError, ValueError):
            return True
        if decided.tzinfo is None:
            decided = decided.replace(tzinfo=timezone.utc)
        deadline = decided + timedelta(seconds=self._pre_approved_ttl_seconds)
        return datetime.now(timezone.utc) >= deadline

    async def _claim_pre_approved_decision(
        self,
        *,
        decision_id: uuid.UUID,
        tenant_id: str | None,
    ) -> bool:
        """Atomically claim a one-time grant. ``True`` if not yet used.

        Enforced only when a Redis client is configured; without one,
        binding + expiry remain the active controls and consumption is
        not tracked (the call returns ``True``).
        """
        if self._redis_client is None:
            return True
        key = f"agent:pre_approved_consumed:{tenant_id or ''}:{decision_id}"
        claimed = await self._redis_client.set(
            key, "1", nx=True, ex=self._pre_approved_ttl_seconds
        )
        return bool(claimed)

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
            # S-05: stamp the deterministic action binding so a persisted
            # ALLOW can only be replayed as a pre_approved_decision_id for
            # this exact tenant + tool + target + payload.
            AGENT_ACTION_BINDING_KEY: compute_agent_action_binding(
                tenant_id=context.tenant_id,
                tool_name=request.tool_name,
                target_resource=target_resource,
                payload=request.payload,
            ),
        },
    )


def _target_resource_for(request: ToolInvocationRequest) -> str:
    """Resolve the binding target resource identically at decision time
    and at pre-approval verification time."""
    return str(request.metadata.get("target_resource") or request.tool_name)


def compute_agent_action_binding(
    *,
    tenant_id: str | None,
    tool_name: str,
    target_resource: str,
    payload: Mapping[str, Any],
) -> str:
    """Deterministic fingerprint binding a governance ALLOW to one act.

    Covers tenant + tool + the stable ``agent.tool_invocation`` action +
    target resource + a canonical hash of the payload. Equal inputs →
    equal fingerprint, so a pre-approved decision can be matched to the
    exact request it authorised (S-05).
    """
    payload_canonical = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), default=str
    )
    payload_hash = sha256(payload_canonical.encode("utf-8")).hexdigest()
    signing_input = "|".join(
        [
            tenant_id or "",
            tool_name,
            _AGENT_ACTION,
            target_resource,
            payload_hash,
        ]
    )
    return sha256(signing_input.encode("utf-8")).hexdigest()


def _tool_capability(tool: BaseTool) -> ToolCapability:
    raw = getattr(tool, "capability", ToolCapability.ACTION)
    return raw if isinstance(raw, ToolCapability) else ToolCapability.ACTION


def _metadata_str(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "AGENT_ACTION_BINDING_KEY",
    "ToolInvoker",
    "compute_agent_action_binding",
]
