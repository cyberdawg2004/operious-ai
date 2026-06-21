"""W0 break-controls: tenant message templates (TenantKnowledgeDocumentType.TEMPLATE).

Templates reuse tenant_knowledge_documents as-is — same RLS, same
QUARANTINED -> APPROVED review gate, same dual-control create/update
flow as SOP/POLICY documents — with two additional structured columns
(template_purpose, template_channel) for exact-match retrieval by a
future probe-dispatch workflow (W4). No parallel store.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)
from app.services.tenant_configuration_service import TenantConfigurationService
from app.tenant.change_requests import (
    PostgresTenantConfigChangeRequestRepository,
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeType,
)
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.exceptions import (
    TenantConfigurationError,
    TenantConfigurationPersistenceError,
)
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentQuery,
)
from app.tenant.runtime import TenantConfigurationRuntime
from app.tenant.template_placeholders import extract_placeholders
from app.events import PostgresOperationalEventPersistence
from app.events.appender import OperationalEventAppender
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_MASTER_KEY = "w0-templates-master-key-32-bytes-minimum"


class _RedisStub:
    async def publish(self, _channel: str, _payload: str) -> None:
        return None


def _tenant_configuration(session: AsyncSession) -> TenantConfigurationService:
    return TenantConfigurationService(
        runtime=TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
            credential_encryptor=TenantCredentialEncryptor(
                platform_master_key=_MASTER_KEY,
            ),
        ),
        session=session,
        redis_client=_RedisStub(),
    )


def _change_request_service(
    session: AsyncSession,
) -> TenantConfigChangeRequestService:
    return TenantConfigChangeRequestService(
        repository=PostgresTenantConfigChangeRequestRepository(session),
        tenant_configuration_service=_tenant_configuration(session),
        event_appender=OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        ),
        session=session,
    )


def _tenant() -> str:
    return f"tenant-template-{uuid.uuid4().hex}"


def _template_payload(
    *,
    title: str,
    content: str = "Hi! We still need {order_id} to proceed.",
    purpose: str = "probe.missing_invoice",
    channel: str = "whatsapp",
) -> dict[str, object]:
    return {
        "title": title,
        "content": content,
        "document_type": TenantKnowledgeDocumentType.TEMPLATE.value,
        "status": TenantKnowledgeDocumentStatus.ACTIVE.value,
        "template_purpose": purpose,
        "template_channel": channel,
    }


# ─── dual-control creation + review-gating ─────────────────────────────────


@pytest.mark.asyncio
async def test_template_created_via_dual_control_flow_is_quarantined_until_approved(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _change_request_service(pg_session)

    proposed = await service.propose(
        tenant_id=tenant_id,
        change_type=TenantConfigChangeType.KNOWLEDGE,
        payload=_template_payload(title="Missing Invoice Probe"),
        proposed_by="principal-a",
    )
    await service.approve(
        change_request_id=proposed.change_request_id,
        approved_by="principal-b",
        expected_tenant_id=tenant_id,
    )
    applied = await service.apply(
        change_request_id=proposed.change_request_id,
        expected_tenant_id=tenant_id,
        applied_by="principal-b",
    )
    assert applied.outcome_payload is not None
    assert applied.outcome_payload["kind"] == "knowledge_document"

    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_session),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY
        ),
    )
    # Dual-control sign-off (two-person propose/approve) is a SEPARATE gate
    # from content review_status — applying the change request creates the
    # row, but it still defaults to QUARANTINED and must not be retrievable
    # until a reviewer separately approves the content.
    not_yet = await runtime.get_approved_template(
        tenant_id=tenant_id, purpose="probe.missing_invoice", channel="whatsapp"
    )
    assert not_yet is None

    docs = await PostgresTenantConfigurationRepository(
        pg_session
    ).list_knowledge_documents(
        TenantKnowledgeDocumentQuery(document_type=TenantKnowledgeDocumentType.TEMPLATE),
        expected_tenant_id=tenant_id,
    )
    assert docs.total == 1
    assert docs.items[0].review_status is TenantKnowledgeReviewStatus.QUARANTINED
    assert docs.items[0].template_purpose == "probe.missing_invoice"
    assert docs.items[0].template_channel == "whatsapp"


@pytest.mark.asyncio
async def test_template_change_request_rejects_missing_purpose_or_channel(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _change_request_service(pg_session)
    payload = _template_payload(title="Incomplete Template")
    del payload["template_channel"]

    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.propose(
            tenant_id=tenant_id,
            change_type=TenantConfigChangeType.KNOWLEDGE,
            payload=payload,
            proposed_by="principal-a",
        )


@pytest.mark.asyncio
async def test_approving_review_status_makes_template_retrievable(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    config = _tenant_configuration(pg_session)
    created = await config.create_knowledge_document(
        tenant_id=tenant_id,
        title="Missing Reseller Probe",
        content="We could not verify {seller} as an authorized reseller.",
        document_type=TenantKnowledgeDocumentType.TEMPLATE,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        uploaded_by="principal-a",
        bypass_direct_apply_gate=True,
        template_purpose="probe.unauthorized_reseller",
        template_channel="email",
    )
    assert created.review_status is TenantKnowledgeReviewStatus.QUARANTINED

    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_session),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY
        ),
    )
    still_none = await runtime.get_approved_template(
        tenant_id=tenant_id,
        purpose="probe.unauthorized_reseller",
        channel="email",
    )
    assert still_none is None

    await config.update_knowledge_document(
        tenant_id=tenant_id,
        document_id=created.document_id,
        content=None,
        status=None,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        uploaded_by="reviewer-a",
        bypass_direct_apply_gate=True,
    )

    found = await runtime.get_approved_template(
        tenant_id=tenant_id,
        purpose="probe.unauthorized_reseller",
        channel="email",
    )
    assert found is not None
    assert found.document_id == created.document_id
    assert found.review_status is TenantKnowledgeReviewStatus.APPROVED


# ─── retrieval: exact match, not-found, no fabricated default ─────────────


@pytest.mark.asyncio
async def test_retrieval_returns_the_correct_template_among_several(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    config = _tenant_configuration(pg_session)

    async def _create_approved(
        *, title: str, purpose: str, channel: str, content: str
    ) -> None:
        created = await config.create_knowledge_document(
            tenant_id=tenant_id,
            title=title,
            content=content,
            document_type=TenantKnowledgeDocumentType.TEMPLATE,
            status=TenantKnowledgeDocumentStatus.ACTIVE,
            uploaded_by="principal-a",
            bypass_direct_apply_gate=True,
            template_purpose=purpose,
            template_channel=channel,
        )
        await config.update_knowledge_document(
            tenant_id=tenant_id,
            document_id=created.document_id,
            content=None,
            status=None,
            review_status=TenantKnowledgeReviewStatus.APPROVED,
            uploaded_by="reviewer-a",
            bypass_direct_apply_gate=True,
        )

    await _create_approved(
        title="Invoice Probe WhatsApp",
        purpose="probe.missing_invoice",
        channel="whatsapp",
        content="whatsapp invoice probe",
    )
    await _create_approved(
        title="Invoice Probe Email",
        purpose="probe.missing_invoice",
        channel="email",
        content="email invoice probe",
    )
    await _create_approved(
        title="Reseller Probe WhatsApp",
        purpose="probe.unauthorized_reseller",
        channel="whatsapp",
        content="whatsapp reseller probe",
    )

    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_session),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY
        ),
    )
    match = await runtime.get_approved_template(
        tenant_id=tenant_id, purpose="probe.missing_invoice", channel="email"
    )
    assert match is not None
    assert match.content == "email invoice probe"

    other_match = await runtime.get_approved_template(
        tenant_id=tenant_id,
        purpose="probe.unauthorized_reseller",
        channel="whatsapp",
    )
    assert other_match is not None
    assert other_match.content == "whatsapp reseller probe"


@pytest.mark.asyncio
async def test_missing_template_returns_none_not_a_fabricated_default(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_session),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY
        ),
    )
    result = await runtime.get_approved_template(
        tenant_id=tenant_id, purpose="probe.nonexistent", channel="whatsapp"
    )
    assert result is None


# ─── cross-tenant isolation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_tenant_isolation(pg_session: AsyncSession) -> None:
    owner_tenant = _tenant()
    other_tenant = _tenant()
    await set_pg_rls_tenant(pg_session, owner_tenant)
    config = _tenant_configuration(pg_session)
    created = await config.create_knowledge_document(
        tenant_id=owner_tenant,
        title="Owner Template",
        content="owner-only content",
        document_type=TenantKnowledgeDocumentType.TEMPLATE,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        uploaded_by="principal-a",
        bypass_direct_apply_gate=True,
        template_purpose="probe.missing_invoice",
        template_channel="whatsapp",
    )
    await config.update_knowledge_document(
        tenant_id=owner_tenant,
        document_id=created.document_id,
        content=None,
        status=None,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        uploaded_by="reviewer-a",
        bypass_direct_apply_gate=True,
    )

    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_session),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY
        ),
    )
    # Application-level defense in depth: the repository's mandatory
    # tenant_id clamp on every query (same guarantee AttachmentRepository
    # gives B1a). Table-level FORCE ROW LEVEL SECURITY itself is already
    # covered for every tenant_id-bearing table — tenant_knowledge_documents
    # included, unchanged by migration 0090 — by the generic
    # test_rls_coverage_invariant.py::test_every_tenant_table_forces_rls;
    # this file doesn't re-prove RLS bypass since pg_session's owner-role
    # connection bypasses RLS by design for seeding.
    cross_tenant = await runtime.get_approved_template(
        tenant_id=other_tenant, purpose="probe.missing_invoice", channel="whatsapp"
    )
    assert cross_tenant is None


# ─── placeholder convention ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_placeholder_content_stores_and_retrieves_intact(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    config = _tenant_configuration(pg_session)
    content = (
        "Hi! To process order {order_id}, we still need: {missing_fields}. "
        "Reply when ready."
    )
    created = await config.create_knowledge_document(
        tenant_id=tenant_id,
        title="Placeholder Probe",
        content=content,
        document_type=TenantKnowledgeDocumentType.TEMPLATE,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        uploaded_by="principal-a",
        bypass_direct_apply_gate=True,
        template_purpose="probe.missing_invoice",
        template_channel="whatsapp",
    )
    await config.update_knowledge_document(
        tenant_id=tenant_id,
        document_id=created.document_id,
        content=None,
        status=None,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        uploaded_by="reviewer-a",
        bypass_direct_apply_gate=True,
    )

    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_session),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY
        ),
    )
    found = await runtime.get_approved_template(
        tenant_id=tenant_id, purpose="probe.missing_invoice", channel="whatsapp"
    )
    assert found is not None
    assert found.content == content
    assert extract_placeholders(found.content) == frozenset(
        {"order_id", "missing_fields"}
    )


def test_extract_placeholders_ignores_escaped_braces() -> None:
    assert extract_placeholders("literal {{not_a_placeholder}} text") == frozenset()


def test_extract_placeholders_ignores_malformed_names() -> None:
    assert extract_placeholders("{Order ID} is not snake_case") == frozenset()


# ─── fail-closed validation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_template_without_purpose_or_channel_rejected(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    config = _tenant_configuration(pg_session)
    with pytest.raises(TenantConfigurationError):
        await config.create_knowledge_document(
            tenant_id=tenant_id,
            title="Bad Template",
            content="missing purpose/channel",
            document_type=TenantKnowledgeDocumentType.TEMPLATE,
            status=TenantKnowledgeDocumentStatus.ACTIVE,
            uploaded_by="principal-a",
            bypass_direct_apply_gate=True,
        )


@pytest.mark.asyncio
async def test_non_template_rejects_purpose_or_channel(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    config = _tenant_configuration(pg_session)
    with pytest.raises(TenantConfigurationError):
        await config.create_knowledge_document(
            tenant_id=tenant_id,
            title="Misplaced Fields",
            content="this is a FAQ, not a template",
            document_type=TenantKnowledgeDocumentType.FAQ,
            status=TenantKnowledgeDocumentStatus.ACTIVE,
            uploaded_by="principal-a",
            bypass_direct_apply_gate=True,
            template_purpose="probe.missing_invoice",
            template_channel="whatsapp",
        )


@pytest.mark.asyncio
async def test_duplicate_template_slot_rejected(pg_session: AsyncSession) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    config = _tenant_configuration(pg_session)
    await config.create_knowledge_document(
        tenant_id=tenant_id,
        title="First Invoice Probe",
        content="first",
        document_type=TenantKnowledgeDocumentType.TEMPLATE,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        uploaded_by="principal-a",
        bypass_direct_apply_gate=True,
        template_purpose="probe.missing_invoice",
        template_channel="whatsapp",
    )
    with pytest.raises((TenantConfigurationPersistenceError, IntegrityError)):
        await config.create_knowledge_document(
            tenant_id=tenant_id,
            title="Second Invoice Probe",
            content="second, same slot",
            document_type=TenantKnowledgeDocumentType.TEMPLATE,
            status=TenantKnowledgeDocumentStatus.ACTIVE,
            uploaded_by="principal-a",
            bypass_direct_apply_gate=True,
            template_purpose="probe.missing_invoice",
            template_channel="whatsapp",
        )
