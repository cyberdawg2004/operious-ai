"""Sprint I Hardening — typed governance subject tests.

Properties pinned:

* every subject is immutable (frozen dataclass),
* every subject discriminates via the `kind` field,
* every subject serializes deterministically via `to_dict()`,
* same input → byte-identical dict (replay-safe),
* subject factories produce typed subjects matching Sprint H state.
"""

from __future__ import annotations

import pytest

from app.governance.subjects import (
    AgentActionGovernanceSubject,
    AttachmentSummary,
    BaseGovernanceSubject,
    CandidateSummary,
    CommunicationGovernanceSubject,
    ExecutionGovernanceSubject,
    GenericGovernanceSubject,
    RetrievalGovernanceSubject,
    SubjectKind,
)


# ─── Immutability ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "subject",
    [
        GenericGovernanceSubject(),
        RetrievalGovernanceSubject(query="hi"),
        ExecutionGovernanceSubject(query="hi"),
        AgentActionGovernanceSubject(agent_id="a", capability="c"),
        CommunicationGovernanceSubject(channel="email"),
    ],
)
def test_subjects_are_frozen(subject) -> None:
    with pytest.raises((AttributeError, Exception)):
        subject.kind = SubjectKind.GENERIC  # type: ignore[misc]


# ─── Discriminator ────────────────────────────────────────────────────


def test_every_subject_sets_its_own_kind() -> None:
    pairs = [
        (GenericGovernanceSubject(), SubjectKind.GENERIC),
        (RetrievalGovernanceSubject(), SubjectKind.RETRIEVAL),
        (ExecutionGovernanceSubject(), SubjectKind.EXECUTION),
        (AgentActionGovernanceSubject(), SubjectKind.AGENT_ACTION),
        (CommunicationGovernanceSubject(), SubjectKind.COMMUNICATION),
    ]
    for subject, expected_kind in pairs:
        assert subject.kind is expected_kind
        assert isinstance(subject, BaseGovernanceSubject)


# ─── Serialization determinism ────────────────────────────────────────


def test_retrieval_subject_serializes_deterministically() -> None:
    s = RetrievalGovernanceSubject(
        query="hello",
        tenant_id="acme",
        policy_id="default",
        request_id="req-1",
        candidate_count=2,
        estimated_tokens=42,
        retrieval_candidates=(
            CandidateSummary(
                chunk_id="c1",
                document_id="d1",
                score=0.9,
                content="alpha",
                source="src",
                source_strategy="single_query",
            ),
            CandidateSummary(
                chunk_id="c2",
                document_id="d1",
                score=0.7,
                content="beta",
            ),
        ),
        metadata={"k": "v"},
    )
    a = s.to_dict()
    b = s.to_dict()
    assert a == b
    assert a["kind"] == "retrieval"
    assert a["retrieval_candidates"][0]["chunk_id"] == "c1"
    assert a["retrieval_candidates"][1]["score"] == 0.7
    assert a["metadata"] == {"k": "v"}


def test_execution_subject_serializes_deterministically() -> None:
    s = ExecutionGovernanceSubject(
        query="hello",
        tenant_id="acme",
        execution_action="ai.completion",
        downstream_targets=("model:openai:gpt-4o",),
        citation_count=3,
        fragment_count=3,
        candidate_count_included=3,
        estimated_tokens=200,
        grounding_strategy="default",
    )
    assert s.to_dict() == s.to_dict()
    assert s.to_dict()["downstream_targets"] == ["model:openai:gpt-4o"]


def test_agent_action_subject_serializes_with_full_contract() -> None:
    s = AgentActionGovernanceSubject(
        agent_id="ag-1",
        capability="retrieval.read",
        tool_name="search",
        target_resource="tenant:acme/doc:1",
        execution_scope="tenant:acme/workflow:onboarding",
        supervisor_context={"plan_id": "p1"},
        request_id="req-1",
        tenant_id="acme",
    )
    d = s.to_dict()
    assert d["kind"] == "agent_action"
    assert d["agent_id"] == "ag-1"
    assert d["capability"] == "retrieval.read"
    assert d["supervisor_context"] == {"plan_id": "p1"}


def test_communication_subject_serializes_attachments() -> None:
    s = CommunicationGovernanceSubject(
        channel="email",
        recipient_scope="tenant:acme",
        content_summary="onboarding update",
        attachment_metadata=(
            AttachmentSummary(
                attachment_id="a1",
                mime_type="application/pdf",
                size_bytes=1024,
                classification="internal",
                digest="sha256:abcd",
            ),
        ),
        escalation_flags=("requires_legal_review",),
    )
    d = s.to_dict()
    assert d["attachment_metadata"][0]["digest"] == "sha256:abcd"
    assert d["escalation_flags"] == ["requires_legal_review"]


def test_generic_subject_serializes_dictionary_data() -> None:
    s = GenericGovernanceSubject(data={"k": "v"}, metadata={"m": "n"})
    d = s.to_dict()
    assert d == {"kind": "generic", "metadata": {"m": "n"}, "data": {"k": "v"}}


# ─── Equality / hashability ───────────────────────────────────────────


def test_identical_subjects_compare_equal() -> None:
    a = RetrievalGovernanceSubject(query="hello", tenant_id="acme")
    b = RetrievalGovernanceSubject(query="hello", tenant_id="acme")
    assert a == b


def test_different_subjects_compare_unequal() -> None:
    a = RetrievalGovernanceSubject(query="hello", tenant_id="acme")
    b = RetrievalGovernanceSubject(query="hello", tenant_id="globex")
    assert a != b


# ─── Factories ────────────────────────────────────────────────────────


def test_retrieval_subject_factory_for_assembly_request() -> None:
    from app.governance.subjects.factories import retrieval_subject_for_assembly
    from app.rag.assembly.models import AssemblyRequest

    req = AssemblyRequest(query="hello")
    subject = retrieval_subject_for_assembly(
        req, tenant_id="acme", request_id="req-1"
    )
    assert isinstance(subject, RetrievalGovernanceSubject)
    assert subject.query == "hello"
    assert subject.tenant_id == "acme"
    assert subject.request_id == "req-1"
    assert subject.retrieval_candidates == ()


def test_execution_subject_factory_for_assembled_context() -> None:
    from app.governance.subjects.factories import (
        execution_subject_for_assembled_context,
    )
    from app.rag.assembly.models import AssembledContext
    from app.rag.budgeting.models import BudgetConstraint, BudgetingResult
    from app.rag.citations.models import CitationIndex
    from app.rag.grounding.models import GroundingResult

    ac = AssembledContext(
        query="hello",
        retrieval_candidates=(),
        budgeting=BudgetingResult(
            constraint=BudgetConstraint(),
            included=(),
            excluded=(),
            decisions=(),
            total_tokens=0,
            included_count=0,
            excluded_count=0,
        ),
        citation_index=CitationIndex(citations=()),
        grounding=GroundingResult(strategy_name="default", fragments=()),
        reranker_name="identity",
        grounding_strategy="default",
    )
    subject = execution_subject_for_assembled_context(
        ac, tenant_id="acme", request_id="req-1"
    )
    assert isinstance(subject, ExecutionGovernanceSubject)
    assert subject.query == "hello"
    assert subject.tenant_id == "acme"
    assert subject.fragment_count == 0
    assert subject.grounding_strategy == "default"
