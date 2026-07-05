"""MVP-6 — Semantic QA Agent tests.

Tests verify all plan-specified cases plus structural invariants:
- Proposal with strong KB citations → grounding_verdict = STRONG
- Proposal with citations that don't support claims → grounding_verdict = WEAK
- LLM timeout → AgentProposal(status=REQUIRE_APPROVAL), existing QA score unaffected
- Does NOT change proposal status directly (observational only)
- Missing policy → REQUIRE_APPROVAL (never blocks flow)
- Garbage LLM output → REQUIRE_APPROVAL (fail-closed)
- parse_output: markdown code fence stripped, invalid verdict derived from score
- score_to_verdict: all four thresholds correct
- extract_semantic_grounding_score: happy path and edge cases
- SemanticGroundingVerdict enum has exactly STRONG/ADEQUATE/WEAK/MISSING
- QAScoreDimension includes SEMANTIC_GROUNDING
- INVARIANT: _check_money_goods always False (observational agent)
- INVARIANT: grounding score clamped [0, 1]
- INVARIANT: claim_scores items validated and sanitized
- Domain-agnostic: no vertical terms in SemanticQAAgent source
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from typing import Any, Sequence

import pytest

from app.agents.governed.base import AgentInput
from app.agents.governed.proposal import AgentProposalStatus
from app.agents.governed.semantic_qa import (
    SEMANTIC_QA_POLICY_TYPE,
    SEMANTIC_QA_RESULT_SCHEMA,
    SemanticQAAgent,
    extract_semantic_grounding_score,
    score_to_verdict,
)
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.governance.capability.acts import OperationalAct
from app.qa.enums import (
    QA_SCORE_DIMENSIONS,
    QAScoreDimension,
    SemanticGroundingVerdict,
)
from app.qa.persistence.records import QAScoreRecord
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.persistence import InMemoryTenantConfigurationRepository

_TENANT = "tenant-mvp6-semantic-qa"
_SESSION = "session-mvp6"
_EXECUTION = "exec-mvp6"


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
            usage=DiagnosticLLMUsage(prompt_tokens=50, completion_tokens=80, total_tokens=130),
            stop_reason="end_turn",
            raw_metadata={},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _semantic_qa_output(
    proposal_id: str = "prop-123",
    overall: float = 0.85,
    verdict: str = "STRONG",
    claims: list[dict[str, Any]] | None = None,
) -> str:
    if claims is None:
        claims = [
            {
                "segment_id": "claim-1",
                "relevance_score": overall,
                "reason": "Citation directly supports this claim.",
            }
        ]
    return json.dumps({
        "proposal_id": proposal_id,
        "claim_scores": claims,
        "overall_semantic_grounding": overall,
        "grounding_verdict": verdict,
    })


async def _repo_with_policy(
    tenant_id: str = _TENANT,
    role_description: str = "You are a QA specialist scoring citation grounding.",
) -> InMemoryTenantConfigurationRepository:
    from app.tenant.chronology import canonical_sha256
    from app.tenant.identity import derive_governance_policy_version_id
    from app.tenant.persistence import TenantGovernancePolicyRecord

    repo = InMemoryTenantConfigurationRepository()
    now = datetime.now(timezone.utc)
    params = {"role_description": role_description}
    sha = canonical_sha256({
        "tenant_id": tenant_id,
        "policy_type": SEMANTIC_QA_POLICY_TYPE,
        "parameters": params,
        "status": TenantGovernancePolicyStatus.ACTIVE.value,
        "version": 1,
        "approved_by": "admin",
        "effective_from": now.isoformat(),
        "source_approval_id": "approval-mvp6",
    })
    await repo.save_governance_policy(
        TenantGovernancePolicyRecord(
            policy_id=derive_governance_policy_version_id(
                tenant_id=tenant_id,
                policy_type=SEMANTIC_QA_POLICY_TYPE,
                version=1,
            ),
            tenant_id=tenant_id,
            policy_type=SEMANTIC_QA_POLICY_TYPE,
            parameters=params,
            status=TenantGovernancePolicyStatus.ACTIVE,
            version=1,
            approved_by="admin",
            effective_from=now,
            created_at=now,
            source_approval_id="approval-mvp6",
            content_sha256=sha,
            previous_version_sha256=None,
        ),
        expected_tenant_id=tenant_id,
    )
    return repo


def _input(
    proposal_id: str = "prop-123",
    reply_text: str = "Your order will be refunded within 5-7 business days.",
    citations: list[dict[str, Any]] | None = None,
) -> AgentInput:
    if citations is None:
        citations = [
            {
                "title": "Refund Policy v1",
                "safe_excerpt": "Refunds are processed within 5-7 business days of approval.",
                "score": 0.92,
            }
        ]
    return AgentInput(
        tenant_id=_TENANT,
        session_id=_SESSION,
        execution_id=_EXECUTION,
        content={
            "proposal_id": proposal_id,
            "reply_text": reply_text,
            "citations": citations,
        },
    )


# ---------------------------------------------------------------------------
# Plan-specified test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strong_citations_return_strong_verdict() -> None:
    """Proposal with strong KB citations → grounding_verdict = STRONG."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient(_semantic_qa_output(overall=0.90, verdict="STRONG"))
    agent = SemanticQAAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output is not None
    assert proposal.output["grounding_verdict"] == SemanticGroundingVerdict.STRONG
    assert proposal.output["overall_semantic_grounding"] == pytest.approx(0.90)


