"""Cross-boundary contract alignment invariants."""

from __future__ import annotations

import ast
import hashlib
import inspect
import re
import textwrap
import uuid
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, get_type_hints

import pytest

from app.agents.diagnostic_agent import DiagnosticResult
from app.cognition.diagnostic_runtime import _retrieved_citations_payload
from app.db.models.admission import AdmissionRecordRow
from app.execution import runtime as execution_runtime_module
from app.execution.enums import (
    ExecutionAttemptState,
    ExecutionOutboxState,
    ExecutionState,
)
from app.execution.persistence import memory as execution_memory_module
from app.execution.persistence import postgres as execution_postgres_module
from app.execution.persistence.records import ExecutionOutboxRecord
from app.governance.context import GovernanceContext
from app.governance.enums import Decision, EnforcementStage
from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
from app.governance.subjects.base import (
    GenericGovernanceSubject,
    SubjectKind,
)
from app.governance.subjects.capability import CapabilityGovernanceSubject
from app.governance.subjects.communication import CommunicationGovernanceSubject
from app.governance.subjects.execution import ExecutionGovernanceSubject
from app.governance.subjects.retrieval import RetrievalGovernanceSubject
from app.identity import coerce_tenant_id
from app.knowledge.identity import as_chunk_id, as_document_id, as_vector_id
from app.knowledge.models import (
    KnowledgeCitation,
    KnowledgeRetrievalItem,
    KnowledgeRetrievalResult,
)
from app.models.timeline import TimelineEvent
from app.resolution.db.models import (
    ResolutionOutboundDraftRow,
    ResolutionProposalRow,
)
from app.resolution.enums import (
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
)
from app.resolution.persistence import (
    InMemoryResolutionProposalPersistence,
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)
from app.runtime.resolution_governance_gate import (
    ResolutionCommunicationPolicy,
    _communication_subject,
)
from app.runtime.resolution_runtime import (
    ResolutionGovernanceGateRequest,
    ResolutionGovernanceGateResult,
    ResolutionOutboundDraftRuntime,
    ResolutionProposalRequest,
    ResolutionRuntime,
    resolution_outbound_draft_timeline_payload,
    resolution_proposal_is_send_eligible,
    resolution_proposal_timeline_payload,
)
from app.session.enums import SessionContinuityMode, SessionEventKind
from app.session.identity import as_session_id, derive_event_id
from app.session.models.timeline_event import SessionTimelineEvent
from app.execution.celery_publisher import CeleryExecutionPublisher
from app.workers import agent_tasks
from app.workers.agent_tasks import (
    _DiagnosticExecutionWorkItem,
    _dead_letter_task_payload,
    _prepare_diagnostic_execution,
    execute_diagnostic_agent,
)


TENANT_ID = "tenant-contract"
SESSION_ID = "11111111-1111-4111-8111-111111111111"
EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
DISPATCH_ID = "33333333-3333-4333-8333-333333333333"
DIAGNOSTIC_EVENT_ID = "44444444-4444-4444-8444-444444444444"
GOVERNANCE_DECISION_ID = uuid.UUID("99999999-9999-4999-8999-999999999999")


class _StaticResolutionGovernanceGate:
    def __init__(
        self,
        verdict: ResolutionGovernanceVerdict,
        decision_id: uuid.UUID | None = GOVERNANCE_DECISION_ID,
    ) -> None:
        self._verdict = verdict
        self._decision_id = decision_id
        self.requests: list[ResolutionGovernanceGateRequest] = []

    async def evaluate_resolution_proposal(
        self,
        request: ResolutionGovernanceGateRequest,
    ) -> ResolutionGovernanceGateResult:
        self.requests.append(request)
        return ResolutionGovernanceGateResult(
            governance_verdict=self._verdict,
            governance_decision_id=self._decision_id,
        )


def _citation() -> dict[str, object]:
    return {
        "rank": 1,
        "document_id": "55555555-5555-4555-8555-555555555555",
        "title": "Charging Troubleshooting SOP",
        "document_type": "sop",
        "document_status": "active",
        "score": 0.92,
        "chunk_ordinal": 0,
        "token_count": 128,
    }


