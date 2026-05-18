"""Constitutional regression tests for Wedge B5 — unified
fail-closed doctrine across the governance + coordination policy
substrates.

The audit defects being closed
(``docs/identity/tenant-propagation-audit.md``):

* **AP-1 (HIGH)** — ``TenantScopePolicy`` with empty
  ``allowed_tenants`` returned ``Decision.ALLOW`` (fail-open). The
  forensic ``permissive_default=True`` metadata was good audit but
  the SEMANTIC was still fail-open, identical constitutional
  crime to the ``build_decision`` empty-evaluations bug closed by
  Phase 0 Cluster F.
* **AP-3 (HIGH)** — two parallel tenant-policing systems carried
  divergent doctrines for the same constitutional class:
  ``TenantScopePolicy`` was fail-open on empty allowlist while
  ``TenantIsolationEvaluator`` was already fail-closed on missing
  tenant.

This file pins the unified doctrine introduced by Wedge B5:

──────────────────────────────────────────────────────────────────
AUTHORITY POLICIES (gate operations) → fail-closed on every
  indeterminate input.

Class members audited by this file:

  1. ``TenantScopePolicy``
       - empty allowlist            → DENY (``tenant_scope_unconfigured``)
       - missing tenant_id          → DENY (``tenant_missing``)
       - tenant_id not in allowlist → DENY (``tenant_not_allowed``)

  2. ``MaxQueryLengthPolicy``
       - missing/empty query → DENY (``query_missing``)
       - over-long query     → DENY (``query_too_long``)

  3. ``TenantIsolationEvaluator`` (coordination policy substrate)
       - require_tenant=True + no tenant_id → DENY

CONTENT POLICIES (filter/redact content) → permissive on empty
  config is constitutionally legitimate (empty denylist genuinely
  means "nothing to filter"). Class members:

  1. ``ContentDenylistPolicy``
       - empty denylist  → ALLOW (legitimate permissive default)
       - no candidates   → ALLOW
──────────────────────────────────────────────────────────────────

Anyone who:

* reintroduces an ALLOW path on ``TenantScopePolicy`` with empty
  allowlist,
* drops the ``tenant_scope_unconfigured`` rule,
* drops the fail-closed metadata (``policy_class=authority``,
  ``fail_mode=closed``),
* makes ``TenantIsolationEvaluator`` permissive by default,
* makes ``ContentDenylistPolicy`` fail-closed on empty denylist
  (constitutional class confusion),

fails this file.
"""

from __future__ import annotations

import pytest

from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.enums import (
    CoordinationPolicyDecision,
)
from app.coordination.policy.evaluators.builtin.tenant_isolation import (
    TenantIsolationEvaluator,
)
from app.coordination.identity import (
    generate_coordination_id,
    generate_message_id,
)
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.governance.context import GovernanceContext
from app.governance.enums import (
    Decision,
    EnforcementStage,
)
from app.governance.policies.builtin import (
    ContentDenylistPolicy,
    MaxQueryLengthPolicy,
    TenantScopePolicy,
)
from app.governance.subjects.retrieval import (
    CandidateSummary,
    RetrievalGovernanceSubject,
)


# ─── Helpers ────────────────────────────────────────────────────────


def _retrieval_ctx(
    *,
    tenant_id: str | None = None,
    query: str = "ok",
    candidates: tuple[CandidateSummary, ...] = (),
    stage: EnforcementStage = EnforcementStage.PRE_RETRIEVAL,
) -> GovernanceContext:
    return GovernanceContext(
        stage=stage,
        action="rag.assemble_context",
        resource="r",
        tenant_id=tenant_id,
        request_id="b5-test",
        subject=RetrievalGovernanceSubject(
            query=query,
            tenant_id=tenant_id,
            request_id="b5-test",
            retrieval_candidates=candidates,
            candidate_count=len(candidates),
        ),
    )


