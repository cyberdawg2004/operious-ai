"""Tenant configuration runtime boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.exceptions import TenantConfigurationNotFoundError
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
    derive_channel_configuration_id,
    derive_governance_policy_id,
    derive_knowledge_document_id,
)
from app.tenant.persistence import (
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
    TenantChannelConfigurationRecord,
    TenantConfigurationRepository,
    TenantGovernancePolicyPage,
    TenantGovernancePolicyQuery,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentPage,
    TenantKnowledgeDocumentQuery,
    TenantKnowledgeDocumentRecord,
)


class TenantConfigurationRuntime:
    """Runtime authority for tenant-owned configuration records."""

    def __init__(
        self,
        *,
        repository: TenantConfigurationRepository,
        credential_encryptor: TenantCredentialEncryptor,
    ) -> None:
        self._repository = repository
        self._credential_encryptor = credential_encryptor

    async def configure_channel(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
        routing_address: str,
        credentials: Mapping[str, Any],
        webhook_secret: str,
        status: TenantChannelStatus = (
            TenantChannelStatus.PENDING_VERIFICATION
        ),
    ) -> TenantChannelConfigurationRecord:
        now = _utcnow()
        config_id = derive_channel_configuration_id(
            tenant_id=tenant_id,
            channel_type=channel_type,
        )
        existing = await self._repository.get_channel_configuration(
            config_id,
            expected_tenant_id=tenant_id,
        )
        created_at = existing.created_at if existing is not None else now
        record = TenantChannelConfigurationRecord(
            config_id=config_id,
            tenant_id=tenant_id,
            channel_type=channel_type,
            status=status,
            routing_address=routing_address,
            credentials_enc=self._credential_encryptor.encrypt(
                tenant_id=tenant_id,
                credentials=credentials,
            ),
            webhook_secret=webhook_secret,
            verified_at=(
                existing.verified_at if existing is not None else None
            ),
            created_at=created_at,
            updated_at=now,
        )
        await self._repository.save_channel_configuration(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def update_channel(
        self,
        *,
        tenant_id: str,
        config_id: TenantChannelConfigurationId,
        routing_address: str | None = None,
        credentials: Mapping[str, Any] | None = None,
        webhook_secret: str | None = None,
        status: TenantChannelStatus | None = None,
    ) -> TenantChannelConfigurationRecord:
        existing = await self._require_channel(
            tenant_id=tenant_id,
            config_id=config_id,
        )
        record = replace(
            existing,
            routing_address=(
                routing_address
                if routing_address is not None
                else existing.routing_address
            ),
            credentials_enc=(
                self._credential_encryptor.encrypt(
                    tenant_id=tenant_id,
                    credentials=credentials,
                )
                if credentials is not None
                else existing.credentials_enc
            ),
            webhook_secret=(
                webhook_secret
                if webhook_secret is not None
                else existing.webhook_secret
            ),
            status=status if status is not None else existing.status,
            updated_at=_utcnow(),
        )
        await self._repository.save_channel_configuration(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def verify_channel(
        self,
        *,
        tenant_id: str,
        config_id: TenantChannelConfigurationId,
    ) -> TenantChannelConfigurationRecord:
        existing = await self._require_channel(
            tenant_id=tenant_id,
            config_id=config_id,
        )
        now = _utcnow()
        record = replace(
            existing,
            status=TenantChannelStatus.ACTIVE,
            verified_at=now,
            updated_at=now,
        )
        await self._repository.save_channel_configuration(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def list_channels(
        self,
        *,
        tenant_id: str,
        query: TenantChannelConfigurationQuery,
    ) -> TenantChannelConfigurationPage:
        return await self._repository.list_channel_configurations(
            query,
            expected_tenant_id=tenant_id,
        )

    async def resolve_active_channel_for_routing_address(
        self,
        *,
        channel_type: TenantChannelType,
        routing_address: str,
    ) -> TenantChannelConfigurationRecord | None:
        record = await self._repository.resolve_channel_configuration(
            channel_type=channel_type.value,
            routing_address=routing_address,
        )
        if record is None or record.status is not TenantChannelStatus.ACTIVE:
            return None
        return record

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        config_id = derive_channel_configuration_id(
            tenant_id=tenant_id,
            channel_type=channel_type,
        )
        record = await self._require_channel(
            tenant_id=tenant_id,
            config_id=config_id,
        )
        return self._credential_encryptor.decrypt(
            tenant_id=tenant_id,
            encrypted_credentials=record.credentials_enc,
        )

    async def create_knowledge_document(
        self,
        *,
        tenant_id: str,
        title: str,
        content: str,
        document_type: TenantKnowledgeDocumentType,
        uploaded_by: str,
        status: TenantKnowledgeDocumentStatus = (
            TenantKnowledgeDocumentStatus.PENDING_INDEX
        ),
    ) -> TenantKnowledgeDocumentRecord:
        document_id = derive_knowledge_document_id(
            tenant_id=tenant_id,
            title=title,
            document_type=document_type,
        )
        existing = await self._repository.get_knowledge_document(
            document_id,
            expected_tenant_id=tenant_id,
        )
        now = _utcnow()
        record = TenantKnowledgeDocumentRecord(
            document_id=document_id,
            tenant_id=tenant_id,
            title=title,
            content=content,
            document_type=document_type,
            status=status,
            version=1 if existing is None else existing.version + 1,
            uploaded_by=uploaded_by,
            vector_indexed_at=(
                existing.vector_indexed_at
                if existing is not None
                else None
            ),
            created_at=existing.created_at if existing is not None else now,
        )
        await self._repository.save_knowledge_document(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def update_knowledge_document(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
        uploaded_by: str,
        content: str | None = None,
        status: TenantKnowledgeDocumentStatus | None = None,
    ) -> TenantKnowledgeDocumentRecord:
        existing = await self._require_document(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        record = replace(
            existing,
            content=content if content is not None else existing.content,
            status=status if status is not None else existing.status,
            version=existing.version + 1,
            uploaded_by=uploaded_by,
        )
        await self._repository.save_knowledge_document(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def list_knowledge_documents(
        self,
        *,
        tenant_id: str,
        query: TenantKnowledgeDocumentQuery,
    ) -> TenantKnowledgeDocumentPage:
        return await self._repository.list_knowledge_documents(
            query,
            expected_tenant_id=tenant_id,
        )

    async def create_governance_policy(
        self,
        *,
        tenant_id: str,
        policy_type: str,
        parameters: Mapping[str, Any],
        approved_by: str,
        effective_from: datetime,
        status: TenantGovernancePolicyStatus = (
            TenantGovernancePolicyStatus.DRAFT
        ),
    ) -> TenantGovernancePolicyRecord:
        policy_id = derive_governance_policy_id(
            tenant_id=tenant_id,
            policy_type=policy_type,
        )
        existing = await self._repository.get_governance_policy(
            policy_id,
            expected_tenant_id=tenant_id,
        )
        now = _utcnow()
        record = TenantGovernancePolicyRecord(
            policy_id=policy_id,
            tenant_id=tenant_id,
            policy_type=policy_type,
            parameters=dict(parameters),
            status=status,
            version=1 if existing is None else existing.version + 1,
            approved_by=approved_by,
            effective_from=effective_from,
            created_at=existing.created_at if existing is not None else now,
        )
        await self._repository.save_governance_policy(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def update_governance_policy(
        self,
        *,
        tenant_id: str,
        policy_id: TenantGovernancePolicyId,
        approved_by: str,
        parameters: Mapping[str, Any] | None = None,
        status: TenantGovernancePolicyStatus | None = None,
        effective_from: datetime | None = None,
    ) -> TenantGovernancePolicyRecord:
        existing = await self._require_policy(
            tenant_id=tenant_id,
            policy_id=policy_id,
        )
        record = replace(
            existing,
            parameters=(
                dict(parameters)
                if parameters is not None
                else existing.parameters
            ),
            status=status if status is not None else existing.status,
            version=existing.version + 1,
            approved_by=approved_by,
            effective_from=(
                effective_from
                if effective_from is not None
                else existing.effective_from
            ),
        )
        await self._repository.save_governance_policy(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def list_governance_policies(
        self,
        *,
        tenant_id: str,
        query: TenantGovernancePolicyQuery,
    ) -> TenantGovernancePolicyPage:
        return await self._repository.list_governance_policies(
            query,
            expected_tenant_id=tenant_id,
        )

    async def _require_channel(
        self,
        *,
        tenant_id: str,
        config_id: TenantChannelConfigurationId,
    ) -> TenantChannelConfigurationRecord:
        record = await self._repository.get_channel_configuration(
            config_id,
            expected_tenant_id=tenant_id,
        )
        if record is None:
            raise TenantConfigurationNotFoundError(
                "channel configuration not found"
            )
        return record

    async def _require_document(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
    ) -> TenantKnowledgeDocumentRecord:
        record = await self._repository.get_knowledge_document(
            document_id,
            expected_tenant_id=tenant_id,
        )
        if record is None:
            raise TenantConfigurationNotFoundError(
                "knowledge document not found"
            )
        return record

    async def _require_policy(
        self,
        *,
        tenant_id: str,
        policy_id: TenantGovernancePolicyId,
    ) -> TenantGovernancePolicyRecord:
        record = await self._repository.get_governance_policy(
            policy_id,
            expected_tenant_id=tenant_id,
        )
        if record is None:
            raise TenantConfigurationNotFoundError(
                "governance policy not found"
            )
        return record


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["TenantConfigurationRuntime"]
