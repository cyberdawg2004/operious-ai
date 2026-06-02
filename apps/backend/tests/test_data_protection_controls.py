"""Spec 1c data-protection controls over real Postgres."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cognition.db.models import CognitionAuditRecordRow, CognitionLLMUsageRow
from app.cognition.identity import (
    CognitionAuditId,
    CognitionLLMUsageId,
    derive_cognition_audit_id,
)
from app.cognition.models import (
    CognitionAuditRecord,
    CognitionLLMUsageRecord,
    CognitionLLMUsageStatus,
)
from app.cognition.persistence import PostgresCognitionUsagePersistence
from app.data_protection.crypto import (
    DataProtectionError,
    DataProtectionService,
    ErasureRequestSeparationError,
    ErasureRequestStatus,
    LegalHoldBlockedError,
    MasterKeyRing,
)
from app.data_protection.db.models import (
    DataProtectionDataKeyRow,
    DataProtectionErasureRequestRow,
    DataProtectionLegalHoldRow,
    TenantDataRetentionPolicyRow,
)
from app.knowledge.exceptions import KnowledgePersistenceError
from app.knowledge.persistence import PostgresKnowledgeRepository
from app.knowledge.persistence.models import KnowledgeVectorQuery
from app.session.db.models import SessionEventRow
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import (
    SessionEventId,
    SessionId,
    SessionLineageId,
    derive_event_id,
)
from app.session.persistence import PostgresSessionPersistence
from app.session.persistence.records import SessionEventRecord, SessionRecord
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.db.models import TenantKnowledgeDocumentRow, TenantRow
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import TenantKnowledgeDocumentId
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.persistence.records import TenantKnowledgeDocumentRecord
from tests.conftest import requires_postgres

TENANT_ID = "tenant-data-protection"
SUBJECT_ID = "customer-anker-001"
NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return TENANT_ID


def _service(
    session: AsyncSession,
    *,
    key: str | bytes = b"a" * 32,
    version: str = "v1",
) -> DataProtectionService:
    return DataProtectionService(
        session,
        master_key_ring=MasterKeyRing(keys={version: key}, active_version=version),
    )


def _session_record(session_id: SessionId) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        scope=SessionScope.PRINCIPAL,
        external_handle="ticket-anker-001",
        tenant_id=TENANT_ID,
        principal_id=SUBJECT_ID,
        opened_at=NOW,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=NOW,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.uuid4()),
        root_session_id=session_id,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
        context_attributes={"content": "private context value"},
        context_notes="private session note",
        metadata={"route": "support"},
    )


def _event_record(session_id: SessionId) -> SessionEventRecord:
    return SessionEventRecord(
        event_id=SessionEventId(derive_event_id(session_id=session_id, sequence=0)),
        session_id=session_id,
        sequence=0,
        kind=SessionEventKind.CUSTOMER_MESSAGE,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=NOW,
        recorded_at=NOW,
        payload={
            "routing_key": "ticket-anker-001",
            "content": "my battery leaked onto the desk",
        },
    )


def _audit_record(*, subject_id: str = SUBJECT_ID) -> CognitionAuditRecord:
    prompt = "full prompt with customer address 123 secret lane"
    completion = "completion recommends private replacement handling"
    audit_id = derive_cognition_audit_id(
        tenant_id=TENANT_ID,
        execution_id="execution-data-protection",
        model="claude-test",
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        completion_sha256=hashlib.sha256(completion.encode()).hexdigest(),
    )
    return CognitionAuditRecord(
        audit_id=audit_id,
        tenant_id=TENANT_ID,
        execution_id="execution-data-protection",
        prompt_full=prompt,
        completion_full=completion,
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        completion_sha256=hashlib.sha256(completion.encode()).hexdigest(),
        model_name="claude-test",
        token_usage={"total_tokens": 9},
        captured_at=NOW,
        subject_id=subject_id,
    )


def _audit_row(
    *,
    audit_id: uuid.UUID | None = None,
    execution_id: str,
    captured_at: datetime,
) -> CognitionAuditRecordRow:
    return CognitionAuditRecordRow(
        audit_id=audit_id or uuid.uuid4(),
        tenant_id=TENANT_ID,
        execution_id=execution_id,
        usage_id=None,
        prompt_full=b"old",
        completion_full=b"old",
        prompt_sha256=hashlib.sha256(f"{execution_id}:prompt".encode()).hexdigest(),
        completion_sha256=hashlib.sha256(
            f"{execution_id}:completion".encode()
        ).hexdigest(),
        model_name="claude-test",
        token_usage={},
        captured_at=captured_at,
    )


@requires_postgres
@pytest.mark.asyncio
async def test_envelope_encryption_hides_plaintext_and_round_trips(
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    session_repo = PostgresSessionPersistence(
        pg_session,
        data_protection=protection,
    )
    cognition_repo = PostgresCognitionUsagePersistence(
        pg_session,
        audit_encryptor=TenantCredentialEncryptor(platform_master_key=b"l" * 32),
        data_protection=protection,
    )
    session_id = SessionId(uuid.uuid4())

    await session_repo.save_session(_session_record(session_id))
    event = _event_record(session_id)
    await session_repo.save_event(event)
    await cognition_repo.save_llm_usage(
        CognitionLLMUsageRecord(
            usage_id=CognitionLLMUsageId(uuid.uuid4()),
            tenant_id=TENANT_ID,
            execution_id="execution-data-protection",
            dispatch_id="dispatch-data-protection",
            session_id=SUBJECT_ID,
            provider="anthropic",
            model="claude-test",
            prompt_tokens=1,
            completion_tokens=2,
            total_tokens=3,
            estimated_cost_micro_usd=4,
            status=CognitionLLMUsageStatus.ACCEPTED,
            created_at=NOW,
            metadata={
                "retrieved_citations": [
                    {"safe_excerpt": "private SOP excerpt for customer"}
                ]
            },
        ),
        expected_tenant_id=TENANT_ID,
    )
    audit = _audit_record()
    await cognition_repo.save_cognition_audit(audit, expected_tenant_id=TENANT_ID)
    await pg_session.flush()

    event_row = (
        await pg_session.execute(
            select(SessionEventRow).where(SessionEventRow.event_id == event.event_id)
        )
    ).scalar_one()
    assert event_row.payload["routing_key"] == "ticket-anker-001"
    assert event_row.payload["content"]["__op_dp__"] == "v1"
    assert "battery leaked" not in json.dumps(event_row.payload)

    usage_row = (
        await pg_session.execute(
            select(CognitionLLMUsageRow).where(
                CognitionLLMUsageRow.execution_id == "execution-data-protection"
            )
        )
    ).scalar_one()
    assert "private SOP excerpt" not in json.dumps(usage_row.metadata_json)

    audit_row = (
        await pg_session.execute(
            select(CognitionAuditRecordRow).where(
                CognitionAuditRecordRow.audit_id == audit.audit_id
            )
        )
    ).scalar_one()
    assert b"customer address" not in audit_row.prompt_full
    assert b"private replacement" not in audit_row.completion_full

    stored_event = await session_repo.get_event(
        event.event_id,
        expected_tenant_id=TENANT_ID,
    )
    stored_audit = await cognition_repo.get_cognition_audit(
        audit.audit_id,
        expected_tenant_id=TENANT_ID,
    )
    assert stored_event is not None
    assert stored_event.payload["content"] == event.payload["content"]
    assert stored_audit is not None
    assert stored_audit.prompt_full == audit.prompt_full
    assert stored_audit.completion_full == audit.completion_full


@requires_postgres
@pytest.mark.asyncio
async def test_legacy_cognition_audit_ciphertext_dual_reads_after_migration(
    pg_session: AsyncSession,
) -> None:
    legacy_encryptor = TenantCredentialEncryptor(platform_master_key=b"l" * 32)
    legacy_repo = PostgresCognitionUsagePersistence(
        pg_session,
        audit_encryptor=legacy_encryptor,
    )
    audit = _audit_record(subject_id="legacy-session")
    await legacy_repo.save_cognition_audit(audit, expected_tenant_id=TENANT_ID)
    await pg_session.flush()

    protected_repo = PostgresCognitionUsagePersistence(
        pg_session,
        audit_encryptor=legacy_encryptor,
        data_protection=_service(pg_session),
    )
    stored = await protected_repo.get_cognition_audit(
        CognitionAuditId(audit.audit_id),
        expected_tenant_id=TENANT_ID,
    )

    assert stored is not None
    assert stored.prompt_full == audit.prompt_full
    assert stored.completion_full == audit.completion_full


@requires_postgres
@pytest.mark.asyncio
async def test_dsar_data_unrecoverable_after_erasure(
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    session_repo = PostgresSessionPersistence(
        pg_session,
        data_protection=protection,
    )
    session_id = SessionId(uuid.uuid4())
    await session_repo.save_session(_session_record(session_id))
    event = _event_record(session_id)
    await session_repo.save_event(event)
    await pg_session.flush()

    assert await session_repo.get_event(event.event_id, expected_tenant_id=TENANT_ID)
    proposed = await protection.propose_erasure(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        reason="customer GDPR Article 17 request",
        proposed_by="dpo-a",
    )
    assert proposed.status is ErasureRequestStatus.PROPOSED
    assert await session_repo.get_event(event.event_id, expected_tenant_id=TENANT_ID)

    executed = await protection.approve_erasure(
        tenant_id=TENANT_ID,
        request_id=proposed.request_id,
        approved_by="dpo-b",
    )
    assert executed.status is ErasureRequestStatus.EXECUTED
    assert executed.approved_by == "dpo-b"
    assert executed.approved_at is not None
    assert executed.executed_at is not None
    pg_session.expire_all()

    row_still_exists = (
        await pg_session.execute(
            select(SessionEventRow.event_id).where(
                SessionEventRow.event_id == event.event_id
            )
        )
    ).scalar_one_or_none()
    assert row_still_exists == event.event_id
    with pytest.raises(DataProtectionError):
        await session_repo.get_event(event.event_id, expected_tenant_id=TENANT_ID)


@requires_postgres
@pytest.mark.asyncio
async def test_data_past_retention_is_purged(
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    await pg_session.merge(TenantRow(tenant_id=TENANT_ID))
    await protection.set_retention_policy(
        tenant_id=TENANT_ID,
        retention_days=1,
        updated_by="dpo",
    )
    old_audit_id = uuid.uuid4()
    fresh_audit_id = uuid.uuid4()
    pg_session.add_all(
        [
            _audit_row(
                audit_id=old_audit_id,
                execution_id="expired-execution",
                captured_at=NOW - timedelta(days=5),
            ),
            _audit_row(
                audit_id=fresh_audit_id,
                execution_id="fresh-execution",
                captured_at=NOW,
            ),
        ]
    )
    await pg_session.flush()

    assert await protection.purge_expired_cognition_audits(now=NOW) == 1
    old_row = await pg_session.get(CognitionAuditRecordRow, old_audit_id)
    fresh_row = await pg_session.get(CognitionAuditRecordRow, fresh_audit_id)
    assert old_row is None
    assert fresh_row is not None


@requires_postgres
@pytest.mark.asyncio
async def test_legal_hold_blocks_purge(
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    await pg_session.merge(TenantRow(tenant_id=TENANT_ID))
    await protection.set_retention_policy(
        tenant_id=TENANT_ID,
        retention_days=1,
        updated_by="dpo",
    )
    audit_id = uuid.uuid4()
    pg_session.add(
        _audit_row(
            audit_id=audit_id,
            execution_id="held-old-execution",
            captured_at=NOW - timedelta(days=5),
        )
    )
    await protection.create_legal_hold(
        tenant_id=TENANT_ID,
        scope="tenant",
        scope_id=None,
        reason="litigation",
        created_by="legal",
    )
    await pg_session.flush()

    assert await protection.purge_expired_cognition_audits(now=NOW) == 0
    assert await pg_session.get(CognitionAuditRecordRow, audit_id) is not None


@requires_postgres
@pytest.mark.asyncio
async def test_legal_hold_blocks_dsar(
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    session_repo = PostgresSessionPersistence(
        pg_session,
        data_protection=protection,
    )
    session_id = SessionId(uuid.uuid4())
    await session_repo.save_session(_session_record(session_id))
    event = _event_record(session_id)
    await session_repo.save_event(event)
    await protection.create_legal_hold(
        tenant_id=TENANT_ID,
        scope="subject",
        scope_id=SUBJECT_ID,
        reason="litigation",
        created_by="legal",
    )
    proposed = await protection.propose_erasure(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        reason="customer GDPR Article 17 request",
        proposed_by="dpo-a",
    )
    await pg_session.flush()

    with pytest.raises(LegalHoldBlockedError):
        await protection.approve_erasure(
            tenant_id=TENANT_ID,
            request_id=proposed.request_id,
            approved_by="dpo-b",
        )
    blocked = (
        await pg_session.execute(
            select(DataProtectionErasureRequestRow).where(
                DataProtectionErasureRequestRow.request_id == proposed.request_id
            )
        )
    ).scalar_one()
    assert blocked.status == "rejected"
    assert blocked.approved_by is None
    assert blocked.blocked_reason == "active legal hold blocks DSAR erasure"
    key_row = (
        await pg_session.execute(
            select(DataProtectionDataKeyRow).where(
                DataProtectionDataKeyRow.tenant_id == TENANT_ID,
                DataProtectionDataKeyRow.scope == "subject",
                DataProtectionDataKeyRow.scope_id == SUBJECT_ID,
            )
        )
    ).scalar_one_or_none()
    assert key_row is not None
    stored = await session_repo.get_event(event.event_id, expected_tenant_id=TENANT_ID)
    assert stored is not None
    assert stored.payload["content"] == event.payload["content"]


@requires_postgres
@pytest.mark.asyncio
async def test_legal_hold_and_erasure_ledger_restrict_tenant_delete(
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    await pg_session.merge(TenantRow(tenant_id=TENANT_ID))
    await protection.set_retention_policy(
        tenant_id=TENANT_ID,
        retention_days=30,
        updated_by="dpo",
    )
    await protection.encrypt_text(
        "held customer note",
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        field="test.subject_note",
    )
    await protection.create_legal_hold(
        tenant_id=TENANT_ID,
        scope="subject",
        scope_id=SUBJECT_ID,
        reason="litigation",
        created_by="legal",
    )
    proposed = await protection.propose_erasure(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        reason="customer GDPR Article 17 request",
        proposed_by="dpo-a",
    )
    with pytest.raises(LegalHoldBlockedError):
        await protection.approve_erasure(
            tenant_id=TENANT_ID,
            request_id=proposed.request_id,
            approved_by="dpo-b",
        )
    await pg_session.flush()

    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await pg_session.execute(
                delete(TenantRow).where(TenantRow.tenant_id == TENANT_ID)
            )

    await pg_session.execute(
        delete(DataProtectionLegalHoldRow).where(
            DataProtectionLegalHoldRow.tenant_id == TENANT_ID
        )
    )
    await pg_session.flush()
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await pg_session.execute(
                delete(TenantRow).where(TenantRow.tenant_id == TENANT_ID)
            )

    await pg_session.execute(
        delete(DataProtectionErasureRequestRow).where(
            DataProtectionErasureRequestRow.tenant_id == TENANT_ID
        )
    )
    await pg_session.execute(delete(TenantRow).where(TenantRow.tenant_id == TENANT_ID))
    await pg_session.flush()

    data_key = (
        await pg_session.execute(
            select(DataProtectionDataKeyRow.data_key_id).where(
                DataProtectionDataKeyRow.tenant_id == TENANT_ID
            )
        )
    ).scalar_one_or_none()
    retention = await pg_session.get(TenantDataRetentionPolicyRow, TENANT_ID)
    assert data_key is None
    assert retention is None


@requires_postgres
@pytest.mark.asyncio
async def test_erasure_dual_control_rejects_same_principal_at_app_and_db(
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    proposed = await protection.propose_erasure(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        reason="customer GDPR Article 17 request",
        proposed_by="dpo-a",
    )

    with pytest.raises(ErasureRequestSeparationError):
        await protection.approve_erasure(
            tenant_id=TENANT_ID,
            request_id=proposed.request_id,
            approved_by="dpo-a",
        )

    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            pg_session.add(
                DataProtectionErasureRequestRow(
                    request_id=uuid.uuid4(),
                    tenant_id=TENANT_ID,
                    subject_id="customer-anker-002",
                    status="approved",
                    reason="direct database bypass attempt",
                    proposed_by="dpo-a",
                    approved_by="dpo-a",
                    approved_at=NOW,
                )
            )
            await pg_session.flush()


@requires_postgres
@pytest.mark.asyncio
async def test_released_legal_hold_stops_blocking_dsar_erasure(
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    await protection.encrypt_text(
        "erasable customer note",
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        field="test.subject_note",
    )
    hold_id = await protection.create_legal_hold(
        tenant_id=TENANT_ID,
        scope="subject",
        scope_id=SUBJECT_ID,
        reason="litigation",
        created_by="legal",
    )
    assert len(await protection.list_legal_holds(tenant_id=TENANT_ID)) == 1

    released = await protection.release_legal_hold(
        tenant_id=TENANT_ID,
        hold_id=hold_id,
        lifted_by="legal-lead",
    )
    assert released.lifted_at is not None
    assert released.lifted_by == "legal-lead"
    assert await protection.list_legal_holds(tenant_id=TENANT_ID) == ()

    proposed = await protection.propose_erasure(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        reason="customer GDPR Article 17 request",
        proposed_by="dpo-a",
    )
    executed = await protection.approve_erasure(
        tenant_id=TENANT_ID,
        request_id=proposed.request_id,
        approved_by="dpo-b",
    )

    assert executed.status is ErasureRequestStatus.EXECUTED
    assert not await protection.has_active_legal_hold(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
    )


@requires_postgres
@pytest.mark.asyncio
async def test_master_key_rotation_rewraps_data_keys_only(
    pg_session: AsyncSession,
) -> None:
    await pg_session.execute(delete(DataProtectionDataKeyRow))
    protection = _service(pg_session, key=b"a" * 32, version="v1")
    session_repo = PostgresSessionPersistence(
        pg_session,
        data_protection=protection,
    )
    session_id = SessionId(uuid.uuid4())
    event = _event_record(session_id)
    await session_repo.save_session(_session_record(session_id))
    await session_repo.save_event(event)
    await pg_session.flush()

    new_ring = MasterKeyRing(
        keys={"v1": b"a" * 32, "v2": b"b" * 32},
        active_version="v2",
    )
    assert await protection.rotate_master_key(new_ring=new_ring) >= 1
    versions = (
        await pg_session.execute(select(DataProtectionDataKeyRow.master_key_version))
    ).scalars().all()
    assert set(versions) == {"v2"}

    v2_only = DataProtectionService(
        pg_session,
        master_key_ring=MasterKeyRing(keys={"v2": b"b" * 32}, active_version="v2"),
    )
    rotated_repo = PostgresSessionPersistence(
        pg_session,
        data_protection=v2_only,
    )
    stored = await rotated_repo.get_event(event.event_id, expected_tenant_id=TENANT_ID)
    assert stored is not None
    assert stored.payload["content"] == event.payload["content"]


@requires_postgres
@pytest.mark.asyncio
async def test_tenant_owned_knowledge_uses_tenant_key_and_blocks_full_text(
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    tenant_repo = PostgresTenantConfigurationRepository(
        pg_session,
        data_protection=protection,
    )
    document_id = TenantKnowledgeDocumentId(uuid.uuid4())
    document = TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=TENANT_ID,
        title="Battery SOP",
        content="replace private customer battery pack",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        version=1,
        uploaded_by="ops",
        vector_indexed_at=None,
        created_at=NOW,
    )
    await tenant_repo.save_knowledge_document(document, expected_tenant_id=TENANT_ID)
    await pg_session.flush()

    raw = (
        await pg_session.execute(
            select(TenantKnowledgeDocumentRow).where(
                TenantKnowledgeDocumentRow.document_id == document_id
            )
        )
    ).scalar_one()
    assert "private customer" not in raw.content
    stored = await tenant_repo.get_knowledge_document(
        document_id,
        expected_tenant_id=TENANT_ID,
    )
    assert stored is not None
    assert stored.content == document.content

    knowledge_repo = PostgresKnowledgeRepository(
        pg_session,
        data_protection=protection,
    )
    with pytest.raises(KnowledgePersistenceError):
        await knowledge_repo.list_vector_entries(
            KnowledgeVectorQuery(
                vector_index_name="default",
                search_text="private customer",
            ),
            expected_tenant_id=TENANT_ID,
        )
