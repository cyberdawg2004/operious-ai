# pyright: reportArgumentType=false
"""P2-B regression tests — singular capability legality gate.

Pins the constitutional invariants the gate exists to enforce:

* operational-act catalog is closed, namespaced, and free of bypass
  tokens;
* gate is the only legitimate construction site for a
  :class:`CapabilityGovernanceSubject` used in legality evaluation;
* :class:`RBACPolicy` is encapsulated — no orchestration substrate
  imports it directly;
* the gate routes every call through the shared
  :class:`GovernanceRuntime` (no short-circuits);
* the gate is a pure builder — identical inputs yield identical
  outputs;
* the gate's verdict is determined entirely by
  ``authority.capabilities`` × ``required_capability`` — no role
  inference, no act-specific branches;
* no orchestration substrate references a bypass/override token.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.governance.capability import (
    CAPABILITY_GOVERNED_ACTS,
    CapabilityLegalityRequest,
    OperationalAct,
    build_capability_context,
    evaluate_capability_legality,
)
from app.governance.enums import Decision, EnforcementStage
from app.governance.subjects.base import SubjectKind
from app.governance.subjects.capability import (
    CapabilityGovernanceSubject,
)
from app.identity.authority import AuthorityContext


# ─── catalog closure ────────────────────────────────────────────────


_ACT_VALUE_RE = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")
_FORBIDDEN_TOKENS = (
    "admin",
    "root",
    "override",
    "bypass",
    "skip_rbac",
    "skiprbac",
    "dev",
    "debug",
    "test",
    "staging",
    "prod",
    "production",
    "internal",
)


def test_every_operational_act_is_namespaced() -> None:
    for act in OperationalAct:
        assert _ACT_VALUE_RE.match(act.value) is not None, (
            f"OperationalAct.{act.name} = {act.value!r} does not "
            f"match <substrate>:<verb> snake_case"
        )


def test_no_act_contains_bypass_or_admin_tokens() -> None:
    for act in OperationalAct:
        for token in _FORBIDDEN_TOKENS:
            assert token not in act.value, (
                f"OperationalAct.{act.name} = {act.value!r} contains "
                f"forbidden token {token!r}; the catalog must not "
                "name bypass-class acts"
            )


def test_act_values_are_unique() -> None:
    values = [a.value for a in OperationalAct]
    assert len(values) == len(set(values)), (
        "Two OperationalAct members share a string value; the "
        "catalog must be a bijection"
    )


def test_act_string_is_used_as_capability_and_action() -> None:
    """The same string is consumed as the governance action AND the
    required capability. Decoupling them is a known drift vector."""
    auth = AuthorityContext(
        tenant_id="acme", capabilities=frozenset({"session:open"})
    )
    req = CapabilityLegalityRequest(
        authority=auth, act=OperationalAct.SESSION_OPEN
    )
    ctx = build_capability_context(req)
    assert isinstance(ctx.subject, CapabilityGovernanceSubject)
    assert ctx.action == OperationalAct.SESSION_OPEN.value
    assert (
        ctx.subject.required_capability
        == OperationalAct.SESSION_OPEN.value
    )


# ─── builder semantics ──────────────────────────────────────────────


def test_builder_copies_held_capabilities_verbatim() -> None:
    held = frozenset({"session:open", "supervisor:inspect"})
    auth = AuthorityContext(tenant_id="acme", capabilities=held)
    req = CapabilityLegalityRequest(
        authority=auth, act=OperationalAct.SESSION_OPEN
    )
    ctx = build_capability_context(req)
    assert isinstance(ctx.subject, CapabilityGovernanceSubject)
    assert ctx.subject.held_capabilities == held


def test_builder_propagates_tenant_id_from_authority() -> None:
    auth = AuthorityContext(
        tenant_id="acme", capabilities=frozenset({"session:open"})
    )
    req = CapabilityLegalityRequest(
        authority=auth, act=OperationalAct.SESSION_OPEN
    )
    ctx = build_capability_context(req)
    assert isinstance(ctx.subject, CapabilityGovernanceSubject)
    assert ctx.tenant_id == "acme"
    assert ctx.subject.tenant_id == "acme"


def test_builder_uses_pre_request_stage() -> None:
    auth = AuthorityContext(
        tenant_id="acme", capabilities=frozenset({"session:open"})
    )
    req = CapabilityLegalityRequest(
        authority=auth, act=OperationalAct.SESSION_OPEN
    )
    ctx = build_capability_context(req)
    assert ctx.stage is EnforcementStage.PRE_REQUEST


def test_builder_subject_kind_is_capability() -> None:
    auth = AuthorityContext(
        tenant_id="acme", capabilities=frozenset({"session:open"})
    )
    req = CapabilityLegalityRequest(
        authority=auth, act=OperationalAct.SESSION_OPEN
    )
    ctx = build_capability_context(req)
    assert ctx.subject.kind is SubjectKind.CAPABILITY


def test_builder_is_deterministic() -> None:
    """Pure builder — identical inputs produce structurally identical
    outputs. Replay-safe."""
    auth = AuthorityContext(
        tenant_id="acme",
        capabilities=frozenset({"session:open", "supervisor:inspect"}),
    )
    req = CapabilityLegalityRequest(
        authority=auth,
        act=OperationalAct.SESSION_OPEN,
        resource="acme/session/handle-1",
        actor="caller",
    )
    a = build_capability_context(req)
    b = build_capability_context(req)
    assert a.subject == b.subject
    assert a.action == b.action
    assert a.resource == b.resource
    assert a.stage == b.stage
    assert a.tenant_id == b.tenant_id


def test_empty_capabilities_yield_deny_via_rbac_policy() -> None:
    """End-to-end: zero held capabilities means every act is denied
    by :class:`RBACPolicy` (fail-closed)."""
    from app.governance.policies.builtin import RBACPolicy
    from app.governance.policies.base import PolicyEvaluationResult

    auth = AuthorityContext(
        tenant_id="acme", capabilities=frozenset()
    )
    ctx = build_capability_context(
        CapabilityLegalityRequest(
            authority=auth, act=OperationalAct.SESSION_OPEN
        )
    )
    import asyncio

    results = asyncio.run(RBACPolicy().evaluate(ctx))
    assert len(results) == 1
    res: PolicyEvaluationResult = results[0]
    assert res.decision is Decision.DENY
    assert res.rule_id == "capability_missing"


def test_present_capability_yields_allow_via_rbac_policy() -> None:
    auth = AuthorityContext(
        tenant_id="acme",
        capabilities=frozenset({OperationalAct.SESSION_OPEN.value}),
    )
    ctx = build_capability_context(
        CapabilityLegalityRequest(
            authority=auth, act=OperationalAct.SESSION_OPEN
        )
    )
    import asyncio

    from app.governance.policies.builtin import RBACPolicy

    results = asyncio.run(RBACPolicy().evaluate(ctx))
    assert len(results) == 1
    assert results[0].decision is Decision.ALLOW
    assert results[0].rule_id == "capability_granted"


# ─── full-runtime invocation ────────────────────────────────────────


def _capability_runtime():
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
    from app.governance.evaluators.engine import (
        PolicyEvaluationEngine,
    )
    from app.governance.policies.builtin import RBACPolicy
    from app.governance.policies.chain import PolicyChain

    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=registry,
        chains={
            EnforcementStage.PRE_REQUEST: PolicyChain(
                chain_id="capability-legality",
                stage=EnforcementStage.PRE_REQUEST,
                policies=(RBACPolicy(),),
            ),
        },
    )


@pytest.mark.asyncio
async def test_gate_routes_through_governance_runtime_for_deny() -> None:
    """The gate calls :meth:`GovernanceRuntime.evaluate` and returns
    the produced envelope — no parallel evaluation path."""
    runtime = _capability_runtime()

    envelope = await evaluate_capability_legality(
        runtime,
        CapabilityLegalityRequest(
            authority=AuthorityContext(
                tenant_id="acme", capabilities=frozenset()
            ),
            act=OperationalAct.SESSION_OPEN,
        ),
    )

    assert envelope.is_ok is True  # runtime succeeded
    assert envelope.decision is not None
    assert envelope.decision.decision is Decision.DENY


@pytest.mark.asyncio
async def test_gate_routes_through_governance_runtime_for_allow() -> None:
    runtime = _capability_runtime()

    envelope = await evaluate_capability_legality(
        runtime,
        CapabilityLegalityRequest(
            authority=AuthorityContext(
                tenant_id="acme",
                capabilities=frozenset(
                    {OperationalAct.SUPERVISOR_INSPECT.value}
                ),
            ),
            act=OperationalAct.SUPERVISOR_INSPECT,
        ),
    )

    assert envelope.is_ok is True
    assert envelope.decision is not None
    assert envelope.decision.decision is Decision.ALLOW


# ─── substrate sealing invariants ───────────────────────────────────


def _repo_app_root() -> Path:
    """Return ``apps/backend/app/``."""
    return Path(__file__).resolve().parents[1] / "app"


def _iter_python_sources(root: Path):
    for path in root.rglob("*.py"):
        # `_deprecated` is constitutionally out of scope.
        if "_deprecated" in path.parts:
            continue
        yield path


def _imports_symbol(source: str, symbol: str) -> bool:
    """True iff ``source`` imports ``symbol`` from anywhere.

    Detects ``from X import Y`` and ``from X import (… Y …)`` while
    ignoring docstring / comment mentions. Implemented via AST so
    quoted occurrences in docstrings are ignored.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == symbol:
                    return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith(f".{symbol}") or alias.name == symbol:
                    return True
    return False


