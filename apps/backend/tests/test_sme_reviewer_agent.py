"""SME Reviewer Agent tests.

Tests verify all plan-specified cases plus structural invariants:
- SME case package contains accurate lineage data (verified via content structure)
- Agent LLM timeout → REQUIRE_APPROVAL (degraded, not failed — approval case proceeds)
- Money/goods: SMECasePackage never triggers money/goods gate (agent only assembles context)
- Missing policy → REQUIRE_APPROVAL (never blocks flow)
- parse_output: code fence stripping, trailing rationale, field sanitization
- INVARIANT: _check_money_goods always False (observer agent)
- INVARIANT: decision_options always exactly the canonical four
- INVARIANT: run() NEVER raises (fail-closed contract)
- Garbage LLM output → REQUIRE_APPROVAL
- recommended_resolution.confidence clamped [0, 1]
- Domain-agnostic: no vertical terms in SMEReviewerAgent source
- FRAUD_RISK_HIGH in CaseApprovalEntryCategory
- resolution_proposal_gate_reasons() reads from metadata correctly
- ResolutionProposalRecord.metadata field present and roundtrippable
- SME_DECISION_OPTIONS has exactly the four canonical values
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from typing import Any, Sequence

import pytest

from app.agents.governed.base import AgentInput
from app.agents.governed.proposal import AgentProposalStatus
from app.agents.governed.sme_reviewer import (
    SME_DECISION_OPTIONS,
    SME_CASE_PACKAGE_SCHEMA,
    SME_REVIEWER_POLICY_TYPE,
    SMEReviewerAgent,
)
from app.approvals.enums import CaseApprovalEntryCategory
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.governance.capability.acts import OperationalAct
from app.resolution.persistence.records import (
    ResolutionProposalRecord,
    resolution_proposal_gate_reasons,
)
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.persistence import InMemoryTenantConfigurationRepository

_TENANT = "tenant-sme-reviewer"
_SESSION = "session-sme"
_EXECUTION = "exec-sme"


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
            usage=DiagnosticLLMUsage(prompt_tokens=80, completion_tokens=120, total_tokens=200),
            stop_reason="end_turn",
            raw_metadata={},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sme_package_output(
    case_id: str = "case-123",
    ticket_summary: str = "Customer claims item damaged on arrival. Fraud signal detected.",
    fraud_signal: dict[str, Any] | None = None,
    evidence_summary: str = "Citation directly supports the proposed resolution.",
    lineage_trace: list[dict[str, Any]] | None = None,
    recommended_action: str = "DENY",
    reasoning: str = "High-confidence fraud signal. Pattern matches velocity + address change.",
    confidence: float = 0.80,
) -> str:
    if lineage_trace is None:
        lineage_trace = [
            {"act": "resolution_proposal", "substrate": "execution",
             "timestamp": "2026-07-04T10:00:00Z", "note": "status=pending_human_approval"}
        ]
    return json.dumps({
        "case_id": case_id,
        "ticket_summary": ticket_summary,
        "fraud_signal": fraud_signal,
        "evidence_summary": evidence_summary,
        "lineage_trace": lineage_trace,
        "recommended_resolution": {
            "action": recommended_action,
            "reasoning": reasoning,
            "confidence": confidence,
        },
        "decision_options": SME_DECISION_OPTIONS,
    })


async def _repo_with_policy(
    tenant_id: str = _TENANT,
    role_description: str = "You are an SME reviewer assembling case packages for human approval.",
) -> InMemoryTenantConfigurationRepository:
    from app.tenant.chronology import canonical_sha256
    from app.tenant.identity import derive_governance_policy_version_id
    from app.tenant.persistence import TenantGovernancePolicyRecord

    repo = InMemoryTenantConfigurationRepository()
    now = datetime.now(timezone.utc)
    params = {"role_description": role_description}
    sha = canonical_sha256({
        "tenant_id": tenant_id,
        "policy_type": SME_REVIEWER_POLICY_TYPE,
        "parameters": params,
        "status": TenantGovernancePolicyStatus.ACTIVE.value,
        "version": 1,
        "approved_by": "admin",
        "effective_from": now.isoformat(),
        "source_approval_id": "approval-sme",
    })
    await repo.save_governance_policy(
        TenantGovernancePolicyRecord(
            policy_id=derive_governance_policy_version_id(
                tenant_id=tenant_id,
                policy_type=SME_REVIEWER_POLICY_TYPE,
                version=1,
            ),
            tenant_id=tenant_id,
            policy_type=SME_REVIEWER_POLICY_TYPE,
            parameters=params,
            status=TenantGovernancePolicyStatus.ACTIVE,
            version=1,
            approved_by="admin",
            effective_from=now,
            created_at=now,
            source_approval_id="approval-sme",
            content_sha256=sha,
            previous_version_sha256=None,
        ),
        expected_tenant_id=tenant_id,
    )
    return repo


def _input(
    case_id: str = "case-123",
    ticket_text: str = "Item arrived damaged. Order #1234. Multiple claims this week.",
    proposed_reply: str = "We cannot process this request due to fraud signals.",
    fraud_signal: dict[str, Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    lineage_events: list[dict[str, Any]] | None = None,
    entry_category: str = "fraud_risk_high",
) -> AgentInput:
    if fraud_signal is None:
        fraud_signal = {
            "risk_score": 0.85,
            "signal_kinds": ["identity_mismatch", "velocity"],
            "confidence": 0.85,
            "reasoning": "High velocity + recent address change.",
        }
    if citations is None:
        citations = [
            {
                "title": "Fraud Prevention Policy",
                "safe_excerpt": "Accounts with 3+ claims per week require SME review.",
                "score": 0.91,
            }
        ]
    if lineage_events is None:
        lineage_events = [
            {"act": "fraud_signal", "substrate": "agents",
             "timestamp": "2026-07-04T09:55:00Z", "note": "score=0.85"},
            {"act": "resolution_proposal", "substrate": "execution",
             "timestamp": "2026-07-04T09:56:00Z", "note": "PENDING_HUMAN_APPROVAL"},
        ]
    return AgentInput(
        tenant_id=_TENANT,
        session_id=_SESSION,
        execution_id=_EXECUTION,
        content={
            "case_id": case_id,
            "ticket_text": ticket_text,
            "proposed_reply": proposed_reply,
            "fraud_signal": fraud_signal,
            "citations": citations,
            "lineage_events": lineage_events,
            "extracted_fields": {"order_id": "1234"},
            "entry_category": entry_category,
            "recommended_actions": [],
        },
    )


# ---------------------------------------------------------------------------
# Plan-specified test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sme_case_package_contains_accurate_lineage() -> None:
    """SME case package contains lineage data from the input context."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient(_sme_package_output(
        lineage_trace=[
            {"act": "fraud_signal", "substrate": "agents",
             "timestamp": "2026-07-04T09:55:00Z", "note": "score=0.85"},
            {"act": "resolution_proposal", "substrate": "execution",
             "timestamp": "2026-07-04T09:56:00Z", "note": "PENDING"},
        ]
    ))
    agent = SMEReviewerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output is not None
    lineage = proposal.output.get("lineage_trace", [])
    assert isinstance(lineage, list)
    assert len(lineage) >= 1
    # Each event has the required keys
    for event in lineage:
        assert "act" in event
        assert "substrate" in event
        assert "timestamp" in event


