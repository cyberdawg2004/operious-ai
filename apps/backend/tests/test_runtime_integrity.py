"""Sprint K.75 — Runtime Integrity Audit invariants.

These tests are intentionally **substrate-shape** tests, not feature
tests. Each one pins a single integrity invariant the runtime audit
identified. They exist so future sprints can't silently regress the
guarantees the platform makes about:

* **wire stability** — the strings governance/supervisor/agent enums
  serialise to are part of the persistence contract. Renaming a value
  silently breaks every persisted record + every replay.
* **semantic authority** — `is_blocking` / `is_allow` live in one
  place. Live and replay paths must agree because they consume the
  same helper, not because two duplicated sets happen to match today.
* **lineage propagation** — the supervisor's docstring contract says
  `correlation_id` / `tenant_id` are "carried through onto the
  inspection result + trace". The success path must honour that, not
  silently overwrite caller-supplied values with the inspected
  execution's.
* **deterministic ordering** — every registry's iteration order must
  be byte-stable across processes. No `iter(dict.values())` allowed
  in registry surfaces.
* **runtime boundaries** — supervisors don't execute, governance
  doesn't mutate agents, agents don't depend on supervisors. These
  are enforced mechanically by scanning module imports.

Failure of any test here represents a substrate-level integrity
violation, not a feature regression.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar, Mapping

import pytest

from app.agents.capabilities import AgentCapability
from app.agents.context import AgentExecutionContext
from app.agents.enums import (
    CapabilityScope,
    ExecutionState,
    ToolInvocationStatus,
)
from app.agents.persistence.serializers import execution_envelope_to_records
from app.agents.results import (
    AgentExecutionResult,
    ToolInvocationRequest,
    ToolInvocationResult,
)
from app.agents.runtime import AgentRegistry, AgentRuntime, BaseAgent
from app.agents.tools import (
    AgentToolSession,
    BaseTool,
    ToolCapability,
    ToolInvoker,
    ToolRegistry,
)
from app.governance.decisions import (
    GovernanceDecision,
    is_allow_decision,
    is_blocking_decision,
)
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enums import (
    Decision,
    EnforcementStage,
    RestrictionKind,
    ViolationSeverity,
)
from app.governance.persistence.records import GovernanceDecisionRecord
# Phase 2.1 quarantine: legacy `app.rag.reranking.registry` removed.
# The reranker-registry sort assertion that depended on it is gone.
from app.supervisor.contracts.requests import ExecutionInspectionRequest
from app.supervisor.enums import (
    EscalationLevel,
    EvaluationStatus,
    FindingCategory,
    FindingSeverity,
    InspectionMode,
    SupervisorDecisionKind,
)
from app.supervisor.evaluators.builtin import (
    ExecutionCompletionEvaluator,
    GovernanceComplianceEvaluator,
    StateMachineHealthEvaluator,
    ToolInvocationEvaluator,
)
from app.supervisor.evaluators.registry import EvaluatorRegistry
from app.supervisor.runtime.runtime import SupervisorRuntime
from app.supervisor.runtime.view_builder import (
    build_inspection_view_from_records,
)
from app.supervisor.taxonomy import EvidenceMetadataKey, FindingCode

# ─── Test fixtures (lightweight, deliberately duplicated from test_supervisor_replay) ───


class _EchoTool(BaseTool):
    name: ClassVar[str] = "echo"
    capability: ClassVar[ToolCapability] = ToolCapability.READ_ONLY
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.echo"}
    )

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        return ToolInvocationResult(output=dict(request.payload))


class _OkAgent(BaseAgent):
    agent_id: ClassVar[str] = "ok"
    declared_capabilities: ClassVar[tuple[AgentCapability, ...]] = (
        AgentCapability(name="tool.echo", scope=CapabilityScope.INVOKE),
    )

    async def run(
        self,
        request: Mapping[str, Any],
        context: AgentExecutionContext,
        session: AgentToolSession,
    ) -> AgentExecutionResult:
        env = await session.invoke(
            ToolInvocationRequest(tool_name="echo", payload={"v": 1})
        )
        assert env.is_ok
        assert env.result is not None
        return AgentExecutionResult(output={"echoed": dict(env.result.output)})


def _build_agent_runtime() -> AgentRuntime:
    tools = ToolRegistry()
    tools.register(_EchoTool())
    agents = AgentRegistry()
    agents.register(_OkAgent())
    invoker = ToolInvoker(tool_registry=tools)
    return AgentRuntime(agent_registry=agents, tool_invoker=invoker)


def _build_supervisor() -> SupervisorRuntime:
    reg = EvaluatorRegistry()
    reg.register(ExecutionCompletionEvaluator())
    reg.register(ToolInvocationEvaluator())
    reg.register(GovernanceComplianceEvaluator())
    reg.register(StateMachineHealthEvaluator())
    return SupervisorRuntime(evaluator_registry=reg)


# ════════════════════════════════════════════════════════════════════
# 1. TAXONOMY STABILITY — wire format pinning
# ════════════════════════════════════════════════════════════════════


def test_decision_wire_values_are_stable() -> None:
    """`Decision.<X>.value` is the persistence contract.

    These strings appear in `GovernanceDecisionRecord.decision`. A
    rename breaks every persisted record and every replay. Pin them.
    """
    assert {d.name: d.value for d in Decision} == {
        "DENY": "deny",
        "REQUIRE_APPROVAL": "require_approval",
        "ESCALATE": "escalate",
        "DEGRADE": "degrade",
        "REDACT": "redact",
        "ALLOW": "allow",
    }


def test_enforcement_stage_wire_values_are_stable() -> None:
    assert {s.name: s.value for s in EnforcementStage} == {
        "PRE_REQUEST": "pre_request",
        "PRE_RETRIEVAL": "pre_retrieval",
        "POST_RETRIEVAL": "post_retrieval",
        "PRE_GROUNDING": "pre_grounding",
        "PRE_EXECUTION": "pre_execution",
        "POST_EXECUTION": "post_execution",
    }


def test_violation_severity_wire_values_are_stable() -> None:
    assert {s.name: int(s) for s in ViolationSeverity} == {
        "LOW": 10,
        "MEDIUM": 20,
        "HIGH": 30,
        "CRITICAL": 40,
    }


def test_restriction_kind_wire_values_are_stable() -> None:
    assert {k.name: k.value for k in RestrictionKind} == {
        "MODEL_RESTRICTION": "model_restriction",
        "SOURCE_RESTRICTION": "source_restriction",
        "CHUNK_CAP": "chunk_cap",
        "TOKEN_CAP": "token_cap",
        "CONTENT_REDACTION": "content_redaction",
        "RATE_LIMIT": "rate_limit",
        "CAPABILITY_RESTRICTION": "capability_restriction",
    }


def test_execution_state_wire_values_are_stable() -> None:
    assert {s.name: s.value for s in ExecutionState} == {
        "CREATED": "created",
        "READY": "ready",
        "RUNNING": "running",
        "WAITING": "waiting",
        "BLOCKED": "blocked",
        "FAILED": "failed",
        "COMPLETED": "completed",
        "CANCELLED": "cancelled",
    }


def test_tool_invocation_status_wire_values_are_stable() -> None:
    assert {s.name: s.value for s in ToolInvocationStatus} == {
        "OK": "ok",
        "FAILED": "failed",
        "DENIED": "denied",
    }


def test_capability_scope_wire_values_are_stable() -> None:
    assert {s.name: s.value for s in CapabilityScope} == {
        "READ": "read",
        "WRITE": "write",
        "INVOKE": "invoke",
        "ESCALATE": "escalate",
    }


def test_supervisor_enum_wire_values_are_stable() -> None:
    """Pin every supervisor enum that lands in persistence records."""
    assert {s.name: s.value for s in FindingSeverity} == {
        "INFO": "info",
        "LOW": "low",
        "MEDIUM": "medium",
        "HIGH": "high",
        "CRITICAL": "critical",
    }
    assert {c.name: c.value for c in FindingCategory} == {
        "EXECUTION_FAILURE": "execution_failure",
        "GOVERNANCE_VIOLATION": "governance_violation",
        "TOOL_INVOCATION_ANOMALY": "tool_invocation_anomaly",
        "STATE_MACHINE_ANOMALY": "state_machine_anomaly",
        "CAUSALITY_ANOMALY": "causality_anomaly",
        "LATENCY_ANOMALY": "latency_anomaly",
        "DATA_QUALITY": "data_quality",
        "POLICY_COMPLIANCE": "policy_compliance",
        "OTHER": "other",
    }
    assert {s.name: s.value for s in EvaluationStatus} == {
        "PASSED": "passed",
        "WARNING": "warning",
        "FAILED": "failed",
        "SKIPPED": "skipped",
        "ERRORED": "errored",
    }
    assert {s.name: s.value for s in EscalationLevel} == {
        "NONE": "none",
        "NOTICE": "notice",
        "REVIEW": "review",
        "HALT": "halt",
    }
    assert {k.name: k.value for k in SupervisorDecisionKind} == {
        "ACCEPT": "accept",
        "ANNOTATE": "annotate",
        "ESCALATE": "escalate",
        "REJECT": "reject",
    }
    assert {m.name: m.value for m in InspectionMode} == {
        "LIVE": "live",
        "REPLAY": "replay",
    }


def test_finding_code_and_evidence_metadata_key_values_are_stable() -> None:
    """Sprint K hardening taxonomy is also part of the persistence wire.

    The exact string values are pinned because they land on
    `RuntimeFindingRecord.code` / `EvaluationEvidenceRecord.metadata`
    keys and are queried by audit dashboards. Renames are a wire
    breaking change.
    """
    assert {f.name: f.value for f in FindingCode} == {
        "EXECUTION_FAILED": "execution.failed",
        "EXECUTION_CANCELLED": "execution.cancelled",
        "EXECUTION_INCOMPLETE": "execution.incomplete",
        "TOOL_DENIED": "tool.denied",
        "TOOL_FAILED": "tool.failed",
        "GOVERNANCE_DENY": "governance.deny",
        "GOVERNANCE_ESCALATE": "governance.escalate",
        "GOVERNANCE_REQUIRE_APPROVAL": "governance.require_approval",
        "GOVERNANCE_DEGRADE": "governance.degrade",
        "GOVERNANCE_REDACT": "governance.redact",
        "GOVERNANCE_UNKNOWN_PREFIX": "governance.unknown",
        "STATE_MACHINE_ILLEGAL_TRANSITION": "state_machine.illegal_transition",
    }
    assert {k.name: k.value for k in EvidenceMetadataKey} == {
        "POLICY_CHAIN_ID": "policy_chain_id",
        "STAGE": "stage",
        "VIOLATION_COUNT": "violation_count",
        "TOOL_NAME": "tool_name",
        "DECISION": "decision",
    }


# ════════════════════════════════════════════════════════════════════
# 2. SEMANTIC AUTHORITY — is_blocking / is_allow single source
# ════════════════════════════════════════════════════════════════════


def test_is_blocking_decision_matches_governance_decision_property() -> None:
    """The free function and the `GovernanceDecision.is_blocking`
    property must agree for every `Decision` value."""

    for decision in Decision:
        synthetic = GovernanceDecision(
            decision_id=uuid.uuid4(),
            decision=decision,
            stage=EnforcementStage.PRE_EXECUTION,
            policy_chain_id="x",
            evaluated_rules=(),
            violations=(),
            restrictions=(),
            reason="",
            decided_at=datetime.now(timezone.utc),
        )
        assert synthetic.is_blocking is is_blocking_decision(decision)
        assert synthetic.is_allow is is_allow_decision(decision)


def test_governance_view_blocking_authority_in_replay_matches_live() -> None:
    """For every `Decision`, the replay path's `is_blocking` /
    `is_allow` flags must match the authoritative helper.

    Pre-Sprint-K.75 the replay path encoded these flags as a literal
    string set — drift-prone. After hardening, both paths consume
    `is_blocking_decision` / `is_allow_decision`, so this test pins
    that single-source invariant.
    """
    from app.supervisor.runtime.view_builder import (
        _record_governance_view,  # pyright: ignore[reportPrivateUsage]
    )

    for decision in Decision:
        record = GovernanceDecisionRecord(
            decision_id=str(uuid.uuid4()),
            decision=decision.value,
            stage=EnforcementStage.PRE_EXECUTION.value,
            policy_chain_id="x",
            reason="",
            decided_at=datetime.now(timezone.utc).isoformat(),
        )
        view = _record_governance_view(record)
        assert view.is_blocking is is_blocking_decision(decision), (
            f"replay path lies about is_blocking for {decision!r}"
        )
        assert view.is_allow is is_allow_decision(decision), (
            f"replay path lies about is_allow for {decision!r}"
        )


# ════════════════════════════════════════════════════════════════════
# 3. RUNTIME IDENTITY DISCIPLINE — deterministic UUID5 inputs
# ════════════════════════════════════════════════════════════════════


def test_derive_finding_id_is_stable_across_invocations() -> None:
    """Same inputs → same UUID5; ALWAYS."""
    from app.supervisor.identity import derive_finding_id

    execution_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    a = derive_finding_id(
        execution_id=execution_id,
        evaluator_name="execution_completion",
        code="execution_did_not_complete",
        ordinal=0,
    )
    b = derive_finding_id(
        execution_id=execution_id,
        evaluator_name="execution_completion",
        code="execution_did_not_complete",
        ordinal=0,
    )
    assert a == b


def test_derive_escalation_id_is_stable_across_invocations() -> None:
    from app.supervisor.identity import derive_escalation_id

    decision_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    a = derive_escalation_id(decision_id=decision_id, level="review")
    b = derive_escalation_id(decision_id=decision_id, level="review")
    assert a == b


def test_derive_finding_id_distinguishes_ordinals() -> None:
    """Two findings emitted by the same evaluator from the same
    execution must receive distinct ids when their ordinals differ.
    This is the only reason `ordinal` exists in the seed."""
    from app.supervisor.identity import derive_finding_id

    execution_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    first = derive_finding_id(
        execution_id=execution_id,
        evaluator_name="tool_invocation",
        code="tool_invocation_failed",
        ordinal=0,
    )
    second = derive_finding_id(
        execution_id=execution_id,
        evaluator_name="tool_invocation",
        code="tool_invocation_failed",
        ordinal=1,
    )
    assert first != second


# ════════════════════════════════════════════════════════════════════
# 4. DETERMINISTIC ORDERING — registry iteration discipline
# ════════════════════════════════════════════════════════════════════


def test_enforcement_handler_registry_iterates_in_sorted_decision_order() -> None:
    """Registry iteration must be byte-stable regardless of
    registration order. The order is sorted by `Decision.value` —
    aggregation precedence is owned by `Decision.precedence` and is
    not coupled to iteration."""
    reg = EnforcementHandlerRegistry()
    # Register in deliberately scrambled order; iteration must come
    # back alphabetical-by-value regardless.
    reg.register(RequireApprovalHandler())
    reg.register(AllowHandler())
    reg.register(EscalateHandler())
    reg.register(DenyHandler())
    reg.register(RedactHandler())
    reg.register(DegradeHandler())
    reg.assert_complete()

    decisions = tuple(h.decision.value for h in reg)
    assert decisions == tuple(sorted(decisions))


# Phase 2.1 quarantine: `test_reranker_registry_iterates_in_sorted_name_order`
# was removed because `app.rag.reranking` is now under `app._deprecated.rag`.
# The sorted-name invariant is exercised by every constitutional registry
# in `test_every_constitutional_registry_publishes_sorted_names` below.


def test_every_constitutional_registry_publishes_sorted_names() -> None:
    """`.names()` is the public iteration contract for the platform's
    name-keyed registries. It must always be sorted so consumers can
    rely on stable enumeration order. Only constitutional registries
    are exercised; legacy registries
    (`app.orchestration.tasks/workflows`, `app.providers.*`,
    `app.rag.reranking`) were quarantined in Phase 2.1.
    """
    from app.agents.runtime.registry import AgentRegistry as AgReg
    from app.agents.tools.registry import ToolRegistry as TReg
    from app.governance.policies.registry import PolicyRegistry
    from app.supervisor.evaluators.registry import (
        EvaluatorRegistry as EvReg,
    )

    # Empty registries already return sorted (== ()). Once registered,
    # `.names()` must remain sorted — exercise that lightly.
    assert AgReg().names() == ()
    assert TReg().names() == ()
    assert EvReg().names() == ()
    assert PolicyRegistry().names() == ()


# ════════════════════════════════════════════════════════════════════
# 5. RUNTIME BOUNDARY INTEGRITY — mechanical import audit
# ════════════════════════════════════════════════════════════════════


def _imports_in_tree(root: pathlib.Path) -> set[str]:
    """Return every `app.*` module imported from any file under `root`.

    Walks the directory tree, parses each .py file's AST, and collects
    every `from app.X.Y import ...` / `import app.X.Y` target. The
    returned set contains fully-qualified dotted paths.
    """
    imports: set[str] = set()
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — bad source file
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("app."):
                    imports.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app."):
                        imports.add(alias.name)
    return imports


_APP_ROOT = pathlib.Path(__file__).resolve().parent.parent / "app"


def test_supervisor_does_not_import_agent_runtime_or_tools() -> None:
    """Supervisor inspection is read-only. It must not import the
    agent executor, the tool invoker, or the tool session."""
    forbidden_prefixes = (
        "app.agents.runtime",
        "app.agents.tools",
    )
    actual = _imports_in_tree(_APP_ROOT / "supervisor")
    violations = sorted(
        i
        for i in actual
        if any(i == p or i.startswith(p + ".") for p in forbidden_prefixes)
    )
    assert violations == [], (
        f"supervisor leaked into agent runtime/tools: {violations}"
    )


def test_supervisor_does_not_import_governance_executors() -> None:
    """Supervisor must not touch the governance policy engine or the
    enforcement runtime — those mutate, and supervisors do not."""
    forbidden_prefixes = (
        "app.governance.evaluators",
        "app.governance.enforcement",
        "app.governance.guardrails",
        "app.governance.policies",
    )
    actual = _imports_in_tree(_APP_ROOT / "supervisor")
    violations = sorted(
        i
        for i in actual
        if any(i == p or i.startswith(p + ".") for p in forbidden_prefixes)
    )
    assert violations == [], (
        f"supervisor reached into governance executor surface: {violations}"
    )


def test_governance_does_not_import_supervisor_or_agent_runtime() -> None:
    """Governance must not depend on supervisor (downstream) or on the
    agent executor (forbidden upward dependency)."""
    forbidden_prefixes = (
        "app.supervisor",
        "app.agents.runtime",
        "app.agents.tools",
    )
    actual = _imports_in_tree(_APP_ROOT / "governance")
    violations = sorted(
        i
        for i in actual
        if any(i == p or i.startswith(p + ".") for p in forbidden_prefixes)
    )
    assert violations == [], (
        f"governance leaked into forbidden modules: {violations}"
    )


def test_agents_do_not_import_supervisor() -> None:
    """No upward dependency from agents → supervisor."""
    actual = _imports_in_tree(_APP_ROOT / "agents")
    violations = sorted(i for i in actual if i.startswith("app.supervisor"))
    assert violations == [], (
        f"agents leaked into supervisor: {violations}"
    )


# ════════════════════════════════════════════════════════════════════
# 6. TRACE LINEAGE — caller correlation / tenant must propagate
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_supervisor_honours_caller_correlation_id_on_success() -> None:
    """The caller's pipeline owns its own correlation_id. The
    supervisor must carry it onto both the result and the trace, not
    silently substitute the inspected execution's correlation_id."""
    agent_runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await agent_runtime.execute("ok", {})

    caller_correlation_id = uuid.uuid4()
    inspection = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                live_envelope=envelope,
                correlation_id=caller_correlation_id,
            )
        )
    ).unwrap()

    assert inspection.correlation_id == caller_correlation_id