def test_capability_subject_not_imported_outside_governance() -> None:
    """``CapabilityGovernanceSubject`` is encapsulated. Only the
    governance substrate may import it (definition + gate). Any
    orchestration import is a parallel legality semantic."""
    permitted = {
        Path("governance/subjects/capability.py"),
        Path("governance/subjects/__init__.py"),
        Path("governance/capability/gate.py"),
        Path("governance/policies/builtin.py"),
    }
    app_root = _repo_app_root()
    offenders: list[str] = []
    for py in _iter_python_sources(app_root):
        rel = py.relative_to(app_root)
        if rel in permitted:
            continue
        src = py.read_text(encoding="utf-8")
        if _imports_symbol(src, "CapabilityGovernanceSubject"):
            offenders.append(str(rel))
    assert not offenders, (
        "CapabilityGovernanceSubject leaked outside the governance "
        f"substrate: {offenders}"
    )


def test_rbac_policy_not_imported_by_orchestration() -> None:
    """``RBACPolicy`` is encapsulated. Orchestration MUST NOT import
    it directly — capability legality goes through the gate."""
    app_root = _repo_app_root()
    offenders: list[str] = []
    for py in _iter_python_sources(app_root):
        rel = py.relative_to(app_root)
        if rel.parts and rel.parts[0] == "governance":
            continue
        src = py.read_text(encoding="utf-8")
        if _imports_symbol(src, "RBACPolicy"):
            offenders.append(str(rel))
    assert not offenders, (
        "RBACPolicy leaked outside the governance substrate: "
        f"{offenders}"
    )


