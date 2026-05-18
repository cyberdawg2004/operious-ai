"""Constitutional regression tests for Wedge B7 — coordination
singular authority resolution.

The audit defect being closed (DR-4 from
``docs/identity/tenant-propagation-audit.md``): the coordination
runtime coalesced ``request.tenant_id or msg.recipient.tenant_id``
at SIX independent sites (topology subrequest, policy subrequest,
governance subject, governance context, envelope, fail-fast trace)
with the falsy-string bug from Wedge B4 (``""`` silently fell back
to recipient) and zero attribution. Replay reconstruction could
not audit which source produced the effective tenant.

This file pins:

1. ``CoordinationDispatchRequest`` accepts the typed
   ``AuthorityContext`` field (Wedge B2 surface adopted by
   coordination) and enforces the B2 coexistence invariant.

2. Coordination authority resolution is SINGULAR — one resolution
   per dispatch drives Envelope, Trace, and persistence Record.
   No site coalesces tenants independently.

3. The priority is DETERMINISTIC: typed_authority wins, then
   legacy_tenant, then observed_tenant (= recipient tenant), then
   NONE.

4. Empty-string ``tenant_id`` is preserved (NOT silently coalesced
   to recipient tenant) — closes the B4-style falsy-string bug at
   the coordination layer.

5. The envelope, trace, AND persisted record all stamp the same
   ``tenant_authority_source``.

6. The fail-fast path consumes the same resolution as the main
   path — site 6 of 6 is closed.

7. Persistence round-trip: ``CoordinationRecord`` carries
   ``tenant_authority_source`` and ``from_dict`` honours both
   pre-B7 (missing key → None) and post-B7 (explicit value).

8. Static scan: zero ``tenant_id or`` coalescing patterns remain
   in ``app/coordination/runtime/runtime.py``.

Anyone who reintroduces an independent coalescing site, weakens
the priority order, drops the source attribution, or revives the
falsy-string bug fails this file.
"""

from __future__ import annotations

import pathlib
from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.contracts.requests import (
    CoordinationDispatchRequest,
)
from app.coordination.contracts.results import (
    CoordinationDispatchOutcome,
)
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import generate_message_id
from app.coordination.models.participants import (
    CoordinationParticipant,
)
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence.memory import (
    InMemoryCoordinationPersistence,
)
from app.coordination.persistence.records import CoordinationRecord
from app.coordination.persistence.serializers import (
    envelope_to_record,
    record_to_envelope,
)
from app.coordination.registry.registry import CoordinationRegistry
from app.coordination.runtime.runtime import CoordinationRuntime
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import (
    Decision,
    EnforcementStage,
    ViolationSeverity,
)
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.identity import (
    AuthorityContext,
    AuthoritySource,
    TenantId,
)


# ─── Test scaffolding (mirrors test_coordination_runtime.py) ─────────


class _FixedPolicy(BaseGovernancePolicy):
    """Deterministic policy that always emits one fixed verdict."""

    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = (
        frozenset({EnforcementStage.PRE_EXECUTION})
    )

    def __init__(self, name: str, verdict: Decision) -> None:
        self._name = name
        self._verdict = verdict

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self._name,
                rule_id="fixed",
                decision=self._verdict,
                severity=ViolationSeverity.LOW,
                reason="fixed for test",
            ),
        )


def _handler_registry() -> EnforcementHandlerRegistry:
    reg = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        reg.register(handler)
    return reg


def _governance_runtime() -> GovernanceRuntime:
    chain = PolicyChain(
        chain_id="coord.b7.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_FixedPolicy("coord.b7.policy", Decision.ALLOW),),
    )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_handler_registry(),
        chains={EnforcementStage.PRE_EXECUTION: chain},
    )


def _registry() -> CoordinationRegistry:
    reg = CoordinationRegistry()
    reg.register(
        CoordinationParticipant(
            participant_id="agent:retriever", kind="agent"
        )
    )
    reg.register(
        CoordinationParticipant(
            participant_id="agent:planner", kind="agent"
        )
    )
    return reg


def _runtime() -> CoordinationRuntime:
    return CoordinationRuntime(
        governance_runtime=_governance_runtime(),
        persistence=InMemoryCoordinationPersistence(),
        registry=_registry(),
    )


