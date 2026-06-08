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
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.base import BaseTool
from app.agents.tools.capability import ToolCapability
from app.agents.tools.connector_invocations import (
    CONNECTOR_INVOCATION_FAILED,
    CONNECTOR_INVOCATION_SUCCEEDED,
    ConnectorInvocationLedgerError,
    ConnectorInvocationReconciliationRequired,
    ConnectorInvocationRecord,
    ConnectorInvocationRepository,
    ConnectorInvocationStatus,
    connector_result_output,
    derive_auto_allow_provider_idempotency_key,
    hash_connector_request,
)
from app.agents.tools.grants import (
    AGENT_ACTION_ACTOR_KEY,
    AGENT_ACTION_GRANT_ID_KEY,
    AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY,
    ActorMismatchError,
    AgentActionGrantRepository,
    AlreadyConsumedError,
    compute_agent_action_payload_hash,
    compute_agent_execution_actor,
)
from app.agents.tools.registry import ToolRegistry
from app.agents.tracing import ToolInvocationTrace
from app.agents.identity import derive_tool_invocation_id
from app.escalation.celery_publisher import CeleryEscalationPublisher
from app.governance.context import GovernanceContext
from app.governance.crisis import publish_crisis_intercept_event
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.envelopes import GovernanceEnvelope
from app.governance.enums import Decision, EnforcementStage
from app.governance.policies.crisis import crisis_policy_name_from_decision
from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
from app.governance.identity.decision_ids import derive_decision_id
from app.identity import TenantId