@pytest.mark.asyncio
async def test_llm_timeout_returns_require_approval_not_hard_fail() -> None:
    """LLM timeout → REQUIRE_APPROVAL (degraded, not failed). Approval case proceeds."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient(TimeoutError("LLM timed out"))
    agent = SMEReviewerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "llm_invocation_failed"


@pytest.mark.asyncio
async def test_money_goods_invariant_never_triggered() -> None:
    """SMECasePackage never triggers the money/goods gate. Agent assembles context only."""
    repo = await _repo_with_policy()
    # Even if the output contains refund/credit language in the recommended resolution
    output = _sme_package_output(recommended_action="APPROVE_AS_IS",
                                  reasoning="Customer should receive full refund of $500.")
    llm = _FakeLLMClient(output)
    agent = SMEReviewerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    # Must NOT be PENDING_HUMAN_APPROVAL — the money/goods gate must not fire
    assert proposal.status != AgentProposalStatus.PENDING_HUMAN_APPROVAL
    assert proposal.status == AgentProposalStatus.COMPLETED


@pytest.mark.asyncio
async def test_missing_policy_returns_require_approval() -> None:
    """No active sme_reviewer policy → REQUIRE_APPROVAL, LLM never called."""
    repo = InMemoryTenantConfigurationRepository()  # empty
    llm = _FakeLLMClient(_sme_package_output())
    agent = SMEReviewerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "tenant_agent_policy_not_found"
    assert len(llm.calls) == 0  # LLM never called


@pytest.mark.asyncio
async def test_garbage_output_returns_require_approval() -> None:
    """Non-JSON output → REQUIRE_APPROVAL."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient("This is definitely not JSON {{ garbage }")
    agent = SMEReviewerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())

    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "llm_output_unparseable"