def _policy_eval_request(
    *,
    tenant_id: str | None = None,
    sender_tenant: str | None = None,
    recipient_tenant: str | None = None,
) -> CoordinationPolicyEvaluationRequest:
    return CoordinationPolicyEvaluationRequest(
        sender_id="agent:s",
        recipient_id="agent:r",
        recipient_kind="agent",
        direction=CoordinationDirection.AGENT_TO_AGENT,
        message_type=CoordinationMessageType.HANDOFF,
        priority=CoordinationPriority.NORMAL,
        coordination_id=generate_coordination_id(),
        coordination_message_id=generate_message_id(),
        tenant_id=tenant_id,
        sender_tenant_id=sender_tenant,
        recipient_tenant_id=recipient_tenant,
    )


# ─── AUTHORITY class — TenantScopePolicy (Wedge B5 AP-1 closure) ────


@pytest.mark.asyncio
async def test_tenant_scope_empty_allowlist_denies() -> None:
    """AP-1 closure: an unconfigured allowlist is an indeterminate
    config, not operator consent. AUTHORITY policies fail closed."""
    results = await TenantScopePolicy().evaluate(
        _retrieval_ctx(tenant_id="anything")
    )
    assert results[0].decision is Decision.DENY
    assert results[0].rule_id == "tenant_scope_unconfigured"


@pytest.mark.asyncio
async def test_tenant_scope_empty_allowlist_denies_even_with_none_tenant() -> (
    None
):
    """The unconfigured-allowlist DENY fires regardless of whether
    the caller supplied a tenant. The policy CANNOT decide without
    an allowlist, and AUTHORITY doctrine forbids guessing."""
    results = await TenantScopePolicy().evaluate(
        _retrieval_ctx(tenant_id=None)
    )
    assert results[0].decision is Decision.DENY
    assert results[0].rule_id == "tenant_scope_unconfigured"


@pytest.mark.asyncio
async def test_tenant_scope_unconfigured_metadata_pins_authority_class() -> (
    None
):
    """The DENY result carries the fail-mode metadata. Audit + replay
    tools can detect the constitutional class without re-running the
    policy."""
    results = await TenantScopePolicy().evaluate(
        _retrieval_ctx(tenant_id="x")
    )
    md = results[0].metadata
    assert md["config_missing"] == "allowed_tenants"
    assert md["fail_mode"] == "closed"
    assert md["policy_class"] == "authority"


@pytest.mark.asyncio
async def test_tenant_scope_no_permissive_default_ever_emitted() -> None:
    """Static doctrine: no ``TenantScopePolicy`` evaluation can carry
    ``permissive_default=True``. The legacy ``open_allowlist`` rule
    was the only producer of that metadata and Wedge B5 removed it.

    Drives every documented input axis and asserts the doctrine."""
    cases = [
        # (allowlist, tenant_id, expected_decision)
        (frozenset(), "acme", Decision.DENY),  # unconfigured
        (frozenset(), None, Decision.DENY),  # unconfigured + no tenant
        (frozenset({"acme"}), None, Decision.DENY),  # missing tenant
        (
            frozenset({"acme"}),
            "globex",
            Decision.DENY,
        ),  # non-allowlisted
        (frozenset({"acme"}), "acme", Decision.ALLOW),  # only ALLOW path
    ]
    for allowlist, tenant_id, expected in cases:
        policy = TenantScopePolicy(allowed_tenants=allowlist)
        results = await policy.evaluate(
            _retrieval_ctx(tenant_id=tenant_id)
        )
        assert results[0].decision is expected
        md = dict(results[0].metadata or {})
        assert "permissive_default" not in md, (
            f"TenantScopePolicy emitted permissive_default for "
            f"(allowlist={allowlist!r}, tenant_id={tenant_id!r})"
            " — Wedge B5 regression"
        )


# ─── AUTHORITY symmetry — MaxQueryLengthPolicy + build_decision ────


@pytest.mark.asyncio
async def test_max_query_length_query_missing_still_fail_closed() -> (
    None
):
    """The Phase 0 Cluster F doctrine survives Wedge B5 unchanged —
    ``MaxQueryLengthPolicy`` continues to DENY on missing query.
    This is the OTHER half of the AUTHORITY-class symmetry."""
    results = await MaxQueryLengthPolicy(max_length=5).evaluate(
        _retrieval_ctx(query="")
    )
    assert results[0].decision is Decision.DENY
    assert results[0].rule_id == "query_missing"


# ─── AUTHORITY class — TenantIsolationEvaluator (coordination) ─────


