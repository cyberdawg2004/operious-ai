"""Phase 2.5-A tenant configuration runtime tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.exceptions import (
    TenantConfigurationPersistenceError,
    TenantCredentialEncryptionError,
)
from app.tenant.identity import (
    derive_channel_configuration_id,
    derive_governance_policy_id,
    derive_knowledge_document_id,
)
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantChannelConfigurationQuery,
    TenantChannelConfigurationRecord,
)
from app.tenant.runtime import TenantConfigurationRuntime

_MASTER_KEY = "tenant-config-test-master-key-material-32-bytes"


def _runtime() -> TenantConfigurationRuntime:
    return TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY,
        ),
    )


def test_channel_config_identity_is_deterministic_uuid5() -> None:
    first = derive_channel_configuration_id(
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
    )
    second = derive_channel_configuration_id(
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
    )
    other = derive_channel_configuration_id(
        tenant_id="tenant-other",
        channel_type=TenantChannelType.EMAIL,
    )

    assert first == second
    assert first != other
    assert first.version == 5


def test_document_and_policy_identities_are_deterministic_uuid5() -> None:
    document_id = derive_knowledge_document_id(
        tenant_id="tenant-acme",
        document_type=TenantKnowledgeDocumentType.FAQ,
        title="Warranty FAQ",
    )
    policy_id = derive_governance_policy_id(
        tenant_id="tenant-acme",
        policy_type="refund_limit",
    )

    assert document_id == derive_knowledge_document_id(
        tenant_id="tenant-acme",
        document_type=TenantKnowledgeDocumentType.FAQ,
        title="Warranty FAQ",
    )
    assert policy_id == derive_governance_policy_id(
        tenant_id="tenant-acme",
        policy_type="refund_limit",
    )
    assert document_id.version == 5
    assert policy_id.version == 5


@pytest.mark.asyncio
async def test_credentials_are_encrypted_and_only_decrypted_at_runtime() -> None:
    runtime = _runtime()
    record = await runtime.configure_channel(
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        credentials={"api_key": "super-secret-api-key"},
        webhook_secret="webhook-secret",
    )

    assert b"super-secret-api-key" not in record.credentials_enc
    assert "super-secret-api-key" not in repr(record)
    assert await runtime.load_channel_credentials(
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
    ) == {"api_key": "super-secret-api-key"}

    encryptor = TenantCredentialEncryptor(platform_master_key=_MASTER_KEY)
    with pytest.raises(TenantCredentialEncryptionError):
        encryptor.decrypt(
            tenant_id="tenant-other",
            encrypted_credentials=record.credentials_enc,
        )


@pytest.mark.asyncio
async def test_repository_enforces_expected_tenant_id_on_writes() -> None:
    repository = InMemoryTenantConfigurationRepository()
    config_id = derive_channel_configuration_id(
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
    )
    record = TenantChannelConfigurationRecord(
        config_id=config_id,
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
        status=TenantChannelStatus.PENDING_VERIFICATION,
        routing_address="support@example.com",
        credentials_enc=b"encrypted",
        webhook_secret="webhook-secret",
        verified_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(TenantConfigurationPersistenceError):
        await repository.save_channel_configuration(
            record,
            expected_tenant_id="tenant-other",
        )


@pytest.mark.asyncio
async def test_tenant_isolation_on_reads() -> None:
    runtime = _runtime()
    await runtime.configure_channel(
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        credentials={"api_key": "secret"},
        webhook_secret="webhook-secret",
    )

    page = await runtime.list_channels(
        tenant_id="tenant-other",
        query=TenantChannelConfigurationQuery(),
    )

    assert page.items == ()


@pytest.mark.asyncio
async def test_active_channel_route_resolution_fails_closed() -> None:
    runtime = _runtime()
    await runtime.configure_channel(
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        credentials={"api_key": "secret"},
        webhook_secret="webhook-secret",
        status=TenantChannelStatus.ACTIVE,
    )
    await runtime.configure_channel(
        tenant_id="tenant-paused",
        channel_type=TenantChannelType.EMAIL,
        routing_address="paused@example.com",
        credentials={"api_key": "secret"},
        webhook_secret="webhook-secret",
        status=TenantChannelStatus.PAUSED,
    )

    resolved = await runtime.resolve_active_channel_for_routing_address(
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
    )

    assert resolved is not None
    assert resolved.tenant_id == "tenant-acme"
    assert await runtime.resolve_active_channel_for_routing_address(
        channel_type=TenantChannelType.EMAIL,
        routing_address="paused@example.com",
    ) is None
    assert await runtime.resolve_active_channel_for_routing_address(
        channel_type=TenantChannelType.EMAIL,
        routing_address="missing@example.com",
    ) is None


@pytest.mark.asyncio
async def test_knowledge_and_policy_versions_increment() -> None:
    runtime = _runtime()
    first_doc = await runtime.create_knowledge_document(
        tenant_id="tenant-acme",
        title="Warranty FAQ",
        content="v1",
        document_type=TenantKnowledgeDocumentType.FAQ,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        uploaded_by="principal-a",
    )
    second_doc = await runtime.create_knowledge_document(
        tenant_id="tenant-acme",
        title="Warranty FAQ",
        content="v2",
        document_type=TenantKnowledgeDocumentType.FAQ,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        uploaded_by="principal-a",
    )

    assert second_doc.document_id == first_doc.document_id
    assert second_doc.version == first_doc.version + 1

    first_policy = await runtime.create_governance_policy(
        tenant_id="tenant-acme",
        policy_type="refund_limit",
        parameters={"max_refund_usd": 50},
        status=TenantGovernancePolicyStatus.DRAFT,
        approved_by="principal-a",
        effective_from=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    second_policy = await runtime.update_governance_policy(
        tenant_id="tenant-acme",
        policy_id=first_policy.policy_id,
        parameters={"max_refund_usd": 75},
        status=TenantGovernancePolicyStatus.ACTIVE,
        approved_by="principal-b",
        effective_from=None,
    )

    assert second_policy.policy_id == first_policy.policy_id
    assert second_policy.version == first_policy.version + 1
