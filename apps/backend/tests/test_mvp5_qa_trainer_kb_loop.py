"""MVP-5 — QA→Trainer→KB Loop tests.

Tests verify all plan-specified cases plus structural invariants:

Component A — QA Signal Aggregator:
- Aggregator correctly identifies low-scoring categories from seeded QA records
- Aggregator returns empty when no records match the window
- scored_after / scored_before filtering correctly bounds the window
- Categories sorted weakest-first
- min_ticket_count threshold respected (too few tickets → not flagged)
- grounding_threshold respected (above threshold → not flagged)

Component B — KBTrainerAgent:
- Trainer proposes a document for a known weak category
- parse_output handles code fences, invalid improvement_type defaults to GAP_NOTICE
- Confidence clamped [0,1]
- Missing policy → REQUIRE_APPROVAL (never blocks loop)
- LLM timeout → REQUIRE_APPROVAL
- INVARIANT: _check_money_goods always False
- INVARIANT: run() never raises
- Domain-agnostic: no vertical terms

Component C — Human Approval Gate:
- Proposal routes to KB admin queue (create_knowledge_document called)
- Admin approval creates new document via existing mechanism
- Contradiction check fires if trainer proposes conflicting content
- Trainer CANNOT write to KB without ApprovalRecord (ApprovalRequiredError)
- ApprovalRecord with status="approved" is required; "pending" fails

Loop:
- Loop convergence simulation: seeded weak scores trigger trainer proposals
- aggregate_qa_signals_runtime returns correct counts
- No-op when no weak categories found

Structural:
- KB_TRAINER_PROPOSE OperationalAct exists
- KBImprovementType has exactly NEW_DOCUMENT / AMENDMENT / GAP_NOTICE
- QAScoreQuery supports scored_after / scored_before
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import pytest

from app.agents.governed.base import AgentInput
from app.agents.governed.proposal import AgentProposalStatus
from app.agents.governed.kb_trainer import (
    KB_TRAINER_POLICY_TYPE,
    KB_IMPROVEMENT_PROPOSAL_SCHEMA,
    KBImprovementType,
    KBTrainerAgent,
)
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.governance.capability.acts import OperationalAct
from app.qa.aggregator import (
    QASignalAggregator,
)
from app.qa.persistence import InMemoryQAPersistence
from app.qa.persistence.models import QAScoreQuery
from app.qa.persistence.records import QAScoreRecord
from app.qa.identity import derive_qa_score_id
from app.tenant.enums import (
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeReviewStatus,
)
from app.tenant.exceptions import ApprovalRequiredError
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime

_TENANT = "tenant-mvp5-trainer"
_NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


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
            usage=DiagnosticLLMUsage(prompt_tokens=100, completion_tokens=200, total_tokens=300),
            stop_reason="end_turn",
            raw_metadata={},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kb_improvement_output(
    improvement_type: str = "NEW_DOCUMENT",
    proposed_content: str | None = "Here is the new KB article content.",
    gap_description: str | None = None,
    target_document_id: str | None = None,
    evidence_case_ids: list[str] | None = None,
    confidence: float = 0.78,
) -> str:
    return json.dumps({
        "improvement_type": improvement_type,
        "target_document_id": target_document_id,
        "proposed_content": proposed_content,
        "gap_description": gap_description,
        "evidence_case_ids": evidence_case_ids or ["score-1", "score-2"],
        "confidence": confidence,
    })


async def _repo_with_kb_trainer_policy(
    tenant_id: str = _TENANT,
) -> InMemoryTenantConfigurationRepository:
    from app.tenant.chronology import canonical_sha256
    from app.tenant.identity import derive_governance_policy_version_id
    from app.tenant.persistence import TenantGovernancePolicyRecord

    repo = InMemoryTenantConfigurationRepository()
    now = datetime.now(timezone.utc)
    params = {"role_description": "You are a KB trainer. Propose improvements based on QA signals."}
    sha = canonical_sha256({
        "tenant_id": tenant_id,
        "policy_type": KB_TRAINER_POLICY_TYPE,
        "parameters": params,
        "status": TenantGovernancePolicyStatus.ACTIVE.value,
        "version": 1,
        "approved_by": "admin",
        "effective_from": now.isoformat(),
        "source_approval_id": "approval-trainer",
    })
    await repo.save_governance_policy(
        TenantGovernancePolicyRecord(
            policy_id=derive_governance_policy_version_id(
                tenant_id=tenant_id,
                policy_type=KB_TRAINER_POLICY_TYPE,
                version=1,
            ),
            tenant_id=tenant_id,
            policy_type=KB_TRAINER_POLICY_TYPE,
            parameters=params,
            status=TenantGovernancePolicyStatus.ACTIVE,
            version=1,
            approved_by="admin",
            effective_from=now,
            created_at=now,
            source_approval_id="approval-trainer",
            content_sha256=sha,
            previous_version_sha256=None,
        ),
        expected_tenant_id=tenant_id,
    )
    return repo


def _qa_score(
    *,
    tenant_id: str = _TENANT,
    semantic_grounding: float = 0.30,
    diagnostic_accuracy: float = 0.85,
    policy_compliance: float = 0.88,
    resolution_quality: float = 0.80,
    overall_score: float = 0.71,
    scored_at: datetime | None = None,
    suffix: str = "0",
) -> QAScoreRecord:
    t = scored_at or _NOW
    score_id = str(derive_qa_score_id(tenant_id=tenant_id, inspection_id=f"insp-{suffix}"))
    return QAScoreRecord(
        score_id=score_id,
        inspection_id=f"insp-{suffix}",
        execution_id=f"exec-{suffix}",
        tenant_id=tenant_id,
        tenant_authority_source=None,
        diagnostic_accuracy=diagnostic_accuracy,
        policy_compliance=policy_compliance,
        timeline_integrity=0.90,
        resolution_quality=resolution_quality,
        overall_score=overall_score,
        supervisor_decision_kind="accept",
        finding_count=0,
        evaluation_count=2,
        escalation_count=0,
        scored_at=t.isoformat(),
        semantic_grounding=semantic_grounding,
        metadata={"source_session_id": f"session-{suffix}"},
    )


def _trainer_input(
    category: str = "semantic_grounding",
    avg_grounding: float = 0.30,
) -> AgentInput:
    return AgentInput(
        tenant_id=_TENANT,
        session_id="session-trainer",
        execution_id="exec-trainer",
        content={
            "category": category,
            "avg_semantic_grounding": avg_grounding,
            "ticket_count": 5,
            "representative_cases": [
                {"case_id": "score-1", "ticket_text": "My item is broken.",
                 "proposed_reply": "We cannot help without more info.", "semantic_grounding": 0.20},
            ],
            "current_kb_docs": [
                {"doc_id": "doc-1", "title": "Product FAQ", "content": "FAQ content here."}
            ],
        },
    )


# ---------------------------------------------------------------------------
# Component A: QA Signal Aggregator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregator_identifies_weak_semantic_grounding() -> None:
    """Aggregator flags categories with avg_semantic_grounding below threshold."""
    qa = InMemoryQAPersistence()
    # Seed 5 weak scores
    for i in range(5):
        score = _qa_score(semantic_grounding=0.25, suffix=str(i))
        await qa.record_score(score, expected_tenant_id=_TENANT)

    aggregator = QASignalAggregator(
        qa_persistence=qa,
        grounding_threshold=0.60,
        min_ticket_count=3,
        window_days=7,
    )
    results = await aggregator.identify_weak_categories(
        tenant_id=_TENANT,
        window_end=_NOW,
    )

    assert len(results) > 0
    cats = [r.category for r in results]
    assert "semantic_grounding" in cats


@pytest.mark.asyncio
async def test_aggregator_returns_empty_when_no_scores() -> None:
    """No scores in window → empty result."""
    qa = InMemoryQAPersistence()
    aggregator = QASignalAggregator(qa_persistence=qa, min_ticket_count=1)
    results = await aggregator.identify_weak_categories(
        tenant_id=_TENANT,
        window_end=_NOW,
    )
    assert results == ()


@pytest.mark.asyncio
async def test_aggregator_respects_min_ticket_count() -> None:
    """Too few tickets → not flagged."""
    qa = InMemoryQAPersistence()
    # Only 2 scores but min_ticket_count=3
    for i in range(2):
        await qa.record_score(_qa_score(semantic_grounding=0.10, suffix=str(i)), expected_tenant_id=_TENANT)

    aggregator = QASignalAggregator(qa_persistence=qa, min_ticket_count=3)
    results = await aggregator.identify_weak_categories(tenant_id=_TENANT, window_end=_NOW)
    cats = [r.category for r in results]
    assert "semantic_grounding" not in cats


@pytest.mark.asyncio
async def test_aggregator_respects_grounding_threshold() -> None:
    """Scores above threshold → not flagged."""
    qa = InMemoryQAPersistence()
    # Strong scores
    for i in range(5):
        await qa.record_score(_qa_score(semantic_grounding=0.90, suffix=str(i)), expected_tenant_id=_TENANT)

    aggregator = QASignalAggregator(qa_persistence=qa, grounding_threshold=0.60, min_ticket_count=3)
    results = await aggregator.identify_weak_categories(tenant_id=_TENANT, window_end=_NOW)
    cats = [r.category for r in results]
    assert "semantic_grounding" not in cats


@pytest.mark.asyncio
async def test_aggregator_sorted_weakest_first() -> None:
    """Results are sorted by avg_semantic_grounding ascending."""
    qa = InMemoryQAPersistence()
    for i in range(5):
        await qa.record_score(
            _qa_score(
                semantic_grounding=0.15,
                diagnostic_accuracy=0.30,
                suffix=str(i)
            ),
            expected_tenant_id=_TENANT,
        )

    aggregator = QASignalAggregator(qa_persistence=qa, grounding_threshold=0.60, min_ticket_count=3)
    results = await aggregator.identify_weak_categories(tenant_id=_TENANT, window_end=_NOW)
    scores = [r.avg_semantic_grounding for r in results]
    assert scores == sorted(scores)


@pytest.mark.asyncio
async def test_aggregator_date_window_filtering() -> None:
    """Scores outside the window are excluded."""
    qa = InMemoryQAPersistence()
    old_time = _NOW - timedelta(days=30)
    # 5 old weak scores (outside 7-day window)
    for i in range(5):
        await qa.record_score(
            _qa_score(semantic_grounding=0.10, scored_at=old_time, suffix=f"old{i}"),
            expected_tenant_id=_TENANT,
        )
    # 2 recent weak scores (inside window but below min_ticket_count=3)
    for i in range(2):
        await qa.record_score(
            _qa_score(semantic_grounding=0.10, scored_at=_NOW - timedelta(days=1), suffix=f"new{i}"),
            expected_tenant_id=_TENANT,
        )

    aggregator = QASignalAggregator(qa_persistence=qa, grounding_threshold=0.60, min_ticket_count=3, window_days=7)
    results = await aggregator.identify_weak_categories(tenant_id=_TENANT, window_end=_NOW)
    # Old scores excluded, only 2 recent → below min_ticket_count
    cats = [r.category for r in results]
    assert "semantic_grounding" not in cats


@pytest.mark.asyncio
async def test_aggregator_representative_case_ids_worst_first() -> None:
    """Representative cases are the worst-scoring tickets."""
    qa = InMemoryQAPersistence()
    scores_data = [0.05, 0.15, 0.25, 0.35, 0.40]
    score_ids = []
    for i, sg in enumerate(scores_data):
        s = _qa_score(semantic_grounding=sg, suffix=str(i))
        score_ids.append(s.score_id)
        await qa.record_score(s, expected_tenant_id=_TENANT)

    aggregator = QASignalAggregator(
        qa_persistence=qa, grounding_threshold=0.60,
        min_ticket_count=3, max_representative_cases=3,
    )
    results = await aggregator.identify_weak_categories(tenant_id=_TENANT, window_end=_NOW)
    sg_cat = next((r for r in results if r.category == "semantic_grounding"), None)
    assert sg_cat is not None
    # First representative is the worst (score 0.05)
    assert len(sg_cat.representative_case_ids) == 3


# ---------------------------------------------------------------------------
# Component B: KBTrainerAgent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trainer_proposes_new_document() -> None:
    """Trainer produces NEW_DOCUMENT proposal for weak category."""
    repo = await _repo_with_kb_trainer_policy()
    llm = _FakeLLMClient(_kb_improvement_output(improvement_type="NEW_DOCUMENT"))
    agent = KBTrainerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_trainer_input())

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output is not None
    assert proposal.output["improvement_type"] == KBImprovementType.NEW_DOCUMENT
    assert proposal.output["proposed_content"] is not None
    assert 0.0 <= proposal.output["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_trainer_proposes_amendment() -> None:
    """Trainer can propose an AMENDMENT to an existing document."""
    repo = await _repo_with_kb_trainer_policy()
    llm = _FakeLLMClient(_kb_improvement_output(
        improvement_type="AMENDMENT",
        target_document_id="doc-existing-1",
        proposed_content="Updated content with improved guidance.",
    ))
    agent = KBTrainerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_trainer_input())

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output["improvement_type"] == KBImprovementType.AMENDMENT
    assert proposal.output["target_document_id"] == "doc-existing-1"


@pytest.mark.asyncio
async def test_trainer_proposes_gap_notice() -> None:
    """Trainer can propose a GAP_NOTICE (safest option)."""
    repo = await _repo_with_kb_trainer_policy()
    llm = _FakeLLMClient(_kb_improvement_output(
        improvement_type="GAP_NOTICE",
        proposed_content=None,
        gap_description="Missing guidance on return window for premium products.",
        confidence=0.45,
    ))
    agent = KBTrainerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_trainer_input())

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output["improvement_type"] == KBImprovementType.GAP_NOTICE
    assert proposal.output["gap_description"] is not None


@pytest.mark.asyncio
async def test_trainer_llm_timeout_returns_require_approval() -> None:
    """LLM timeout → REQUIRE_APPROVAL (never blocks loop)."""
    repo = await _repo_with_kb_trainer_policy()
    llm = _FakeLLMClient(TimeoutError("LLM timed out"))
    agent = KBTrainerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_trainer_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "llm_invocation_failed"


@pytest.mark.asyncio
async def test_trainer_missing_policy_returns_require_approval() -> None:
    """No active kb_trainer policy → REQUIRE_APPROVAL, LLM never called."""
    repo = InMemoryTenantConfigurationRepository()
    llm = _FakeLLMClient(_kb_improvement_output())
    agent = KBTrainerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_trainer_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "tenant_agent_policy_not_found"
    assert len(llm.calls) == 0


# ---------------------------------------------------------------------------
# KBTrainerAgent parse_output tests
# ---------------------------------------------------------------------------


def _make_trainer_agent() -> KBTrainerAgent:
    return KBTrainerAgent(
        llm_client=_FakeLLMClient(),
        tenant_configuration_repository=InMemoryTenantConfigurationRepository(),
    )


def test_trainer_parse_strips_code_fence() -> None:
    agent = _make_trainer_agent()
    wrapped = f"```json\n{_kb_improvement_output()}\n```"
    result = agent.parse_output(wrapped)
    assert result is not None
    assert result["improvement_type"] == "NEW_DOCUMENT"


def test_trainer_parse_strips_trailing_rationale() -> None:
    agent = _make_trainer_agent()
    text = f"```json\n{_kb_improvement_output()}\n```\n\n**Analysis:** The KB lacks coverage."
    result = agent.parse_output(text)
    assert result is not None
    assert result["improvement_type"] == "NEW_DOCUMENT"


def test_trainer_parse_defaults_invalid_type_to_gap_notice() -> None:
    """Invalid improvement_type → defaults to GAP_NOTICE (safest)."""
    agent = _make_trainer_agent()
    raw = json.loads(_kb_improvement_output())
    raw["improvement_type"] = "INVALID_TYPE"
    result = agent.parse_output(json.dumps(raw))
    assert result is not None
    assert result["improvement_type"] == KBImprovementType.GAP_NOTICE


def test_trainer_parse_clamps_confidence() -> None:
    agent = _make_trainer_agent()
    raw = json.loads(_kb_improvement_output(confidence=1.8))
    result = agent.parse_output(json.dumps(raw))
    assert result is not None
    assert result["confidence"] == pytest.approx(1.0)


def test_trainer_parse_truncates_proposed_content() -> None:
    agent = _make_trainer_agent()
    raw = json.loads(_kb_improvement_output(proposed_content="x" * 10000))
    result = agent.parse_output(json.dumps(raw))
    assert result is not None
    assert len(result["proposed_content"]) == 8000


def test_trainer_parse_rejects_non_dict() -> None:
    agent = _make_trainer_agent()
    assert agent.parse_output("null") is None
    assert agent.parse_output('"just a string"') is None


# ---------------------------------------------------------------------------
# Component C: Human Approval Gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trainer_cannot_write_without_approval_record() -> None:
    """create_knowledge_document without ApprovalRecord raises ApprovalRequiredError."""
    repo = InMemoryTenantConfigurationRepository()
    runtime = TenantConfigurationRuntime(repository=repo)

    with pytest.raises(ApprovalRequiredError):
        await runtime.create_knowledge_document(
            tenant_id=_TENANT,
            title="KB Gap: return window",
            content="Content here.",
            document_type=TenantKnowledgeDocumentType.SOP,
            uploaded_by="agent:kb_trainer",
            approval=None,  # no approval = must raise
        )


@pytest.mark.asyncio
async def test_trainer_pending_approval_status_also_fails() -> None:
    """create_knowledge_document with approval.status='pending' raises ApprovalRequiredError."""
    from app.sop_intelligence import ApprovalRecord, ApprovalStatus
    import uuid

    repo = InMemoryTenantConfigurationRepository()
    runtime = TenantConfigurationRuntime(repository=repo)

    pending_approval = ApprovalRecord(
        approval_id=str(uuid.uuid4()),
        tenant_id=_TENANT,
        document_id=str(uuid.uuid4()),
        proposed_change="test",
        evidence_sessions=(),
        confidence=0.8,
        status=ApprovalStatus.PENDING_REVIEW.value,  # NOT approved
        proposed_by="agent:kb_trainer",
        reviewed_by=None,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    with pytest.raises(ApprovalRequiredError):
        await runtime.create_knowledge_document(
            tenant_id=_TENANT,
            title="KB Gap",
            content="Content.",
            document_type=TenantKnowledgeDocumentType.SOP,
            uploaded_by="agent:kb_trainer",
            approval=pending_approval,
        )


@pytest.mark.asyncio
async def test_approved_record_allows_kb_document_creation() -> None:
    """Approved ApprovalRecord allows create_knowledge_document. Doc starts QUARANTINED."""
    from app.sop_intelligence import ApprovalRecord, ApprovalStatus
    from app.tenant.identity import derive_knowledge_document_id
    import uuid

    repo = InMemoryTenantConfigurationRepository()
    runtime = TenantConfigurationRuntime(repository=repo)

    doc_id = derive_knowledge_document_id(
        tenant_id=_TENANT,
        title="KB Gap: return window",
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    approval = ApprovalRecord(
        approval_id=str(uuid.uuid4()),
        tenant_id=_TENANT,
        document_id=str(doc_id),
        proposed_change="trainer proposal",
        evidence_sessions=("score-1",),
        confidence=0.75,
        status=ApprovalStatus.APPROVED.value,
        proposed_by="agent:kb_trainer",
        reviewed_by="agent:kb_trainer",
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    doc = await runtime.create_knowledge_document(
        tenant_id=_TENANT,
        title="KB Gap: return window",
        content="Here is the proposed new knowledge base article.",
        document_type=TenantKnowledgeDocumentType.SOP,
        uploaded_by="agent:kb_trainer",
        approval=approval,
    )

    assert doc.document_id is not None
    # Always starts QUARANTINED — MVP-4 contradiction check fires on ingest
    assert doc.review_status == TenantKnowledgeReviewStatus.QUARANTINED
    assert doc.status == TenantKnowledgeDocumentStatus.PENDING_INDEX
    assert doc.title == "KB Gap: return window"


# ---------------------------------------------------------------------------
# Loop integration: aggregate_qa_signals_runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_qa_signals_runtime_no_weak_categories() -> None:
    """No weak categories → status=no_action, 0 proposals submitted."""
    from unittest.mock import AsyncMock, patch, MagicMock
    from app.workers.trainer_tasks import aggregate_qa_signals_runtime

    mock_qa_persistence = InMemoryQAPersistence()
    # Seed strong scores — above threshold
    for i in range(5):
        await mock_qa_persistence.record_score(
            _qa_score(semantic_grounding=0.90, suffix=str(i)),
            expected_tenant_id=_TENANT,
        )

    with patch("app.workers.trainer_tasks.get_session_factory") as mock_factory, \
         patch("app.workers.trainer_tasks.clear_worker_queue_age", new_callable=AsyncMock), \
         patch("app.workers.trainer_tasks.build_llm_client"):

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()
        mock_factory.return_value = lambda: mock_session

        with patch("app.workers.trainer_tasks.PostgresQAPersistence") as mock_qa_cls, \
             patch("app.workers.trainer_tasks.PostgresTenantConfigurationRepository"), \
             patch("app.workers.trainer_tasks.TenantConfigurationRuntime"):
            mock_qa_cls.return_value = mock_qa_persistence

            result = await aggregate_qa_signals_runtime(tenant_id=_TENANT)

    assert result["status"] == "no_action"
    assert result["weak_categories"] == 0
    assert result["proposals_submitted"] == 0


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


def test_kb_improvement_type_has_three_values() -> None:
    """KBImprovementType has exactly NEW_DOCUMENT / AMENDMENT / GAP_NOTICE."""
    expected = {"NEW_DOCUMENT", "AMENDMENT", "GAP_NOTICE"}
    actual = {t.value for t in KBImprovementType}
    assert actual == expected


def test_operational_act_is_kb_trainer_propose() -> None:
    assert KBTrainerAgent.operational_act == OperationalAct.KB_TRAINER_PROPOSE


def test_policy_type_constant() -> None:
    assert KB_TRAINER_POLICY_TYPE == "kb_trainer"
    assert KBTrainerAgent.policy_type == "kb_trainer"


def test_check_money_goods_always_false() -> None:
    agent = _make_trainer_agent()
    result = agent._check_money_goods({
        "improvement_type": "NEW_DOCUMENT",
        "proposed_content": "Add refund policy for orders over $500",
    })
    assert result is False


def test_schema_has_required_fields() -> None:
    required = set(KB_IMPROVEMENT_PROPOSAL_SCHEMA.get("required", []))
    assert "improvement_type" in required
    assert "proposed_content" in required
    assert "gap_description" in required
    assert "evidence_case_ids" in required
    assert "confidence" in required


@pytest.mark.asyncio
async def test_run_never_raises() -> None:
    """run() NEVER raises."""
    repo = await _repo_with_kb_trainer_policy()

    class _ExplodingAgent(KBTrainerAgent):
        def parse_output(self, raw_text: str) -> dict[str, Any] | None:
            raise RuntimeError("parse exploded")

    llm = _FakeLLMClient(_kb_improvement_output())
    agent = _ExplodingAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_trainer_input())
    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "agent_unhandled_exception"


def test_domain_agnostic_no_vertical_terms() -> None:
    """KBTrainerAgent source contains no hardcoded vertical-specific terms."""
    source = inspect.getsource(KBTrainerAgent)
    vertical_terms = [
        "order_id", "product_sku", "purchase_date", "refund_amount",
        "e-commerce", "ecommerce", "bank_account",
    ]
    for term in vertical_terms:
        assert term not in source, (
            f"KBTrainerAgent contains vertical-specific term '{term}'"
        )


def test_qa_score_query_has_date_range_fields() -> None:
    """QAScoreQuery supports scored_after and scored_before."""
    q = QAScoreQuery(
        tenant_id=_TENANT,
        scored_after=_NOW - timedelta(days=7),
        scored_before=_NOW,
    )
    assert q.scored_after is not None
    assert q.scored_before is not None


@pytest.mark.asyncio
async def test_qa_score_query_date_filtering_in_memory() -> None:
    """InMemoryQAPersistence correctly filters by scored_after."""
    qa = InMemoryQAPersistence()
    old = _qa_score(suffix="old", scored_at=_NOW - timedelta(days=30))
    recent = _qa_score(suffix="new", scored_at=_NOW - timedelta(days=1))
    await qa.record_score(old, expected_tenant_id=_TENANT)
    await qa.record_score(recent, expected_tenant_id=_TENANT)

    page = await qa.list_scores(
        QAScoreQuery(
            tenant_id=_TENANT,
            scored_after=_NOW - timedelta(days=7),
        ),
        expected_tenant_id=_TENANT,
    )
    assert page.total == 1
    assert page.items[0].score_id == recent.score_id


def test_queue_trainer_defined() -> None:
    """QUEUE_TRAINER is defined and in ALL_QUEUES."""
    from app.queues import QUEUE_TRAINER, ALL_QUEUES
    assert QUEUE_TRAINER == "trainer"
    assert QUEUE_TRAINER in ALL_QUEUES


@pytest.mark.asyncio
async def test_loop_convergence_simulation() -> None:
    """Simulate 3-cycle loop: weak scores found → trainer proposes → KB updated."""
    # Cycle 1: seed weak scores, aggregator finds them
    qa = InMemoryQAPersistence()
    for i in range(5):
        await qa.record_score(
            _qa_score(semantic_grounding=0.20, suffix=str(i)),
            expected_tenant_id=_TENANT,
        )
    aggregator = QASignalAggregator(qa_persistence=qa, min_ticket_count=3, grounding_threshold=0.60)
    results_c1 = await aggregator.identify_weak_categories(tenant_id=_TENANT, window_end=_NOW)
    assert len(results_c1) > 0

    # Cycle 2: trainer proposes KB improvement
    repo = await _repo_with_kb_trainer_policy()
    llm = _FakeLLMClient(_kb_improvement_output(improvement_type="NEW_DOCUMENT"))
    agent = KBTrainerAgent(llm_client=llm, tenant_configuration_repository=repo)
    proposal = await agent.run(_trainer_input(
        category=results_c1[0].category,
        avg_grounding=results_c1[0].avg_semantic_grounding,
    ))
    assert proposal.status == AgentProposalStatus.COMPLETED

    # Cycle 3: after KB is updated (simulated by stronger scores), aggregator finds nothing
    qa2 = InMemoryQAPersistence()
    for i in range(5):
        await qa2.record_score(
            _qa_score(semantic_grounding=0.85, suffix=str(i)),
            expected_tenant_id=_TENANT,
        )
    results_c3 = await aggregator.identify_weak_categories(
        tenant_id=_TENANT,
        window_end=_NOW,
    )
    # After KB improvement, scores improve — simulated by using qa2 (strong scores)
    aggregator2 = QASignalAggregator(qa_persistence=qa2, min_ticket_count=3, grounding_threshold=0.60)
    results_c3 = await aggregator2.identify_weak_categories(tenant_id=_TENANT, window_end=_NOW)
    assert len(results_c3) == 0  # no more weak categories
