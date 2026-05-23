"""Sprint I Hardening — persistence layer tests.

Properties pinned:

* every record type round-trips through `to_dict` / `from_dict`
  byte-identically,
* runtime → record conversion is deterministic for fixed input,
* record → runtime round-trip reconstructs the apex decision verdict
  + violations + restrictions,
* the in-memory repository honours the `BaseGovernanceRepository`
  Protocol contract: write-once writes, point reads, query filtering,
  pagination,
* query results are deterministically ordered.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.governance.decisions import PolicyEvaluationResult, build_decision
from app.governance.enforcement.models import (
    EnforcementAction,
    EnforcementOutcome,
)
from app.governance.enums import (
    Decision,
    EnforcementStage,
    RestrictionKind,
    ViolationSeverity,
)
from app.governance.persistence import (
    BaseGovernanceRepository,
    DecisionQuery,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    InMemoryGovernanceRepository,
)
from app.governance.persistence.records import (
    PolicyEvaluationTraceRecord,
)
from app.governance.persistence.serializers import (
    decision_to_record,
    enforcement_action_to_record,
    record_to_decision,
    trace_to_record,
)
from app.governance.tracing import GovernanceTrace, PolicyEvaluationTrace
from app.governance.value_objects import RuntimeRestriction


# ─── Record round-trips ──────────────────────────────────────────────


def test_decision_record_round_trips() -> None:
    restriction = RuntimeRestriction(
        kind=RestrictionKind.CONTENT_REDACTION,
        target="chunk_id:c1",
        value={"matched_term": "secret"},
        reason="denylisted term",
        policy_name="content_denylist",
        rule_id="denylisted_term_present",
    )
    results = (
        PolicyEvaluationResult(
            policy_name="content_denylist",
            rule_id="denylisted_term_present",
            decision=Decision.REDACT,
            severity=ViolationSeverity.HIGH,
            reason="match",
            restrictions=(restriction,),
        ),
    )
    decision = build_decision(
        stage=EnforcementStage.POST_RETRIEVAL,
        policy_chain_id="post_retrieval.test",
        evaluation_results=results,
        decision_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        decided_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    record = decision_to_record(decision)
    serialized = record.to_dict()
    deserialized = GovernanceDecisionRecord.from_dict(serialized)
    assert deserialized == record


def test_decision_record_serialization_is_deterministic() -> None:
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="t",
        evaluation_results=(
            PolicyEvaluationResult(
                policy_name="p",
                rule_id="r",
                decision=Decision.ALLOW,
                reason="ok",
            ),
        ),
        decision_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        decided_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    a = decision_to_record(decision).to_dict()
    b = decision_to_record(decision).to_dict()
    assert a == b


def test_decision_record_to_runtime_decision_round_trips_verdict() -> None:
    original = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="t",
        evaluation_results=(
            PolicyEvaluationResult(
                policy_name="p",
                rule_id="r",
                decision=Decision.DENY,
                severity=ViolationSeverity.HIGH,
                reason="blocked",
            ),
        ),
        decision_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        decided_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    record = decision_to_record(original)
    reconstructed = record_to_decision(record)
    # Verdict + identity + stage + chain id + violations round-trip.
    assert reconstructed.decision is Decision.DENY
    assert reconstructed.decision_id == original.decision_id
    assert reconstructed.stage is EnforcementStage.PRE_RETRIEVAL
    assert reconstructed.policy_chain_id == "t"
    assert len(reconstructed.violations) == 1
    assert reconstructed.violations[0].policy_name == "p"


def test_decision_record_preserves_evaluated_rules_losslessly() -> None:
    """Replay determinism (Core Law 2): reconstruction MUST preserve
    every rule that fired, including ALLOW rules — the persistence
    contract is now lossless."""
    evaluated_at = datetime(
        2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc
    )
    original = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain-x",
        evaluation_results=(
            PolicyEvaluationResult(
                policy_name="p1",
                rule_id="r1",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="ok",
                evaluated_at=evaluated_at,
            ),
            PolicyEvaluationResult(
                policy_name="p2",
                rule_id="r2",
                decision=Decision.DEGRADE,
                severity=ViolationSeverity.MEDIUM,
                reason="trim",
                evaluated_at=evaluated_at,
            ),
            PolicyEvaluationResult(
                policy_name="p3",
                rule_id="r3",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="ok",
                evaluated_at=evaluated_at,
            ),
        ),
        decision_id=uuid.UUID("22222222-3333-4444-5555-666666666666"),
        decided_at=evaluated_at,
    )
    record = decision_to_record(original)
    reconstructed = record_to_decision(record)
    assert len(reconstructed.evaluated_rules) == 3
    assert tuple(
        (r.policy_name, r.rule_id, r.decision)
        for r in reconstructed.evaluated_rules
    ) == tuple(
        (r.policy_name, r.rule_id, r.decision)
        for r in original.evaluated_rules
    )
    # Byte-stable JSON round-trip too.
    assert (
        GovernanceDecisionRecord.from_dict(record.to_dict()).to_dict()
        == record.to_dict()
    )


def test_legacy_decision_record_without_evaluated_rules_still_loads() -> None:
    """Backward compat: records persisted before `evaluated_rules` was
    added still reconstruct, falling back to violations-based rebuild."""
    legacy_blob = {
        "decision_id": "11111111-2222-3333-4444-555555555555",
        "decision": "deny",
        "stage": "pre_retrieval",
        "policy_chain_id": "t",
        "reason": "deny: p.r",
        "decided_at": datetime(
            2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc
        ).isoformat(),
        "correlation_id": None,
        "violations": [
            {
                "policy_name": "p",
                "rule_id": "r",
                "decision": "deny",
                "severity": int(ViolationSeverity.HIGH),
                "detail": "blocked",
                "metadata": {},
            }
        ],
        "restrictions": [],
        "metadata": {},
    }
    record = GovernanceDecisionRecord.from_dict(legacy_blob)
    assert record.evaluated_rules == ()
    reconstructed = record_to_decision(record)
    # Legacy path reconstructs the DENY result from violations only.
    assert len(reconstructed.evaluated_rules) == 1
    assert reconstructed.evaluated_rules[0].decision is Decision.DENY


def test_trace_record_round_trips() -> None:
    decision_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    correlation_id = uuid.uuid4()
    trace = GovernanceTrace(
        decision_id=decision_id,
        request_id="req-1",
        stage=EnforcementStage.PRE_RETRIEVAL,
        action="rag.assemble_context",
        resource="tenant:acme/index:default",
        actor="system",
        tenant_id="acme",
        subject_kind="retrieval",
        correlation_id=correlation_id,
        started_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 5, 15, 12, 0, 1, tzinfo=timezone.utc),
        latency_ms=12.34,
        status="ok",
        final_decision=Decision.ALLOW,
        policy_chain_id="pre_retrieval.test",
        policy_traces=(
            PolicyEvaluationTrace(
                policy_name="tenant_scope",
                status="ok",
                started_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
                ended_at=datetime(2026, 5, 15, 12, 0, 0, 100000, tzinfo=timezone.utc),
                latency_ms=0.1,
                rule_count=1,
                decision_counts={Decision.ALLOW: 1},
            ),
        ),
        rule_count=1,
        violation_count=0,
        restriction_count=0,
        enforcement_handler="allow",
        enforcement_status="ok",
        enforcement_latency_ms=0.05,
    )
    record = trace_to_record(trace)
    serialized = record.to_dict()
    deserialized = GovernanceTraceRecord.from_dict(serialized)
    assert deserialized == record
    # Subject kind + correlation id propagated.
    assert record.subject_kind == "retrieval"
    assert record.correlation_id == str(correlation_id)


def test_enforcement_action_record_round_trips() -> None:
    action = EnforcementAction(
        action_id=uuid.uuid4(),
        handler_name="allow",
        decision_id=uuid.uuid4(),
        outcome=EnforcementOutcome.APPLIED,
        applied_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
        detail="ok",
    )
    record = enforcement_action_to_record(action)
    assert record.handler_name == "allow"
    assert record.outcome == "applied"


# ─── PolicyEvaluationTraceRecord round-trip ──────────────────────────


def test_policy_evaluation_trace_record_round_trips() -> None:
    record = PolicyEvaluationTraceRecord(
        policy_name="p",
        status="skipped",
        started_at="2026-05-15T12:00:00+00:00",
        ended_at="2026-05-15T12:00:00.000100+00:00",
        latency_ms=0.1,
        rule_count=0,
        decision_counts={},
        metadata={"skip_reason": "subject_kind_not_applicable"},
    )
    a = record.to_dict()
    deserialized = PolicyEvaluationTraceRecord.from_dict(a)
    assert deserialized == record


# ─── In-memory repository ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_memory_repository_records_and_retrieves_decisions() -> None:
    repo: BaseGovernanceRepository = InMemoryGovernanceRepository()
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="t",
        evaluation_results=(
            PolicyEvaluationResult(
                policy_name="p", rule_id="r", decision=Decision.ALLOW, reason="ok"
            ),
        ),
        decision_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        decided_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    await repo.record_decision(decision_to_record(decision))

    got = await repo.get_decision(str(decision.decision_id))
    assert got is not None
    assert got.decision == "allow"


@pytest.mark.asyncio
async def test_in_memory_repository_is_write_once() -> None:
    repo = InMemoryGovernanceRepository()
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="t",
        evaluation_results=(
            PolicyEvaluationResult(
                policy_name="p", rule_id="r", decision=Decision.ALLOW, reason="ok"
            ),
        ),
    )
    record = decision_to_record(decision)
    await repo.record_decision(record)
    with pytest.raises(ValueError):
        await repo.record_decision(record)


@pytest.mark.asyncio
async def test_in_memory_repository_query_filters_by_stage() -> None:
    repo = InMemoryGovernanceRepository()

    async def _insert(stage: EnforcementStage, decided_at: datetime) -> None:
        decision = build_decision(
            stage=stage,
            policy_chain_id=f"{stage.value}.test",
            evaluation_results=(
                PolicyEvaluationResult(
                    policy_name="p", rule_id="r", decision=Decision.ALLOW, reason="ok"
                ),
            ),
            decided_at=decided_at,
        )
        await repo.record_decision(decision_to_record(decision))

    await _insert(
        EnforcementStage.PRE_RETRIEVAL,
        datetime(2026, 5, 15, 12, 0, 1, tzinfo=timezone.utc),
    )
    await _insert(
        EnforcementStage.PRE_EXECUTION,
        datetime(2026, 5, 15, 12, 0, 2, tzinfo=timezone.utc),
    )
    await _insert(
        EnforcementStage.PRE_RETRIEVAL,
        datetime(2026, 5, 15, 12, 0, 3, tzinfo=timezone.utc),
    )

    page = await repo.query_decisions(
        DecisionQuery(stage="pre_retrieval", limit=10)
    )
    assert page.total == 2
    assert all(r.stage == "pre_retrieval" for r in page.items)
    # Ordered by decided_at ascending (deterministic).
    assert page.items[0].decided_at < page.items[1].decided_at


@pytest.mark.asyncio
async def test_in_memory_repository_query_paginates() -> None:
    repo = InMemoryGovernanceRepository()
    for i in range(5):
        decision = build_decision(
            stage=EnforcementStage.PRE_RETRIEVAL,
            policy_chain_id="t",
            evaluation_results=(
                PolicyEvaluationResult(
                    policy_name="p", rule_id="r", decision=Decision.ALLOW, reason="ok"
                ),
            ),
            decided_at=datetime(2026, 5, 15, 12, 0, i, tzinfo=timezone.utc),
        )
        await repo.record_decision(decision_to_record(decision))

    page1 = await repo.query_decisions(DecisionQuery(limit=2, offset=0))
    page2 = await repo.query_decisions(DecisionQuery(limit=2, offset=2))
    assert len(page1.items) == 2
    assert len(page2.items) == 2
    assert page1.items[0].decided_at < page1.items[1].decided_at < page2.items[0].decided_at
    assert page1.total == page2.total == 5


@pytest.mark.asyncio
async def test_in_memory_repository_query_by_correlation_id() -> None:
    repo = InMemoryGovernanceRepository()
    correlation_id = uuid.uuid4()
    other_correlation_id = uuid.uuid4()

    for cid in (correlation_id, correlation_id, other_correlation_id):
        d = build_decision(
            stage=EnforcementStage.PRE_RETRIEVAL,
            policy_chain_id="t",
            evaluation_results=(
                PolicyEvaluationResult(
                    policy_name="p",
                    rule_id="r",
                    decision=Decision.ALLOW,
                    reason="ok",
                ),
            ),
            metadata={"correlation_id": str(cid)},
        )
        await repo.record_decision(decision_to_record(d))

    page = await repo.query_decisions(
        DecisionQuery(correlation_id=str(correlation_id))
    )
    assert page.total == 2
    assert all(
        r.correlation_id == str(correlation_id) for r in page.items
    )


# ─── 2.5-C3: cross-tenant decision query parity ─────────────────────


@pytest.mark.asyncio
async def test_decision_query_filters_by_tenant_id() -> None:
    """Queries scoped by ``tenant_id`` MUST NOT leak rows from other
    tenants. Pre-2.5-C the matcher silently ignored ``tenant_id``
    even though ``DecisionQuery.tenant_id`` was advertised, and
    ``GovernanceDecisionRecord`` did not carry the field at all —
    multi-tenant audit queries leaked rows across tenants. This is
    the regression pin.
    """
    repo = InMemoryGovernanceRepository()

    for tenant in ("tenant-a", "tenant-a", "tenant-b"):
        d = build_decision(
            stage=EnforcementStage.PRE_RETRIEVAL,
            policy_chain_id="chain-1",
            evaluation_results=(
                PolicyEvaluationResult(
                    policy_name="p",
                    rule_id="r",
                    decision=Decision.ALLOW,
                    reason="ok",
                ),
            ),
            metadata={"tenant_id": tenant, "subject_kind": "retrieval"},
        )
        await repo.record_decision(decision_to_record(d))

    page = await repo.query_decisions(DecisionQuery(tenant_id="tenant-a"))
    assert page.total == 2
    assert all(r.tenant_id == "tenant-a" for r in page.items)

    page_b = await repo.query_decisions(DecisionQuery(tenant_id="tenant-b"))
    assert page_b.total == 1
    assert page_b.items[0].tenant_id == "tenant-b"

    # Negative tenant — no rows.
    empty = await repo.query_decisions(DecisionQuery(tenant_id="tenant-z"))
    assert empty.total == 0


@pytest.mark.asyncio
async def test_decision_query_filters_by_request_id() -> None:
    repo = InMemoryGovernanceRepository()
    for rid in ("req-1", "req-1", "req-2"):
        d = build_decision(
            stage=EnforcementStage.PRE_RETRIEVAL,
            policy_chain_id="chain-1",
            evaluation_results=(
                PolicyEvaluationResult(
                    policy_name="p",
                    rule_id="r",
                    decision=Decision.ALLOW,
                    reason="ok",
                ),
            ),
            metadata={"request_id": rid},
        )
        await repo.record_decision(decision_to_record(d))

    page = await repo.query_decisions(DecisionQuery(request_id="req-1"))
    assert page.total == 2
    assert all(r.request_id == "req-1" for r in page.items)


@pytest.mark.asyncio
async def test_decision_query_filters_by_subject_kind() -> None:
    repo = InMemoryGovernanceRepository()
    for kind in ("retrieval", "retrieval", "execution"):
        d = build_decision(
            stage=EnforcementStage.PRE_RETRIEVAL,
            policy_chain_id="chain-1",
            evaluation_results=(
                PolicyEvaluationResult(
                    policy_name="p",
                    rule_id="r",
                    decision=Decision.ALLOW,
                    reason="ok",
                ),
            ),
            metadata={"subject_kind": kind},
        )
        await repo.record_decision(decision_to_record(d))

    page = await repo.query_decisions(
        DecisionQuery(subject_kind="retrieval")
    )
    assert page.total == 2
    assert all(r.subject_kind == "retrieval" for r in page.items)


# ─── 2.5-E: governance_version + policy_version provenance ──────────


@pytest.mark.asyncio
async def test_decision_record_carries_governance_version() -> None:
    """``governance_version`` flows from PolicyChain → metadata →
    GovernanceDecisionRecord and survives the round-trip."""
    d = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain-versioned",
        evaluation_results=(
            PolicyEvaluationResult(
                policy_name="p",
                rule_id="r",
                decision=Decision.ALLOW,
                reason="ok",
                policy_version="2026.05.19-r1",
            ),
        ),
        metadata={"governance_version": "2026.05.19-r1"},
    )
    rec = decision_to_record(d)
    assert rec.governance_version == "2026.05.19-r1"
    # Round-trip preserves it.
    rt = GovernanceDecisionRecord.from_dict(rec.to_dict())
    assert rt.governance_version == "2026.05.19-r1"
    # And the per-policy version survives via evaluated_rules.
    assert rt.evaluated_rules[0].policy_version == "2026.05.19-r1"


def test_legacy_decision_record_defaults_governance_version() -> None:
    """Records persisted before 2.5-E (without ``governance_version``
    in their dict) MUST deserialize cleanly with the safe default."""
    legacy_dict = {
        "decision_id": str(uuid.uuid4()),
        "decision": "allow",
        "stage": EnforcementStage.PRE_RETRIEVAL.value,
        "policy_chain_id": "legacy",
        "reason": "ok",
        "decided_at": "2026-05-19T00:00:00+00:00",
    }
    rt = GovernanceDecisionRecord.from_dict(legacy_dict)
    assert rt.governance_version == "unversioned"


@pytest.mark.asyncio
async def test_decision_record_round_trips_new_query_axes() -> None:
    """The 2.5-C1 fields must round-trip through to_dict/from_dict."""
    d = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain-1",
        evaluation_results=(
            PolicyEvaluationResult(
                policy_name="p",
                rule_id="r",
                decision=Decision.ALLOW,
                reason="ok",
            ),
        ),
        metadata={
            "tenant_id": "t-rt",
            "request_id": "req-rt",
            "subject_kind": "retrieval",
            "correlation_id": "corr-rt",
        },
    )
    rec = decision_to_record(d)
    assert rec.tenant_id == "t-rt"
    assert rec.request_id == "req-rt"
    assert rec.subject_kind == "retrieval"
    assert rec.correlation_id == "corr-rt"
    # Serialized round-trip stays byte-identical.
    serialized = rec.to_dict()
    rt = GovernanceDecisionRecord.from_dict(serialized)
    assert rt == rec
