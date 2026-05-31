"""Resolution proposal runtime and safety invariants."""

from __future__ import annotations

import ast
import hashlib
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.persistence import (
    InMemoryResolutionProposalPersistence,
    PostgresResolutionProposalPersistence,
    ResolutionOutboundDraftQuery,
    ResolutionProposalQuery,
)
from app.governance.persistence import InMemoryGovernanceRepository
from app.runtime.resolution_governance_gate import (
    ResolutionGovernanceGate,
    build_resolution_governance_runtime,
)
from app.runtime.resolution_runtime import (
    ResolutionGovernanceGateRequest,
    ResolutionGovernanceGateResult,
    ResolutionOutboundDraftRuntime,
    ResolutionProposalRequest,
    ResolutionRuntime,
    _map_central_governance_result,
    resolution_outbound_draft_timeline_payload,
    resolution_proposal_is_send_eligible,
    resolution_proposal_timeline_payload,
)
from app.tenant.db.models import TenantRow
from tests.conftest import requires_postgres, set_pg_rls_tenant

TENANT_ID = "tenant-resolution"
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


def _governed_resolution_runtime(
    *,
    governance_repository: InMemoryGovernanceRepository,
) -> ResolutionRuntime:
    return ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository
            )
        ),
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
            "vector_index_name": "tenant_knowledge_default",
            "safe_excerpt": safe_excerpt,
            "safe_excerpt_sha256": hashlib.sha256(
                safe_excerpt.encode("utf-8")
            ).hexdigest(),
            "chunk_content_hash": "sha256:charging-sop-chunk",
        }
    )
    return citation


def _request(
    *,
    content: str = "My PowerCore stopped charging.",
    category: str = "charging_issue",
    confidence: float = 0.91,
    citations: list[dict[str, object]] | None = None,
) -> ResolutionProposalRequest:
    return ResolutionProposalRequest(
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=DIAGNOSTIC_EVENT_ID,
        diagnostic_summary="Charging issue found.",
        diagnostic_category=category,
        diagnostic_confidence=confidence,
        original_content=content,
        retrieved_citations=citations if citations is not None else [_citation()],
    )


async def _ensure_committed_tenants(
    seed_engine: AsyncEngine | None,
    fallback_session: AsyncSession,
    *tenant_ids: str,
) -> None:
    if seed_engine is None:
        for tenant_id in tenant_ids:
            await fallback_session.merge(TenantRow(tenant_id=tenant_id))
        if TENANT_ID in tenant_ids:
            await _ensure_resolution_fk_targets(fallback_session)
        await fallback_session.flush()
        return

    async with seed_engine.begin() as connection:
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            for tenant_id in tenant_ids:
                await session.merge(TenantRow(tenant_id=tenant_id))
            if TENANT_ID in tenant_ids:
                await _ensure_resolution_fk_targets(session)
            await session.flush()
            await session.commit()
        finally:
            await session.close()


async def _ensure_resolution_fk_targets(session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            INSERT INTO public.operational_sessions (
                session_id, scope, external_handle, tenant_id, principal_id,
                opened_at, lifecycle_phase, lifecycle_recorded_at,
                lifecycle_reason, lineage_id, root_session_id,
                parent_session_id, ancestor_session_ids, lineage_depth,
                sequence_head, revision, context_environment,
                context_labels, context_attributes, context_notes, metadata
            )
            VALUES (
                :session_id, 'tenant', 'resolution-test-session',
                :tenant_id, NULL, :now, 'active', :now, NULL,
                :session_id, :session_id, NULL, '[]'::jsonb, 0, 0, 0,
                NULL, '[]'::jsonb, '{}'::jsonb, NULL, '{}'::jsonb
            )
            ON CONFLICT (session_id) DO NOTHING
            """
        ),
        {
            "session_id": uuid.UUID(SESSION_ID),
            "tenant_id": TENANT_ID,
            "now": now,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO public.execution_records (
                execution_id, kind, dispatch_id, session_id, tenant_id,
                state, attempt_count, requested_at, result, metadata
            )
            VALUES (
                :execution_id, 'diagnostic_agent', :dispatch_id,
                :session_id_text, :tenant_id, 'requested', 0,
                :now, '{}'::jsonb, '{}'::jsonb
            )
            ON CONFLICT (tenant_id, dispatch_id, kind) DO NOTHING
            """
        ),
        {
            "execution_id": uuid.UUID(EXECUTION_ID),
            "dispatch_id": DISPATCH_ID,
            "session_id_text": SESSION_ID,
            "tenant_id": TENANT_ID,
            "now": now,
        },
    )