@pytest.mark.asyncio
async def test_full_case_package_shape() -> None:
    """Complete case package has all required fields with correct types."""
    repo = await _repo_with_policy()
    fraud_signal = {"risk_score": 0.85, "signal_kinds": ["velocity"], "confidence": 0.9, "reasoning": "High velocity."}
    llm = _FakeLLMClient(_sme_package_output(
        case_id="case-full",
        fraud_signal=fraud_signal,
        recommended_action="DENY",
        confidence=0.88,
    ))
    agent = SMEReviewerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input(case_id="case-full", fraud_signal=fraud_signal))

    assert proposal.status == AgentProposalStatus.COMPLETED
    out = proposal.output
    assert out is not None
    assert out["case_id"] == "case-full"
    assert isinstance(out["ticket_summary"], str)
    assert isinstance(out["evidence_summary"], str)
    assert isinstance(out["lineage_trace"], list)
    rec = out["recommended_resolution"]
    assert isinstance(rec["action"], str)
    assert isinstance(rec["reasoning"], str)
    assert 0.0 <= rec["confidence"] <= 1.0
    assert out["decision_options"] == SME_DECISION_OPTIONS


@pytest.mark.asyncio
async def test_fraud_signal_null_case() -> None:
    """Package with no fraud signal (non-fraud escalation)."""
    repo = await _repo_with_policy()
    llm = _FakeLLMClient(_sme_package_output(fraud_signal=None))
    agent = SMEReviewerAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input(fraud_signal=None, entry_category="resolution_require_approval"))

    assert proposal.status == AgentProposalStatus.COMPLETED
    assert proposal.output["fraud_signal"] is None


@pytest.mark.asyncio
async def test_run_never_raises() -> None:
    """run() NEVER raises regardless of internal exception."""
    repo = await _repo_with_policy()

    class _ExplodingAgent(SMEReviewerAgent):
        def parse_output(self, raw_text: str) -> dict[str, Any] | None:
            raise RuntimeError("parse exploded in test")

    llm = _FakeLLMClient(_sme_package_output())
    agent = _ExplodingAgent(llm_client=llm, tenant_configuration_repository=repo)

    proposal = await agent.run(_input())
    assert proposal.status == AgentProposalStatus.REQUIRE_APPROVAL
    assert proposal.reason == "agent_unhandled_exception"


# ---------------------------------------------------------------------------
# parse_output unit tests
# ---------------------------------------------------------------------------