def _immutable_citation() -> dict[str, object]:
    safe_excerpt = "Check USB-C cable fit before warranty replacement triage."
    citation = _citation()
    citation.update(
        {
            "citation_schema_version": 2,
            "chunk_id": "66666666-6666-4666-8666-666666666666",
            "vector_id": "77777777-7777-4777-8777-777777777777",
            "document_version": 3,
            "char_start": 12,
            "char_end": 69,
            "vector_index_name": "tenant_knowledge_default",
            "safe_excerpt": safe_excerpt,
            "safe_excerpt_sha256": hashlib.sha256(
                safe_excerpt.encode("utf-8")
            ).hexdigest(),
            "chunk_content_hash": "sha256:charging-sop-chunk",
        }
    )
    return citation


def _proposal_request(
    *,
    citations: list[dict[str, object]] | None = None,
) -> ResolutionProposalRequest:
    return ResolutionProposalRequest(
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=DIAGNOSTIC_EVENT_ID,
        diagnostic_summary="Charging issue found.",
        diagnostic_category="charging_issue",
        diagnostic_confidence=0.91,
        original_content="My PowerCore stopped charging.",
        retrieved_citations=citations if citations is not None else [_citation()],
    )


async def _send_eligible_proposal(
) -> tuple[ResolutionProposalRecord, _StaticResolutionGovernanceGate]:
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ALLOW)
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=gate,
    ).create_proposal(_proposal_request(citations=[_immutable_citation()]))
    return record, gate


def _dataclass_field_names(record_type: type[Any]) -> set[str]:
    return {field.name for field in fields(record_type)}


def _session_timeline_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    sequence: int,
) -> SessionTimelineEvent:
    session_id = as_session_id(SESSION_ID)
    now = datetime.now(timezone.utc)
    return SessionTimelineEvent(
        event_id=derive_event_id(session_id=session_id, sequence=sequence),
        session_id=session_id,
        sequence=sequence,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=now,
        recorded_at=now,
        payload={
            "event_type": event_type,
            "payload": payload,
        },
    )


def _orm_column_names(row_type: type[Any]) -> set[str]:
    return set(row_type.__table__.columns.keys())


def _apply_async_kwarg_keys(function: object) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "apply_async":
            continue
        for keyword in node.keywords:
            if keyword.arg != "kwargs" or not isinstance(keyword.value, ast.Dict):
                continue
            for key in keyword.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
    if not keys:
        raise AssertionError("apply_async kwargs dict was not found")
    return keys


def _constructor_keyword_names(function: object, constructor_name: str) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != constructor_name:
            continue
        names.update(
            keyword.arg
            for keyword in node.keywords
            if keyword.arg is not None
        )
    if not names:
        raise AssertionError(f"{constructor_name} constructor call was not found")
    return names


def test_diagnostic_timeline_payload_matches_diagnostic_result_contract() -> None:
    result = DiagnosticResult(
        summary="Charging issue found.",
        category="charging_issue",
        confidence=0.91,
    )

    payload = result.model_dump()

    assert agent_tasks._COMPLETED == "diagnostic_analysis_completed"
    assert set(DiagnosticResult.model_fields) <= set(payload)
    assert payload["retrieved_citations"] == []
    assert DiagnosticResult.model_fields["retrieved_citations"].is_required() is False


def test_projected_diagnostic_timeline_payload_carries_span_provenance() -> None:
    event = _session_timeline_event(
        event_type="diagnostic_analysis_completed",
        payload={
            "category": "charging_issue",
            "confidence": 0.91,
            "summary": "Charging issue found.",
            "governance_decision_id": str(GOVERNANCE_DECISION_ID),
            "retrieved_citations": [_immutable_citation()],
        },
        sequence=1,
    )

    projected = TimelineEvent.from_session_event(event)

    assert projected.payload["retrieved_citations"][0]["char_start"] == 12
    assert projected.payload["retrieved_citations"][0]["char_end"] == 69