@pytest.mark.asyncio
async def test_safe_charging_issue_creates_send_eligible_proposal() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ALLOW)
    runtime = ResolutionRuntime(persistence=persistence, governance_gate=gate)

    record = await runtime.create_proposal(_request())

    assert record.tenant_id == TENANT_ID
    assert record.resolution_category == "charging_issue"
    assert record.autonomy_decision is ResolutionAutonomyDecision.AUTO_APPROVED
    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.supervisor_verdict is ResolutionSupervisorVerdict.PASS
    assert record.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID
    assert record.evidence
    assert "refund" not in record.proposed_customer_reply.lower()
    assert len(gate.requests) == 1
    assert gate.requests[0].local_status is ResolutionProposalStatus.AUTO_APPROVED


@pytest.mark.asyncio
async def test_concrete_gate_persists_allow_decision_and_proposal_stores_id() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository
    )

    record = await runtime.create_proposal(_request())

    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_decision_id is not None
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id),
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    assert decision.decision == "allow"
    assert decision.policy_chain_id == "resolution.communication.pre_execution"
    assert decision.subject_kind == "communication"
    assert decision.request_id == f"resolution:{record.proposal_id}"
    assert decision.metadata["proposal_id"] == str(record.proposal_id)


@pytest.mark.asyncio
async def test_missing_governance_gate_fails_closed_for_send_eligibility() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request())

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.governance_decision_id is None
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_allow_without_governance_decision_id_fails_closed() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW,
            decision_id=None,
        ),
    ).create_proposal(_request())

    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.governance_decision_id is None
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_missing_citations_prevent_auto_approval() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(citations=[]))

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.evidence == ()


@pytest.mark.asyncio
async def test_central_allow_cannot_override_missing_citations() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
    ).create_proposal(_request(citations=[]))

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_concrete_gate_missing_evidence_blocks_send_eligibility() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository
    )

    record = await runtime.create_proposal(_request(citations=[]))

    assert record.status is not ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_decision_id is not None
    assert resolution_proposal_is_send_eligible(record) is False
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id),
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    assert decision.decision in {"require_approval", "deny"}


@pytest.mark.asyncio
async def test_resolution_evidence_preserves_immutable_citation_fields() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(citations=[_immutable_citation()]))

    evidence = record.evidence[0]
    assert evidence["citation_schema_version"] == 2
    assert evidence["chunk_id"] == "66666666-6666-4666-8666-666666666666"
    assert evidence["vector_id"] == "77777777-7777-4777-8777-777777777777"
    assert evidence["document_version"] == 3
    assert evidence["vector_index_name"] == "tenant_knowledge_default"
    assert (
        evidence["safe_excerpt"]
        == "Check USB-C cable fit before warranty replacement triage."
    )
    assert evidence["safe_excerpt_sha256"] == hashlib.sha256(
        str(evidence["safe_excerpt"]).encode("utf-8")
    ).hexdigest()
    assert evidence["chunk_content_hash"] == "sha256:charging-sop-chunk"


@pytest.mark.asyncio
async def test_old_citation_payloads_still_normalize() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(citations=[_citation()]))

    evidence = record.evidence[0]
    assert evidence["document_id"] == _citation()["document_id"]
    assert evidence["title"] == "Charging Troubleshooting SOP"
    assert "chunk_id" not in evidence
    assert "safe_excerpt" not in evidence