def _make_agent() -> SMEReviewerAgent:
    return SMEReviewerAgent(
        llm_client=_FakeLLMClient(),
        tenant_configuration_repository=InMemoryTenantConfigurationRepository(),
    )


def test_parse_strips_markdown_code_fence() -> None:
    agent = _make_agent()
    wrapped = f"```json\n{_sme_package_output()}\n```"
    result = agent.parse_output(wrapped)
    assert result is not None
    assert result["case_id"] == "case-123"


def test_parse_strips_trailing_rationale_after_fence() -> None:
    """Model appends rationale text after closing ``` — must be stripped."""
    agent = _make_agent()
    text = f"```json\n{_sme_package_output()}\n```\n\n**Analysis:** This case requires SME review."
    result = agent.parse_output(text)
    assert result is not None
    assert result["case_id"] == "case-123"


def test_parse_clamps_confidence() -> None:
    agent = _make_agent()
    raw = json.loads(_sme_package_output(confidence=1.5))
    raw["recommended_resolution"]["confidence"] = 1.5
    result = agent.parse_output(json.dumps(raw))
    assert result is not None
    assert result["recommended_resolution"]["confidence"] == pytest.approx(1.0)


def test_parse_enforces_decision_options_always_canonical() -> None:
    """decision_options must always be exactly the canonical four values."""
    agent = _make_agent()
    raw = json.loads(_sme_package_output())
    raw["decision_options"] = ["APPROVE_ONLY"]  # wrong
    result = agent.parse_output(json.dumps(raw))
    assert result is not None
    assert result["decision_options"] == SME_DECISION_OPTIONS


def test_parse_uses_fallback_recommended_resolution_when_missing() -> None:
    agent = _make_agent()
    raw = json.loads(_sme_package_output())
    del raw["recommended_resolution"]
    result = agent.parse_output(json.dumps(raw))
    assert result is not None
    # Fallback is ESCALATE_FURTHER
    assert result["recommended_resolution"]["action"] == "ESCALATE_FURTHER"


def test_parse_truncates_ticket_summary() -> None:
    agent = _make_agent()
    long_summary = "x" * 1500
    raw = json.loads(_sme_package_output(ticket_summary=long_summary))
    result = agent.parse_output(json.dumps(raw))
    assert result is not None
    assert len(result["ticket_summary"]) == 1000


def test_parse_rejects_missing_case_id() -> None:
    agent = _make_agent()
    raw = json.loads(_sme_package_output())
    del raw["case_id"]
    result = agent.parse_output(json.dumps(raw))
    assert result is None


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


def test_sme_decision_options_has_exactly_four_values() -> None:
    """SME_DECISION_OPTIONS has exactly the canonical four human decisions."""
    expected = {"APPROVE_AS_IS", "EDIT_AND_APPROVE", "DENY", "ESCALATE_FURTHER"}
    assert set(SME_DECISION_OPTIONS) == expected
    assert len(SME_DECISION_OPTIONS) == 4


def test_operational_act_is_sme_review_request() -> None:
    assert SMEReviewerAgent.operational_act == OperationalAct.SME_REVIEW_REQUEST


def test_policy_type_constant() -> None:
    assert SME_REVIEWER_POLICY_TYPE == "sme_reviewer"
    assert SMEReviewerAgent.policy_type == "sme_reviewer"


def test_check_money_goods_always_false() -> None:
    """SME case package output never triggers money/goods gate."""
    agent = _make_agent()
    result = agent._check_money_goods({
        "case_id": "c",
        "recommended_resolution": {"action": "APPROVE_AS_IS", "reasoning": "full refund of $500", "confidence": 0.9},
    })
    assert result is False


def test_schema_has_required_fields() -> None:
    required = set(SME_CASE_PACKAGE_SCHEMA.get("required", []))
    assert "case_id" in required
    assert "ticket_summary" in required
    assert "fraud_signal" in required
    assert "evidence_summary" in required
    assert "lineage_trace" in required
    assert "recommended_resolution" in required
    assert "decision_options" in required