#: Metadata key under which the deterministic action binding fingerprint
#: is stamped on every agent-tool governance decision (S-05). The
#: fingerprint covers tenant + tool + action + actor + payload hash, so
#: a persisted ALLOW decision can only be reused as a
#: ``pre_approved_decision_id`` by the EXACT execution actor for the
#: EXACT request it authorised.
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
        grant_repository: AgentActionGrantRepository | None = None,
        connector_invocation_repository: ConnectorInvocationRepository | None = None,
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
        self._grants = grant_repository
        self._connector_invocations = connector_invocation_repository
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
        provider_idempotency_key: str | None = None
        effective_request = request
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
            tenant_id = context.tenant_id
            if tenant_id is None:
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=None,
                    reason="pre_approved_decision_tenant_required",
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
                expected_tenant_id=tenant_id,
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
            actor = compute_agent_execution_actor(context)
            expected_binding = compute_agent_action_binding(
                tenant_id=tenant_id,
                tool_name=request.tool_name,
                actor=actor,
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
            if self._grants is None:
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=ToolConfigurationError(
                        "durable action grant repository is required "
                        "for pre-approved actions"
                    ),
                    reason="pre_approved_decision_grant_repository_required",
                    governance_envelope=None,
                    governance_decision_id=governance_decision_id,
                )
            try:
                grant = await self._grants.consume_grant(
                    decision_id=governance_decision_id,
                    tenant_id=tenant_id,
                    actor=actor,
                )
            except ActorMismatchError as exc:
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=exc,
                    reason="pre_approved_decision_actor_mismatch",
                    extra_metadata={"http_status": 403},
                    governance_envelope=None,
                    governance_decision_id=governance_decision_id,
                )
            except AlreadyConsumedError as exc:
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=exc,
                    reason="pre_approved_decision_already_consumed",
                    governance_envelope=None,
                    governance_decision_id=governance_decision_id,
                )
            if not hmac.compare_digest(grant.binding_hash, expected_binding):
                return self._denied_envelope(
                    invocation_id=invocation_id,
                    request=request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=None,
                    reason="pre_approved_decision_grant_binding_mismatch",
                    governance_envelope=None,
                    governance_decision_id=governance_decision_id,
                )
            provider_idempotency_key = grant.idempotency_key
            await self._cache_pre_approved_decision_claim(
                decision_id=governance_decision_id,
                tenant_id=tenant_id,
            )
            effective_request = ToolInvocationRequest(
                tool_name=request.tool_name,
                payload=request.payload,
                metadata={
                    **dict(request.metadata),
                    AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: provider_idempotency_key,
                    AGENT_ACTION_GRANT_ID_KEY: grant.grant_id,
                },
            )
        elif self._governance is not None:
            governance_context = _build_governance_context(request, context, tool)
            seeded_decision_id = _seeded_governance_decision_id(
                governance_context.metadata
            )
            persisted_replay = None
            if (
                requires_action_governance
                and seeded_decision_id is not None
                and context.tenant_id is not None
            ):
                persisted_replay = await self._governance.get_persisted_decision(
                    seeded_decision_id,
                    expected_tenant_id=context.tenant_id,
                )
            if persisted_replay is not None:
                assert seeded_decision_id is not None
                assert context.tenant_id is not None
                tenant_id = context.tenant_id
                governance_decision_id = seeded_decision_id
                if persisted_replay.decision != Decision.ALLOW.value:
                    return self._denied_envelope(
                        invocation_id=invocation_id,
                        request=request,
                        context=context,
                        started_at=started_at,
                        loop_start=loop_start,
                        error=None,
                        reason="governance_not_allow",
                        extra_metadata={
                            "governance_decision": persisted_replay.decision,
                            "governance_reason": persisted_replay.reason,
                        },
                        governance_envelope=None,
                        governance_decision_id=governance_decision_id,
                    )
                payload_hash = compute_agent_action_payload_hash(request.payload)
                provider_idempotency_key = str(
                    derive_auto_allow_provider_idempotency_key(
                        tenant_id=tenant_id,
                        governance_decision_id=governance_decision_id,
                        payload_hash=payload_hash,
                    )
                )
                effective_request = ToolInvocationRequest(
                    tool_name=request.tool_name,
                    payload=request.payload,
                    metadata={
                        **dict(request.metadata),
                        AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: (
                            provider_idempotency_key
                        ),
                    },
                )
            else:
                try:
                    governance_envelope = await self._governance.evaluate(
                        governance_context
                    )
                except Exception as exc:  # noqa: BLE001 - invoker never raises.
                    return self._denied_envelope(
                        invocation_id=invocation_id,
                        request=request,
                        context=context,
                        started_at=started_at,
                        loop_start=loop_start,
                        error=exc,
                        reason="governance_evaluation_failed",
                        governance_envelope=None,
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
                crisis_policy_name = crisis_policy_name_from_decision(decision)
                if self._redis_client is not None and context.tenant_id is not None:
                    await publish_crisis_intercept_event(
                        redis_client=self._redis_client,
                        tenant_id=context.tenant_id,
                        execution_id=str(context.execution.execution_id),
                        decision=decision,
                        category=_metadata_str(request.metadata, "issue_category"),
                    )
                try:
                    await _publish_crisis_handoff_if_needed(
                        decision=decision,
                        tenant_id=context.tenant_id,
                        session_id=_metadata_str(request.metadata, "session_id"),
                    )
                except Exception as exc:  # noqa: BLE001 - invoker never raises.
                    return self._denied_envelope(
                        invocation_id=invocation_id,
                        request=request,
                        context=context,
                        started_at=started_at,
                        loop_start=loop_start,
                        error=exc,
                        reason="crisis_handoff_publication_failed",
                        governance_envelope=governance_envelope,
                        governance_decision_id=governance_decision_id,
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
                                "crisis_policy": crisis_policy_name,
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
                                "crisis_policy": crisis_policy_name,
                            },
                            governance_envelope=governance_envelope,
                            governance_decision_id=governance_decision_id,
                        )
                    if context.tenant_id is not None:
                        payload_hash = compute_agent_action_payload_hash(
                            request.payload
                        )
                        provider_idempotency_key = str(
                            derive_auto_allow_provider_idempotency_key(
                                tenant_id=context.tenant_id,
                                governance_decision_id=governance_decision_id,
                                payload_hash=payload_hash,
                            )
                        )
                        effective_request = ToolInvocationRequest(
                            tool_name=request.tool_name,
                            payload=request.payload,
                            metadata={
                                **dict(request.metadata),
                                AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: (
                                    provider_idempotency_key
                                ),
                            },
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
                            "crisis_policy": crisis_policy_name,
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

        connector_invocations = self._connector_invocations
        reserved_connector_invocation: ConnectorInvocationRecord | None = None
        if requires_action_governance and connector_invocations is not None:
            if context.tenant_id is None:
                return self._failed_envelope(
                    invocation_id=invocation_id,
                    request=effective_request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=ToolConfigurationError(
                        "tenant_id is required for connector invocation ledger"
                    ),
                    reason="connector_invocation_tenant_required",
                    governance_envelope=governance_envelope,
                    governance_decision_id=governance_decision_id,
                    provider_idempotency_key=provider_idempotency_key,
                )
            if governance_decision_id is None:
                return self._failed_envelope(
                    invocation_id=invocation_id,
                    request=effective_request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=ToolConfigurationError(
                        "governance decision is required for connector invocation ledger"
                    ),
                    reason="connector_invocation_governance_decision_required",
                    governance_envelope=governance_envelope,
                    governance_decision_id=governance_decision_id,
                    provider_idempotency_key=provider_idempotency_key,
                )
            if provider_idempotency_key is None:
                return self._failed_envelope(
                    invocation_id=invocation_id,
                    request=effective_request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=ToolConfigurationError(
                        "provider idempotency key is required for connector invocation ledger"
                    ),
                    reason="connector_invocation_provider_key_required",
                    governance_envelope=governance_envelope,
                    governance_decision_id=governance_decision_id,
                    provider_idempotency_key=provider_idempotency_key,
                )
            try:
                reservation = await connector_invocations.reserve_invocation(
                    tenant_id=context.tenant_id,
                    provider_idempotency_key=provider_idempotency_key,
                    connector_type=effective_request.tool_name,
                    action_type=_connector_action_type(effective_request),
                    target_resource=_connector_target_resource(effective_request),
                    request_hash=hash_connector_request(effective_request.payload),
                    governance_decision_id=governance_decision_id,
                )
            except Exception as exc:  # noqa: BLE001 - invoker never raises.
                return self._failed_envelope(
                    invocation_id=invocation_id,
                    request=effective_request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=exc,
                    reason="connector_invocation_ledger_failed",
                    governance_envelope=governance_envelope,
                    governance_decision_id=governance_decision_id,
                    provider_idempotency_key=provider_idempotency_key,
                )
            if reservation.status == "terminal":
                return self._replayed_connector_envelope(
                    invocation_id=invocation_id,
                    request=effective_request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    governance_envelope=governance_envelope,
                    governance_decision_id=governance_decision_id,
                    record=reservation.record,
                )
            if reservation.status == "pending":
                error = ConnectorInvocationReconciliationRequired(
                    "connector invocation is pending reconciliation"
                )
                return self._failed_envelope(
                    invocation_id=invocation_id,
                    request=effective_request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=error,
                    reason="connector_invocation_reconciliation_required",
                    governance_envelope=governance_envelope,
                    governance_decision_id=governance_decision_id,
                    provider_idempotency_key=provider_idempotency_key,
                )
            reserved_connector_invocation = reservation.record

        # 5. Invoke the tool.
        try:
            result = await tool.invoke(effective_request, context)
        except Exception as exc:
            if (
                reserved_connector_invocation is not None
                and connector_invocations is not None
            ):
                try:
                    await connector_invocations.complete_invocation(
                        tenant_id=reserved_connector_invocation.tenant_id,
                        provider_idempotency_key=(
                            reserved_connector_invocation.provider_idempotency_key
                        ),
                        status=CONNECTOR_INVOCATION_FAILED,
                        provider_id=None,
                        provider_status="tool_raised",
                        provider_error=f"{type(exc).__name__}: {exc}",
                    )
                except Exception:
                    pass
            ended_at = datetime.now(timezone.utc)
            latency_ms = round((loop.time() - loop_start) * 1000, 2)
            trace = ToolInvocationTrace(
                invocation_id=invocation_id,
                execution_id=context.execution.execution_id,
                tool_name=effective_request.tool_name,
                status=ToolInvocationStatus.FAILED,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                governance_decision_id=governance_decision_id,
                error=f"{type(exc).__name__}: {exc}",
                metadata=_tool_trace_metadata(
                    reason="tool_raised",
                    provider_idempotency_key=provider_idempotency_key,
                ),
            )
            return ToolInvocationEnvelope(
                trace=trace,
                error=exc,
                governance_envelope=governance_envelope,
                provider_idempotency_key=provider_idempotency_key,
            )

        # 6. Success.
        if (
            reserved_connector_invocation is not None
            and connector_invocations is not None
        ):
            completion_status = _connector_completion_status(result)
            try:
                await connector_invocations.complete_invocation(
                    tenant_id=reserved_connector_invocation.tenant_id,
                    provider_idempotency_key=(
                        reserved_connector_invocation.provider_idempotency_key
                    ),
                    status=completion_status,
                    provider_id=_connector_result_text(result, "provider_id"),
                    provider_status=_connector_provider_status(result),
                    provider_error=_connector_provider_error(result),
                )
            except ConnectorInvocationLedgerError as exc:
                return self._failed_envelope(
                    invocation_id=invocation_id,
                    request=effective_request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=exc,
                    reason="connector_invocation_terminal_update_failed",
                    governance_envelope=governance_envelope,
                    governance_decision_id=governance_decision_id,
                    provider_idempotency_key=provider_idempotency_key,
                )
            except Exception as exc:  # noqa: BLE001 - invoker never raises.
                return self._failed_envelope(
                    invocation_id=invocation_id,
                    request=effective_request,
                    context=context,
                    started_at=started_at,
                    loop_start=loop_start,
                    error=exc,
                    reason="connector_invocation_terminal_update_failed",
                    governance_envelope=governance_envelope,
                    governance_decision_id=governance_decision_id,
                    provider_idempotency_key=provider_idempotency_key,
                )
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        trace = ToolInvocationTrace(
            invocation_id=invocation_id,
            execution_id=context.execution.execution_id,
            tool_name=effective_request.tool_name,
            status=ToolInvocationStatus.OK,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            governance_decision_id=governance_decision_id,
            metadata=_tool_trace_metadata(
                provider_idempotency_key=provider_idempotency_key,
            ),
        )
        return ToolInvocationEnvelope(
            trace=trace,
            result=result,
            governance_envelope=governance_envelope,
            provider_idempotency_key=provider_idempotency_key,
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

    async def _cache_pre_approved_decision_claim(
        self,
        *,
        decision_id: uuid.UUID,
        tenant_id: str | None,
    ) -> None:
        """Best-effort Redis marker; Postgres is the source of truth."""
        if self._redis_client is None:
            return
        key = f"agent:pre_approved_consumed:{tenant_id or ''}:{decision_id}"
        try:
            await self._redis_client.set(
                key, "1", nx=True, ex=self._pre_approved_ttl_seconds
            )
        except Exception:
            return

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

    def _failed_envelope(
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
        provider_idempotency_key: str | None = None,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> ToolInvocationEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        metadata = _tool_trace_metadata(
            reason=reason,
            provider_idempotency_key=provider_idempotency_key,
        )
        if extra_metadata:
            metadata.update(extra_metadata)
        trace = ToolInvocationTrace(
            invocation_id=invocation_id,
            execution_id=context.execution.execution_id,
            tool_name=request.tool_name,
            status=ToolInvocationStatus.FAILED,
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
            provider_idempotency_key=provider_idempotency_key,
        )

    def _replayed_connector_envelope(
        self,
        *,
        invocation_id: uuid.UUID,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
        started_at: datetime,
        loop_start: float,
        governance_envelope: GovernanceEnvelope | None,
        governance_decision_id: uuid.UUID | None,
        record: ConnectorInvocationRecord,
    ) -> ToolInvocationEnvelope:
        if record.status == CONNECTOR_INVOCATION_FAILED:
            error = ConnectorInvocationLedgerError(
                record.provider_error or "connector invocation previously failed"
            )
            return self._failed_envelope(
                invocation_id=invocation_id,
                request=request,
                context=context,
                started_at=started_at,
                loop_start=loop_start,
                error=error,
                reason="connector_invocation_terminal_replay",
                governance_envelope=governance_envelope,
                governance_decision_id=governance_decision_id,
                provider_idempotency_key=record.provider_idempotency_key,
                extra_metadata={
                    "provider_status": record.provider_status,
                    "replayed": True,
                },
            )

        loop = asyncio.get_event_loop()
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
            metadata=_tool_trace_metadata(
                reason="connector_invocation_terminal_replay",
                provider_idempotency_key=record.provider_idempotency_key,
            ),
        )
        return ToolInvocationEnvelope(
            trace=trace,
            result=ToolInvocationResult(
                output=connector_result_output(record),
                metadata={"replayed": True},
                status="success",
                idempotency_key=record.provider_idempotency_key,
            ),
            governance_envelope=governance_envelope,
            provider_idempotency_key=record.provider_idempotency_key,
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
    action_actor = compute_agent_execution_actor(context)
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
    metadata: dict[str, Any] = {
        "execution_id": str(context.execution.execution_id),
        "runtime_instance_id": str(context.identity.runtime_instance_id),
        # S-05: stamp the deterministic action binding so a persisted
        # ALLOW can only be replayed as a pre_approved_decision_id for
        # this exact tenant + tool + actor + payload.
        AGENT_ACTION_ACTOR_KEY: action_actor,
        AGENT_ACTION_BINDING_KEY: compute_agent_action_binding(
            tenant_id=context.tenant_id,
            tool_name=request.tool_name,
            actor=action_actor,
            payload=request.payload,
        ),
    }
    if _tool_capability(tool) is not ToolCapability.READ_ONLY:
        metadata["governance.decision_seed"] = _action_governance_decision_seed(
            request=request,
            context=context,
            target_resource=target_resource,
            action_actor=action_actor,
        )

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
        metadata=metadata,
    )


def compute_agent_action_binding(
    *,
    tenant_id: str | None,
    tool_name: str,
    actor: str,
    payload: Mapping[str, Any],
) -> str:
    """Deterministic fingerprint binding a governance ALLOW to one act.

    Covers tenant + tool + the stable ``agent.tool_invocation`` action +
    execution actor + a canonical hash of the payload. Equal inputs →
    equal fingerprint, so a pre-approved decision can be matched to the
    exact actor and request it authorised (S-05).
    """
    payload_hash = compute_agent_action_payload_hash(payload)
    signing_input = "|".join(
        [
            tenant_id or "",
            tool_name,
            _AGENT_ACTION,
            actor,
            payload_hash,
        ]
    )
    return sha256(signing_input.encode("utf-8")).hexdigest()


def _tool_trace_metadata(
    *,
    provider_idempotency_key: str | None,
    reason: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if reason is not None:
        metadata["reason"] = reason
    if provider_idempotency_key is not None:
        metadata[AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY] = (
            provider_idempotency_key
        )
    return metadata


def _tool_capability(tool: BaseTool) -> ToolCapability:
    raw = getattr(tool, "capability", ToolCapability.ACTION)
    return raw if isinstance(raw, ToolCapability) else ToolCapability.ACTION


def _metadata_str(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def _publish_crisis_handoff_if_needed(
    *,
    decision: Any,
    tenant_id: str | None,
    session_id: str | None,
) -> bool:
    if tenant_id is None or session_id is None:
        return False
    if crisis_policy_name_from_decision(decision) is None:
        return False
    publisher = CeleryEscalationPublisher()
    if decision.decision is Decision.DENY:
        await publisher.publish_governance_denial(
            governance_decision_id=str(decision.decision_id),
            tenant_id=tenant_id,
            session_id=session_id,
        )
        return True
    if decision.decision is Decision.ESCALATE:
        await publisher.publish_governance_escalation(
            governance_decision_id=str(decision.decision_id),
            tenant_id=tenant_id,
            session_id=session_id,
        )
        return True
    return False


def _seeded_governance_decision_id(
    metadata: Mapping[str, Any],
) -> uuid.UUID | None:
    seed = metadata.get("governance.decision_seed")
    if not isinstance(seed, str) or not seed.strip():
        return None
    return derive_decision_id(seed=seed)


def _action_governance_decision_seed(
    *,
    request: ToolInvocationRequest,
    context: AgentExecutionContext,
    target_resource: str,
    action_actor: str,
) -> str:
    payload_hash = compute_agent_action_payload_hash(request.payload)
    return "|".join(
        [
            _AGENT_ACTION,
            context.tenant_id or "",
            str(context.execution.execution_id),
            str(context.execution.request_id or ""),
            request.tool_name,
            target_resource,
            action_actor,
            payload_hash,
        ]
    )


def _connector_action_type(request: ToolInvocationRequest) -> str:
    return (
        _metadata_str(request.metadata, "action_type")
        or _metadata_str(request.metadata, "tool_name")
        or request.tool_name
    )


def _connector_target_resource(request: ToolInvocationRequest) -> str:
    return (
        _metadata_str(request.metadata, "target_resource")
        or _metadata_str(request.metadata, "target_resource_id")
        or _metadata_str(request.metadata, "idempotency_key")
        or request.tool_name
    )


def _connector_completion_status(
    result: ToolInvocationResult,
) -> ConnectorInvocationStatus:
    status = _normalized_text(result.status)
    if status in {"error", "failed", "failure"}:
        return CONNECTOR_INVOCATION_FAILED
    output_status = _normalized_mapping_text(result.output, "status")
    if output_status in {"error", "failed", "failure"}:
        return CONNECTOR_INVOCATION_FAILED
    if result.error_code is not None or result.error_message is not None:
        return CONNECTOR_INVOCATION_FAILED
    return CONNECTOR_INVOCATION_SUCCEEDED


def _connector_provider_status(result: ToolInvocationResult) -> str | None:
    return (
        _connector_result_text(result, "provider_status")
        or _connector_result_text(result, "status")
        or _clean_text(result.status)
    )


def _connector_provider_error(result: ToolInvocationResult) -> str | None:
    return (
        _clean_text(result.error_message)
        or _connector_result_text(result, "provider_error")
        or _clean_text(result.error_code)
    )


def _connector_result_text(
    result: ToolInvocationResult,
    key: str,
) -> str | None:
    output_value = result.output.get(key)
    if isinstance(output_value, str) and output_value.strip():
        return output_value.strip()
    metadata_value = result.metadata.get(key)
    if isinstance(metadata_value, str) and metadata_value.strip():
        return metadata_value.strip()
    return None


def _normalized_mapping_text(
    values: Mapping[str, Any],
    key: str,
) -> str | None:
    value = values.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def _normalized_text(value: str | None) -> str | None:
    clean = _clean_text(value)
    return clean.lower() if clean is not None else None


def _clean_text(value: str | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "AGENT_ACTION_BINDING_KEY",
    "ToolInvoker",
    "compute_agent_action_binding",
    "compute_agent_execution_actor",
]