@pytest.mark.asyncio
async def test_low_confidence_requires_human_approval() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(confidence=0.42))

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.supervisor_verdict is ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW


@pytest.mark.asyncio
async def test_central_allow_cannot_override_low_confidence() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
    ).create_proposal(_request(confidence=0.42))

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_concrete_gate_local_pending_state_blocks_send_eligibility() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository
    )

    record = await runtime.create_proposal(_request(confidence=0.42))

    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.governance_decision_id is not None
    assert resolution_proposal_is_send_eligible(record) is False
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id),
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    assert decision.decision == "require_approval"


@pytest.mark.asyncio
async def test_safety_smoke_fire_or_injury_requires_human_approval() -> None:
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ESCALATE)
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=gate,
    ).create_proposal(
        _request(
            content="The charger started smoking and caused a hand injury.",
            confidence=0.95,
        )
    )

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.ESCALATE
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID


@pytest.mark.asyncio
async def test_central_allow_cannot_override_safety_escalation() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
    ).create_proposal(
        _request(
            content="The charger started smoking and caused a hand injury.",
            confidence=0.95,
        )
    )

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.ESCALATE
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_central_allow_cannot_override_unsupported_promise_denial() -> None:
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ALLOW)
    await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=gate,
    ).create_proposal(_request())
    request = replace(
        gate.requests[0],
        proposed_customer_reply="We will refund and replace this under warranty.",
        local_supervisor_verdict=ResolutionSupervisorVerdict.FAIL,
        local_governance_verdict=ResolutionGovernanceVerdict.DENY,
        local_autonomy_decision=ResolutionAutonomyDecision.DENIED,
        local_status=ResolutionProposalStatus.DENIED,
        local_reasons=("unsupported_refund_replacement_or_warranty_promise",),
    )

    result = _map_central_governance_result(
        request,
        ResolutionGovernanceGateResult(
            governance_verdict=ResolutionGovernanceVerdict.ALLOW,
            governance_decision_id=GOVERNANCE_DECISION_ID,
        ),
    )

    assert result.autonomy_decision is ResolutionAutonomyDecision.DENIED
    assert result.status is ResolutionProposalStatus.DENIED
    assert result.governance_verdict is ResolutionGovernanceVerdict.DENY
    assert result.governance_decision_id == GOVERNANCE_DECISION_ID


@pytest.mark.asyncio
async def test_concrete_gate_refund_warranty_category_requires_approval() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository
    )

    record = await runtime.create_proposal(
        _request(
            content="I need a warranty replacement for this charger.",
            confidence=0.95,
        )
    )

    assert record.resolution_category == "warranty_replacement_inquiry"
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.governance_decision_id is not None
    assert resolution_proposal_is_send_eligible(record) is False
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id),
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    assert decision.decision == "require_approval"


@pytest.mark.asyncio
async def test_resolution_proposal_reads_are_tenant_scoped() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    record = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )

    assert (
        await persistence.get_resolution_proposal(
            str(record.proposal_id),
            expected_tenant_id="tenant-other",
        )
        is None
    )
    page = await persistence.list_resolution_proposals(
        ResolutionProposalQuery(),
        expected_tenant_id="tenant-other",
    )
    assert page.total == 0


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_resolution_persistence_enforces_tenant_rls(
    pg_session,
    pg_seed_engine,
) -> None:
    await _ensure_committed_tenants(
        pg_seed_engine,
        pg_session,
        TENANT_ID,
        "tenant-other",
    )
    await set_pg_rls_tenant(pg_session, TENANT_ID)
    persistence = PostgresResolutionProposalPersistence(pg_session)
    record = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )
    assert record.governance_decision_id is None

    assert (
        await persistence.get_resolution_proposal(
            str(record.proposal_id),
            expected_tenant_id=TENANT_ID,
        )
    ) is not None

    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, "tenant-other")
        assert (
            await persistence.get_resolution_proposal(
                str(record.proposal_id),
                expected_tenant_id="tenant-other",
            )
        ) is None
        assert (
            await persistence.get_resolution_proposal(
                str(record.proposal_id),
                expected_tenant_id=TENANT_ID,
            )
        ) is None
    finally:
        await pg_session.execute(text("RESET ROLE"))