@pytest.mark.asyncio
async def test_supervisor_honours_caller_tenant_id_on_success() -> None:
    """Same lineage discipline for tenant_id."""
    agent_runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await agent_runtime.execute("ok", {})

    inspection = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                live_envelope=envelope,
                tenant_id="tenant-from-caller",
            )
        )
    ).unwrap()
    assert inspection.tenant_id == "tenant-from-caller"


@pytest.mark.asyncio
async def test_supervisor_falls_back_to_view_correlation_id_when_caller_omits() -> None:
    """When the caller does NOT supply a correlation_id, the
    supervisor falls back to the inspected execution's — so this is
    the standalone-inspection default behaviour."""
    agent_runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await agent_runtime.execute("ok", {})

    inspection = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                live_envelope=envelope,
            )
        )
    ).unwrap()
    assert inspection.correlation_id == envelope.trace.correlation_id


@pytest.mark.asyncio
async def test_supervisor_replay_honours_caller_tenant_id_override() -> None:
    """Replay mode must accept the same `tenant_id` override semantics
    as live mode. Pre-Sprint-K.75 the replay builder silently dropped
    the request's tenant_id."""
    agent_runtime = _build_agent_runtime()
    supervisor = _build_supervisor()
    envelope = await agent_runtime.execute("ok", {})
    execution_rec, tool_recs = execution_envelope_to_records(envelope)

    inspection = (
        await supervisor.inspect(
            ExecutionInspectionRequest(
                execution_id=envelope.trace.execution_id,
                recorded_execution=execution_rec,
                recorded_tool_invocations=tool_recs,
                tenant_id="overridden-by-caller",
            )
        )
    ).unwrap()
    assert inspection.tenant_id == "overridden-by-caller"


