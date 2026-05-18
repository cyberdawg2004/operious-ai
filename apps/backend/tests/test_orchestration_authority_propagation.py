# pyright: reportArgumentType=false
"""Branch A — orchestration-wide ``authority`` field propagation.

Covers the 12 request contracts whose ``authority`` field +
coexistence invariant Branch A introduces, plus the 4 contracts
B2/B6/B7 already shipped (re-pinned against the central helper).

Doctrine
────────
Every orchestration request that carries ``tenant_id`` MUST also
expose ``authority: AuthorityContext | None = None`` and run the
shared ``check_tenant_authority_coexistence`` invariant. The
helper rejects only the disagreement axis — ``None`` on either
side is legal during the typed-ingress transition.
"""

from __future__ import annotations

import datetime as dt
import inspect
import uuid

import pytest

from app.identity import (
    AuthorityContext,
    PrincipalId,
    TenantId,
    check_tenant_authority_coexistence,
)


# ─── Central helper invariants ─────────────────────────────────────


def test_helper_silent_when_both_none() -> None:
    check_tenant_authority_coexistence(
        contract_name="T",
        authority=None,
        tenant_id=None,
    )


def test_helper_silent_when_authority_only() -> None:
    check_tenant_authority_coexistence(
        contract_name="T",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
        tenant_id=None,
    )


def test_helper_silent_when_tenant_only() -> None:
    check_tenant_authority_coexistence(
        contract_name="T",
        authority=None,
        tenant_id="acme",
    )


def test_helper_silent_when_authority_tenant_none() -> None:
    """An AuthorityContext with no tenant axis silently coexists
    with a legacy tenant_id — the typed side is omitting that axis."""
    check_tenant_authority_coexistence(
        contract_name="T",
        authority=AuthorityContext(principal_id=PrincipalId("alice")),
        tenant_id="acme",
    )


def test_helper_silent_when_agreement() -> None:
    check_tenant_authority_coexistence(
        contract_name="T",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
        tenant_id="acme",
    )


def test_helper_raises_on_disagreement() -> None:
    with pytest.raises(ValueError, match="must agree"):
        check_tenant_authority_coexistence(
            contract_name="T",
            authority=AuthorityContext(tenant_id=TenantId("other")),
            tenant_id="acme",
        )


def test_helper_error_message_carries_contract_name() -> None:
    with pytest.raises(ValueError, match="MySpecialRequest:"):
        check_tenant_authority_coexistence(
            contract_name="MySpecialRequest",
            authority=AuthorityContext(tenant_id=TenantId("x")),
            tenant_id="y",
        )


# ─── Contract surface coverage ─────────────────────────────────────


def _disagreeing_authority() -> AuthorityContext:
    return AuthorityContext(tenant_id=TenantId("other"))


def _build(cls, **defaults):
    """Construct ``cls`` with positional-required fields filled
    via sensible defaults; pass kwargs through."""

    sig = inspect.signature(cls)
    positional = {}
    for name, param in sig.parameters.items():
        if param.default is not inspect.Parameter.empty:
            continue
        if name in defaults:
            continue
        positional[name] = _stub_value(name, param.annotation)
    return cls(**positional, **defaults)


def _stub_value(name: str, annotation):
    """Lightweight default for required-but-irrelevant fields."""
    text = str(annotation)
    if "str" in text:
        return "stub"
    if "tuple" in text:
        return ()
    if "datetime" in text:
        return dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    if "UUID" in text:
        return uuid.uuid4()
    return None