@pytest.mark.asyncio
async def test_resolution_timeline_payload_is_customer_safe_handoff() -> None:
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ALLOW)
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=gate,
    ).create_proposal(_request())

    payload = resolution_proposal_timeline_payload(record)

    assert payload["proposal_id"] == str(record.proposal_id)
    assert payload["proposed_customer_reply"] == record.proposed_customer_reply
    assert payload["recommended_actions"] == [
        dict(action) for action in record.recommended_actions
    ]
    assert payload["evidence"] == [dict(item) for item in record.evidence]
    assert payload["governance_decision_id"] == str(GOVERNANCE_DECISION_ID)
    assert payload["send_eligible"] is True
    assert payload["requires_human_approval"] is False


@pytest.mark.asyncio
async def test_send_eligible_helper_requires_governance_decision_id() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
    ).create_proposal(_request())

    old_row_shape = replace(record, governance_decision_id=None)
    payload = resolution_proposal_timeline_payload(old_row_shape)

    assert old_row_shape.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert resolution_proposal_is_send_eligible(old_row_shape) is False
    assert payload["send_eligible"] is False


@pytest.mark.asyncio
async def test_ready_outbound_draft_for_governance_backed_send_eligible_proposal() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    proposal = await ResolutionRuntime(
        persistence=persistence,
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
    ).create_proposal(_request())

    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(proposal)
    payload = resolution_outbound_draft_timeline_payload(
        draft=draft,
        proposal=proposal,
    )

    assert draft.tenant_id == TENANT_ID
    assert draft.proposal_id == proposal.proposal_id
    assert draft.status is ResolutionOutboundDraftStatus.READY
    assert draft.governance_decision_id == GOVERNANCE_DECISION_ID
    assert draft.draft_body == proposal.proposed_customer_reply
    assert draft.draft_body_sha256 == hashlib.sha256(
        proposal.proposed_customer_reply.encode("utf-8")
    ).hexdigest()
    assert payload["send_eligible"] is True
    assert "adapter_name" not in payload
    assert "sent_at" not in payload


@pytest.mark.asyncio
async def test_pending_proposal_creates_pending_human_approval_draft() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    proposal = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )

    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(proposal)

    assert proposal.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert draft.status is ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL
    assert resolution_outbound_draft_timeline_payload(
        draft=draft,
        proposal=proposal,
    )["send_eligible"] is False


@pytest.mark.asyncio
async def test_denied_proposal_creates_denied_draft() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    proposal = await ResolutionRuntime(
        persistence=persistence,
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.DENY
        ),
    ).create_proposal(_request())

    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(proposal)

    assert proposal.status is ResolutionProposalStatus.DENIED
    assert draft.status is ResolutionOutboundDraftStatus.DENIED


@pytest.mark.asyncio
async def test_old_send_eligible_proposal_without_governance_id_creates_pending_draft() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    proposal = await ResolutionRuntime(
        persistence=persistence,
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
    ).create_proposal(_request())
    old_row_shape = replace(proposal, governance_decision_id=None)

    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(old_row_shape)

    assert old_row_shape.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert resolution_proposal_is_send_eligible(old_row_shape) is False
    assert draft.status is ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_resolution_outbound_draft_enforces_tenant_rls(
    pg_session,
    pg_seed_engine,
) -> None:
    await _ensure_committed_tenants(
        pg_seed_engine,
        pg_session,
        TENANT_ID,
        "tenant-other",
    )
    await set_pg_rls_tenant(pg_session, TENANT_ID)
    persistence = PostgresResolutionProposalPersistence(pg_session)
    proposal = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )
    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(proposal)

    assert (
        await persistence.get_resolution_outbound_draft(
            str(draft.draft_id),
            expected_tenant_id=TENANT_ID,
        )
    ) is not None

    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, "tenant-other")
        assert (
            await persistence.get_resolution_outbound_draft(
                str(draft.draft_id),
                expected_tenant_id="tenant-other",
            )
        ) is None
        assert (
            await persistence.get_resolution_outbound_draft(
                str(draft.draft_id),
                expected_tenant_id=TENANT_ID,
            )
        ) is None
        page = await persistence.list_resolution_outbound_drafts(
            ResolutionOutboundDraftQuery(),
            expected_tenant_id="tenant-other",
        )
    finally:
        await pg_session.execute(text("RESET ROLE"))
    assert page.total == 0


