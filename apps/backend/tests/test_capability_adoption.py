# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Wedge 2.75-\u03b1 regression tests — capability gate adoption.

The capability legality gate shipped in P2-B
(``evaluate_capability_legality``) but no orchestration runtime
invoked it. Effective RBAC was therefore fail-open. Wedge 2.75-\u03b1
adopts the gate at every P2-A runtime entry via the shared
``gate_or_deny`` helper.

These tests pin the adoption contract on three axes:

1. **Helper semantics** — ``gate_or_deny`` returns ``None`` on
   ALLOW, ``CapabilityDenied`` on DENY, and is inert when no
   ``GovernanceRuntime`` is configured.
2. **Per-runtime adoption** — a representative runtime
   (``SessionRuntime``) folds a DENY verdict into its existing
   fail-fast envelope path without raising.
3. **Static adoption invariant** — every runtime source file that
   declares a capability-governed ``OperationalAct`` also calls
   ``gate_or_deny`` somewhere in that file. Drift here is how
   capability adoption silently regresses.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.governance.capability import (
    CAPABILITY_GOVERNED_ACTS,
    CapabilityDenied,
    CapabilityLegalityRequest,
    OperationalAct,
    evaluate_capability_legality,
    gate_or_deny,
)
from app.governance.context import GovernanceContext
from app.governance.decisions import GovernanceDecision
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import (
    Decision,
    EnforcementStage,
    ViolationSeverity,
)
from app.governance.envelopes import GovernanceEnvelope
from app.governance.exceptions import GovernanceConfigurationError
from app.governance.tracing import GovernanceTrace
from app.identity import (
    AuthorityContext,
    AuthorityResolution,
    AuthoritySource,
    TenantId,
)


def test_gate_or_deny_importable_from_core() -> None:
    from app.core.capability_gate import gate_or_deny as core_gate_or_deny

    assert callable(core_gate_or_deny)


def test_governance_capability_re_export_unchanged() -> None:
    from app.governance.capability import gate_or_deny as governance_gate_or_deny

    assert callable(governance_gate_or_deny)


def test_no_new_circular_imports() -> None:
    for module in (
        "app.core.capability_gate",
        "app.governance.capability",
    ):
        env = {
            **os.environ,
            "PYTHONPATH": str(_BACKEND_APP.parent),
        }
        completed = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr


# ─── Stub governance runtime helpers ─────────────────────────────────


def _stub_trace(
    final_decision: Decision = Decision.ALLOW,
    status: str = "ok",
    error: str | None = None,
) -> GovernanceTrace:
    now = datetime.now(tz=timezone.utc)
    return GovernanceTrace(
        decision_id=uuid.uuid4(),
        request_id=None,
        stage=EnforcementStage.PRE_REQUEST,
        action="session:open",
        resource="",
        actor="test",
        tenant_id="acme",
        started_at=now,
        ended_at=now,
        latency_ms=0.0,
        status=status,  # type: ignore[arg-type]
        final_decision=final_decision,
        policy_chain_id="stub",
        policy_traces=(),
        rule_count=0,
        violation_count=0,
        restriction_count=0,
        error=error,
    )


class _StubAllowRuntime:
    """Behaves like ``GovernanceRuntime`` but always returns ALLOW.

    The gate consumes a ``GovernanceRuntime`` shape; for the
    helper-semantics tests we only need ``evaluate`` to return a
    well-formed envelope. We do not subclass ``GovernanceRuntime``
    because constructing one requires the full chain + handler
    registry; the helper API only depends on the runtime's
    ``evaluate`` method shape.
    """

    async def evaluate(
        self, context: GovernanceContext
    ) -> GovernanceEnvelope:
        decision = GovernanceDecision(
            decision_id=uuid.uuid4(),
            decision=Decision.ALLOW,
            stage=EnforcementStage.PRE_REQUEST,
            policy_chain_id="stub",
            evaluated_rules=(),
            violations=(),
            restrictions=(),
            reason="stub allow",
            decided_at=datetime.now(tz=timezone.utc),
        )
        return GovernanceEnvelope(
            trace=_stub_trace(Decision.ALLOW),
            decision=decision,
        )