@pytest.mark.asyncio
async def test_resolution_proposal_timeline_payload_alignment() -> None:
    record, _gate = await _send_eligible_proposal()

    payload = resolution_proposal_timeline_payload(record)

    assert {
        "proposal_id",
        "status",
        "governance_decision_id",
        "send_eligible",
        "evidence",
        "proposed_customer_reply",
    } <= set(payload)
    assert payload["proposal_id"] == str(record.proposal_id)
    assert payload["status"] == ResolutionProposalStatus.SEND_ELIGIBLE.value
    assert payload["governance_decision_id"] == str(GOVERNANCE_DECISION_ID)
    assert payload["evidence"] == [dict(item) for item in record.evidence]
    assert payload["proposed_customer_reply"] == record.proposed_customer_reply
    assert payload["send_eligible"] is resolution_proposal_is_send_eligible(record)


@pytest.mark.asyncio
async def test_projected_resolution_timeline_payload_carries_span_provenance() -> None:
    record, _gate = await _send_eligible_proposal()
    event = _session_timeline_event(
        event_type="resolution_proposal_created",
        payload=resolution_proposal_timeline_payload(record),
        sequence=2,
    )

    projected = TimelineEvent.from_session_event(event)

    assert projected.payload["evidence"][0]["char_start"] == 12
    assert projected.payload["evidence"][0]["char_end"] == 69


@pytest.mark.asyncio
async def test_resolution_outbound_draft_timeline_payload_alignment() -> None:
    proposal, _gate = await _send_eligible_proposal()
    persistence = InMemoryResolutionProposalPersistence()
    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence,
    ).create_draft_for_proposal(proposal)

    payload = resolution_outbound_draft_timeline_payload(
        draft=draft,
        proposal=proposal,
    )

    assert {
        "draft_id",
        "proposal_id",
        "status",
        "draft_body_sha256",
        "governance_decision_id",
        "send_eligible",
    } <= set(payload)
    assert payload["draft_id"] == str(draft.draft_id)
    assert payload["proposal_id"] == str(proposal.proposal_id)
    assert payload["status"] == ResolutionOutboundDraftStatus.READY.value
    assert payload["draft_body_sha256"] == hashlib.sha256(
        proposal.proposed_customer_reply.encode("utf-8")
    ).hexdigest()
    assert payload["governance_decision_id"] == str(GOVERNANCE_DECISION_ID)
    assert payload["send_eligible"] is resolution_proposal_is_send_eligible(proposal)
    assert {
        "adapter_name",
        "provider",
        "target_uri",
        "credentials",
        "delivery_attempt",
        "delivery_provider",
        "provider_message_id",
        "send_at",
        "sent_at",
    }.isdisjoint(payload)


def test_diagnostic_worker_task_kwargs_align_with_work_item_contract() -> None:
    task_parameters = inspect.signature(execute_diagnostic_agent).parameters
    task_kwargs = set(task_parameters)
    required_task_kwargs = {
        name
        for name, parameter in task_parameters.items()
        if parameter.default is inspect.Parameter.empty
    }
    work_item_fields = _dataclass_field_names(_DiagnosticExecutionWorkItem)
    work_item_constructor_fields = _constructor_keyword_names(
        _prepare_diagnostic_execution,
        "_DiagnosticExecutionWorkItem",
    )
    work_item = _DiagnosticExecutionWorkItem(
        execution_id=EXECUTION_ID,
        attempt_id="attempt-1",
        attempt_number=1,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        content="The power bank will not charge.",
    )

    assert task_kwargs == {"execution_id", "tenant_id", "_enqueued_at"}
    assert _apply_async_kwarg_keys(CeleryExecutionPublisher.publish_execution) == (
        task_kwargs
    )
    assert required_task_kwargs == {"execution_id", "tenant_id"}
    assert required_task_kwargs <= work_item_fields
    assert "_enqueued_at" not in work_item_fields
    assert work_item.conversation_turn_id is None
    assert work_item_constructor_fields == work_item_fields
    assert set(_dead_letter_task_payload(work_item)) == (
        work_item_fields - {"content", "conversation_turn_id"}
    )


