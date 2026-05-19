"""PR-B2 tenant-scope invariants for governance persistence.

Storage-agnostic tests that pin the tenant-scoping contract
introduced in PR-B2 (M8 closure). Every backend that satisfies
``BaseGovernanceRepository`` MUST honour the same observable
semantics — the Postgres integration counterpart in
``test_governance_persistence_postgres.py`` runs the same shape of
assertions against a real Postgres backend.

Contract:

* Point reads with ``expected_tenant_id is None``      → cross-tenant visible.
* Point reads with ``expected_tenant_id = T``          → only T's rows visible.
* Tenantless (``tenant_id is None``) rows              → invisible to scoped reads.
* Enforcement-action point read with ``expected_tenant_id = T``
  → empty when the parent decision is owned by another tenant
  (scope inherits from parent).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.governance.persistence import (
    BaseGovernanceRepository,
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    InMemoryGovernanceRepository,
)


def _decision(
    *,
    decision_id: str,
    tenant_id: str | None,
    decided_at: datetime | None = None,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=decision_id,
        decision="allow",
        stage="pre_retrieval",
        policy_chain_id="t",
        reason="ok",
        decided_at=(decided_at or datetime(2026, 5, 19, 9, tzinfo=timezone.utc)).isoformat(),
        tenant_id=tenant_id,
    )


def _trace(
    *,
    decision_id: str,
    tenant_id: str | None,
) -> GovernanceTraceRecord:
    return GovernanceTraceRecord(
        decision_id=decision_id,
        request_id=None,
        correlation_id=None,
        stage="pre_retrieval",
        action="retrieve",
        resource="docs/*",
        actor="agent:test",
        tenant_id=tenant_id,
        subject_kind="generic",
        started_at="2026-05-19T09:00:00+00:00",
        ended_at="2026-05-19T09:00:00.000100+00:00",
        latency_ms=0.1,
        status="ok",
        final_decision="allow",
        policy_chain_id="t",
        rule_count=0,
        violation_count=0,
        restriction_count=0,
        enforcement_handler=None,
        enforcement_status=None,
        enforcement_latency_ms=None,
    )


def _action(
    *, action_id: str, decision_id: str
) -> EnforcementActionRecord:
    return EnforcementActionRecord(
        action_id=action_id,
        handler_name="allow",
        decision_id=decision_id,
        outcome="applied",
        applied_at="2026-05-19T09:00:00.001000+00:00",
    )


# ─── get_decision ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_decision_returns_row_when_expected_tenant_matches() -> None:
    repo: BaseGovernanceRepository = InMemoryGovernanceRepository()
    decision_id = str(uuid.uuid4())
    await repo.record_decision(
        _decision(decision_id=decision_id, tenant_id="tenant-acme")
    )

    got = await repo.get_decision(
        decision_id, expected_tenant_id="tenant-acme"
    )
    assert got is not None
    assert got.tenant_id == "tenant-acme"


@pytest.mark.asyncio
async def test_get_decision_returns_none_when_expected_tenant_mismatches() -> None:
    repo: BaseGovernanceRepository = InMemoryGovernanceRepository()
    decision_id = str(uuid.uuid4())
    await repo.record_decision(
        _decision(decision_id=decision_id, tenant_id="tenant-acme")
    )

    # Other tenant cannot see the row — indistinguishable from absence.
    got = await repo.get_decision(
        decision_id, expected_tenant_id="tenant-other"
    )
    assert got is None


@pytest.mark.asyncio
async def test_get_decision_tenantless_row_invisible_to_scoped_reader() -> None:
    repo: BaseGovernanceRepository = InMemoryGovernanceRepository()
    decision_id = str(uuid.uuid4())
    await repo.record_decision(
        _decision(decision_id=decision_id, tenant_id=None)
    )

    # System-level (tenantless) decisions must NOT leak into a
    # tenant-scoped read — the scoped reader observes "no row".
    got = await repo.get_decision(
        decision_id, expected_tenant_id="tenant-acme"
    )
    assert got is None


@pytest.mark.asyncio
async def test_get_decision_tenantless_row_visible_to_admin_reader() -> None:
    repo: BaseGovernanceRepository = InMemoryGovernanceRepository()
    decision_id = str(uuid.uuid4())
    await repo.record_decision(
        _decision(decision_id=decision_id, tenant_id=None)
    )

    # Admin / substrate-internal path (expected_tenant_id=None)
    # legitimately reads across all tenants including tenantless.
    got = await repo.get_decision(decision_id)
    assert got is not None
    assert got.tenant_id is None


# ─── get_trace ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_trace_honors_tenant_scope() -> None:
    repo: BaseGovernanceRepository = InMemoryGovernanceRepository()
    decision_id = str(uuid.uuid4())
    await repo.record_trace(
        _trace(decision_id=decision_id, tenant_id="tenant-acme")
    )

    # Match → visible.
    assert (
        await repo.get_trace(
            decision_id, expected_tenant_id="tenant-acme"
        )
        is not None
    )
    # Mismatch → invisible.
    assert (
        await repo.get_trace(
            decision_id, expected_tenant_id="tenant-other"
        )
        is None
    )
    # No clamp → visible (admin path).
    assert await repo.get_trace(decision_id) is not None


# ─── get_enforcement_actions ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_enforcement_actions_inherits_tenant_scope_from_decision() -> None:
    repo: BaseGovernanceRepository = InMemoryGovernanceRepository()
    decision_id = str(uuid.uuid4())
    await repo.record_decision(
        _decision(decision_id=decision_id, tenant_id="tenant-acme")
    )
    await repo.record_enforcement_action(
        _action(action_id=str(uuid.uuid4()), decision_id=decision_id)
    )

    # Owning tenant sees the actions.
    owned = await repo.get_enforcement_actions(
        decision_id, expected_tenant_id="tenant-acme"
    )
    assert len(owned) == 1

    # Cross-tenant: empty — caller cannot enumerate by guessing
    # decision_ids.
    other = await repo.get_enforcement_actions(
        decision_id, expected_tenant_id="tenant-other"
    )
    assert other == ()

    # Admin path: unscoped.
    unscoped = await repo.get_enforcement_actions(decision_id)
    assert len(unscoped) == 1


@pytest.mark.asyncio
async def test_get_enforcement_actions_invisible_when_parent_missing() -> None:
    """A scoped read for actions whose parent decision is missing
    MUST be empty. Without the parent, the substrate cannot
    confirm the tenant ownership and so MUST fail closed."""
    repo: BaseGovernanceRepository = InMemoryGovernanceRepository()
    orphan_decision_id = str(uuid.uuid4())
    await repo.record_enforcement_action(
        _action(action_id=str(uuid.uuid4()), decision_id=orphan_decision_id)
    )

    result = await repo.get_enforcement_actions(
        orphan_decision_id, expected_tenant_id="tenant-acme"
    )
    assert result == ()


# ─── Protocol shape ──────────────────────────────────────────────────────


def test_in_memory_satisfies_protocol_with_expected_tenant_id() -> None:
    """``BaseGovernanceRepository`` is ``runtime_checkable``-style by
    interface; the in-memory implementation MUST present the
    PR-B2 keyword on every point read. The shape check here is a
    static-style guard: if the signature drifts, the call site
    below stops type-checking."""
    repo: BaseGovernanceRepository = InMemoryGovernanceRepository()

    async def _shape() -> None:
        await repo.get_decision("id", expected_tenant_id=None)
        await repo.get_decision("id", expected_tenant_id="t")
        await repo.get_trace("id", expected_tenant_id=None)
        await repo.get_trace("id", expected_tenant_id="t")
        await repo.get_enforcement_actions(
            "id", expected_tenant_id=None
        )
        await repo.get_enforcement_actions(
            "id", expected_tenant_id="t"
        )

    # The function does not need to run — defining it is the
    # type-shape assertion. Reference it so the linter doesn't
    # eliminate the closure.
    assert callable(_shape)