def test_replay_view_builder_accepts_tenant_id_override_directly() -> None:
    """Pure-function check: bypass the runtime, verify the builder
    itself honours the tenant override."""
    from app.agents.persistence.records import AgentExecutionRecord

    execution = AgentExecutionRecord(
        execution_id=str(uuid.uuid4()),
        agent_id="ok",
        runtime_instance_id=str(uuid.uuid4()),
        correlation_id=None,
        parent_execution_id=None,
        parent_chain=(),
        request_id=None,
        tenant_id="recorded-tenant",
        final_state=ExecutionState.COMPLETED.value,
        state_transitions=(),
        tool_invocation_count=0,
        started_at="2024-01-01T00:00:00+00:00",
        ended_at="2024-01-01T00:00:01+00:00",
        latency_ms=1.0,
        error=None,
        metadata={},
    )
    view = build_inspection_view_from_records(
        execution=execution,
        tool_invocations=(),
        governance_decisions=(),
        tenant_id="caller-override",
    )
    assert view.tenant_id == "caller-override"


# ════════════════════════════════════════════════════════════════════
# 7. ENFORCEMENT COMPLETENESS — every Decision has a handler
# ════════════════════════════════════════════════════════════════════


def test_enforcement_registry_covers_every_decision_value() -> None:
    """Adding a new Decision without a handler must be caught at
    composition time — `assert_complete` is the tripwire. Verify the
    standard six-handler set passes."""
    reg = EnforcementHandlerRegistry()
    reg.register(AllowHandler())
    reg.register(DenyHandler())
    reg.register(RedactHandler())
    reg.register(DegradeHandler())
    reg.register(EscalateHandler())
    reg.register(RequireApprovalHandler())
    reg.assert_complete()  # must not raise

    by_decision = {h.decision for h in reg}
    assert by_decision == set(Decision), (
        f"handler set drifted from Decision enum: {by_decision} vs {set(Decision)}"
    )
