"""Tenant configuration service boundary."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
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
    TenantKnowledgeReviewStatus,
    TenantTopologyStatus,
)
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
)
from app.tenant.exceptions import TenantConfigurationDirectApplyDisabledError
from app.tenant.persistence import (
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
    TenantChannelConfigurationRecord,
    TenantConnectorConfigurationPage,
    TenantConnectorConfigurationQuery,
    TenantConnectorConfigurationRecord,
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
_POLICY_INVALIDATION_CHANNEL_PREFIX = "governance:policy:invalidate"
_logger = get_logger(__name__)


class TenantConfigurationService:
    """Application service for tenant-owned configuration writes/reads."""

    def __init__(
        self,
        *,
        runtime: TenantConfigurationRuntime,
        session: AsyncSession,
        redis_client: Any,
    ) -> None:
        self._runtime = runtime
        self._session = session
        self._redis_client = redis_client

    async def configure_channel(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
        routing_address: str,
        credentials: Mapping[str, Any],
        webhook_secret: str,
        status: TenantChannelStatus,
        self_service_config: Mapping[str, Any] | None = None,
        last_validation_error: str | None = None,
        validation_evidence: Mapping[str, Any] | None = None,
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantChannelConfigurationRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        record = await self._runtime.configure_channel(
            tenant_id=tenant_id,
            channel_type=channel_type,
            routing_address=routing_address,
            credentials=credentials,
            webhook_secret=webhook_secret,
            status=status,
            self_service_config=self_service_config,
            last_validation_error=last_validation_error,
            validation_evidence=validation_evidence,
        )
        if commit:
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
        self_service_config: Mapping[str, Any] | None = None,
        last_validation_error: str | None = None,
        validation_evidence: Mapping[str, Any] | None = None,
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantChannelConfigurationRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        record = await self._runtime.update_channel(
            tenant_id=tenant_id,
            config_id=config_id,
            routing_address=routing_address,
            credentials=credentials,
            webhook_secret=webhook_secret,
            status=status,
            self_service_config=self_service_config,
            last_validation_error=last_validation_error,
            validation_evidence=validation_evidence,
        )
        if commit:
            await self._session.commit()
        return record

    async def _publish_governance_policy_invalidation(
        self,
        *,
        tenant_id: str,
    ) -> None:
        try:
            await self._redis_client.publish(
                f"{_POLICY_INVALIDATION_CHANNEL_PREFIX}:{tenant_id}",
                json.dumps(
                    {
                        "tenant_id": tenant_id,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "governance_policy_invalidation_publish_failed",
                extra={"tenant_id": tenant_id, "error": str(exc)},
            )

    async def publish_governance_policy_invalidation(
        self,
        *,
        tenant_id: str,
    ) -> None:
        await self._publish_governance_policy_invalidation(tenant_id=tenant_id)

    async def verify_channel(
        self,
        *,
        tenant_id: str,
        config_id: TenantChannelConfigurationId,
        validation_evidence: Mapping[str, Any] | None = None,
        validation_error: str | None = None,
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantChannelConfigurationRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        record = await self._runtime.verify_channel(
            tenant_id=tenant_id,
            config_id=config_id,
            validation_evidence=validation_evidence,
            validation_error=validation_error,
        )
        if commit:
            await self._session.commit()
        return record

    async def configure_connector(
        self,
        *,
        tenant_id: str,
        connector_type: str,
        tool_name: str,
        http_method: str,
        endpoint_template: str,
        endpoint_host: str,
        field_mappings: Mapping[str, Any],
        idempotency_header_name: str,
        response_parse: Mapping[str, Any],
        success_status_codes: tuple[int, ...],
        status: str,
        configured_by: str,
        approval: ApprovalRecord | None = None,
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantConnectorConfigurationRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        if approval is None:
            approval = _approved_configuration_change(
                tenant_id=tenant_id,
                target_id=f"connector:{tool_name}",
                change_kind="connector_config_configure",
                proposed_by=configured_by,
                material={
                    "connector_type": connector_type,
                    "tool_name": tool_name,
                    "http_method": http_method,
                    "endpoint_template": endpoint_template,
                    "endpoint_host": endpoint_host,
                    "field_mappings": dict(field_mappings),
                    "idempotency_header_name": idempotency_header_name,
                    "response_parse": dict(response_parse),
                    "success_status_codes": list(success_status_codes),
                    "status": status,
                },
            )
        record = await self._runtime.configure_connector(
            tenant_id=tenant_id,
            connector_type=connector_type,
            tool_name=tool_name,
            http_method=http_method,
            endpoint_template=endpoint_template,
            endpoint_host=endpoint_host,
            field_mappings=field_mappings,
            idempotency_header_name=idempotency_header_name,
            response_parse=response_parse,
            success_status_codes=success_status_codes,
            status=status,
            configured_by=configured_by,
            approval=approval,
        )
        if commit:
            await self._session.commit()
        return record

    async def list_connector_configurations(
        self,
        *,
        tenant_id: str,
        connector_type: str | None,
        tool_name: str | None,
        status: str | None,
        limit: int | None,
        offset: int,
    ) -> TenantConnectorConfigurationPage:
        return await self._runtime.list_connector_configurations(
            tenant_id=tenant_id,
            query=TenantConnectorConfigurationQuery(
                connector_type=connector_type,
                tool_name=tool_name,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

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

    async def get_channel_configuration(
        self,
        *,
        tenant_id: str,
        config_id: TenantChannelConfigurationId,
    ) -> TenantChannelConfigurationRecord | None:
        return await self._runtime.get_channel_configuration(
            tenant_id=tenant_id,
            config_id=config_id,
        )

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        return await self._runtime.load_channel_credentials(
            tenant_id=tenant_id,
            channel_type=channel_type,
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
        approval: ApprovalRecord | None = None,
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantKnowledgeDocumentRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        if approval is None:
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
        if commit:
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
        review_status: TenantKnowledgeReviewStatus | None = None,
        approval: ApprovalRecord | None = None,
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantKnowledgeDocumentRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        if approval is None:
            approval = _approved_configuration_change(
                tenant_id=tenant_id,
                target_id=str(document_id),
                change_kind="knowledge_document_update",
                proposed_by=uploaded_by,
                material={
                    "document_id": str(document_id),
                    "content": content,
                    "status": None if status is None else status.value,
                    "review_status": (
                        None if review_status is None else review_status.value
                    ),
                },
            )
        record = await self._runtime.update_knowledge_document(
            tenant_id=tenant_id,
            document_id=document_id,
            content=content,
            status=status,
            review_status=review_status,
            uploaded_by=uploaded_by,
            approval=approval,
        )
        if commit:
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
        approval: ApprovalRecord | None = None,
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantGovernancePolicyRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        if approval is None:
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
        if commit:
            await self._session.commit()
            await self._publish_governance_policy_invalidation(tenant_id=tenant_id)
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
        approval: ApprovalRecord | None = None,
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantGovernancePolicyRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        if approval is None:
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
        if commit:
            await self._session.commit()
            await self._publish_governance_policy_invalidation(tenant_id=tenant_id)
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
        approval: ApprovalRecord | None = None,
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantExecutionGovernanceConfigurationRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        if approval is None:
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
                    "governance_budget_window_minutes": (
                        governance_budget_window_minutes
                    ),
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
        if commit:
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
        bypass_direct_apply_gate: bool = False,
        commit: bool = True,
    ) -> TenantTopologyConfigurationRecord:
        _require_direct_apply_enabled(bypass=bypass_direct_apply_gate)
        record = await self._runtime.configure_topology_from_mapping(
            tenant_id=tenant_id,
            topology_name=topology_name,
            topology=topology,
            status=status,
            configured_by=configured_by,
        )
        if commit:
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
    reviewed_by: str | None = None,
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
        reviewed_by=reviewed_by or proposed_by,
        created_at=now,
        metadata={
            "approval_source": "tenant_configuration_service",
            "material_sha256": material_hash,
        },
    )


def _require_direct_apply_enabled(*, bypass: bool = False) -> None:
    if bypass:
        return
    if get_settings().tenant_config_self_approval_allowed:
        return
    raise TenantConfigurationDirectApplyDisabledError(
        "direct tenant configuration mutation is disabled; use change requests"
    )


__all__ = ["TenantConfigurationService"]