@pytest.mark.asyncio
async def test_weak_citations_return_weak_verdict() -> None:
    """Proposal with citations that don't support claims → grounding_verdict = WEAK."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient(_semantic_qa_output(
        overall=0.25,
        verdict="WEAK",
        claims=[
            {
                "segment_id": "claim-1",
                "relevance_score": 0.20,
                "reason": "The cited text discusses shipping, not refunds.",
            }
        ],
    ))
    agent = SemanticQAAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input(
        reply_text="Your refund is approved and will arrive in 3 days.",
        citations=[{
            "title": "Shipping Policy",
            "safe_excerpt": "Standard shipping takes 5-7 business days.",
            "score": 0.31,
        }],
    ))

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output is not None
    assert proposal.output["grounding_verdict"] == SemanticGroundingVerdict.WEAK
    assert proposal.output["overall_semantic_grounding"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_llm_timeout_returns_require_approval() -> None:
    """LLM failure → REQUIRE_APPROVAL — never raises, never blocks the flow."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient(TimeoutError("LLM timed out"))
    agent = SemanticQAAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "llm_invocation_failed"


@pytest.mark.asyncio
async def test_missing_policy_returns_require_approval() -> None:
    """No active semantic_qa policy → REQUIRE_APPROVAL (never hard-fails)."""
    repo = InMemoryTenantConfigurationRepository()  # empty
    llm = _FakeLLMClient(_semantic_qa_output())
    agent = SemanticQAAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "tenant_agent_policy_not_found"
    assert len(llm.calls) == 0  # LLM never called


@pytest.mark.asyncio
async def test_does_not_change_proposal_status_directly() -> None:
    """Observational: output is a SemanticQAResult, never PENDING_HUMAN_APPROVAL."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient(_semantic_qa_output(overall=0.10, verdict="MISSING"))
    agent = SemanticQAAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    # Even a MISSING verdict produces COMPLETED, not PENDING_HUMAN_APPROVAL
    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output is not None
    assert proposal.output["grounding_verdict"] == SemanticGroundingVerdict.MISSING


@pytest.mark.asyncio
async def test_garbage_output_returns_require_approval() -> None:
    """Non-JSON output → REQUIRE_APPROVAL (fail-closed)."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient("This is definitely not JSON {{ garbage }")
    agent = SemanticQAAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "llm_output_unparseable"


@pytest.mark.asyncio
async def test_adequate_verdict() -> None:
    """Citations partially support claims → ADEQUATE."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient(_semantic_qa_output(overall=0.65, verdict="ADEQUATE"))
    agent = SemanticQAAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output["grounding_verdict"] == SemanticGroundingVerdict.ADEQUATE


@pytest.mark.asyncio
async def test_missing_verdict_no_citations() -> None:
    """No citations → MISSING verdict."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient(_semantic_qa_output(overall=0.0, verdict="MISSING", claims=[]))
    agent = SemanticQAAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input(citations=[]))

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output["grounding_verdict"] == SemanticGroundingVerdict.MISSING
    assert proposal.output["overall_semantic_grounding"] == pytest.approx(0.0)
    assert proposal.output["claim_scores"] == []