def test_no_bypass_tokens_in_orchestration() -> None:
    """No orchestration substrate may name a bypass / override
    construct. The aggressive list mirrors :data:`_FORBIDDEN_TOKENS`
    but is scoped to symbol-like patterns (``bypass_rbac``,
    ``skip_capability``, ``admin_override``, etc.)."""
    app_root = _repo_app_root()
    forbidden_patterns = (
        re.compile(r"\bbypass_rbac\b"),
        re.compile(r"\bskip_rbac\b"),
        re.compile(r"\bskip_capability\b"),
        re.compile(r"\badmin_override\b"),
        re.compile(r"\broot_override\b"),
        re.compile(r"\bgrant_all_capabilities\b"),
    )
    offenders: list[tuple[str, str]] = []
    for py in _iter_python_sources(app_root):
        rel = py.relative_to(app_root)
        # The gate sub-package + this test must name the forbidden
        # patterns to enforce them; everything else is forbidden.
        if rel.parts[:2] == ("governance", "capability"):
            continue
        if str(rel).endswith("test_capability_legality_gate.py"):
            continue
        src = py.read_text(encoding="utf-8")
        for pat in forbidden_patterns:
            if pat.search(src):
                offenders.append((str(rel), pat.pattern))
    assert not offenders, (
        f"Bypass-class symbol(s) found in orchestration: {offenders}"
    )


