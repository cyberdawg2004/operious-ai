"""Tenant configuration service boundary."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.sop_intelligence import ApprovalRecord, ApprovalStatus
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantExecutionCircuitState,
    TenantExecutionGovernanceStatus,
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
    TenantExecutionCircuitBreakerPage,
    TenantExecutionCircuitBreakerQuery,
    TenantExecutionGovernanceConfigurationPage,
    TenantExecutionGovernanceConfigurationQuery,
    TenantExecutionGovernanceConfigurationRecord,
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

_SERVICE_APPROVAL_NAMESPACE = uuid.UUID("f4ff1200-0940-5537-9752-c7693db8b5f6")


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
        approval = _approved_configuration_change(
            tenant_id=tenant_id,
            target_id=f"knowledge:{document_type.value}:{title}",
            change_kind="knowledge_document_create",
            proposed_by=uploaded_by,
            material={
                "title": title,
                "content": content,
                "document_type": document_type.value,
                "status": status.value,
            },
        )
        record = await self._runtime.create_knowledge_document(
            tenant_id=tenant_id,
            title=title,
            content=content,
            document_type=document_type,
            status=status,
            uploaded_by=uploaded_by,
            approval=approval,
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
        approval = _approved_configuration_change(
            tenant_id=tenant_id,
            target_id=str(document_id),
            change_kind="knowledge_document_update",
            proposed_by=uploaded_by,
            material={
                "document_id": str(document_id),
                "content": content,
                "status": None if status is None else status.value,
            },
        )
        record = await self._runtime.update_knowledge_document(
            tenant_id=tenant_id,
            document_id=document_id,
            content=content,
            status=status,
            uploaded_by=uploaded_by,
            approval=approval,
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
        approval = _approved_configuration_change(
            tenant_id=tenant_id,
            target_id=f"governance_policy:{policy_type}",
            change_kind="governance_policy_create",
            proposed_by=approved_by,
            material={
                "policy_type": policy_type,
                "parameters": dict(parameters),
                "status": status.value,
                "effective_from": effective_from.isoformat(),
            },
        )
        record = await self._runtime.create_governance_policy(
            tenant_id=tenant_id,
            policy_type=policy_type,
            parameters=parameters,
            status=status,
            approved_by=approved_by,
            effective_from=effective_from,
            approval=approval,
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
        approval = _approved_configuration_change(
            tenant_id=tenant_id,
            target_id=str(policy_id),
            change_kind="governance_policy_update",
            proposed_by=approved_by,
            material={
                "policy_id": str(policy_id),
                "parameters": None if parameters is None else dict(parameters),
                "status": None if status is None else status.value,
                "effective_from": (
                    None if effective_from is None else effective_from.isoformat()
                ),
            },
        )
        record = await self._runtime.update_governance_policy(
            tenant_id=tenant_id,
            policy_id=policy_id,
            parameters=parameters,
            status=status,
            approved_by=approved_by,
            effective_from=effective_from,
            approval=approval,
        )
        await self._session.commit()
        return record

    async def configure_execution_governance(
        self,
        *,
        tenant_id: str,
        execution_quota: int,
        throughput_limit: int,
        throughput_window_minutes: int,
        governance_budget_limit: int,
        governance_budget_window_minutes: int,
        circuit_failure_threshold: int,
        circuit_window_minutes: int,
        circuit_cooldown_minutes: int,
        status: TenantExecutionGovernanceStatus,
        configured_by: str,
        metadata: Mapping[str, Any],
    ) -> TenantExecutionGovernanceConfigurationRecord:
        approval = _approved_configuration_change(
            tenant_id=tenant_id,
            target_id="execution_governance",
            change_kind="execution_governance_configure",
            proposed_by=configured_by,
            material={
                "execution_quota": execution_quota,
                "throughput_limit": throughput_limit,
                "throughput_window_minutes": throughput_window_minutes,
                "governance_budget_limit": governance_budget_limit,
                "governance_budget_window_minutes": governance_budget_window_minutes,
                "circuit_failure_threshold": circuit_failure_threshold,
                "circuit_window_minutes": circuit_window_minutes,
                "circuit_cooldown_minutes": circuit_cooldown_minutes,
                "status": status.value,
                "metadata": dict(metadata),
            },
        )
        record = await self._runtime.configure_execution_governance(
            tenant_id=tenant_id,
            execution_quota=execution_quota,
            throughput_limit=throughput_limit,
            throughput_window_minutes=throughput_window_minutes,
            governance_budget_limit=governance_budget_limit,
            governance_budget_window_minutes=governance_budget_window_minutes,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_window_minutes=circuit_window_minutes,
            circuit_cooldown_minutes=circuit_cooldown_minutes,
            configured_by=configured_by,
            status=status,
            approval=approval,
            metadata=metadata,
        )
        await self._session.commit()
        return record

    async def list_execution_governance_configurations(
        self,
        *,
        tenant_id: str,
        status: TenantExecutionGovernanceStatus | None,
        limit: int | None,
        offset: int,
    ) -> TenantExecutionGovernanceConfigurationPage:
        return await self._runtime.list_execution_governance_configurations(
            tenant_id=tenant_id,
            query=TenantExecutionGovernanceConfigurationQuery(
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    async def list_execution_circuit_breakers(
        self,
        *,
        tenant_id: str,
        state: TenantExecutionCircuitState | None,
        limit: int | None,
        offset: int,
    ) -> TenantExecutionCircuitBreakerPage:
        return await self._runtime.list_execution_circuit_breakers(
            tenant_id=tenant_id,
            query=TenantExecutionCircuitBreakerQuery(
                state=state,
                limit=limit,
                offset=offset,
            ),
        )

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


def _approved_configuration_change(
    *,
    tenant_id: str,
    target_id: str,
    change_kind: str,
    proposed_by: str,
    material: Mapping[str, Any],
) -> ApprovalRecord:
    material_hash = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "target_id": target_id,
            "change_kind": change_kind,
            "material": material,
        }
    )
    approval_id = str(
        uuid.uuid5(
            _SERVICE_APPROVAL_NAMESPACE,
            f"{tenant_id}|{target_id}|{change_kind}|{material_hash}",
        )
    )
    now = datetime.now(timezone.utc).isoformat()
    return ApprovalRecord(
        approval_id=approval_id,
        tenant_id=tenant_id,
        document_id=target_id,
        proposed_change=change_kind,
        evidence_sessions=(),
        confidence=1.0,
        status=ApprovalStatus.APPROVED.value,
        proposed_by=proposed_by,
        reviewed_by=proposed_by,
        created_at=now,
        metadata={
            "approval_source": "tenant_configuration_service",
            "material_sha256": material_hash,
        },
    )


__all__ = ["TenantConfigurationService"]