def test_domain_agnostic_no_vertical_terms() -> None:
    """SMEReviewerAgent source contains no hardcoded vertical-specific terms."""
    source = inspect.getsource(SMEReviewerAgent)
    vertical_terms = [
        "order_id", "product_sku", "purchase_date", "refund_amount",
        "e-commerce", "ecommerce", "bank_account",
    ]
    for term in vertical_terms:
        assert term not in source, (
            f"SMEReviewerAgent contains vertical-specific term '{term}'"
        )


# ---------------------------------------------------------------------------
# CaseApprovalEntryCategory.FRAUD_RISK_HIGH
# ---------------------------------------------------------------------------


def test_fraud_risk_high_in_entry_categories() -> None:
    """FRAUD_RISK_HIGH is a member of CaseApprovalEntryCategory."""
    assert CaseApprovalEntryCategory.FRAUD_RISK_HIGH in list(CaseApprovalEntryCategory)
    assert CaseApprovalEntryCategory.FRAUD_RISK_HIGH.value == "fraud_risk_high"


# ---------------------------------------------------------------------------
# resolution_proposal_gate_reasons
# ---------------------------------------------------------------------------


def _make_proposal(gate_reasons: list[str] | None = None) -> ResolutionProposalRecord:
    from app.resolution.enums import (
        ResolutionAutonomyDecision,
        ResolutionGovernanceVerdict,
        ResolutionProposalStatus,
        ResolutionSupervisorVerdict,
    )
    from app.resolution.identity import as_resolution_proposal_id
    import uuid

    metadata: dict[str, Any] = {}
    if gate_reasons is not None:
        metadata["gate_reasons"] = gate_reasons

    return ResolutionProposalRecord(
        proposal_id=as_resolution_proposal_id(uuid.uuid4()),
        tenant_id=_TENANT,
        session_id=_SESSION,
        execution_id=_EXECUTION,
        dispatch_id=str(uuid.uuid4()),
        diagnostic_event_id=None,
        proposed_customer_reply="Test reply.",
        resolution_category="general",
        confidence=0.75,
        supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
        governance_verdict=ResolutionGovernanceVerdict.ESCALATE,
        autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
        status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metadata=metadata,
    )


def test_gate_reasons_extracted_from_metadata() -> None:
    """resolution_proposal_gate_reasons() reads gate_reasons from proposal.metadata."""
    proposal = _make_proposal(gate_reasons=["fraud_risk_high", "missing_citations"])
    reasons = resolution_proposal_gate_reasons(proposal)
    assert "fraud_risk_high" in reasons
    assert "missing_citations" in reasons


def test_gate_reasons_empty_when_no_metadata() -> None:
    """Empty metadata → empty tuple (backward-compat for pre-migration rows)."""
    proposal = _make_proposal(gate_reasons=None)
    reasons = resolution_proposal_gate_reasons(proposal)
    assert reasons == ()


def test_gate_reasons_empty_when_no_gate_reasons_key() -> None:
    """Metadata without gate_reasons key → empty tuple."""
    proposal = _make_proposal()
    reasons = resolution_proposal_gate_reasons(proposal)
    assert reasons == ()


def test_resolution_proposal_record_has_metadata_field() -> None:
    """ResolutionProposalRecord.metadata field exists with default={}."""
    proposal = _make_proposal()
    assert hasattr(proposal, "metadata")
    assert isinstance(proposal.metadata, dict)


def test_resolution_proposal_record_to_dict_includes_metadata() -> None:
    """to_dict() includes metadata key."""
    proposal = _make_proposal(gate_reasons=["fraud_risk_high"])
    d = proposal.to_dict()
    assert "metadata" in d
    assert "gate_reasons" in d["metadata"]
    assert "fraud_risk_high" in d["metadata"]["gate_reasons"]