# ─── public surface ────────────────────────────────────────────────


def test_capability_module_public_surface() -> None:
    """``app.governance.capability.__all__`` MUST be exactly the
    documented surface. Drift here grows the gate's API silently.

    2.75-\u03b1 added three symbols: ``CapabilityDenied`` and
    ``gate_or_deny`` (the adoption helper consumed by every P2-A
    runtime entry) plus ``GovernanceRuntime`` re-exported so that
    leaf substrates can take the runtime type as a parameter
    without breaking substrate isolation. 2.75-\u03b4 added two
    more symbols — ``CapabilityGateOutcome`` and
    ``evaluate_capability_gate`` — the provenance-bearing variant
    consumed by runtimes that project governance_decision_id /
    governance_chain_id onto their traces.
    """
    import app.governance.capability as cap

    assert set(cap.__all__) == {
        "CapabilityDenied",
        "CapabilityGateOutcome",
        "CapabilityLegalityRequest",
        "CAPABILITY_GOVERNED_ACTS",
        "GovernanceRuntime",
        "OperationalAct",
        "build_capability_context",
        "evaluate_capability_gate",
        "evaluate_capability_legality",
        "gate_or_deny",
    }


def test_operational_act_catalog_covers_p2a_runtimes() -> None:
    """Every P2-A-migrated runtime has a corresponding act in the
    catalog. Drift here is how runtimes silently develop their own
    legality vocabularies."""
    required = {
        "arbitration:evaluate",
        "boundary_translation:ingress",
        "boundary_translation:egress",
        "boundary_voice:ingress",
        "boundary_voice:egress",
        "coordination:dispatch",
        "coordination_policy:evaluate",
        "coordination_topology:evaluate",
        "hardening:record_failure",
        "oi_communication:register",
        "oi_communication:retrieve",
        "oi_memory:list",
        "oi_memory:propose",
        "oi_recommendation:generate",
        "oi_sop:ingest",
        "oi_tonality:classify",
        "session:open",
        "supervisor:inspect",
    }
    present = {a.value for a in OperationalAct}
    missing = required - present
    assert not missing, (
        f"OperationalAct catalog missing entries for migrated "
        f"runtimes: {sorted(missing)}"
    )


def test_capability_governed_acts_cover_p2a_runtimes() -> None:
    """Capability gates remain bounded to runtime entry acts.

    Event-fabric-only chronology acts may exist in ``OperationalAct``
    without forcing policy expansion or per-event governance checks.
    """
    required = {
        "arbitration:evaluate",
        "boundary_translation:ingress",
        "boundary_translation:egress",
        "boundary_voice:ingress",
        "boundary_voice:egress",
        "coordination:dispatch",
        "coordination_policy:evaluate",
        "coordination_topology:evaluate",
        "hardening:record_failure",
        "oi_communication:register",
        "oi_communication:retrieve",
        "oi_memory:list",
        "oi_memory:propose",
        "oi_recommendation:generate",
        "oi_sop:ingest",
        "oi_tonality:classify",
        "session:open",
        "supervisor:inspect",
    }
    present = {a.value for a in CAPABILITY_GOVERNED_ACTS}
    assert present == required


def test_session_projection_acts_do_not_inflate_capability_governance() -> None:
    projection_only = {
        OperationalAct.SESSION_ATTACH_CONTEXT,
        OperationalAct.SESSION_RECORD_CORRELATION,
        OperationalAct.SESSION_LINK_LINEAGE,
        OperationalAct.SESSION_RECLASSIFY_LIFECYCLE,
        OperationalAct.SESSION_RECORD_DORMANCY,
        OperationalAct.SESSION_RECORD_RESUMPTION,
        OperationalAct.SESSION_RECORD_TERMINATION,
        OperationalAct.SESSION_RECORD_ARCHIVAL,
        OperationalAct.SESSION_OBSERVE_OPERATION,
        OperationalAct.OI_SOP_APPROVAL_PROPOSE,
        OperationalAct.OI_SOP_APPROVAL_APPROVE,
        OperationalAct.OI_SOP_APPROVAL_REJECT,
        OperationalAct.OI_SOP_APPROVAL_APPLY,
    }
    assert projection_only.isdisjoint(CAPABILITY_GOVERNED_ACTS)
