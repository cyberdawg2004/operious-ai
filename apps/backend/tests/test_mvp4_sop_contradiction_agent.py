"""MVP-4 — SOP Contradiction Agent tests.

Tests verify:
- Two documents with direct contradicting claims → has_contradiction=True
- Two documents on different topics → has_contradiction=False
- Submitting contradicting SOP via KnowledgeRuntime → QUARANTINED, check_status=CHECKED_CONTRADICTION
- Clean SOP → ingests normally, check_status=CHECKED_CLEAN
- Agent LLM timeout → QUARANTINED for human review, check_status=UNCHECKED_AGENT_UNAVAILABLE
  (BEHAVIOR CHANGE from fail-open: agent-unavailable now fails to human review, not silently clean)
- Tri-state distinguishability: CHECKED_CLEAN / CHECKED_CONTRADICTION / UNCHECKED_AGENT_UNAVAILABLE
  are all structurally distinct — downstream consumers and operators can tell the difference
- parse_output handles markdown code blocks, invalid contradiction types, clamping
- contradiction_report_to_quarantine_metadata extracts correct metadata
- ContradictionType enum has correct structural values
- INVARIANT: contradiction agent output contains no money/goods commitment
- INVARIANT: unchecked_agent_unavailable != checked_clean (doctrine enforcement)
- Domain-agnostic: no vertical terms in SOPContradictionAgent source
- KnowledgeRuntime without contradiction agent → zero regression (NOT_APPLICABLE)
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Sequence

import pytest

from app.agents.governed.base import AgentInput
from app.agents.governed.proposal import AgentProposalStatus
from app.agents.governed.sop_contradiction import (
    CONTRADICTION_REPORT_SCHEMA,
    ContradictionType,
    SOPContradictionAgent,
    SOP_CONTRADICTION_POLICY_TYPE,
    contradiction_report_to_quarantine_metadata,
    safe_no_contradiction,
)
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.governance.capability.acts import OperationalAct
from app.knowledge.models import ContradictionCheckStatus
from app.tenant.enums import (
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.persistence import InMemoryTenantConfigurationRepository

_TENANT = "tenant-mvp4-sop-contradiction"
_SESSION = "session-mvp4"
_EXECUTION = "exec-mvp4"


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------


class _FakeLLMClient:
    provider_name = "test"
    model_name = "test-model"

    def __init__(self, response: str | Exception = "{}") -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        self.calls.append({"system_prompt": system_prompt, "messages": messages})
        if isinstance(self._response, Exception):
            raise self._response
        return DiagnosticLLMCompletion(
            provider="test",
            model="test-model",
            text=self._response,
            usage=DiagnosticLLMUsage(prompt_tokens=20, completion_tokens=20, total_tokens=40),
            stop_reason="end_turn",
            raw_metadata={},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contradiction_output(
    document_id: str = "doc-123",
    has_contradiction: bool = True,
    contradicting_documents: list[dict[str, Any]] | None = None,
) -> str:
    if contradicting_documents is None and has_contradiction:
        contradicting_documents = [
            {
                "doc_id": "existing-doc-1",
                "excerpt": "Returns are allowed within 7 days.",
                "contradicting_excerpt": "Our policy allows 30-day returns.",
                "contradiction_type": ContradictionType.DIRECT_CONFLICT.value,
                "confidence": 0.92,
            }
        ]
    return json.dumps({
        "document_id": document_id,
        "has_contradiction": has_contradiction,
        "contradicting_documents": contradicting_documents or [],
    })


async def _repo_with_sop_policy(
    tenant_id: str = _TENANT,
) -> InMemoryTenantConfigurationRepository:
    from app.tenant.chronology import canonical_sha256
    from app.tenant.identity import derive_governance_policy_version_id
    from datetime import datetime, timezone

    repo = InMemoryTenantConfigurationRepository()
    now = datetime.now(timezone.utc)
    params = {
        "role_description": (
            "You are a specialist in detecting semantic contradictions between "
            "knowledge base documents. Analyze whether two policy documents "
            "contradict each other."
        ),
    }
    from app.tenant.persistence import TenantGovernancePolicyRecord

    content_sha256 = canonical_sha256({
        "tenant_id": tenant_id,
        "policy_type": SOP_CONTRADICTION_POLICY_TYPE,
        "parameters": params,
        "status": TenantGovernancePolicyStatus.ACTIVE.value,
        "version": 1,
        "approved_by": "admin",
        "effective_from": now.isoformat(),
        "source_approval_id": "approval-mvp4",
    })
    record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=SOP_CONTRADICTION_POLICY_TYPE,
            version=1,
        ),
        tenant_id=tenant_id,
        policy_type=SOP_CONTRADICTION_POLICY_TYPE,
        parameters=params,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by="admin",
        effective_from=now,
        created_at=now,
        source_approval_id="approval-mvp4",
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )
    await repo.save_governance_policy(record, expected_tenant_id=tenant_id)
    return repo


def _agent_input(
    new_doc_id: str = "doc-new",
    new_doc_content: str = "Refunds accepted within 30 days.",
    corpus_docs: list[dict[str, Any]] | None = None,
) -> AgentInput:
    return AgentInput(
        tenant_id=_TENANT,
        session_id=_SESSION,
        execution_id=_EXECUTION,
        content={
            "new_document_id": new_doc_id,
            "new_document_title": "Return Policy v2",
            "new_document_type": "sop",
            "new_document_content": new_doc_content,
            "corpus_documents": corpus_docs or [],
        },
    )


# ---------------------------------------------------------------------------
# Unit tests — SOPContradictionAgent directly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_conflict_detected() -> None:
    """Two documents with opposing claims → has_contradiction=True."""
    repo = await _repo_with_sop_policy()
    llm = _FakeLLMClient(_contradiction_output(has_contradiction=True))
    agent = SOPContradictionAgent(
        llm_client=llm, tenant_configuration_repository=repo
    )

    proposal = await agent.run(_agent_input(
        corpus_docs=[{
            "doc_id": "existing-doc-1",
            "title": "Return Policy v1",
            "content": "Returns are allowed within 7 days.",
        }]
    ))

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output is not None
    assert proposal.output["has_contradiction"] is True
    assert len(proposal.output["contradicting_documents"]) == 1
    assert proposal.output["contradicting_documents"][0]["contradiction_type"] == "direct_conflict"
    assert proposal.output["contradicting_documents"][0]["confidence"] == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_no_contradiction_on_different_topics() -> None:
    """Documents covering different topics → has_contradiction=False."""
    repo = await _repo_with_sop_policy()
    llm = _FakeLLMClient(_contradiction_output(
        has_contradiction=False,
        contradicting_documents=[],
    ))
    agent = SOPContradictionAgent(
        llm_client=llm, tenant_configuration_repository=repo
    )

    proposal = await agent.run(_agent_input(
        new_doc_content="Escalation path for billing disputes.",
        corpus_docs=[{
            "doc_id": "shipping-doc-1",
            "title": "Shipping Policy",
            "content": "Standard shipping takes 5-7 business days.",
        }]
    ))

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output is not None
    assert proposal.output["has_contradiction"] is False
    assert proposal.output["contradicting_documents"] == []


@pytest.mark.asyncio
async def test_llm_timeout_returns_require_approval() -> None:
    """LLM failure → REQUIRE_APPROVAL, never raises."""
    repo = await _repo_with_sop_policy()
    llm = _FakeLLMClient(TimeoutError("LLM timed out"))
    agent = SOPContradictionAgent(
        llm_client=llm, tenant_configuration_repository=repo
    )

    proposal = await agent.run(_agent_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "llm_invocation_failed"


@pytest.mark.asyncio
async def test_garbage_output_returns_require_approval() -> None:
    """Non-JSON LLM output → REQUIRE_APPROVAL."""
    repo = await _repo_with_sop_policy()
    llm = _FakeLLMClient("this is definitely not json {{{{")
    agent = SOPContradictionAgent(
        llm_client=llm, tenant_configuration_repository=repo
    )

    proposal = await agent.run(_agent_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "llm_output_unparseable"


@pytest.mark.asyncio
async def test_missing_policy_returns_require_approval() -> None:
    """No active sop_contradiction policy → REQUIRE_APPROVAL."""
    repo = InMemoryTenantConfigurationRepository()  # empty
    llm = _FakeLLMClient(_contradiction_output())
    agent = SOPContradictionAgent(
        llm_client=llm, tenant_configuration_repository=repo
    )

    proposal = await agent.run(_agent_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "tenant_agent_policy_not_found"
    assert len(llm.calls) == 0


# ---------------------------------------------------------------------------
# parse_output unit tests
# ---------------------------------------------------------------------------


def _make_agent() -> SOPContradictionAgent:
    return SOPContradictionAgent(
        llm_client=_FakeLLMClient(),
        tenant_configuration_repository=InMemoryTenantConfigurationRepository(),
    )


def test_parse_output_strips_markdown_code_block() -> None:
    """parse_output handles ```json ... ``` wrapping."""
    agent = _make_agent()
    wrapped = f"```json\n{_contradiction_output()}\n```"
    result = agent.parse_output(wrapped)
    assert result is not None
    assert result["has_contradiction"] is True


def test_parse_output_rejects_missing_has_contradiction() -> None:
    """parse_output returns None if has_contradiction field is missing."""
    agent = _make_agent()
    result = agent.parse_output(json.dumps({"document_id": "x", "contradicting_documents": []}))
    assert result is None


def test_parse_output_rejects_non_bool_has_contradiction() -> None:
    """parse_output returns None if has_contradiction is not a bool."""
    agent = _make_agent()
    result = agent.parse_output(json.dumps({
        "document_id": "x",
        "has_contradiction": "yes",
        "contradicting_documents": [],
    }))
    assert result is None


def test_parse_output_filters_invalid_contradiction_types() -> None:
    """parse_output drops contradicting_documents with invalid contradiction_type."""
    agent = _make_agent()
    raw = json.dumps({
        "document_id": "doc-x",
        "has_contradiction": True,
        "contradicting_documents": [
            {
                "doc_id": "d1",
                "excerpt": "a",
                "contradicting_excerpt": "b",
                "contradiction_type": "invented_type",
                "confidence": 0.9,
            },
            {
                "doc_id": "d2",
                "excerpt": "c",
                "contradicting_excerpt": "d",
                "contradiction_type": ContradictionType.SCOPE_OVERLAP.value,
                "confidence": 0.8,
            },
        ],
    })
    result = agent.parse_output(raw)
    assert result is not None
    # only the valid type survives
    assert len(result["contradicting_documents"]) == 1
    assert result["contradicting_documents"][0]["doc_id"] == "d2"


def test_parse_output_clamps_confidence() -> None:
    """parse_output clamps confidence to [0.0, 1.0]."""
    agent = _make_agent()
    raw = json.dumps({
        "document_id": "doc-x",
        "has_contradiction": True,
        "contradicting_documents": [
            {
                "doc_id": "d1",
                "excerpt": "a",
                "contradicting_excerpt": "b",
                "contradiction_type": ContradictionType.TEMPORAL_CONFLICT.value,
                "confidence": 1.5,
            }
        ],
    })
    result = agent.parse_output(raw)
    assert result is not None
    assert result["contradicting_documents"][0]["confidence"] == pytest.approx(1.0)


def test_parse_output_clears_contradicting_docs_when_no_contradiction() -> None:
    """If has_contradiction=False, contradicting_documents is always empty."""
    agent = _make_agent()
    raw = json.dumps({
        "document_id": "doc-x",
        "has_contradiction": False,
        "contradicting_documents": [
            {
                "doc_id": "d1",
                "excerpt": "a",
                "contradicting_excerpt": "b",
                "contradiction_type": ContradictionType.DIRECT_CONFLICT.value,
                "confidence": 0.9,
            }
        ],
    })
    result = agent.parse_output(raw)
    assert result is not None
    assert result["has_contradiction"] is False
    assert result["contradicting_documents"] == []


# ---------------------------------------------------------------------------
# Schema / policy type invariants
# ---------------------------------------------------------------------------


def test_policy_type_constant() -> None:
    """SOP_CONTRADICTION_POLICY_TYPE is the expected string."""
    assert SOP_CONTRADICTION_POLICY_TYPE == "sop_contradiction"


def test_operational_act() -> None:
    """SOPContradictionAgent uses OperationalAct.SOP_CONTRADICTION_FLAG."""
    assert SOPContradictionAgent.operational_act == OperationalAct.SOP_CONTRADICTION_FLAG


def test_contradiction_type_enum_values() -> None:
    """ContradictionType has exactly the expected structural values."""
    expected = {"direct_conflict", "scope_overlap", "temporal_conflict"}
    actual = {t.value for t in ContradictionType}
    assert actual == expected


def test_output_schema_has_required_fields() -> None:
    """ContradictionReport schema requires document_id, has_contradiction, contradicting_documents."""
    required = set(CONTRADICTION_REPORT_SCHEMA.get("required", []))
    assert "document_id" in required
    assert "has_contradiction" in required
    assert "contradicting_documents" in required


# ---------------------------------------------------------------------------
# safe_no_contradiction
# ---------------------------------------------------------------------------


def test_safe_no_contradiction_fail_open() -> None:
    """safe_no_contradiction returns zero-risk fallback."""
    result = safe_no_contradiction("doc-42")
    assert result["document_id"] == "doc-42"
    assert result["has_contradiction"] is False
    assert result["contradicting_documents"] == []


# ---------------------------------------------------------------------------
# contradiction_report_to_quarantine_metadata
# ---------------------------------------------------------------------------


def test_quarantine_metadata_extracted_correctly() -> None:
    """contradiction_report_to_quarantine_metadata extracts all fields."""
    report = {
        "document_id": "doc-x",
        "has_contradiction": True,
        "contradicting_documents": [
            {
                "doc_id": "doc-a",
                "excerpt": "7-day return",
                "contradicting_excerpt": "30-day return",
                "contradiction_type": "direct_conflict",
                "confidence": 0.95,
            },
            {
                "doc_id": "doc-b",
                "excerpt": "escalation via email",
                "contradicting_excerpt": "escalation via phone",
                "contradiction_type": "scope_overlap",
                "confidence": 0.80,
            },
        ],
    }
    meta = contradiction_report_to_quarantine_metadata(report)
    assert meta is not None
    assert meta["contradiction_flagged"] is True
    assert meta["contradiction_count"] == 2
    assert set(meta["contradicting_doc_ids"]) == {"doc-a", "doc-b"}
    assert meta["highest_confidence"] == pytest.approx(0.95)
    assert set(meta["contradiction_types"]) == {"direct_conflict", "scope_overlap"}


def test_quarantine_metadata_returns_none_when_no_contradiction() -> None:
    """Returns None when has_contradiction=False."""
    report = {"document_id": "doc-x", "has_contradiction": False, "contradicting_documents": []}
    assert contradiction_report_to_quarantine_metadata(report) is None


def test_quarantine_metadata_returns_none_for_empty_contradicting_docs() -> None:
    """Returns None when has_contradiction=True but contradicting_documents is empty."""
    report = {"document_id": "doc-x", "has_contradiction": True, "contradicting_documents": []}
    assert contradiction_report_to_quarantine_metadata(report) is None


# ---------------------------------------------------------------------------
# INVARIANT: money/goods never in contradiction output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_money_goods_invariant_not_triggered() -> None:
    """Contradiction output never contains money/goods commitment."""
    repo = await _repo_with_sop_policy()
    contradiction_json = _contradiction_output(has_contradiction=True)
    llm = _FakeLLMClient(contradiction_json)
    agent = SOPContradictionAgent(
        llm_client=llm, tenant_configuration_repository=repo
    )

    proposal = await agent.run(_agent_input())

    assert proposal.status != AgentProposalStatus.PENDING_HUMAN_APPROVAL


# ---------------------------------------------------------------------------
# Domain-agnostic invariant
# ---------------------------------------------------------------------------


def test_domain_agnostic_no_vertical_terms() -> None:
    """SOPContradictionAgent source contains no hardcoded vertical-specific terms."""
    source = inspect.getsource(SOPContradictionAgent)
    vertical_terms = [
        "order_id", "product_sku", "purchase_date", "refund_amount",
        "e-commerce", "ecommerce", "bank_account", "telecom",
    ]
    for term in vertical_terms:
        assert term not in source, (
            f"SOPContradictionAgent contains vertical-specific term '{term}'"
        )


# ---------------------------------------------------------------------------
# KnowledgeRuntime integration tests
# ---------------------------------------------------------------------------


async def _knowledge_runtime_with_agent(
    contradiction_response: str | Exception = "{}",
) -> tuple[Any, InMemoryTenantConfigurationRepository, Any]:
    """Build a KnowledgeRuntime with a fake SOPContradictionAgent wired in."""
    from app.knowledge.runtime import KnowledgeRuntime
    from app.knowledge.persistence.memory import InMemoryKnowledgeRepository

    class _FakeEmbeddingProvider:
        provider_name = "fake"
        model_name = "fake-model"
        dimensions = 4

        async def embed_texts(
            self, *, tenant_id: str, texts: tuple[str, ...]
        ) -> list[list[float]]:
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    repo = await _repo_with_sop_policy()
    llm = _FakeLLMClient(contradiction_response)
    agent = SOPContradictionAgent(
        llm_client=llm, tenant_configuration_repository=repo
    )
    knowledge_repo = InMemoryKnowledgeRepository()
    runtime = KnowledgeRuntime(
        repository=knowledge_repo,
        tenant_configuration_repository=repo,
        embedding_provider=_FakeEmbeddingProvider(),  # type: ignore[arg-type]
        sop_contradiction_agent=agent,
    )
    return runtime, repo, knowledge_repo


async def _save_knowledge_doc(
    repo: InMemoryTenantConfigurationRepository,
    *,
    title: str,
    content: str,
    document_type: TenantKnowledgeDocumentType = TenantKnowledgeDocumentType.SOP,
    review_status: TenantKnowledgeReviewStatus = TenantKnowledgeReviewStatus.QUARANTINED,
    tenant_id: str = _TENANT,
) -> Any:
    from app.tenant.persistence.records import TenantKnowledgeDocumentRecord
    from app.tenant.identity import derive_knowledge_document_id
    from datetime import datetime, timezone

    doc_id = derive_knowledge_document_id(
        tenant_id=tenant_id,
        title=title,
        document_type=document_type,
    )
    now = datetime.now(timezone.utc)
    record = TenantKnowledgeDocumentRecord(
        document_id=doc_id,
        tenant_id=tenant_id,
        title=title,
        content=content,
        document_type=document_type,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        review_status=review_status,
        version=1,
        uploaded_by="test-admin",
        vector_indexed_at=None,
        created_at=now,
    )
    await repo.save_knowledge_document(record, expected_tenant_id=tenant_id)
    return record


@pytest.mark.asyncio
async def test_contradiction_quarantines_sop_document() -> None:
    """Contradicting SOP → document stays QUARANTINED, not indexed."""
    runtime, repo, knowledge_repo = await _knowledge_runtime_with_agent(
        _contradiction_output(document_id="doc-new", has_contradiction=True)
    )
    doc = await _save_knowledge_doc(
        repo,
        title="Return Policy v2",
        content="Returns accepted within 30 days.",
    )

    result = await runtime.ingest_document(
        tenant_id=_TENANT, document_id=doc.document_id
    )

    stored = await repo.get_knowledge_document(
        doc.document_id, expected_tenant_id=_TENANT
    )
    assert stored is not None
    assert stored.review_status == TenantKnowledgeReviewStatus.QUARANTINED
    assert stored.status == TenantKnowledgeDocumentStatus.ACTIVE
    assert result.contradiction_check_status == ContradictionCheckStatus.CHECKED_CONTRADICTION
    assert result.chunk_count == 0
    assert result.vector_count == 0
    assert result.contradiction_metadata is not None
    assert result.contradiction_metadata["contradiction_flagged"] is True


@pytest.mark.asyncio
async def test_clean_sop_proceeds_to_active() -> None:
    """Clean SOP (no contradictions) → ingests normally, check_status=CHECKED_CLEAN."""
    runtime, repo, knowledge_repo = await _knowledge_runtime_with_agent(
        _contradiction_output(
            document_id="doc-clean",
            has_contradiction=False,
            contradicting_documents=[],
        )
    )
    doc = await _save_knowledge_doc(
        repo,
        title="Escalation Procedure v1",
        content="All billing escalations go to the billing team.",
    )

    result = await runtime.ingest_document(
        tenant_id=_TENANT, document_id=doc.document_id
    )

    stored = await repo.get_knowledge_document(
        doc.document_id, expected_tenant_id=_TENANT
    )
    assert stored is not None
    assert stored.status == TenantKnowledgeDocumentStatus.ACTIVE
    assert result.contradiction_check_status == ContradictionCheckStatus.CHECKED_CLEAN
    assert result.chunk_count > 0
    assert result.vector_count > 0


@pytest.mark.asyncio
async def test_agent_unavailable_quarantines_for_human_review() -> None:
    """Agent LLM timeout → document QUARANTINED for human review, NOT silently ingested.

    BEHAVIOR CHANGE (from fail-open to fail-to-review): the previous implementation
    treated agent-unavailable as equivalent to a clean check and ingested the document
    normally. This violated the doctrine that "the check could not run" must never be
    indistinguishable from "the check passed."

    New behavior: when the contradiction agent is unavailable (any reason — LLM timeout,
    parse failure, no active policy, exception), the SOP/POLICY document is quarantined
    with status=UNCHECKED_AGENT_UNAVAILABLE. It is NOT admitted to the active KB.
    A human must verify the document before it becomes searchable.

    This is Option A (stricter): fail-to-review, not fail-open. The document is
    captured in the system but held until the known-unknown is resolved.
    """
    runtime, repo, knowledge_repo = await _knowledge_runtime_with_agent(
        TimeoutError("LLM timed out")
    )
    doc = await _save_knowledge_doc(
        repo,
        title="Warranty Policy v1",
        content="Warranty claims must be submitted within 90 days of purchase.",
    )

    result = await runtime.ingest_document(
        tenant_id=_TENANT, document_id=doc.document_id
    )

    stored = await repo.get_knowledge_document(
        doc.document_id, expected_tenant_id=_TENANT
    )
    assert stored is not None
    # Document is captured but quarantined — not admitted to the active KB.
    assert stored.review_status == TenantKnowledgeReviewStatus.QUARANTINED
    assert stored.status == TenantKnowledgeDocumentStatus.ACTIVE
    # The result clearly states WHY it was quarantined — human must review.
    assert result.contradiction_check_status == ContradictionCheckStatus.UNCHECKED_AGENT_UNAVAILABLE
    assert result.chunk_count == 0
    assert result.vector_count == 0
    assert result.contradiction_metadata is None


@pytest.mark.asyncio
async def test_contradiction_agent_not_run_for_faq_document() -> None:
    """Contradiction agent only runs for SOP/POLICY documents, not FAQ."""
    runtime, repo, knowledge_repo = await _knowledge_runtime_with_agent(
        _contradiction_output(has_contradiction=True)  # would quarantine if called
    )
    doc = await _save_knowledge_doc(
        repo,
        title="Shipping FAQ",
        content="Q: When does my order ship? A: Within 2 business days.",
        document_type=TenantKnowledgeDocumentType.FAQ,
    )

    result = await runtime.ingest_document(
        tenant_id=_TENANT, document_id=doc.document_id
    )

    # FAQ: agent never called, doc indexed normally despite LLM returning contradiction
    assert result.contradiction_check_status == ContradictionCheckStatus.NOT_APPLICABLE
    assert result.chunk_count > 0


@pytest.mark.asyncio
async def test_zero_regression_without_contradiction_agent() -> None:
    """KnowledgeRuntime without contradiction agent → NOT_APPLICABLE, zero regression."""
    from app.knowledge.runtime import KnowledgeRuntime
    from app.knowledge.persistence.memory import InMemoryKnowledgeRepository

    class _FakeEmbeddingProvider:
        provider_name = "fake"
        model_name = "fake-model"
        dimensions = 4

        async def embed_texts(
            self, *, tenant_id: str, texts: tuple[str, ...]
        ) -> list[list[float]]:
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    repo = InMemoryTenantConfigurationRepository()
    knowledge_repo = InMemoryKnowledgeRepository()
    runtime = KnowledgeRuntime(
        repository=knowledge_repo,
        tenant_configuration_repository=repo,
        embedding_provider=_FakeEmbeddingProvider(),  # type: ignore[arg-type]
        # NO sop_contradiction_agent
    )
    doc = await _save_knowledge_doc(
        repo,
        title="Standard Shipping Policy",
        content="All orders ship within 3 business days via standard carrier.",
    )

    result = await runtime.ingest_document(
        tenant_id=_TENANT, document_id=doc.document_id
    )

    assert result.contradiction_check_status == ContradictionCheckStatus.NOT_APPLICABLE
    assert result.chunk_count > 0
    assert result.vector_count > 0


@pytest.mark.asyncio
async def test_three_states_are_distinguishable() -> None:
    """CHECKED_CLEAN / CHECKED_CONTRADICTION / UNCHECKED_AGENT_UNAVAILABLE are all distinct.

    Doctrine: downstream consumers must be able to tell the difference between
    'agent checked and found it clean', 'agent found a contradiction', and
    'the check could not run'. These must never collapse into one another.
    """
    # CHECKED_CLEAN
    runtime_clean, repo_clean, _ = await _knowledge_runtime_with_agent(
        _contradiction_output(has_contradiction=False, contradicting_documents=[])
    )
    doc_clean = await _save_knowledge_doc(
        repo_clean, title="Clean Doc", content="Standard operating procedure."
    )
    result_clean = await runtime_clean.ingest_document(
        tenant_id=_TENANT, document_id=doc_clean.document_id
    )

    # CHECKED_CONTRADICTION
    runtime_contra, repo_contra, _ = await _knowledge_runtime_with_agent(
        _contradiction_output(has_contradiction=True)
    )
    doc_contra = await _save_knowledge_doc(
        repo_contra, title="Contradicting Doc", content="Returns allowed within 7 days."
    )
    result_contra = await runtime_contra.ingest_document(
        tenant_id=_TENANT, document_id=doc_contra.document_id
    )

    # UNCHECKED_AGENT_UNAVAILABLE
    runtime_unavail, repo_unavail, _ = await _knowledge_runtime_with_agent(
        TimeoutError("agent down")
    )
    doc_unavail = await _save_knowledge_doc(
        repo_unavail, title="Unchecked Doc", content="Returns allowed within 90 days."
    )
    result_unavail = await runtime_unavail.ingest_document(
        tenant_id=_TENANT, document_id=doc_unavail.document_id
    )

    # All three states are structurally distinct
    assert result_clean.contradiction_check_status == ContradictionCheckStatus.CHECKED_CLEAN
    assert result_contra.contradiction_check_status == ContradictionCheckStatus.CHECKED_CONTRADICTION
    assert result_unavail.contradiction_check_status == ContradictionCheckStatus.UNCHECKED_AGENT_UNAVAILABLE

    # CHECKED_CLEAN admits the document; the other two do not
    assert result_clean.chunk_count > 0
    assert result_contra.chunk_count == 0
    assert result_unavail.chunk_count == 0

    # The three values are all different from each other
    statuses = {
        result_clean.contradiction_check_status,
        result_contra.contradiction_check_status,
        result_unavail.contradiction_check_status,
    }
    assert len(statuses) == 3
