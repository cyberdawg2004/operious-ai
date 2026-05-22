"""Tenant configuration service boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantTopologyStatus,
)
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
)
from app.tenant.persistence import (
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
    TenantChannelConfigurationRecord,
    TenantGovernancePolicyPage,
    TenantGovernancePolicyQuery,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentPage,
    TenantKnowledgeDocumentQuery,
    TenantKnowledgeDocumentRecord,
    TenantTopologyConfigurationPage,
    TenantTopologyConfigurationQuery,
    TenantTopologyConfigurationRecord,
)
from app.tenant.runtime import TenantConfigurationRuntime


class TenantConfigurationService:
    """Application service for tenant-owned configuration writes/reads."""

    def __init__(
        self,
        *,
        runtime: TenantConfigurationRuntime,
        session: AsyncSession,
    ) -> None:
        self._runtime = runtime
        self._session = session

    async def configure_channel(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
        routing_address: str,
        credentials: Mapping[str, Any],
        webhook_secret: str,
        status: TenantChannelStatus,
    ) -> TenantChannelConfigurationRecord:
        record = await self._runtime.configure_channel(
            tenant_id=tenant_id,
            channel_type=channel_type,
            routing_address=routing_address,
            credentials=credentials,
            webhook_secret=webhook_secret,
            status=status,
        )
        await self._session.commit()
        return record

    async def update_channel(
        self,
        *,
        tenant_id: str,
        config_id: TenantChannelConfigurationId,
        routing_address: str | None,
        credentials: Mapping[str, Any] | None,
        webhook_secret: str | None,
        status: TenantChannelStatus | None,
    ) -> TenantChannelConfigurationRecord:
        record = await self._runtime.update_channel(
            tenant_id=tenant_id,
            config_id=config_id,
            routing_address=routing_address,
            credentials=credentials,
            webhook_secret=webhook_secret,
            status=status,
        )
        await self._session.commit()
        return record

    async def verify_channel(
        self,
        *,
        tenant_id: str,
        config_id: TenantChannelConfigurationId,
    ) -> TenantChannelConfigurationRecord:
        record = await self._runtime.verify_channel(
            tenant_id=tenant_id,
            config_id=config_id,
        )
        await self._session.commit()
        return record

    async def list_channels(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType | None,
        status: TenantChannelStatus | None,
        limit: int | None,
        offset: int,
    ) -> TenantChannelConfigurationPage:
        return await self._runtime.list_channels(
            tenant_id=tenant_id,
            query=TenantChannelConfigurationQuery(
                channel_type=channel_type,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    async def create_knowledge_document(
        self,
        *,
        tenant_id: str,
        title: str,
        content: str,
        document_type: TenantKnowledgeDocumentType,
        status: TenantKnowledgeDocumentStatus,
        uploaded_by: str,
    ) -> TenantKnowledgeDocumentRecord:
        record = await self._runtime.create_knowledge_document(
            tenant_id=tenant_id,
            title=title,
            content=content,
            document_type=document_type,
            status=status,
            uploaded_by=uploaded_by,
        )
        await self._session.commit()
        return record

    async def update_knowledge_document(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
        content: str | None,
        status: TenantKnowledgeDocumentStatus | None,
        uploaded_by: str,
    ) -> TenantKnowledgeDocumentRecord:
        record = await self._runtime.update_knowledge_document(
            tenant_id=tenant_id,
            document_id=document_id,
            content=content,
            status=status,
            uploaded_by=uploaded_by,
        )
        await self._session.commit()
        return record

    async def list_knowledge_documents(
        self,
        *,
        tenant_id: str,
        document_type: TenantKnowledgeDocumentType | None,
        status: TenantKnowledgeDocumentStatus | None,
        limit: int | None,
        offset: int,
    ) -> TenantKnowledgeDocumentPage:
        return await self._runtime.list_knowledge_documents(
            tenant_id=tenant_id,
            query=TenantKnowledgeDocumentQuery(
                document_type=document_type,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    async def create_governance_policy(
        self,
        *,
        tenant_id: str,
        policy_type: str,
        parameters: Mapping[str, Any],
        status: TenantGovernancePolicyStatus,
        approved_by: str,
        effective_from: datetime,
    ) -> TenantGovernancePolicyRecord:
        record = await self._runtime.create_governance_policy(
            tenant_id=tenant_id,
            policy_type=policy_type,
            parameters=parameters,
            status=status,
            approved_by=approved_by,
            effective_from=effective_from,
        )
        await self._session.commit()
        return record

    async def update_governance_policy(
        self,
        *,
        tenant_id: str,
        policy_id: TenantGovernancePolicyId,
        parameters: Mapping[str, Any] | None,
        status: TenantGovernancePolicyStatus | None,
        approved_by: str,
        effective_from: datetime | None,
    ) -> TenantGovernancePolicyRecord:
        record = await self._runtime.update_governance_policy(
            tenant_id=tenant_id,
            policy_id=policy_id,
            parameters=parameters,
            status=status,
            approved_by=approved_by,
            effective_from=effective_from,
        )
        await self._session.commit()
        return record

    async def list_governance_policies(
        self,
        *,
        tenant_id: str,
        policy_type: str | None,
        status: TenantGovernancePolicyStatus | None,
        limit: int | None,
        offset: int,
    ) -> TenantGovernancePolicyPage:
        return await self._runtime.list_governance_policies(
            tenant_id=tenant_id,
            query=TenantGovernancePolicyQuery(
                policy_type=policy_type,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    async def configure_topology(
        self,
        *,
        tenant_id: str,
        topology_name: str,
        topology: Mapping[str, Any],
        status: TenantTopologyStatus,
        configured_by: str,
    ) -> TenantTopologyConfigurationRecord:
        record = await self._runtime.configure_topology_from_mapping(
            tenant_id=tenant_id,
            topology_name=topology_name,
            topology=topology,
            status=status,
            configured_by=configured_by,
        )
        await self._session.commit()
        return record

    async def list_topology_configurations(
        self,
        *,
        tenant_id: str,
        topology_name: str | None,
        status: TenantTopologyStatus | None,
        limit: int | None,
        offset: int,
    ) -> TenantTopologyConfigurationPage:
        return await self._runtime.list_topology_configurations(
            tenant_id=tenant_id,
            query=TenantTopologyConfigurationQuery(
                topology_name=topology_name,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )


__all__ = ["TenantConfigurationService"]