@pytest.mark.asyncio
async def test_governance_subjects_and_resolution_metadata_fail_closed() -> None:
    subjects = (
        GenericGovernanceSubject(),
        RetrievalGovernanceSubject(),
        ExecutionGovernanceSubject(),
        AgentActionGovernanceSubject(),
        CommunicationGovernanceSubject(),
        CapabilityGovernanceSubject(),
    )
    for subject in subjects:
        assert subject.kind in set(SubjectKind)
        assert subject.to_dict()["kind"] == subject.kind.value

    _record, gate = await _send_eligible_proposal()
    communication_subject = _communication_subject(gate.requests[0])
    assert communication_subject.kind is SubjectKind.COMMUNICATION
    assert {
        "request_id",
        "proposal_id",
        "session_id",
        "execution_id",
        "dispatch_id",
        "evidence_count",
        "proposed_reply_sha256",
        "original_content_sha256",
        "local_status",
        "local_autonomy_decision",
    } <= set(communication_subject.metadata)

    policy = ResolutionCommunicationPolicy()
    for subject, expected_rule in (
        (CommunicationGovernanceSubject(tenant_id=TENANT_ID), "request_id_required"),
        (
            CommunicationGovernanceSubject(
                tenant_id=TENANT_ID,
                request_id="resolution:missing",
                metadata={"unknown": "value"},
            ),
            "proposal_id_required",
        ),
    ):
        results = await policy.evaluate(
            GovernanceContext(
                stage=EnforcementStage.PRE_EXECUTION,
                action="resolution.proposal.prepare",
                resource="resolution_proposal:missing",
                actor="agent:diagnostic",
                tenant_id=coerce_tenant_id(TENANT_ID),
                request_id=subject.request_id,
                subject=subject,
            )
        )
        assert len(results) == 1
        assert results[0].decision is Decision.DENY
        assert results[0].rule_id == expected_rule


def test_execution_outbox_state_vocabulary_alignment() -> None:
    execution_states = {state.value for state in ExecutionState}
    attempt_states = {state.value for state in ExecutionAttemptState}
    outbox_states = {state.value for state in ExecutionOutboxState}
    terminal_execution_states = frozenset(
        {
            ExecutionState.COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.DEAD_LETTERED,
        }
    )

    assert execution_states == {
        "requested",
        "claimed",
        "completed",
        "failed",
        "dead_lettered",
    }
    assert attempt_states == {"running", "completed", "failed", "dead_lettered"}
    assert outbox_states == {"pending", "publishing", "published", "failed"}
    assert get_type_hints(ExecutionOutboxRecord)["state"] is ExecutionOutboxState
    assert (
        execution_runtime_module._TERMINAL_OUTBOX_RETRY_EXECUTION_STATES
        == terminal_execution_states
    )
    assert (
        execution_memory_module._TERMINAL_OUTBOX_RETRY_EXECUTION_STATES
        == terminal_execution_states
    )
    assert set(execution_postgres_module._TERMINAL_OUTBOX_RETRY_EXECUTION_STATE_VALUES) == {
        state.value for state in terminal_execution_states
    }
    assert ExecutionOutboxState.FAILED.value in outbox_states


