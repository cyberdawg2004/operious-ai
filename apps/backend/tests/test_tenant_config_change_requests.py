"""Durable tenant config dual-control ledger tests (S-03)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.action_governance import ACTION_TOOLS_POLICY_TYPE
from app.api.v1.schemas.tenant import TenantConfigChangeRequestResponse
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
    TenantConfigChangeRequestSeparationError,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
    derive_tenant_config_change_request_id,
)
from app.tenant.chronology import canonical_sha256
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.exceptions import TenantConfigurationDirectApplyDisabledError
from app.tenant.identity import derive_channel_configuration_id
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantConnectorConfigurationQuery,
    TenantKnowledgeDocumentQuery,
)
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_MASTER_KEY = "tenant-config-change-ledger-master-key-32-bytes"
_ACTION_POLICY_EFFECTIVE_FROM = datetime(2026, 6, 1, tzinfo=timezone.utc)


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


def _connector_payload(
    *,
    endpoint_template: str = "https://refunds.example.com/refunds/{order_id}",
) -> dict[str, Any]:
    return {
        "connector_type": TenantChannelType.ZENDESK.value,
        "tool_name": "refund.request",
        "http_method": "POST",
        "endpoint_template": endpoint_template,
        "endpoint_host": "refunds.example.com",
        "field_mappings": {"order_id": "payload.order_id"},
        "idempotency_header_name": "X-Idempotency-Key",
        "response_parse": {"provider_id": "refund.id"},
        "success_status_codes": [200, 201, 202],
        "status": "active",
    }


def _valid_action_tools_parameters() -> dict[str, Any]:
    return {
        "phase": "2.4",
        "tools": {
            "warranty.claim": {
                "allow": {
                    "confidence_gte": 0.85,
                    "issue_category_in": ["charging_issue", "product_defect"],
                },
                "else": "require_approval",
            },
            "replacement.order": {"always": "require_approval"},
            "refund.request": {
                "allow": {"refund_amount_cents_lte": 5000},
                "else": "require_approval",
            },
            "warehouse.repair.report": {
                "allow": {"severity_in": ["low", "medium"]},
                "require_approval": {"severity_in": ["high", "critical"]},
            },
        },
    }


def _action_tools_policy_payload(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_type": ACTION_TOOLS_POLICY_TYPE,
        "parameters": parameters,
        "status": TenantGovernancePolicyStatus.ACTIVE.value,
        "effective_from": _ACTION_POLICY_EFFECTIVE_FROM.isoformat(),
    }


def _connector_content_sha256(
    *,
    tenant_id: str,
    payload: dict[str, Any],
    version: int,
    configured_by: str,
    source_approval_id: str,
) -> str:
    return canonical_sha256(
        {
            "tenant_id": tenant_id,
            "connector_type": payload["connector_type"],
            "tool_name": payload["tool_name"],
            "http_method": payload["http_method"],
            "endpoint_template": payload["endpoint_template"],
            "endpoint_host": payload["endpoint_host"],
            "field_mappings": payload["field_mappings"],
            "idempotency_header_name": payload["idempotency_header_name"],
            "response_parse": payload["response_parse"],
            "success_status_codes": payload["success_status_codes"],
            "status": payload["status"],
            "version": version,
            "configured_by": configured_by,
            "source_approval_id": source_approval_id,
        }
    )


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
async def test_2_5a_1_connector_dual_control_app_and_db_check(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _service(pg_session)
    proposed = await service.propose(
        tenant_id=tenant_id,
        change_type=TenantConfigChangeType.CONNECTOR,
        payload=_connector_payload(),
        proposed_by="principal-a",
    )

    with pytest.raises(TenantConfigChangeRequestSeparationError):
        await service.approve(
            change_request_id=proposed.change_request_id,
            approved_by="principal-a",
            expected_tenant_id=tenant_id,
        )

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
                        'connector',
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
                    "payload": json.dumps(
                        {"_schema_version": "1", **_connector_payload()}
                    ),
                },
            )


@pytest.mark.asyncio
async def test_2_5a_2_connector_target_reconstruction_chain(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _service(pg_session)
    repo = PostgresTenantConfigurationRepository(pg_session)

    first_payload = _connector_payload()
    first = await service.propose(
        tenant_id=tenant_id,
        change_type="connector",
        payload=first_payload,
        proposed_by="principal-a",
    )
    await service.approve(
        change_request_id=first.change_request_id,
        approved_by="principal-b",
        expected_tenant_id=tenant_id,
    )
    await service.apply(
        change_request_id=first.change_request_id,
        expected_tenant_id=tenant_id,
        applied_by="principal-b",
    )

    second_payload = _connector_payload(
        endpoint_template="https://refunds.example.com/v2/refunds/{order_id}"
    )
    second = await service.propose(
        tenant_id=tenant_id,
        change_type="connector",
        payload=second_payload,
        proposed_by="principal-a",
    )
    await service.approve(
        change_request_id=second.change_request_id,
        approved_by="principal-b",
        expected_tenant_id=tenant_id,
    )
    await service.apply(
        change_request_id=second.change_request_id,
        expected_tenant_id=tenant_id,
        applied_by="principal-b",
    )

    page = await repo.list_connector_configurations(
        TenantConnectorConfigurationQuery(
            connector_type=TenantChannelType.ZENDESK.value,
            tool_name="refund.request",
        ),
        expected_tenant_id=tenant_id,
    )
    assert [record.version for record in page.items] == [1, 2]
    first_record, second_record = page.items
    assert first_record.previous_version_sha256 is None
    assert second_record.previous_version_sha256 == first_record.content_sha256
    assert first_record.content_sha256 == _connector_content_sha256(
        tenant_id=tenant_id,
        payload=first_payload,
        version=1,
        configured_by="principal-b",
        source_approval_id=first_record.source_approval_id,
    )
    assert second_record.content_sha256 == _connector_content_sha256(
        tenant_id=tenant_id,
        payload=second_payload,
        version=2,
        configured_by="principal-b",
        source_approval_id=second_record.source_approval_id,
    )
    assert first_record.source_approval_id != second_record.source_approval_id


@pytest.mark.asyncio
async def test_2_5a_3_action_tools_policy_malformed_rejected_at_propose_and_apply(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _service(pg_session)
    malformed_parameters = _valid_action_tools_parameters()
    del malformed_parameters["tools"]["refund.request"]

    with pytest.raises(
        TenantConfigChangeRequestLifecycleError,
        match="invalid action_tools policy parameters",
    ):
        await service.propose(
            tenant_id=tenant_id,
            change_type="policy",
            payload=_action_tools_policy_payload(malformed_parameters),
            proposed_by="principal-a",
        )

    tampered = await service.propose(
        tenant_id=tenant_id,
        change_type="policy",
        payload=_action_tools_policy_payload(_valid_action_tools_parameters()),
        proposed_by="principal-a",
    )
    tampered_payload = {
        "_schema_version": "1",
        **_action_tools_policy_payload(malformed_parameters),
    }
    await pg_session.execute(
        text("""
            UPDATE public.tenant_config_change_requests
            SET proposed_payload = CAST(:payload AS jsonb)
            WHERE change_request_id = CAST(:change_request_id AS uuid)
            """),
        {
            "change_request_id": str(tampered.change_request_id),
            "payload": json.dumps(tampered_payload),
        },
    )
    await service.approve(
        change_request_id=tampered.change_request_id,
        approved_by="principal-b",
        expected_tenant_id=tenant_id,
    )
    with pytest.raises(
        TenantConfigChangeRequestLifecycleError,
        match="invalid action_tools policy parameters",
    ):
        await service.apply(
            change_request_id=tampered.change_request_id,
            expected_tenant_id=tenant_id,
            applied_by="principal-b",
        )


@pytest.mark.asyncio
async def test_2_5a_4_channel_credentials_write_only_and_reusable_by_connector(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant()
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _service(pg_session)
    channel_payload = {
        "channel_type": TenantChannelType.ZENDESK.value,
        "routing_address": "support.example.com",
        "credentials": {"api_key": "secret-api-key"},
        "webhook_secret": "secret-webhook",
        "status": TenantChannelStatus.ACTIVE.value,
    }

    proposed = await service.propose(
        tenant_id=tenant_id,
        change_type="channel",
        payload=channel_payload,
        proposed_by="principal-a",
    )
    proposed_response = TenantConfigChangeRequestResponse.from_record(proposed)
    assert "secret-api-key" not in proposed_response.model_dump_json()
    assert "secret-webhook" not in proposed_response.model_dump_json()

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
    applied_response = TenantConfigChangeRequestResponse.from_record(applied)
    assert "secret-api-key" not in applied_response.model_dump_json()
    assert "secret-webhook" not in applied_response.model_dump_json()

    repo = PostgresTenantConfigurationRepository(pg_session)
    stored = await repo.get_channel_configuration(
        derive_channel_configuration_id(
            tenant_id=tenant_id,
            channel_type=TenantChannelType.ZENDESK,
        ),
        expected_tenant_id=tenant_id,
    )
    assert stored is not None
    assert b"secret-api-key" not in stored.credentials_enc
    runtime = TenantConfigurationRuntime(
        repository=repo,
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY,
        ),
    )
    assert await runtime.load_channel_credentials(
        tenant_id=tenant_id,
        channel_type=TenantChannelType.ZENDESK,
    ) == {"api_key": "secret-api-key"}

    connector = await service.propose(
        tenant_id=tenant_id,
        change_type="connector",
        payload=_connector_payload(),
        proposed_by="principal-a",
    )
    assert "secret-api-key" not in TenantConfigChangeRequestResponse.from_record(
        connector
    ).model_dump_json()
    assert "credentials" not in connector.proposed_payload


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