# ---------------------------------------------------------------------------
# parse_output unit tests
# ---------------------------------------------------------------------------


def _make_agent() -> SemanticQAAgent:
    return SemanticQAAgent(
        llm_client=_FakeLLMClient(),
        tenant_configuration_repository=InMemoryTenantConfigurationRepository(),
    )


def test_parse_strips_markdown_code_fence() -> None:
    agent = _make_agent()
    wrapped = f"```json\n{_semantic_qa_output()}\n```"
    result = agent.parse_output(wrapped)
    assert result is not None
    assert result["grounding_verdict"] == "STRONG"


def test_parse_strips_trailing_explanation_after_fence() -> None:
    """Model sometimes appends rationale after closing ```."""
    agent = _make_agent()
    text = f"```json\n{_semantic_qa_output()}\n```\n\n**Analysis:** The citations are strong."
    result = agent.parse_output(text)
    assert result is not None
    assert result["grounding_verdict"] == "STRONG"


def test_parse_clamps_relevance_score_above_one() -> None:
    agent = _make_agent()
    raw = json.dumps({
        "proposal_id": "prop-x",
        "claim_scores": [{"segment_id": "s1", "relevance_score": 1.5, "reason": "test"}],
        "overall_semantic_grounding": 0.85,
        "grounding_verdict": "STRONG",
    })
    result = agent.parse_output(raw)
    assert result is not None
    assert result["claim_scores"][0]["relevance_score"] == pytest.approx(1.0)


def test_parse_clamps_overall_above_one() -> None:
    agent = _make_agent()
    raw = json.dumps({
        "proposal_id": "prop-x",
        "claim_scores": [],
        "overall_semantic_grounding": 1.5,
        "grounding_verdict": "STRONG",
    })
    result = agent.parse_output(raw)
    assert result is not None
    assert result["overall_semantic_grounding"] == pytest.approx(1.0)


def test_parse_derives_verdict_when_invalid() -> None:
    """Invalid grounding_verdict → derived from overall_semantic_grounding."""
    agent = _make_agent()
    raw = json.dumps({
        "proposal_id": "prop-x",
        "claim_scores": [],
        "overall_semantic_grounding": 0.75,
        "grounding_verdict": "INVALID_VERDICT",
    })
    result = agent.parse_output(raw)
    assert result is not None
    assert result["grounding_verdict"] == SemanticGroundingVerdict.ADEQUATE.value


def test_parse_rejects_missing_proposal_id() -> None:
    agent = _make_agent()
    raw = json.dumps({
        "claim_scores": [],
        "overall_semantic_grounding": 0.5,
        "grounding_verdict": "ADEQUATE",
    })
    result = agent.parse_output(raw)
    assert result is None


def test_parse_rejects_non_numeric_overall() -> None:
    agent = _make_agent()
    raw = json.dumps({
        "proposal_id": "p",
        "claim_scores": [],
        "overall_semantic_grounding": "high",
        "grounding_verdict": "STRONG",
    })
    result = agent.parse_output(raw)
    assert result is None


def test_parse_truncates_reason_to_300_chars() -> None:
    agent = _make_agent()
    long_reason = "x" * 400
    raw = json.dumps({
        "proposal_id": "p",
        "claim_scores": [{"segment_id": "s", "relevance_score": 0.5, "reason": long_reason}],
        "overall_semantic_grounding": 0.5,
        "grounding_verdict": "ADEQUATE",
    })
    result = agent.parse_output(raw)
    assert result is not None
    assert len(result["claim_scores"][0]["reason"]) == 300