@pytest.mark.asyncio
async def test_memory_and_citation_evidence_alignment() -> None:
    retrieval_item_fields = _dataclass_field_names(KnowledgeRetrievalItem)
    citation_fields = _dataclass_field_names(KnowledgeCitation)
    immutable_evidence_fields = {
        "chunk_id",
        "vector_id",
        "document_version",
        "vector_index_name",
        "safe_excerpt_sha256",
        "chunk_content_hash",
        "char_start",
        "char_end",
    }

    assert {
        "chunk_id",
        "vector_id",
        "document_id",
        "document_version",
        "content_hash",
        "char_start",
        "char_end",
        "content",
        "title",
        "estimated_tokens",
        "citation_index",
    } <= retrieval_item_fields
    assert {
        "chunk_id",
        "vector_id",
        "document_id",
        "document_version",
        "content_hash",
        "char_start",
        "char_end",
    } <= citation_fields

    content = "Check USB-C cable fit before warranty replacement triage."
    retrieval = KnowledgeRetrievalResult(
        tenant_id=TENANT_ID,
        query="charging",
        items=(
            KnowledgeRetrievalItem(
                chunk_id=as_chunk_id("66666666-6666-4666-8666-666666666666"),
                vector_id=as_vector_id("77777777-7777-4777-8777-777777777777"),
                document_id=as_document_id(
                    "55555555-5555-4555-8555-555555555555"
                ),
                document_version=3,
                content_hash="sha256:charging-sop-chunk",
                ordinal=0,
                char_start=12,
                char_end=69,
                score=0.9242,
                content=content,
                title="Charging Troubleshooting SOP",
                estimated_tokens=128,
                citation_index=1,
                document_status="active",
                metadata={"document_type": "sop"},
            ),
        ),
        citations=(),
        budget_decisions=(),
        total_tokens=128,
        vector_index_name="tenant_knowledge_default",
    )

    citation = _retrieved_citations_payload(retrieval)[0]
    assert immutable_evidence_fields <= set(citation)
    assert citation["chunk_id"] == "66666666-6666-4666-8666-666666666666"
    assert citation["vector_id"] == "77777777-7777-4777-8777-777777777777"
    assert citation["document_version"] == 3
    assert citation["char_start"] == 12
    assert citation["char_end"] == 69
    assert citation["vector_index_name"] == "tenant_knowledge_default"
    assert citation["safe_excerpt_sha256"] == hashlib.sha256(
        str(citation["safe_excerpt"]).encode("utf-8")
    ).hexdigest()
    assert citation["chunk_content_hash"] == "sha256:charging-sop-chunk"

    legacy_record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
    ).create_proposal(_proposal_request(citations=[_citation()]))
    legacy_evidence = legacy_record.evidence[0]
    assert {
        "rank",
        "document_id",
        "title",
        "document_type",
        "document_status",
        "score",
        "chunk_ordinal",
        "token_count",
    } <= set(legacy_evidence)
    assert immutable_evidence_fields.isdisjoint(legacy_evidence)


def test_persistence_record_and_orm_alignment() -> None:
    assert _dataclass_field_names(ResolutionProposalRecord) == _orm_column_names(
        ResolutionProposalRow
    )
    assert _dataclass_field_names(ResolutionOutboundDraftRecord) == (
        _orm_column_names(ResolutionOutboundDraftRow)
    )
    assert {
        "channel_class",
        "queue_depth_available",
        "queue_age_available",
        "redis_memory_available",
        "telemetry_unavailable",
        "unavailable_reasons",
    } <= _orm_column_names(AdmissionRecordRow)


@pytest.mark.asyncio
async def test_trace_inspector_event_and_optional_payload_contract_smoke() -> None:
    source = Path(
        "apps/command-center2/frontend/components/trace-inspector.tsx"
    ).read_text(encoding="utf-8")
    frontend_resolution_event_types = set(
        re.findall(
            r'"(resolution_(?:proposal|outbound_draft)_created)"',
            source,
        )
    )

    assert frontend_resolution_event_types == {
        agent_tasks._RESOLUTION_CREATED,
        agent_tasks._RESOLUTION_DRAFT_CREATED,
    }
    assert {
        "proposed_customer_reply",
        "resolution_category",
        "confidence",
        "autonomy_decision",
        "status",
        "supervisor_verdict",
        "governance_verdict",
        "recommended_actions",
        "evidence",
        "draft_id",
        "proposal_id",
        "governance_decision_id",
        "draft_body",
        "draft_body_sha256",
        "send_eligible",
    } <= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", source))
    assert "optionalStringField(citation.chunk_id)" in source
    assert "optionalStringField(citation.vector_id)" in source
    assert "optionalNumberField(citation.document_version)" in source
    assert "optionalNumberField(citation.char_start)" in source
    assert "optionalNumberField(citation.char_end)" in source
    assert "optionalStringField(citation.vector_index_name)" in source
    assert "optionalStringField(citation.safe_excerpt_sha256)" in source
    assert "optionalStringField(citation.chunk_content_hash)" in source

    old_diagnostic_payload = DiagnosticResult(
        summary="Legacy diagnostic event.",
        category="charging_issue",
        confidence=0.82,
    ).model_dump(exclude={"retrieved_citations"})
    assert "retrieved_citations" not in old_diagnostic_payload

    old_proposal = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
    ).create_proposal(_proposal_request(citations=[_citation()]))
    old_proposal_payload = resolution_proposal_timeline_payload(old_proposal)
    assert old_proposal_payload["proposed_customer_reply"]
    assert old_proposal_payload["evidence"]
    assert "chunk_id" not in old_proposal_payload["evidence"][0]