class _StubDenyRuntime:
    async def evaluate(
        self, context: GovernanceContext
    ) -> GovernanceEnvelope:
        decision = GovernanceDecision(
            decision_id=uuid.uuid4(),
            decision=Decision.DENY,
            stage=EnforcementStage.PRE_REQUEST,
            policy_chain_id="stub",
            evaluated_rules=(),
            violations=(),
            restrictions=(),
            reason="stub deny",
            decided_at=datetime.now(tz=timezone.utc),
        )
        return GovernanceEnvelope(
            trace=_stub_trace(Decision.DENY),
            decision=decision,
        )


class _StubFailedRuntime:
    """Returns an ``is_ok=False`` envelope (evaluation itself failed).

    The 2.75-\u03b1 doctrine treats this as DENY (fail-closed).
    """

    async def evaluate(
        self, context: GovernanceContext
    ) -> GovernanceEnvelope:
        return GovernanceEnvelope(
            trace=_stub_trace(
                Decision.DENY, status="failed", error="stub failure"
            ),
            decision=None,
            error=GovernanceConfigurationError("stub failure"),
        )


def _resolution(tenant_id: str | None = "acme") -> AuthorityResolution:
    return AuthorityResolution(
        tenant_id=TenantId(tenant_id) if tenant_id is not None else None,
        source=(
            AuthoritySource.TYPED_AUTHORITY
            if tenant_id is not None
            else AuthoritySource.NONE
        ),
    )


# ─── Helper semantics ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_or_deny_returns_none_when_governance_unconfigured() -> None:
    """Inert mode: governance=None ⇒ no gating, no envelope."""
    denial = await gate_or_deny(
        None,
        act=OperationalAct.SESSION_OPEN,
        authority=None,
        resolution=_resolution(),
        actor="test",
    )
    assert denial is None


@pytest.mark.asyncio
async def test_gate_or_deny_returns_none_on_allow_verdict() -> None:
    """ALLOW verdict ⇒ caller proceeds (no denial returned)."""
    denial = await gate_or_deny(
        _StubAllowRuntime(),
        act=OperationalAct.SESSION_OPEN,
        authority=AuthorityContext(
            tenant_id=TenantId("acme"),
            capabilities=frozenset({OperationalAct.SESSION_OPEN.value}),
        ),
        resolution=_resolution(),
        actor="test",
    )
    assert denial is None


@pytest.mark.asyncio
async def test_gate_or_deny_returns_capability_denied_on_deny_verdict() -> None:
    """DENY verdict ⇒ caller folds into fail-fast (denial returned)."""
    denial = await gate_or_deny(
        _StubDenyRuntime(),
        act=OperationalAct.SESSION_OPEN,
        authority=AuthorityContext(tenant_id=TenantId("acme")),
        resolution=_resolution(),
        actor="test",
    )
    assert isinstance(denial, CapabilityDenied)
    assert denial.act is OperationalAct.SESSION_OPEN
    assert denial.envelope.is_ok is True
    assert denial.envelope.decision is not None
    assert denial.envelope.decision.decision is Decision.DENY


@pytest.mark.asyncio
async def test_gate_or_deny_fails_closed_on_governance_evaluation_failure() -> None:
    """Failed evaluation ⇒ DENY (fail-closed doctrine)."""
    denial = await gate_or_deny(
        _StubFailedRuntime(),
        act=OperationalAct.SESSION_OPEN,
        authority=AuthorityContext(tenant_id=TenantId("acme")),
        resolution=_resolution(),
        actor="test",
    )
    assert isinstance(denial, CapabilityDenied)
    assert denial.envelope.is_ok is False


@pytest.mark.asyncio
async def test_gate_or_deny_synthesizes_zero_capability_authority_for_legacy_callers() -> None:
    """When ``authority`` is None, build a context from resolution
    with empty capabilities — fail-closed by doctrine for legacy
    callers that did not present a verified authority context."""
    captured_context: dict[str, GovernanceContext] = {}

    class _Capture:
        async def evaluate(
            self, context: GovernanceContext
        ) -> GovernanceEnvelope:
            captured_context["ctx"] = context
            return await _StubDenyRuntime().evaluate(context)

    denial = await gate_or_deny(
        _Capture(),
        act=OperationalAct.SESSION_OPEN,
        authority=None,
        resolution=_resolution("acme"),
        actor="test",
    )
    assert isinstance(denial, CapabilityDenied)
    # The synthesized capability subject MUST carry the resolved
    # tenant and an empty held-capability set.
    ctx = captured_context["ctx"]
    assert ctx.tenant_id == "acme"
    subject = ctx.subject
    assert subject is not None
    held = getattr(subject, "held_capabilities", None)
    assert held == frozenset()