# ---------------------------------------------------------------------------
# score_to_verdict tests
# ---------------------------------------------------------------------------


def test_score_to_verdict_strong() -> None:
    assert score_to_verdict(0.80) == SemanticGroundingVerdict.STRONG
    assert score_to_verdict(0.95) == SemanticGroundingVerdict.STRONG
    assert score_to_verdict(1.0) == SemanticGroundingVerdict.STRONG


def test_score_to_verdict_adequate() -> None:
    assert score_to_verdict(0.50) == SemanticGroundingVerdict.ADEQUATE
    assert score_to_verdict(0.70) == SemanticGroundingVerdict.ADEQUATE
    assert score_to_verdict(0.79) == SemanticGroundingVerdict.ADEQUATE


def test_score_to_verdict_weak() -> None:
    assert score_to_verdict(0.20) == SemanticGroundingVerdict.WEAK
    assert score_to_verdict(0.35) == SemanticGroundingVerdict.WEAK
    assert score_to_verdict(0.49) == SemanticGroundingVerdict.WEAK


def test_score_to_verdict_missing() -> None:
    assert score_to_verdict(0.0) == SemanticGroundingVerdict.MISSING
    assert score_to_verdict(0.10) == SemanticGroundingVerdict.MISSING
    assert score_to_verdict(0.19) == SemanticGroundingVerdict.MISSING


# ---------------------------------------------------------------------------
# extract_semantic_grounding_score tests
# ---------------------------------------------------------------------------


def test_extract_semantic_grounding_score_happy_path() -> None:
    assert extract_semantic_grounding_score({"overall_semantic_grounding": 0.75}) == pytest.approx(0.75)


def test_extract_semantic_grounding_score_clamps() -> None:
    assert extract_semantic_grounding_score({"overall_semantic_grounding": 1.5}) == pytest.approx(1.0)
    assert extract_semantic_grounding_score({"overall_semantic_grounding": -0.5}) == pytest.approx(0.0)


def test_extract_semantic_grounding_score_missing_key() -> None:
    assert extract_semantic_grounding_score({}) == pytest.approx(0.0)


def test_extract_semantic_grounding_score_non_numeric() -> None:
    assert extract_semantic_grounding_score({"overall_semantic_grounding": "high"}) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


def test_semantic_grounding_verdict_has_four_values() -> None:
    """SemanticGroundingVerdict has exactly STRONG/ADEQUATE/WEAK/MISSING."""
    expected = {"STRONG", "ADEQUATE", "WEAK", "MISSING"}
    actual = {v.value for v in SemanticGroundingVerdict}
    assert actual == expected


def test_qa_score_dimension_includes_semantic_grounding() -> None:
    assert QAScoreDimension.SEMANTIC_GROUNDING in QA_SCORE_DIMENSIONS
    assert QAScoreDimension.SEMANTIC_GROUNDING.value == "semantic_grounding"


def test_semantic_grounding_default_zero_on_qa_score_record() -> None:
    """QAScoreRecord.semantic_grounding defaults to 0.0 (backward-compat)."""
    from app.qa.identity import derive_qa_score_id
    record = QAScoreRecord(
        score_id=str(derive_qa_score_id(tenant_id=_TENANT, inspection_id="insp-1")),
        inspection_id="insp-1",
        execution_id="exec-1",
        tenant_id="t1",
        tenant_authority_source=None,
        diagnostic_accuracy=1.0,
        policy_compliance=1.0,
        timeline_integrity=1.0,
        resolution_quality=1.0,
        overall_score=1.0,
        supervisor_decision_kind="accept",
        finding_count=0,
        evaluation_count=0,
        escalation_count=0,
        scored_at=datetime.now(timezone.utc).isoformat(),
    )
    assert record.semantic_grounding == pytest.approx(0.0)