def test_resolution_runtime_has_no_external_send_path() -> None:
    paths = [
        Path("apps/backend/app/runtime/resolution_runtime.py"),
        Path("apps/backend/app/workers/agent_tasks.py"),
        Path("apps/backend/app/resolution"),
        Path("apps/backend/migrations/versions/0044_resolution_drafts.py"),
    ]
    forbidden = (
        "BoundaryEgressRuntime",
        ".emit(",
        ".send(",
        "boundary_egress",
        "BaseEgressAdapter",
        "BoundaryAdapterRegistry",
        "app.boundary.adapters",
    )

    violations: list[str] = []
    for root in paths:
        scanned = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in scanned:
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in source:
                    violations.append(f"{path}:{token}")

    assert violations == []


def test_resolution_drafts_do_not_persist_delivery_fields() -> None:
    model_source = Path(
        "apps/backend/app/resolution/db/models.py"
    ).read_text(encoding="utf-8")
    draft_model_source = model_source[model_source.index("class ResolutionOutboundDraftRow") :]
    records_source = Path(
        "apps/backend/app/resolution/persistence/records.py"
    ).read_text(encoding="utf-8")
    draft_record_source = records_source[
        records_source.index("class ResolutionOutboundDraftRecord") :
    ]
    sources = "\n".join(
        (
            draft_model_source,
            draft_record_source,
            Path(
                "apps/backend/migrations/versions/0044_resolution_drafts.py"
            ).read_text(encoding="utf-8"),
        )
    )
    forbidden = (
        "adapter_name",
        "provider",
        "target_uri",
        "credentials",
        "delivery_attempt",
        "send_at",
        "sent_at",
        "send_eligible",
    )

    assert [token for token in forbidden if token in sources] == []


def test_resolution_lineage_paths_do_not_use_uuid4() -> None:
    roots = (
        Path("apps/backend/app/resolution"),
        Path("apps/backend/app/runtime/resolution_runtime.py"),
    )
    violations: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            uuid_module_names = {"uuid"}
            uuid4_names = {"uuid4"}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "uuid":
                            uuid_module_names.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module == "uuid":
                    for alias in node.names:
                        if alias.name == "uuid4":
                            violations.append(
                                f"{path}:{node.lineno} imports uuid4 directly"
                            )
                            uuid4_names.add(alias.asname or alias.name)
                elif isinstance(node, ast.Call):
                    func = node.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "uuid4"
                        and isinstance(func.value, ast.Name)
                        and func.value.id in uuid_module_names
                    ):
                        violations.append(
                            f"{path}:{node.lineno} calls {func.value.id}.uuid4()"
                        )
                    elif isinstance(func, ast.Name) and func.id in uuid4_names:
                        violations.append(f"{path}:{node.lineno} calls uuid4()")

    assert violations == []


def test_resolution_migration_enables_force_rls() -> None:
    source = Path(
        "apps/backend/migrations/versions/0041_resolution_proposals.py"
    ).read_text(encoding="utf-8")

    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "operious_tenant_rls_allows(tenant_id)" in source