# ─── Per-runtime adoption (SessionRuntime) ───────────────────────────


@pytest.mark.asyncio
async def test_session_runtime_folds_capability_denial_into_failed_envelope() -> None:
    """SessionRuntime adopts the gate via ``gate_or_deny`` and folds
    the resulting denial into its existing fail-fast envelope."""
    from app.session.contracts.requests import OpenSessionRequest
    from app.session.enums import SessionScope
    from app.session.persistence.memory import (
        InMemorySessionPersistence,
    )
    from app.session.runtime.runtime import SessionRuntime
    from app.session.traces.trace import SessionTraceKind

    runtime = SessionRuntime(
        persistence=InMemorySessionPersistence(),
        governance=_StubDenyRuntime(),
    )
    envelope = await runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="handle-1",
            tenant_id=TenantId("acme"),
            authority=AuthorityContext(tenant_id=TenantId("acme")),
        )
    )
    # Envelope must surface the denial without raising.
    assert envelope.trace.kind is SessionTraceKind.OPEN_SESSION
    assert envelope.result is None
    assert envelope.trace.error is not None


@pytest.mark.asyncio
async def test_session_runtime_proceeds_when_gate_allows() -> None:
    from app.session.contracts.requests import OpenSessionRequest
    from app.session.enums import SessionScope
    from app.session.persistence.memory import (
        InMemorySessionPersistence,
    )
    from app.session.runtime.runtime import SessionRuntime

    runtime = SessionRuntime(
        persistence=InMemorySessionPersistence(),
        governance=_StubAllowRuntime(),
    )
    envelope = await runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="handle-1",
            tenant_id=TenantId("acme"),
            authority=AuthorityContext(
                tenant_id=TenantId("acme"),
                capabilities=frozenset(
                    {OperationalAct.SESSION_OPEN.value}
                ),
            ),
        )
    )
    assert envelope.result is not None
    assert envelope.trace.error is None


# ─── Static adoption invariant ───────────────────────────────────────


_BACKEND_APP = Path(__file__).parent.parent / "app"

# Map every OperationalAct value to the source file we expect the
# gate adoption to live in.
_P2A_ADOPTION_SITES: dict[OperationalAct, Path] = {
    OperationalAct.ARBITRATION_EVALUATE: _BACKEND_APP
    / "arbitration"
    / "runtime"
    / "runtime.py",
    OperationalAct.BOUNDARY_TRANSLATION_INGRESS: _BACKEND_APP
    / "boundary"
    / "translation"
    / "ingress"
    / "runtime.py",
    OperationalAct.BOUNDARY_TRANSLATION_EGRESS: _BACKEND_APP
    / "boundary"
    / "translation"
    / "egress"
    / "runtime.py",
    OperationalAct.BOUNDARY_VOICE_INGRESS: _BACKEND_APP
    / "boundary"
    / "voice"
    / "ingress"
    / "runtime.py",
    OperationalAct.BOUNDARY_VOICE_EGRESS: _BACKEND_APP
    / "boundary"
    / "voice"
    / "egress"
    / "runtime.py",
    OperationalAct.COORDINATION_DISPATCH: _BACKEND_APP
    / "coordination"
    / "runtime"
    / "runtime.py",
    OperationalAct.COORDINATION_POLICY_EVALUATE: _BACKEND_APP
    / "coordination"
    / "policy"
    / "runtime"
    / "runtime.py",
    OperationalAct.COORDINATION_TOPOLOGY_EVALUATE: _BACKEND_APP
    / "coordination"
    / "topology"
    / "runtime"
    / "runtime.py",
    OperationalAct.HARDENING_RECORD_FAILURE: _BACKEND_APP
    / "hardening"
    / "validation"
    / "runtime.py",
    OperationalAct.OI_COMMUNICATION_REGISTER: _BACKEND_APP
    / "organizational_intelligence"
    / "communication"
    / "runtime.py",
    OperationalAct.OI_COMMUNICATION_RETRIEVE: _BACKEND_APP
    / "organizational_intelligence"
    / "communication"
    / "runtime.py",
    OperationalAct.OI_MEMORY_LIST: _BACKEND_APP
    / "organizational_intelligence"
    / "training"
    / "runtime.py",
    OperationalAct.OI_MEMORY_PROPOSE: _BACKEND_APP
    / "organizational_intelligence"
    / "training"
    / "runtime.py",
    OperationalAct.OI_RECOMMENDATION_GENERATE: _BACKEND_APP
    / "organizational_intelligence"
    / "recommendations"
    / "runtime.py",
    OperationalAct.OI_SOP_INGEST: _BACKEND_APP
    / "organizational_intelligence"
    / "sop"
    / "runtime.py",
    OperationalAct.OI_TONALITY_CLASSIFY: _BACKEND_APP
    / "organizational_intelligence"
    / "tonality"
    / "runtime.py",
    OperationalAct.SESSION_OPEN: _BACKEND_APP
    / "session"
    / "runtime"
    / "runtime.py",
    OperationalAct.SUPERVISOR_INSPECT: _BACKEND_APP
    / "supervisor"
    / "runtime"
    / "runtime.py",
}