@pytest.mark.asyncio
async def test_tenant_isolation_require_tenant_denies_missing_tenant() -> (
    None
):
    """``TenantIsolationEvaluator`` is the coordination-substrate
    half of the unified AUTHORITY doctrine. With ``require_tenant=True``
    (the default), missing tenant → DENY. Wedge B5 doesn't modify
    this evaluator; it just pins the unified class."""
    evaluator = TenantIsolationEvaluator(require_tenant=True)
    findings = await evaluator.evaluate(
        _policy_eval_request(tenant_id=None)
    )
    assert len(findings) == 1
    assert findings[0].decision is CoordinationPolicyDecision.DENY


@pytest.mark.asyncio
async def test_tenant_isolation_default_constructor_requires_tenant() -> (
    None
):
    """The default constructor MUST default to ``require_tenant=True``
    — otherwise the coordination half drifts back to fail-open and
    breaks the unified doctrine."""
    evaluator = TenantIsolationEvaluator()
    assert evaluator.require_tenant is True


# ─── CONTENT class — ContentDenylistPolicy stays permissive ────────


@pytest.mark.asyncio
async def test_content_denylist_empty_stays_permissive() -> None:
    """CONTENT-class policies are constitutionally DIFFERENT from
    AUTHORITY-class policies. An empty denylist is "nothing to
    filter" — a legitimate permissive verdict, NOT an indeterminate
    config. Confirming the class boundary holds prevents future
    over-correction that would turn every empty-config into DENY."""
    results = await ContentDenylistPolicy().evaluate(
        _retrieval_ctx(
            stage=EnforcementStage.POST_RETRIEVAL,
            candidates=(
                CandidateSummary(
                    chunk_id="c1",
                    document_id="d1",
                    score=1.0,
                    content="anything",
                ),
            ),
        )
    )
    assert results[0].decision is Decision.ALLOW
    assert results[0].rule_id == "open_denylist"
    assert results[0].metadata.get("permissive_default") is True


# ─── Unified doctrine cross-check ───────────────────────────────────


@pytest.mark.asyncio
async def test_authority_class_unifies_governance_and_coordination() -> (
    None
):
    """End-to-end constitutional check: BOTH the governance AUTHORITY
    policy AND the coordination AUTHORITY evaluator deny when their
    required configuration / input is absent. The unified doctrine
    holds across substrates — the constitutional class is real, not
    coincidental."""
    # Governance side
    gov_results = await TenantScopePolicy().evaluate(
        _retrieval_ctx(tenant_id="x")
    )
    assert gov_results[0].decision is Decision.DENY

    # Coordination side
    coord_findings = await TenantIsolationEvaluator(
        require_tenant=True
    ).evaluate(_policy_eval_request(tenant_id=None))
    assert (
        coord_findings[0].decision
        is CoordinationPolicyDecision.DENY
    )


@pytest.mark.asyncio
async def test_authority_class_deterministic_across_runs() -> None:
    """Same indeterminate input produces byte-identical fail-closed
    output every call — replay determinism preserved."""
    policy = TenantScopePolicy()
    ctx = _retrieval_ctx(tenant_id="x")
    a = await policy.evaluate(ctx)
    b = await policy.evaluate(ctx)
    assert [r.decision for r in a] == [r.decision for r in b]
    assert [r.rule_id for r in a] == [r.rule_id for r in b]
    assert dict(a[0].metadata or {}) == dict(b[0].metadata or {})


def test_no_legacy_open_allowlist_rule_id_in_builtin() -> None:
    """Static doctrine: the legacy ``open_allowlist`` rule_id is
    removed from ``TenantScopePolicy``. Audit-tool source-scans for
    fail-open patterns will catch any future reintroduction."""
    import pathlib

    builtin = (
        pathlib.Path(__file__).parent.parent
        / "app"
        / "governance"
        / "policies"
        / "builtin.py"
    )
    text = builtin.read_text(encoding="utf-8")
    # The legacy rule id was an attribute used by the audit-flagged
    # fail-open path. It must not appear as a string literal that
    # could be emitted at evaluation time.
    assert 'rule_id="open_allowlist"' not in text, (
        "TenantScopePolicy reintroduced the legacy fail-open "
        "rule_id=open_allowlist — Wedge B5 regression"
    )
