"""Sprint I — built-in policy contract tests (Sprint I Hardening migration).

Properties pinned (now on typed subjects):

* `TenantScopePolicy` with empty allowlist is FAIL-CLOSED (Wedge B5
  audit defect AP-1): empty allowlist → DENY ``tenant_scope_unconfigured``,
  unifying the AUTHORITY-class doctrine with ``MaxQueryLengthPolicy``,
  ``TenantIsolationEvaluator``, and ``build_decision``.
* `TenantScopePolicy` DENYs missing / non-allowlisted tenants,
* `MaxQueryLengthPolicy` DENYs over-long queries AND DENYs empty query
  (constitutional symmetry with `TenantScopePolicy.tenant_missing`),
* `ContentDenylistPolicy` REDACTs per candidate with a restriction,
* every policy is deterministic across calls,
* every policy supports only its declared stages.

All subject construction is now via typed
`RetrievalGovernanceSubject` — no dictionary access anywhere.
"""

from __future__ import annotations

import pytest

from app.governance.context import GovernanceContext
from app.identity import TenantId
from app.governance.enums import (
    Decision,
    EnforcementStage,
    RestrictionKind,
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


def _ctx(
    *,
    stage: EnforcementStage = EnforcementStage.PRE_RETRIEVAL,
    tenant_id: str | None = None,
    query: str = "",
    candidates: tuple[CandidateSummary, ...] = (),
) -> GovernanceContext:
    return GovernanceContext(
        stage=stage,
        action="rag.assemble_context",
        resource="r",
        tenant_id=TenantId(tenant_id) if tenant_id is not None else None,
        request_id="req-1",
        subject=RetrievalGovernanceSubject(
            query=query,
            tenant_id=tenant_id,
            request_id="req-1",
            retrieval_candidates=candidates,
            candidate_count=len(candidates),
        ),
    )


# ─── TenantScopePolicy ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_scope_empty_allowlist_fail_closes() -> None:
    """Wedge B5 — audit defect AP-1 closed.

    An empty ``allowed_tenants`` set is an INDETERMINATE
    configuration, not operator consent to be permissive. The
    AUTHORITY-class doctrine declared in
    ``app.governance.policies.builtin`` requires DENY on
    indeterminate config. Operators who legitimately do not want
    tenant scoping MUST omit the policy from the chain entirely —
    registering it with no allowlist is a configuration error and
    is now caught at evaluation time.
    """
    policy = TenantScopePolicy()
    results = await policy.evaluate(_ctx(tenant_id="anything"))
    assert len(results) == 1
    assert results[0].decision is Decision.DENY
    assert results[0].rule_id == "tenant_scope_unconfigured"
    assert results[0].metadata["config_missing"] == "allowed_tenants"
    assert results[0].metadata["fail_mode"] == "closed"
    assert results[0].metadata["policy_class"] == "authority"


@pytest.mark.asyncio
async def test_tenant_scope_denies_missing_tenant() -> None:
    policy = TenantScopePolicy(allowed_tenants=frozenset({"acme"}))
    results = await policy.evaluate(_ctx(tenant_id=None))
    assert results[0].decision is Decision.DENY
    assert results[0].rule_id == "tenant_missing"


@pytest.mark.asyncio
async def test_tenant_scope_denies_non_allowlisted_tenant() -> None:
    policy = TenantScopePolicy(allowed_tenants=frozenset({"acme"}))
    results = await policy.evaluate(_ctx(tenant_id="globex"))
    assert results[0].decision is Decision.DENY
    assert results[0].rule_id == "tenant_not_allowed"
    assert results[0].metadata["tenant_id"] == "globex"


@pytest.mark.asyncio
async def test_tenant_scope_allows_allowlisted_tenant() -> None:
    policy = TenantScopePolicy(allowed_tenants=frozenset({"acme"}))
    results = await policy.evaluate(_ctx(tenant_id="acme"))
    assert results[0].decision is Decision.ALLOW


def test_tenant_scope_supports_only_documented_stages() -> None:
    policy = TenantScopePolicy()
    assert policy.supports(EnforcementStage.PRE_RETRIEVAL)
    assert policy.supports(EnforcementStage.PRE_EXECUTION)
    assert policy.supports(EnforcementStage.PRE_REQUEST)
    assert not policy.supports(EnforcementStage.POST_RETRIEVAL)


# ─── MaxQueryLengthPolicy ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_query_length_allows_short_query() -> None:
    policy = MaxQueryLengthPolicy(max_length=10)
    results = await policy.evaluate(_ctx(query="hi"))
    assert results[0].decision is Decision.ALLOW


@pytest.mark.asyncio
async def test_max_query_length_denies_over_long_query() -> None:
    policy = MaxQueryLengthPolicy(max_length=5)
    results = await policy.evaluate(_ctx(query="0123456789"))
    assert results[0].decision is Decision.DENY
    assert results[0].rule_id == "query_too_long"
    assert results[0].metadata["query_length"] == 10
    assert results[0].metadata["max_length"] == 5


@pytest.mark.asyncio
async def test_max_query_length_denies_when_subject_has_empty_query() -> None:
    """Constitutional symmetry with `TenantScopePolicy.tenant_missing`:
    a missing required field on the subject MUST fail closed
    (Core Law 4) — the substrate refuses to bound an unspecified
    query rather than silently allowing it through."""
    policy = MaxQueryLengthPolicy(max_length=5)
    results = await policy.evaluate(_ctx(query=""))
    assert results[0].decision is Decision.DENY
    assert results[0].rule_id == "query_missing"


def test_max_query_length_does_not_support_post_retrieval() -> None:
    assert not MaxQueryLengthPolicy().supports(EnforcementStage.POST_RETRIEVAL)


# ─── ContentDenylistPolicy ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_content_denylist_empty_is_permissive() -> None:
    policy = ContentDenylistPolicy()
    candidates = (
        CandidateSummary(
            chunk_id="c1", document_id="d1", score=0.9, content="anything"
        ),
    )
    results = await policy.evaluate(
        _ctx(stage=EnforcementStage.POST_RETRIEVAL, candidates=candidates)
    )
    assert results[0].decision is Decision.ALLOW


@pytest.mark.asyncio
async def test_content_denylist_redacts_matching_candidates() -> None:
    policy = ContentDenylistPolicy(denylist=("secret", "classified"))
    candidates = (
        CandidateSummary(
            chunk_id="c1", document_id="d1", score=0.9,
            content="this is a secret document"
        ),
        CandidateSummary(
            chunk_id="c2", document_id="d1", score=0.8, content="totally fine"
        ),
        CandidateSummary(
            chunk_id="c3", document_id="d1", score=0.7,
            content="classified material here"
        ),
    )
    results = await policy.evaluate(
        _ctx(stage=EnforcementStage.POST_RETRIEVAL, candidates=candidates)
    )
    redact_results = [r for r in results if r.decision is Decision.REDACT]
    assert len(redact_results) == 2
    chunk_ids = {r.metadata["chunk_id"] for r in redact_results}
    assert chunk_ids == {"c1", "c3"}

    for r in redact_results:
        assert len(r.restrictions) == 1
        restriction = r.restrictions[0]
        assert restriction.kind is RestrictionKind.CONTENT_REDACTION
        assert restriction.target.startswith("chunk_id:")


@pytest.mark.asyncio
async def test_content_denylist_allows_when_no_matches() -> None:
    policy = ContentDenylistPolicy(denylist=("secret",))
    candidates = (
        CandidateSummary(
            chunk_id="c1", document_id="d1", score=0.9, content="totally fine"
        ),
    )
    results = await policy.evaluate(
        _ctx(stage=EnforcementStage.POST_RETRIEVAL, candidates=candidates)
    )
    assert results[0].decision is Decision.ALLOW


# ─── Determinism ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_policies_are_deterministic_across_repeated_calls() -> None:
    tenant = TenantScopePolicy(allowed_tenants=frozenset({"acme"}))
    length = MaxQueryLengthPolicy(max_length=20)
    denylist = ContentDenylistPolicy(denylist=("a",))

    ctx_pre = _ctx(tenant_id="acme", query="hello")
    ctx_post = _ctx(
        stage=EnforcementStage.POST_RETRIEVAL,
        candidates=(
            CandidateSummary(
                chunk_id="c1", document_id="d1", score=0.9, content="abc"
            ),
        ),
    )

    a = await tenant.evaluate(ctx_pre)
    b = await tenant.evaluate(ctx_pre)
    assert [r.decision for r in a] == [r.decision for r in b]

    a = await length.evaluate(ctx_pre)
    b = await length.evaluate(ctx_pre)
    assert [r.decision for r in a] == [r.decision for r in b]

    a = await denylist.evaluate(ctx_post)
    b = await denylist.evaluate(ctx_post)
    assert [r.decision for r in a] == [r.decision for r in b]