# The capability gate has two equivalent adoption entry points:
#   * ``gate_or_deny`` — denial-only convenience wrapper.
#   * ``evaluate_capability_gate`` — full outcome with governance
#     provenance (decision_id / chain_id). Used by runtimes whose
#     traces project ``governance_decision_id`` /
#     ``governance_chain_id`` (Wedge 2.75-\u03b4).
_CAPABILITY_GATE_FUNCS = frozenset(
    {"gate_or_deny", "evaluate_capability_gate"}
)


def _calls_gate_or_deny_with_act(
    source: ast.AST, act: OperationalAct
) -> bool:
    """Walk an AST and return True if any capability-gate call
    references ``OperationalAct.<NAME>`` matching ``act``."""
    target_attr = act.name
    found = False

    class _Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            nonlocal found
            func = node.func
            is_gate_call = (
                isinstance(func, ast.Name)
                and func.id in _CAPABILITY_GATE_FUNCS
            ) or (
                isinstance(func, ast.Attribute)
                and func.attr in _CAPABILITY_GATE_FUNCS
            )
            if is_gate_call:
                for kw in node.keywords:
                    if kw.arg == "act" and isinstance(
                        kw.value, ast.Attribute
                    ):
                        if kw.value.attr == target_attr:
                            found = True
                            return
            self.generic_visit(node)

    _Visitor().visit(source)
    return found


@pytest.mark.parametrize("act,path", sorted(_P2A_ADOPTION_SITES.items()))
def test_every_p2a_runtime_adopts_the_capability_gate(
    act: OperationalAct, path: Path
) -> None:
    """Every act in the catalog has a corresponding ``gate_or_deny``
    call in the expected runtime source file. Drift here is how
    capability adoption silently regresses."""
    assert path.exists(), f"adoption site path missing: {path}"
    tree = ast.parse(path.read_text())
    assert _calls_gate_or_deny_with_act(tree, act), (
        f"runtime {path.relative_to(_BACKEND_APP)} does not invoke "
        f"the capability gate "
        f"(gate_or_deny | evaluate_capability_gate)"
        f"(act=OperationalAct.{act.name}, ...). Wedge "
        f"2.75-\u03b1 requires every P2-A runtime entry to consult "
        f"the singular capability legality gate."
    )


def test_capability_gate_adoption_covers_governed_catalog() -> None:
    """The adoption table covers every capability-governed act.

    Phase 2-C separates event ontology from governance scope. A new
    capability-governed act added without an adoption site fails this
    test; projected chronology-only acts do not inflate governance.
    """
    catalog = set(CAPABILITY_GOVERNED_ACTS)
    covered = set(_P2A_ADOPTION_SITES.keys())
    assert catalog == covered, (
        f"CAPABILITY_GOVERNED_ACTS ⇄ adoption-site drift. "
        f"ungated governed acts: {catalog - covered}; "
        f"stale adoption sites: {covered - catalog}"
    )
