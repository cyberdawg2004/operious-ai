"""Durable tenant config dual-control ledger tests (S-03)."""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events import PostgresOperationalEventPersistence
from app.events.appender import OperationalEventAppender
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)
from app.services.tenant_configuration_service import TenantConfigurationService
from app.tenant.change_requests import (
    PostgresTenantConfigChangeRequestRepository,
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
    derive_tenant_config_change_request_id,
)
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantKnowledgeDocumentStatus, TenantKnowledgeDocumentType
from app.tenant.exceptions import TenantConfigurationDirectApplyDisabledError
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentQuery,
)
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_MASTER_KEY = "tenant-config-change-ledger-master-key-32-bytes"


class _RedisStub:
    async def publish(self, _channel: str, _payload: str) -> None:
        return None


def _service(session: AsyncSession) -> TenantConfigChangeRequestService:
    tenant_configuration = TenantConfigurationService(
        runtime=TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
            credential_encryptor=TenantCredentialEncryptor(
                platform_master_key=_MASTER_KEY,
            ),
        ),
        session=session,
        redis_client=_RedisStub(),
    )
    return TenantConfigChangeRequestService(
        repository=PostgresTenantConfigChangeRequestRepository(session),
        tenant_configuration_service=tenant_configuration,
        event_appender=OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        ),
        session=session,
    )


def _tenant() -> str:
    return str(uuid.uuid4())


def _knowledge_payload(title: str = "Warranty FAQ") -> dict[str, Any]:
    return {
        "title": title,
        "content": "v1",
        "document_type": TenantKnowledgeDocumentType.FAQ.value,
        "status": TenantKnowledgeDocumentStatus.ACTIVE.value,
    }


@pytest.mark.asyncio
async def test_propose_creates_pending_request(pg_session: AsyncSession) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)

    record = await _service(pg_session).propose(
        tenant_id=tenant_id,
        change_type=TenantConfigChangeType.KNOWLEDGE,
        payload=_knowledge_payload(),
        proposed_by="principal-a",
    )

    assert record.status is TenantConfigChangeRequestStatus.PROPOSED
    assert record.proposed_by == "principal-a"
    assert record.proposed_payload["_schema_version"] == "1"
    assert record.approved_by is None


@pytest.mark.asyncio
async def test_approve_by_different_principal_succeeds(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _service(pg_session)
    proposed = await service.propose(
        tenant_id=tenant_id,
        change_type="knowledge",
        payload=_knowledge_payload(),
        proposed_by="principal-a",
    )

    approved = await service.approve(
        change_request_id=proposed.change_request_id,
        approved_by="principal-b",
        expected_tenant_id=tenant_id,
    )

    assert approved.status is TenantConfigChangeRequestStatus.APPROVED
    assert approved.approved_by == "principal-b"
    assert approved.approved_at is not None


@pytest.mark.asyncio
async def test_approve_by_same_principal_rejected_at_db_layer(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)

    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await pg_session.execute(
                text("""
                    INSERT INTO public.tenant_config_change_requests (
                        change_request_id,
                        tenant_id,
                        change_type,
                        proposed_payload,
                        status,
                        proposed_by,
                        proposed_at,
                        approved_by,
                        approved_at
                    )
                    VALUES (
                        CAST(:change_request_id AS uuid),
                        CAST(:tenant_id AS uuid),
                        'knowledge',
                        CAST(:payload AS jsonb),
                        'APPROVED',
                        'principal-a',
                        now(),
                        'principal-a',
                        now()
                    )
                    """),
                {
                    "change_request_id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "payload": json.dumps({"_schema_version": "1"}),
                },
            )


@pytest.mark.asyncio
async def test_apply_only_after_approved(pg_session: AsyncSession) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _service(pg_session)
    proposed = await service.propose(
        tenant_id=tenant_id,
        change_type="knowledge",
        payload=_knowledge_payload("Approved FAQ"),
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

    assert applied.status is TenantConfigChangeRequestStatus.APPLIED
    assert applied.outcome_payload is not None
    assert applied.outcome_payload["kind"] == "knowledge_document"
    docs = await PostgresTenantConfigurationRepository(
        pg_session
    ).list_knowledge_documents(
        TenantKnowledgeDocumentQuery(),
        expected_tenant_id=tenant_id,
    )
    assert docs.total == 1
    assert docs.items[0].title == "Approved FAQ"


@pytest.mark.asyncio
async def test_apply_unapproved_request_denied(pg_session: AsyncSession) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _service(pg_session)
    proposed = await service.propose(
        tenant_id=tenant_id,
        change_type="knowledge",
        payload=_knowledge_payload("Unapproved FAQ"),
        proposed_by="principal-a",
    )

    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.apply(
            change_request_id=proposed.change_request_id,
            expected_tenant_id=tenant_id,
            applied_by="principal-b",
        )


@pytest.mark.asyncio
async def test_production_blocks_direct_self_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TENANT_CONFIG_ALLOW_SELF_APPROVAL", "true")
    get_settings.cache_clear()
    service = TenantConfigurationService(
        runtime=cast(Any, object()),
        session=cast(Any, object()),
        redis_client=_RedisStub(),
    )

    with pytest.raises(TenantConfigurationDirectApplyDisabledError):
        await service.create_knowledge_document(
            tenant_id=str(uuid.uuid4()),
            title="blocked",
            content="blocked",
            document_type=TenantKnowledgeDocumentType.FAQ,
            status=TenantKnowledgeDocumentStatus.ACTIVE,
            uploaded_by="principal-a",
        )

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ledger_rls_isolation(pg_session: AsyncSession) -> None:
    tenant_a = _tenant()
    tenant_b = _tenant()
    service = _service(pg_session)

    await set_pg_rls_tenant(pg_session, tenant_a)
    await service.propose(
        tenant_id=tenant_a,
        change_type="knowledge",
        payload=_knowledge_payload("Tenant A"),
        proposed_by="principal-a",
    )
    await set_pg_rls_tenant(pg_session, tenant_b)
    await service.propose(
        tenant_id=tenant_b,
        change_type="knowledge",
        payload=_knowledge_payload("Tenant B"),
        proposed_by="principal-b",
    )

    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"restricted RLS role unavailable: {exc}")

    await set_pg_rls_tenant(pg_session, tenant_a)
    visible_a = (
        await pg_session.execute(
            text("SELECT count(*) FROM public.tenant_config_change_requests")
        )
    ).scalar_one()
    await set_pg_rls_tenant(pg_session, tenant_b)
    visible_b = (
        await pg_session.execute(
            text("SELECT count(*) FROM public.tenant_config_change_requests")
        )
    ).scalar_one()

    assert visible_a == 1
    assert visible_b == 1


def test_change_request_id_deterministic_uuid5() -> None:
    tenant_id = _tenant()
    payload = {"_schema_version": "1", **_knowledge_payload()}

    first = derive_tenant_config_change_request_id(
        tenant_id=tenant_id,
        change_type="knowledge",
        proposed_payload=payload,
        proposed_by="principal-a",
    )
    second = derive_tenant_config_change_request_id(
        tenant_id=tenant_id,
        change_type=TenantConfigChangeType.KNOWLEDGE,
        proposed_payload=payload,
        proposed_by="principal-a",
    )

    assert first == second
    assert first.version == 5