def test_resolution_tenant_fk_migration_checks_orphans_and_adds_fk() -> None:
    source = Path(
        "apps/backend/migrations/versions/0042_resolution_proposal_tenant_fk.py"
    ).read_text(encoding="utf-8")

    assert (
        "down_revision: Union[str, None] = \"0041_resolution_proposals\""
        in source
    )
    assert "orphan_rows" in source
    assert "WHERE t.tenant_id IS NULL" in source
    assert "tenant_id values exist" in source
    assert "create_foreign_key" in source
    assert "\"resolution_proposals\"" in source
    assert "\"tenants\"" in source
    assert "[\"tenant_id\"]" in source
    assert "ondelete=\"RESTRICT\"" in source


def test_resolution_governance_decision_migration_is_nullable_and_indexed() -> None:
    source = Path(
        "apps/backend/migrations/versions/0043_resolution_proposal_governance_decision.py"
    ).read_text(encoding="utf-8")

    assert (
        "down_revision: Union[str, None] = "
        "\"0042_resolution_proposal_tenant_fk\"" in source
    )
    assert "\"governance_decision_id\"" in source
    assert "postgresql.UUID(as_uuid=True)" in source
    assert "nullable=True" in source
    assert "ix_resolution_proposals_tenant_governance_decision" in source
    assert "[\"tenant_id\", \"governance_decision_id\"]" in source
    assert "ForeignKey" not in source


def test_resolution_outbound_draft_migration_enables_force_rls_and_indexes() -> None:
    source = Path(
        "apps/backend/migrations/versions/0044_resolution_drafts.py"
    ).read_text(encoding="utf-8")

    assert (
        "down_revision: Union[str, None] = "
        "\"0043_resolution_proposal_governance_decision\"" in source
    )
    assert "\"resolution_outbound_drafts\"" in source
    assert "\"draft_id\"" in source
    assert "\"draft_body_sha256\"" in source
    assert "\"send_eligible\"" not in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "operious_tenant_rls_allows(tenant_id)" in source
    assert "ix_resolution_outbound_drafts_tenant_proposal" in source
    assert "ix_resolution_outbound_drafts_tenant_status" in source
    assert "ix_resolution_outbound_drafts_tenant_created_at" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in source


def test_resolution_substrate_is_leaf_clean() -> None:
    violations: list[str] = []
    forbidden_prefixes = (
        "app.boundary",
        "app.cognition",
        "app.governance",
        "app.session",
    )
    for path in sorted(Path("apps/backend/app/resolution").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(
                        alias.name == prefix or alias.name.startswith(f"{prefix}.")
                        for prefix in forbidden_prefixes
                    ):
                        violations.append(f"{path}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in forbidden_prefixes
                ):
                    violations.append(f"{path}:{node.lineno} imports {module}")

    assert violations == []


def test_worker_hooks_resolution_after_diagnostic_success() -> None:
    source = Path("apps/backend/app/workers/agent_tasks.py").read_text(
        encoding="utf-8"
    )

    completed_index = source.index("event_type=_COMPLETED")
    resolution_index = source.index("_append_resolution_proposal_after_diagnostic")
    complete_execution_index = source.index("complete_execution")
    assert completed_index < resolution_index < complete_execution_index
    assert "_RESOLUTION_CREATED = \"resolution_proposal_created\"" in source
    assert (
        "_RESOLUTION_DRAFT_CREATED = "
        "\"resolution_outbound_draft_created\"" in source
    )
    assert "_RESOLUTION_FAILED = \"resolution_proposal_failed\"" in source
    assert "ResolutionGovernanceGate" in source
    assert "PostgresGovernanceRepository(session)" in source
    assert "build_resolution_governance_runtime" in source
    assert "ResolutionOutboundDraftRuntime" in source
    assert "resolution_outbound_draft_timeline_payload" in source


def test_trace_inspector_renders_resolution_draft_and_old_proposals() -> None:
    source = Path(
        "apps/command-center2/frontend/components/trace-inspector.tsx"
    ).read_text(encoding="utf-8")

    assert "resolution_proposal_created" in source
    assert "ResolutionProposalSummary" in source
    assert "resolution_outbound_draft_created" in source
    assert "ResolutionDraftSummary" in source
    assert "draft_body_sha256" in source