def _message(
    *,
    recipient_tenant: str | None = "recipient-t",
    sender: str = "agent:retriever",
    recipient: str = "agent:planner",
) -> CoordinationMessage:
    return CoordinationMessage(
        message_id=generate_message_id(),
        message_type=CoordinationMessageType.HANDOFF,
        sender_id=sender,
        recipient=CoordinationRecipient(
            recipient_id=recipient,
            kind="agent",
            tenant_id=recipient_tenant,
        ),
        payload=CoordinationPayload(
            content_type="operious/agent-handoff",
            body={"k": "v"},
        ),
        priority=CoordinationPriority.NORMAL,
    )


# ─── Contract: authority + coexistence invariant ─────────────────────


def test_dispatch_request_authority_defaults_to_none() -> None:
    req = CoordinationDispatchRequest(
        message=_message(),
        direction=CoordinationDirection.AGENT_TO_AGENT,
    )
    assert req.authority is None
    assert req.tenant_id is None


def test_dispatch_request_accepts_authority_alone() -> None:
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    req = CoordinationDispatchRequest(
        message=_message(),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        authority=authority,
    )
    assert req.authority is authority


def test_dispatch_request_accepts_agreeing_authority_and_tenant_id() -> (
    None
):
    req = CoordinationDispatchRequest(
        message=_message(),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert req.tenant_id == "acme"
    assert req.authority is not None
    assert req.authority.tenant_id == "acme"


def test_dispatch_request_rejects_disagreeing_authority_and_tenant_id() -> (
    None
):
    with pytest.raises(
        ValueError,
        match="CoordinationDispatchRequest.*must agree",
    ):
        CoordinationDispatchRequest(
            message=_message(),
            direction=CoordinationDirection.AGENT_TO_AGENT,
            tenant_id="acme",
            authority=AuthorityContext(tenant_id=TenantId("beta")),
        )


# ─── Singular resolution at dispatch time ────────────────────────────


@pytest.mark.asyncio
async def test_typed_authority_wins_over_legacy_and_observed() -> (
    None
):
    """When ``authority.tenant_id`` is supplied, it overrides BOTH
    the legacy ``tenant_id`` field (absent here) AND the recipient's
    observed tenant. The result, envelope, and trace stamp
    ``typed_authority`` as the source."""
    runtime = _runtime()
    request = CoordinationDispatchRequest(
        message=_message(recipient_tenant="recipient-t"),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        authority=AuthorityContext(tenant_id=TenantId("typed-t")),
    )
    result = await runtime.dispatch(request)
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED
    assert result.envelope is not None
    env = result.envelope
    assert env.tenant_id == "typed-t"
    assert (
        env.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )
    assert result.trace.tenant_id == "typed-t"
    assert (
        result.trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


@pytest.mark.asyncio
async def test_legacy_tenant_wins_over_observed_when_no_typed() -> (
    None
):
    """Pre-B7 callers (no ``authority``): legacy ``tenant_id`` wins
    over the recipient's tenant. This MATCHES the pre-B7 semantics
    for non-empty strings — replay determinism preserved for every
    legacy caller."""
    runtime = _runtime()
    request = CoordinationDispatchRequest(
        message=_message(recipient_tenant="recipient-t"),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        tenant_id="legacy-t",
    )
    result = await runtime.dispatch(request)
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED
    assert result.envelope is not None
    assert result.envelope.tenant_id == "legacy-t"
    assert (
        result.envelope.tenant_authority_source
        == AuthoritySource.LEGACY_TENANT.value
    )


@pytest.mark.asyncio
async def test_observed_tenant_wins_when_only_recipient_supplied() -> (
    None
):
    """Pre-B7 fallback semantics preserved: with no caller authority,
    the recipient's tenant is the resolved value."""
    runtime = _runtime()
    request = CoordinationDispatchRequest(
        message=_message(recipient_tenant="recipient-t"),
        direction=CoordinationDirection.AGENT_TO_AGENT,
    )
    result = await runtime.dispatch(request)
    assert result.envelope is not None
    assert result.envelope.tenant_id == "recipient-t"
    assert (
        result.envelope.tenant_authority_source
        == AuthoritySource.OBSERVED_TENANT.value
    )


@pytest.mark.asyncio
async def test_none_source_when_all_axes_absent() -> None:
    """Fully tenantless dispatch: source is NONE and tenant is None."""
    runtime = _runtime()
    request = CoordinationDispatchRequest(
        message=_message(recipient_tenant=None),
        direction=CoordinationDirection.AGENT_TO_AGENT,
    )
    result = await runtime.dispatch(request)
    assert result.envelope is not None
    assert result.envelope.tenant_id is None
    assert (
        result.envelope.tenant_authority_source
        == AuthoritySource.NONE.value
    )


# ─── Falsy-string bug closed (B4-doctrine extended to coordination) ──


@pytest.mark.asyncio
async def test_empty_string_legacy_tenant_is_preserved_not_coalesced() -> (
    None
):
    """The pre-B7 code used ``request.tenant_id or msg.recipient.tenant_id``
    — empty string ``""`` is falsy in Python, so callers who passed
    an explicit empty tenant silently fell back to the recipient's
    tenant. Wedge B7 closes this (same constitutional doctrine as
    Wedge B4): ``""`` is a valid distinct legacy tenant value."""
    runtime = _runtime()
    request = CoordinationDispatchRequest(
        message=_message(recipient_tenant="recipient-t"),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        tenant_id="",
    )
    result = await runtime.dispatch(request)
    assert result.envelope is not None
    assert result.envelope.tenant_id == ""
    assert (
        result.envelope.tenant_authority_source
        == AuthoritySource.LEGACY_TENANT.value
    )


# ─── Singularity: envelope and trace share the same resolution ──────


@pytest.mark.asyncio
async def test_envelope_and_trace_share_singular_resolution() -> None:
    """The envelope and the trace must carry the SAME resolved
    tenant_id AND the SAME source. No independent coalescing."""
    runtime = _runtime()
    request = CoordinationDispatchRequest(
        message=_message(recipient_tenant="recipient-t"),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        tenant_id="legacy-t",
    )
    result = await runtime.dispatch(request)
    assert result.envelope is not None
    assert result.envelope.tenant_id == result.trace.tenant_id
    assert (
        result.envelope.tenant_authority_source
        == result.trace.tenant_authority_source
    )


# ─── Fail-fast path consumes the SAME resolution ─────────────────────


@pytest.mark.asyncio
async def test_fail_fast_validation_carries_typed_source() -> None:
    """Unknown-recipient validation failure: the fail-fast trace
    must still stamp the singular resolution (no envelope, but the
    trace records the authority attribution)."""
    runtime = _runtime()
    request = CoordinationDispatchRequest(
        message=_message(
            recipient="agent:nonexistent",
            recipient_tenant="recipient-t",
        ),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        authority=AuthorityContext(tenant_id=TenantId("typed-t")),
    )
    result = await runtime.dispatch(request)
    assert (
        result.outcome is CoordinationDispatchOutcome.VALIDATION_ERROR
    )
    assert result.envelope is None
    assert result.trace.tenant_id == "typed-t"
    assert (
        result.trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


@pytest.mark.asyncio
async def test_fail_fast_validation_carries_observed_source() -> None:
    """Validation fail with only recipient-tenant: fail-fast trace
    falls back to OBSERVED source."""
    runtime = _runtime()
    request = CoordinationDispatchRequest(
        message=_message(
            recipient="agent:nonexistent",
            recipient_tenant="recipient-t",
        ),
        direction=CoordinationDirection.AGENT_TO_AGENT,
    )
    result = await runtime.dispatch(request)
    assert result.envelope is None
    assert result.trace.tenant_id == "recipient-t"
    assert (
        result.trace.tenant_authority_source
        == AuthoritySource.OBSERVED_TENANT.value
    )


# ─── Persistence round-trip ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_persistence_round_trip_preserves_authority_source() -> (
    None
):
    """The persisted CoordinationRecord must carry the authority
    source through ``envelope_to_record`` / ``record_to_envelope``
    AND through ``to_dict`` / ``from_dict``."""
    runtime = _runtime()
    request = CoordinationDispatchRequest(
        message=_message(recipient_tenant="recipient-t"),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        authority=AuthorityContext(tenant_id=TenantId("typed-t")),
    )
    result = await runtime.dispatch(request)
    assert result.envelope is not None
    env = result.envelope

    record = envelope_to_record(env)
    assert (
        record.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )

    wire = record.to_dict()
    assert (
        wire["tenant_authority_source"]
        == AuthoritySource.TYPED_AUTHORITY.value
    )
    reconstructed_record = CoordinationRecord.from_dict(wire)
    assert reconstructed_record == record

    reconstructed_env = record_to_envelope(reconstructed_record)
    assert reconstructed_env.tenant_id == env.tenant_id
    assert (
        reconstructed_env.tenant_authority_source
        == env.tenant_authority_source
    )


def test_persistence_backward_compat_pre_b7_record_missing_key() -> (
    None
):
    """Pre-B7 records (no ``tenant_authority_source`` key) MUST
    deserialize without raising — they recover ``None`` on that axis.
    This pins the constitutional backward-compat contract."""
    pre_b7_wire = {
        "coordination_id": "11111111-1111-1111-1111-111111111111",
        "message_id": "22222222-2222-2222-2222-222222222222",
        "sender_id": "agent:retriever",
        "recipient_id": "agent:planner",
        "recipient_kind": "agent",
        "direction": "agent_to_agent",
        "message_type": "handoff",
        "priority": 50,
        "status": "dispatched",
        "sequence": 1,
        "runtime_instance_id": (
            "33333333-3333-3333-3333-333333333333"
        ),
        "correlation_id": None,
        "parent_coordination_id": None,
        "parent_message_id": None,
        "in_reply_to": None,
        "request_id": None,
        "tenant_id": "acme",
        # NOTE: no tenant_authority_source key.
        "governance_decision_id": None,
        "governance_chain_id": None,
        "payload_content_type": "operious/agent-handoff",
        "payload_schema_version": "1",
        "payload_body": {},
        "created_at": "2025-01-01T00:00:00+00:00",
        "dispatched_at": "2025-01-01T00:00:00+00:00",
        "recipient_metadata": {},
        "payload_metadata": {},
        "message_metadata": {},
        "envelope_metadata": {},
    }
    record = CoordinationRecord.from_dict(pre_b7_wire)
    assert record.tenant_id == "acme"
    assert record.tenant_authority_source is None


# ─── Static doctrine: no `tenant_id or` coalescing remains ──────────


def test_no_or_coalescing_in_coordination_runtime() -> None:
    """Static scan of ``app/coordination/runtime/runtime.py``: every
    audit-flagged ``request.tenant_id or msg.recipient.tenant_id``
    site must be closed. The single remaining match is a doctrine
    comment that quotes the closed pattern verbatim — anything else
    is a B7 regression."""
    runtime_file = (
        pathlib.Path(__file__).parent.parent
        / "app"
        / "coordination"
        / "runtime"
        / "runtime.py"
    )
    text = runtime_file.read_text(encoding="utf-8")
    offenses: list[tuple[int, str]] = []
    for line_num, line in enumerate(
        text.splitlines(), start=1
    ):
        stripped = line.lstrip()
        # Skip doctrine comments (the audit-quoted pattern is allowed
        # as documentation).
        if stripped.startswith("#"):
            continue
        if "tenant_id or msg.recipient.tenant_id" in line:
            offenses.append((line_num, line))
        if (
            "request.tenant_id"
            in line
            and " or " in line
            and "tenant_id" in line
        ):
            # Match the broad pattern: any executable line that
            # combines request.tenant_id with `or`.
            if (
                "request.tenant_id or" in line
                and not stripped.startswith("#")
            ):
                offenses.append((line_num, line))
    assert not offenses, (
        "Audit defect DR-4 regression: coordination runtime "
        "reintroduced ``request.tenant_id or ...`` coalescing at "
        f"lines: {offenses}"
    )


def test_coordination_does_not_import_orchestration_paths() -> None:
    """B7 scope discipline: coordination consumes ``AuthorityContext``
    + ``AuthorityResolution`` + ``resolve_authority`` from
    ``app.identity`` (a leaf substrate). The runtime is coordination-
    internal; B7 must NOT add imports from supervisor / agents /
    arbitration."""
    coord_root = (
        pathlib.Path(__file__).parent.parent / "app" / "coordination"
    )
    forbidden = (
        "app.supervisor.runtime",
        "app.agents.runtime",
        "app.arbitration.runtime",
    )
    for py_file in coord_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for f in forbidden:
            assert f"from {f}" not in text, (
                f"{py_file} imports orchestration runtime {f}; "
                "Wedge B7 must remain coordination-internal"
            )
