"""Break-control tests for at-rest encryption wiring of sensitive fields.

Covers ``boundary_ingress.canonical_payload['text']``,
``resolution_proposals.proposed_customer_reply`` and
``resolution_outbound_drafts.draft_body`` — the three sensitive columns
that, prior to this fix, were written via ``PostgresBoundaryPersistence``
and ``PostgresResolutionProposalPersistence`` instances constructed without
``data_protection``, leaving customer data plaintext at rest.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.db.models import BoundaryIngressRow
from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import BoundaryIngressId
from app.boundary.persistence import BoundaryIngressRecord, PostgresBoundaryPersistence
from app.data_protection.crypto import DataProtectionService, MasterKeyRing
from app.execution.db import models as _execution_db_models  # noqa: F401
from app.resolution.db.models import ResolutionOutboundDraftRow, ResolutionProposalRow
from app.session.db import models as _session_db_models  # noqa: F401
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import (
    ResolutionOutboundDraftId,
    ResolutionProposalId,
)
from app.resolution.persistence import (
    PostgresResolutionProposalPersistence,
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

TENANT_ID = "tenant-dp-at-rest"
SESSION_ID = "55555555-5555-4555-8555-555555555555"
EXECUTION_ID = "66666666-6666-4666-8666-666666666666"
DISPATCH_ID = "77777777-7777-4777-8777-777777777777"
_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return TENANT_ID


def _service(session: AsyncSession) -> DataProtectionService:
    return DataProtectionService(
        session,
        master_key_ring=MasterKeyRing(keys={"v1": b"a" * 32}, active_version="v1"),
    )


async def _ensure_tenant(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO public.tenants (tenant_id)
            VALUES (:tenant_id)
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ),
        {"tenant_id": tenant_id},
    )
    await session.flush()


async def _ensure_resolution_fk_targets(session: AsyncSession) -> None:
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
                :session_id, 'tenant', 'dp-at-rest-session',
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
            "now": _NOW,
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
            "now": _NOW,
        },
    )
    await session.flush()


def _ingress_record(*, ingress_id: BoundaryIngressId, text_value: str) -> BoundaryIngressRecord:
    at = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    return BoundaryIngressRecord(
        ingress_id=ingress_id,
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=uuid.uuid4(),
        sequence=0,
        source_type=BoundarySourceType.GENERIC,
        source_id="adapter-a",
        tenant_id=TENANT_ID,
        adapter_name="test-adapter",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=None,
        event_id=None,
        original_event_id=None,
        external_message_id=f"ext-{ingress_id}",
        external_conversation_id=None,
        external_emitted_at=None,
        received_at=at,
        started_at=at,
        ended_at=at,
        latency_ms=0.5,
        correlation_id=None,
        request_id=None,
        canonical_payload={"text": text_value},
        error=None,
    )


def _proposal_record(
    *, proposal_id: ResolutionProposalId, reply: str
) -> ResolutionProposalRecord:
    return ResolutionProposalRecord(
        proposal_id=proposal_id,
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        proposed_customer_reply=reply,
        resolution_category="product_defect",
        confidence=0.82,
        supervisor_verdict=ResolutionSupervisorVerdict.PASS,
        governance_verdict=ResolutionGovernanceVerdict.ALLOW,
        autonomy_decision=ResolutionAutonomyDecision.AUTO_APPROVED,
        status=ResolutionProposalStatus.SEND_ELIGIBLE,
        created_at=_NOW,
        updated_at=_NOW,
        governance_decision_id=None,
        evidence=(),
    )


def _draft_record(
    *,
    draft_id: ResolutionOutboundDraftId,
    proposal_id: ResolutionProposalId,
    body: str,
) -> ResolutionOutboundDraftRecord:
    return ResolutionOutboundDraftRecord(
        draft_id=draft_id,
        tenant_id=TENANT_ID,
        proposal_id=proposal_id,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        governance_decision_id=None,
        status=ResolutionOutboundDraftStatus.READY,
        draft_body=body,
        draft_body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        resolution_category="product_defect",
        confidence=0.82,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.asyncio
async def test_boundary_ingress_text_encrypted_at_rest_and_decrypts(
    pg_session: AsyncSession,
) -> None:
    await _ensure_tenant(pg_session, TENANT_ID)

    repo = PostgresBoundaryPersistence(pg_session, data_protection=_service(pg_session))
    ingress_id = BoundaryIngressId(uuid.uuid4())
    plaintext = "customer reports the battery is swollen"
    await repo.save_ingress(_ingress_record(ingress_id=ingress_id, text_value=plaintext))
    await pg_session.flush()

    row = (
        await pg_session.execute(
            select(BoundaryIngressRow).where(
                BoundaryIngressRow.ingress_id == uuid.UUID(str(ingress_id))
            )
        )
    ).scalar_one()
    raw_text = row.canonical_payload["text"]
    assert isinstance(raw_text, dict)
    assert raw_text.get("__op_dp__") == "v1"
    assert plaintext not in str(row.canonical_payload)

    got = await repo.get_ingress(ingress_id, expected_tenant_id=TENANT_ID)
    assert got is not None
    assert got.canonical_payload == {"text": plaintext}


@pytest.mark.asyncio
async def test_resolution_proposal_and_draft_encrypted_at_rest_and_decrypts(
    pg_session: AsyncSession,
) -> None:
    await _ensure_tenant(pg_session, TENANT_ID)
    await _ensure_resolution_fk_targets(pg_session)

    repo = PostgresResolutionProposalPersistence(
        pg_session, data_protection=_service(pg_session)
    )

    proposal_id = ResolutionProposalId(uuid.uuid4())
    reply = "We have shipped a replacement battery to your address on file."
    await repo.create_resolution_proposal(
        _proposal_record(proposal_id=proposal_id, reply=reply),
        expected_tenant_id=TENANT_ID,
    )
    await pg_session.flush()

    proposal_row = (
        await pg_session.execute(
            select(ResolutionProposalRow).where(
                ResolutionProposalRow.proposal_id == uuid.UUID(str(proposal_id))
            )
        )
    ).scalar_one()
    assert proposal_row.proposed_customer_reply.startswith("opdp:v1:")
    assert reply not in proposal_row.proposed_customer_reply

    stored_proposal = await repo.get_resolution_proposal(
        str(proposal_id), expected_tenant_id=TENANT_ID
    )
    assert stored_proposal is not None
    assert stored_proposal.proposed_customer_reply == reply

    draft_id = ResolutionOutboundDraftId(uuid.uuid4())
    body = "Your replacement battery (order #A1771) ships today."
    await repo.create_resolution_outbound_draft(
        _draft_record(draft_id=draft_id, proposal_id=proposal_id, body=body),
        expected_tenant_id=TENANT_ID,
    )
    await pg_session.flush()

    draft_row = (
        await pg_session.execute(
            select(ResolutionOutboundDraftRow).where(
                ResolutionOutboundDraftRow.draft_id == uuid.UUID(str(draft_id))
            )
        )
    ).scalar_one()
    assert draft_row.draft_body.startswith("opdp:v1:")
    assert body not in draft_row.draft_body

    stored_draft = await repo.get_resolution_outbound_draft(
        str(draft_id), expected_tenant_id=TENANT_ID
    )
    assert stored_draft is not None
    assert stored_draft.draft_body == body


@pytest.mark.asyncio
async def test_legacy_plaintext_ingress_dual_reads_after_wiring(
    pg_session: AsyncSession,
) -> None:
    await _ensure_tenant(pg_session, TENANT_ID)

    legacy_repo = PostgresBoundaryPersistence(pg_session)
    ingress_id = BoundaryIngressId(uuid.uuid4())
    plaintext = "customer says the charger smells like burning plastic"
    await legacy_repo.save_ingress(
        _ingress_record(ingress_id=ingress_id, text_value=plaintext)
    )
    await pg_session.flush()

    protected_repo = PostgresBoundaryPersistence(
        pg_session, data_protection=_service(pg_session)
    )
    got = await protected_repo.get_ingress(ingress_id, expected_tenant_id=TENANT_ID)
    assert got is not None
    assert got.canonical_payload == {"text": plaintext}


@pytest.mark.asyncio
async def test_legacy_plaintext_proposal_and_draft_dual_reads_after_wiring(
    pg_session: AsyncSession,
) -> None:
    await _ensure_tenant(pg_session, TENANT_ID)
    await _ensure_resolution_fk_targets(pg_session)

    legacy_repo = PostgresResolutionProposalPersistence(pg_session)

    proposal_id = ResolutionProposalId(uuid.uuid4())
    reply = "A technician will contact you within 24 hours to arrange pickup."
    await legacy_repo.create_resolution_proposal(
        _proposal_record(proposal_id=proposal_id, reply=reply),
        expected_tenant_id=TENANT_ID,
    )

    draft_id = ResolutionOutboundDraftId(uuid.uuid4())
    body = "We will arrange pickup of the affected unit within 24 hours."
    await legacy_repo.create_resolution_outbound_draft(
        _draft_record(draft_id=draft_id, proposal_id=proposal_id, body=body),
        expected_tenant_id=TENANT_ID,
    )
    await pg_session.flush()

    protected_repo = PostgresResolutionProposalPersistence(
        pg_session, data_protection=_service(pg_session)
    )

    stored_proposal = await protected_repo.get_resolution_proposal(
        str(proposal_id), expected_tenant_id=TENANT_ID
    )
    assert stored_proposal is not None
    assert stored_proposal.proposed_customer_reply == reply

    stored_draft = await protected_repo.get_resolution_outbound_draft(
        str(draft_id), expected_tenant_id=TENANT_ID
    )
    assert stored_draft is not None
    assert stored_draft.draft_body == body
