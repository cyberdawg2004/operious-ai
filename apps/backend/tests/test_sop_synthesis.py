"""SOP improvement synthesis tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.agents.sop_synthesis_agent import SOPSynthesisAgent
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.cognition.sop_improvement_models import SOPImprovementLLMOutput
from app.governance.persistence import InMemoryGovernanceRepository
from app.qa.persistence import InMemoryQAPersistence
from app.session.persistence import InMemorySessionPersistence
from app.sop_intelligence import (
    ApprovalQuery,
    InMemorySOPApprovalPersistence,
    SOPIntelligenceRuntime,
)
from app.supervisor.persistence import InMemorySupervisorRepository
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)

_TENANT_ID = "tenant-sop-synthesis"
_NOW = datetime(2026, 5, 30, 8, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_synthesis_builds_prompt_with_sop_context() -> None:
    knowledge = _FakeKnowledgeRuntime(
        (
            "For charging issues, confirm adapter and cable condition.",
            "Escalate charging failures after battery reset attempt.",
        )
    )
    llm = _RecordingLLM(_valid_payload())
    agent = SOPSynthesisAgent(
        llm_client=llm,
        knowledge_runtime=cast(Any, knowledge),
    )

    result = await agent.synthesize_improvement(
        category="charging_issue",
        failure_count=4,
        failure_description="DLQ failures during diagnostic execution.",
        tenant_id=_TENANT_ID,
    )

    assert result == "Add a charging diagnostic checklist before escalation."
    assert llm.messages is not None
    prompt = llm.messages[0].content
    assert "For charging issues, confirm adapter and cable condition." in prompt
    assert "Escalate charging failures after battery reset attempt." in prompt
    assert "Category: charging_issue" in prompt


@pytest.mark.asyncio
async def test_synthesis_falls_back_on_llm_failure() -> None:
    agent = SOPSynthesisAgent(
        llm_client=_FailingLLM(),
        knowledge_runtime=cast(Any, _FakeKnowledgeRuntime(("Existing SOP",))),
    )

    result = await agent.synthesize_improvement(
        category="charging_issue",
        failure_count=3,
        failure_description="Provider failures.",
        tenant_id=_TENANT_ID,
    )

    assert result
    assert "charging_issue" in result
    assert result.startswith("Propose updating the SOP")


def test_schema_rejects_invalid_confidence() -> None:
    payload = _valid_payload()
    payload["confidence"] = 2.0

    with pytest.raises(ValidationError):
        SOPImprovementLLMOutput.model_validate(payload)


def test_schema_rejects_unknown_fields() -> None:
    payload = _valid_payload()
    payload["unknown"] = "x"

    with pytest.raises(ValidationError):
        SOPImprovementLLMOutput.model_validate(payload)


@pytest.mark.asyncio
async def test_propose_uses_synthesized_change_when_provided() -> None:
    runtime, approvals = await _runtime()

    record = await runtime.propose_from_failure_pattern(
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
        category="charging_issue",
        recommendation_count=5,
        synthesized_proposed_change="Custom improvement text",
    )
    stored = await approvals.get_approval_record(
        record.approval_id,
        expected_tenant_id=_TENANT_ID,
    )

    assert stored is not None
    assert stored.proposed_change == "Custom improvement text"
    assert stored.metadata["synthesized_proposed_change"] is True


@pytest.mark.asyncio
async def test_propose_uses_static_when_not_provided() -> None:
    runtime, approvals = await _runtime()

    record = await runtime.propose_from_failure_pattern(
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
        category="charging_issue",
        recommendation_count=5,
    )
    page = await approvals.list_approval_records(
        ApprovalQuery(),
        expected_tenant_id=_TENANT_ID,
    )

    assert page.total == 1
    assert record.proposed_change == (
        "Propose updating 'Returns SOP' for repeated QA failures in "
        "charging_issue. Trainer recommendations flagged this category 5 "
        "times in the configured lookback window; review the SOP guidance "
        "and add corrective operator steps."
    )
    assert record.metadata["synthesized_proposed_change"] is False


def _valid_payload() -> dict[str, Any]:
    return {
        "improvement_title": "Improve charging issue handling",
        "problem_statement": "Agents need a clearer charging checklist.",
        "proposed_sop_addition": (
            "Add a charging diagnostic checklist before escalation."
        ),
        "rationale": "The checklist addresses repeated diagnostic failures.",
        "affected_sop_section": "Charging diagnostics",
        "confidence": 0.82,
    }


async def _runtime() -> tuple[
    SOPIntelligenceRuntime,
    InMemorySOPApprovalPersistence,
]:
    tenant_repo = InMemoryTenantConfigurationRepository()
    approval_repo = InMemorySOPApprovalPersistence()
    await tenant_repo.save_knowledge_document(
        _document(),
        expected_tenant_id=_TENANT_ID,
    )
    runtime = SOPIntelligenceRuntime(
        approval_persistence=approval_repo,
        session_persistence=InMemorySessionPersistence(),
        supervisor_repository=InMemorySupervisorRepository(),
        qa_persistence=InMemoryQAPersistence(),
        governance_repository=InMemoryGovernanceRepository(),
        tenant_configuration_repository=tenant_repo,
    )
    return runtime, approval_repo


def _document() -> TenantKnowledgeDocumentRecord:
    document_id = derive_knowledge_document_id(
        tenant_id=_TENANT_ID,
        title="Returns SOP",
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    return TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=_TENANT_ID,
        title="Returns SOP",
        content="Existing SOP content",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        version=3,
        uploaded_by="principal-admin",
        vector_indexed_at=None,
        created_at=_NOW,
    )


@dataclass(frozen=True, slots=True)
class _FakeKnowledgeItem:
    content: str


class _FakeKnowledgeRuntime:
    def __init__(self, contents: tuple[str, ...]) -> None:
        self._contents = contents

    async def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int = 8,
        max_tokens: int | None = None,
        max_chunks_per_document: int | None = None,
        min_score: float | None = None,
    ) -> object:
        del tenant_id, query, top_k, max_tokens, max_chunks_per_document, min_score
        return _FakeRetrieval(
            items=tuple(_FakeKnowledgeItem(content) for content in self._contents)
        )


@dataclass(frozen=True, slots=True)
class _FakeRetrieval:
    items: tuple[_FakeKnowledgeItem, ...]


class _RecordingLLM:
    provider_name = "test"
    model_name = "test-model"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.messages: tuple[DiagnosticLLMMessage, ...] | None = None

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[DiagnosticLLMMessage, ...],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, max_output_tokens, temperature, tenant_id
        self.messages = messages
        text = json.dumps(self.payload, sort_keys=True)
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=text,
            usage=DiagnosticLLMUsage(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
            raw_metadata={},
        )


class _FailingLLM:
    provider_name = "test"
    model_name = "test-model"

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[DiagnosticLLMMessage, ...],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, messages, max_output_tokens, temperature, tenant_id
        raise RuntimeError("provider unavailable")