def test_qa_score_record_roundtrips_semantic_grounding() -> None:
    """to_dict / from_dict preserves semantic_grounding."""
    from app.qa.identity import derive_qa_score_id
    record = QAScoreRecord(
        score_id=str(derive_qa_score_id(tenant_id=_TENANT, inspection_id="insp-2")),
        inspection_id="insp-2",
        execution_id="exec-2",
        tenant_id="t1",
        tenant_authority_source=None,
        diagnostic_accuracy=0.9,
        policy_compliance=0.8,
        timeline_integrity=0.7,
        resolution_quality=0.85,
        overall_score=0.8125,
        supervisor_decision_kind="accept",
        finding_count=0,
        evaluation_count=2,
        escalation_count=0,
        scored_at=datetime.now(timezone.utc).isoformat(),
        semantic_grounding=0.76,
    )
    roundtripped = QAScoreRecord.from_dict(record.to_dict())
    assert roundtripped.semantic_grounding == pytest.approx(0.76)


def test_qa_score_record_from_dict_without_semantic_grounding() -> None:
    """from_dict with no semantic_grounding key → 0.0 (pre-migration rows)."""
    from app.qa.identity import derive_qa_score_id
    data = {
        "score_id": str(derive_qa_score_id(tenant_id=_TENANT, inspection_id="insp-3")),
        "inspection_id": "insp-3",
        "execution_id": "exec-3",
        "tenant_id": "t1",
        "tenant_authority_source": None,
        "diagnostic_accuracy": 1.0,
        "policy_compliance": 1.0,
        "timeline_integrity": 1.0,
        "resolution_quality": 1.0,
        "overall_score": 1.0,
        "supervisor_decision_kind": "accept",
        "finding_count": 0,
        "evaluation_count": 0,
        "escalation_count": 0,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        # NO semantic_grounding key — simulates pre-MVP-6 row
    }
    record = QAScoreRecord.from_dict(data)
    assert record.semantic_grounding == pytest.approx(0.0)


def test_operational_act_is_qa_score() -> None:
    assert SemanticQAAgent.operational_act == OperationalAct.QA_SCORE


def test_policy_type_constant() -> None:
    assert SEMANTIC_QA_POLICY_TYPE == "semantic_qa"
    assert SemanticQAAgent.policy_type == "semantic_qa"


def test_check_money_goods_always_false() -> None:
    """Semantic QA output never triggers money/goods gate."""
    agent = _make_agent()
    # Even if output somehow contained money-adjacent text
    result = agent._check_money_goods({
        "proposal_id": "p",
        "overall_semantic_grounding": 0.8,
        "grounding_verdict": "STRONG",
        "claim_scores": [],
    })
    assert result is False


def test_domain_agnostic_no_vertical_terms() -> None:
    """SemanticQAAgent source contains no hardcoded vertical-specific terms."""
    source = inspect.getsource(SemanticQAAgent)
    vertical_terms = [
        "order_id", "product_sku", "purchase_date", "refund_amount",
        "e-commerce", "ecommerce", "bank_account",
    ]
    for term in vertical_terms:
        assert term not in source, (
            f"SemanticQAAgent contains vertical-specific term '{term}'"
        )


def test_schema_has_required_fields() -> None:
    required = set(SEMANTIC_QA_RESULT_SCHEMA.get("required", []))
    assert "proposal_id" in required
    assert "claim_scores" in required
    assert "overall_semantic_grounding" in required
    assert "grounding_verdict" in required


@pytest.mark.asyncio
async def test_run_never_raises() -> None:
    """run() NEVER raises regardless of internal exception."""
    repo = await _repo_with_policy()

    class _ExplodingAgent(SemanticQAAgent):
        def parse_output(self, raw_text: str) -> dict[str, Any] | None:
            raise RuntimeError("parse exploded in test")

    llm = _FakeLLMClient(_semantic_qa_output())
    agent = _ExplodingAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())
    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "agent_unhandled_exception"