def test_arbitration_request_invariant() -> None:
    from app.arbitration.contracts.requests import ArbitrationRequest
    from app.arbitration.models.case import ArbitrationCase

    case = ArbitrationCase(case_id="c1")
    ok = ArbitrationRequest(
        case=case,
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert ok.authority is not None
    with pytest.raises(ValueError, match="ArbitrationRequest:"):
        ArbitrationRequest(
            case=case,
            tenant_id="acme",
            authority=_disagreeing_authority(),
        )


def test_open_session_request_invariant() -> None:
    from app.session.contracts.requests import OpenSessionRequest
    from app.session.enums import SessionScope

    ok = OpenSessionRequest(
        scope=SessionScope.TENANT,
        external_handle="s1",
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert ok.authority is not None
    with pytest.raises(ValueError, match="OpenSessionRequest:"):
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="s1",
            tenant_id="acme",
            authority=_disagreeing_authority(),
        )


def test_record_failure_request_invariant() -> None:
    from app.hardening.contracts.requests import RecordFailureRequest
    from app.hardening.enums import (
        ContainmentClassification,
        FailureClassification,
        HardeningSeverity,
        SubstrateName,
    )

    base = dict(
        substrate=SubstrateName.AGENTS,
        classification=FailureClassification.BOUNDED,
        containment=ContainmentClassification.CONTAINED,
        severity=HardeningSeverity.LOW,
        summary="x",
        error_class_name="X",
        seed="s",
    )
    ok = RecordFailureRequest(
        **base,
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert ok.authority is not None
    with pytest.raises(ValueError, match="RecordFailureRequest:"):
        RecordFailureRequest(
            **base,
            tenant_id="acme",
            authority=_disagreeing_authority(),
        )


def test_coordination_policy_evaluation_request_invariant() -> None:
    from app.coordination.enums import (
        CoordinationDirection,
        CoordinationMessageType,
    )
    from app.coordination.identity import (
        generate_coordination_id,
        generate_message_id,
    )
    from app.coordination.policy.contracts.requests import (
        CoordinationPolicyEvaluationRequest,
    )

    base = dict(
        sender_id="a",
        recipient_id="b",
        direction=CoordinationDirection.AGENT_TO_AGENT,
        message_type=CoordinationMessageType.REQUEST,
        coordination_id=generate_coordination_id(),
        coordination_message_id=generate_message_id(),
    )
    ok = CoordinationPolicyEvaluationRequest(
        **base,
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert ok.authority is not None
    with pytest.raises(
        ValueError, match="CoordinationPolicyEvaluationRequest:"
    ):
        CoordinationPolicyEvaluationRequest(
            **base,
            tenant_id="acme",
            authority=_disagreeing_authority(),
        )


def test_coordination_topology_evaluation_request_invariant() -> None:
    from app.coordination.enums import (
        CoordinationDirection,
        CoordinationMessageType,
    )
    from app.coordination.identity import (
        generate_coordination_id,
        generate_message_id,
    )
    from app.coordination.topology.contracts.requests import (
        CoordinationTopologyEvaluationRequest,
    )

    base = dict(
        sender_id="a",
        recipient_id="b",
        direction=CoordinationDirection.AGENT_TO_AGENT,
        message_type=CoordinationMessageType.REQUEST,
        coordination_id=generate_coordination_id(),
        coordination_message_id=generate_message_id(),
    )
    ok = CoordinationTopologyEvaluationRequest(
        **base,
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert ok.authority is not None
    with pytest.raises(
        ValueError, match="CoordinationTopologyEvaluationRequest:"
    ):
        CoordinationTopologyEvaluationRequest(
            **base,
            tenant_id="acme",
            authority=_disagreeing_authority(),
        )


# ─── OI request contracts ──────────────────────────────────────────


@pytest.mark.parametrize(
    "factory_name",
    [
        "_ingest_sop",
        "_classify_tonality",
        "_register_communication_pattern",
        "_retrieve_communication_patterns",
        "_memory_evolution_proposal",
        "_list_memory_artifacts",
        "_generate_recommendation",
    ],
)
def test_oi_request_invariants(factory_name: str) -> None:
    factory = globals()[factory_name]
    ok = factory(authority=AuthorityContext(tenant_id=TenantId("acme")), tenant_id="acme")
    assert ok.authority is not None
    with pytest.raises(ValueError, match="must agree"):
        factory(authority=_disagreeing_authority(), tenant_id="acme")


def _ingest_sop(**kw):
    from app.organizational_intelligence.contracts.requests import (
        IngestSopRequest,
    )

    return IngestSopRequest(
        external_handle="h", title="t", body="b", **kw
    )


def _classify_tonality(**kw):
    from app.organizational_intelligence.contracts.requests import (
        ClassifyTonalityRequest,
    )

    return ClassifyTonalityRequest(content="hi", **kw)


def _register_communication_pattern(**kw):
    from app.organizational_intelligence.contracts.requests import (
        RegisterCommunicationPatternRequest,
    )
    from app.organizational_intelligence.enums import (
        ApprovalAuthorityKind,
        ApprovalDecision,
        CommunicationPatternKind,
        TonalityClass,
    )
    from app.organizational_intelligence.models.approval import (
        ApprovalRecord,
    )

    approval = ApprovalRecord(
        approval_id=uuid.uuid4(),
        target_id=uuid.uuid4(),
        target_kind="communication_pattern",
        decision=ApprovalDecision.APPROVED,
        authority=ApprovalAuthorityKind.HUMAN_REVIEWER,
        approver_handle="reviewer",
        decided_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    return RegisterCommunicationPatternRequest(
        handle="h",
        body="b",
        kind=next(iter(CommunicationPatternKind)),
        applicable_classes=(next(iter(TonalityClass)),),
        approval=approval,
        **kw,
    )


def _retrieve_communication_patterns(**kw):
    from app.organizational_intelligence.contracts.requests import (
        RetrieveCommunicationPatternsRequest,
    )
    from app.organizational_intelligence.enums import TonalityClass

    return RetrieveCommunicationPatternsRequest(
        primary_class=next(iter(TonalityClass)), **kw
    )


def _memory_evolution_proposal(**kw):
    from app.organizational_intelligence.contracts.requests import (
        MemoryEvolutionProposalRequest,
    )
    from app.organizational_intelligence.enums import MemoryArtifactKind

    return MemoryEvolutionProposalRequest(
        observation_seed="s",
        summary="sm",
        body="b",
        kind=next(iter(MemoryArtifactKind)),
        **kw,
    )


def _list_memory_artifacts(**kw):
    from app.organizational_intelligence.contracts.requests import (
        ListMemoryArtifactsRequest,
    )

    return ListMemoryArtifactsRequest(**kw)


def _generate_recommendation(**kw):
    from app.organizational_intelligence.contracts.requests import (
        GenerateRecommendationRequest,
    )
    from app.organizational_intelligence.enums import RecommendationKind
    from app.organizational_intelligence.models.recommendation import (
        RecommendationRationale,
    )

    rationale = RecommendationRationale(summary="r", evidence=())
    return GenerateRecommendationRequest(
        title="t",
        body="b",
        kind=next(iter(RecommendationKind)),
        target_handle="th",
        rationale=rationale,
        **kw,
    )
