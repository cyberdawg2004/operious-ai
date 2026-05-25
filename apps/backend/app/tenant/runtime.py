"""Tenant configuration runtime boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
)
from app.coordination.topology.enums import (
    TopologyBoundaryCrossing,
    TopologyBoundaryKind,
    TopologyEdgeKind,
    TopologyNodeKind,
)
from app.coordination.topology.exceptions import (
    CoordinationTopologyConfigurationError,
)
from app.coordination.topology.identity import (
    TopologyNodeId,
    as_edge_id,
    as_node_id,
    as_topology_id,
)
from app.coordination.topology.models.boundary import AuthorityBoundary
from app.coordination.topology.models.edge import CoordinationEdge
from app.coordination.topology.models.escalation_path import EscalationPath
from app.coordination.topology.models.node import CoordinationNode
from app.coordination.topology.models.path import CoordinationPath
from app.coordination.topology.models.topology import CoordinationTopology
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.chronology import ChronologyVerificationResult, canonical_sha256
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
from app.tenant.exceptions import (
    ApprovalRequiredError,
    TenantConfigurationError,
    TenantConfigurationNotFoundError,
    TenantTopologyCycleError,
)
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantExecutionCircuitBreakerId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
    TenantTopologyConfigurationId,
    derive_channel_configuration_id,
    derive_execution_circuit_breaker_id,
    derive_execution_governance_configuration_id,
    derive_governance_policy_version_id,
    derive_knowledge_document_id,
    derive_knowledge_document_version_id,
    derive_topology_configuration_id,
)
from app.tenant.persistence import (
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
    TenantChannelConfigurationRecord,
    TenantExecutionCircuitBreakerPage,
    TenantExecutionCircuitBreakerQuery,
    TenantExecutionCircuitBreakerRecord,
    TenantExecutionGovernanceConfigurationPage,
    TenantExecutionGovernanceConfigurationRecord,
    TenantExecutionGovernanceConfigurationQuery,
    TenantConfigurationRepository,
    TenantGovernancePolicyPage,
    TenantGovernancePolicyQuery,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentPage,
    TenantKnowledgeDocumentQuery,
    TenantKnowledgeDocumentRecord,
    TenantKnowledgeDocumentVersionRecord,
    TenantKnowledgeDocumentVersionQuery,
    TenantTopologyConfigurationPage,
    TenantTopologyConfigurationQuery,
    TenantTopologyConfigurationRecord,
)

if TYPE_CHECKING:
    from app.sop_intelligence import ApprovalRecord


class TenantConfigurationRuntime:
    """Runtime authority for tenant-owned configuration records."""

    def __init__(
        self,
        *,
        repository: TenantConfigurationRepository,
        credential_encryptor: TenantCredentialEncryptor | None = None,
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
        status: TenantChannelStatus = (TenantChannelStatus.PENDING_VERIFICATION),
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
            credentials_enc=self._require_credential_encryptor().encrypt(
                tenant_id=tenant_id,
                credentials=credentials,
            ),
            webhook_secret=webhook_secret,
            verified_at=(existing.verified_at if existing is not None else None),
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
                self._require_credential_encryptor().encrypt(
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

    async def rotate_channel_credentials(
        self,
        *,
        tenant_id: str,
        config_id: TenantChannelConfigurationId,
        credentials: Mapping[str, Any],
        webhook_secret: str,
        grace_period_minutes: int,
    ) -> TenantChannelConfigurationRecord:
        if grace_period_minutes < 1:
            raise TenantConfigurationError(
                "credential rotation grace period must be positive"
            )
        existing = await self._require_channel(
            tenant_id=tenant_id,
            config_id=config_id,
        )
        now = _utcnow()
        record = replace(
            existing,
            credentials_enc=self._require_credential_encryptor().encrypt(
                tenant_id=tenant_id,
                credentials=credentials,
            ),
            webhook_secret=webhook_secret,
            previous_credentials_enc=existing.credentials_enc,
            previous_webhook_secret=existing.webhook_secret,
            credential_rotated_at=now,
            credential_rotation_expires_at=now
            + timedelta(minutes=grace_period_minutes),
            updated_at=now,
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
        expected_tenant_id: str | None = None,
    ) -> TenantChannelConfigurationRecord | None:
        record = await self._repository.resolve_channel_configuration(
            channel_type=channel_type.value,
            routing_address=routing_address,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None or record.status is not TenantChannelStatus.ACTIVE:
            return None
        return record

    async def resolve_tenant_by_routing_address(
        self,
        *,
        routing_address: str,
    ) -> str | None:
        return await self._repository.resolve_tenant_by_routing_address(
            routing_address=routing_address
        )

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
        return self._require_credential_encryptor().decrypt(
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
        approval: ApprovalRecord | None = None,
    ) -> TenantKnowledgeDocumentRecord:
        approval_record = _require_approval(approval, tenant_id=tenant_id)
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
                existing.vector_indexed_at if existing is not None else None
            ),
            created_at=existing.created_at if existing is not None else now,
        )
        await self._repository.save_knowledge_document(
            record,
            expected_tenant_id=tenant_id,
        )
        previous = (
            None
            if existing is None
            else await self._repository.get_knowledge_document_version(
                existing.document_id,
                existing.version,
                expected_tenant_id=tenant_id,
            )
        )
        await self._record_knowledge_document_version(
            record,
            source_approval_id=approval_record.approval_id,
            previous_version_sha256=(
                previous.content_sha256 if previous is not None else None
            ),
            metadata={"origin": "tenant_configuration"},
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
        approval: ApprovalRecord | None = None,
    ) -> TenantKnowledgeDocumentRecord:
        approval_record = _require_approval(approval, tenant_id=tenant_id)
        existing = await self._require_document(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        previous = await self._repository.get_knowledge_document_version(
            existing.document_id,
            existing.version,
            expected_tenant_id=tenant_id,
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
        await self._record_knowledge_document_version(
            record,
            source_approval_id=approval_record.approval_id,
            previous_version_sha256=(
                previous.content_sha256 if previous is not None else None
            ),
            metadata={"origin": "tenant_configuration"},
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

    async def verify_chronology_chain(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
    ) -> ChronologyVerificationResult:
        versions = await self._repository.list_knowledge_document_versions(
            TenantKnowledgeDocumentVersionQuery(document_id=document_id),
            expected_tenant_id=tenant_id,
        )
        previous_sha256: str | None = None
        for version in sorted(versions.items, key=lambda item: item.version):
            expected = _knowledge_version_content_sha256(version)
            if (
                version.content_sha256 != expected
                or version.previous_version_sha256 != previous_sha256
            ):
                return ChronologyVerificationResult(
                    valid=False,
                    broken_at_version=version.version,
                )
            previous_sha256 = version.content_sha256
        return ChronologyVerificationResult(valid=True)

    async def _record_knowledge_document_version(
        self,
        record: TenantKnowledgeDocumentRecord,
        *,
        source_approval_id: str | None,
        previous_version_sha256: str | None,
        metadata: Mapping[str, Any],
    ) -> None:
        if source_approval_id is None:
            raise ApprovalRequiredError("knowledge document version requires approval")
        content_sha256 = _knowledge_document_content_sha256(
            record=record,
            source_approval_id=source_approval_id,
            metadata=metadata,
        )
        await self._repository.save_knowledge_document_version(
            TenantKnowledgeDocumentVersionRecord(
                version_id=derive_knowledge_document_version_id(
                    tenant_id=record.tenant_id,
                    document_id=record.document_id,
                    version=record.version,
                ),
                tenant_id=record.tenant_id,
                document_id=record.document_id,
                version=record.version,
                title=record.title,
                content=record.content,
                document_type=record.document_type,
                status=record.status,
                uploaded_by=record.uploaded_by,
                source_approval_id=source_approval_id,
                content_sha256=content_sha256,
                previous_version_sha256=previous_version_sha256,
                created_at=_utcnow(),
                metadata=dict(metadata),
            ),
            expected_tenant_id=record.tenant_id,
        )

    async def create_governance_policy(
        self,
        *,
        tenant_id: str,
        policy_type: str,
        parameters: Mapping[str, Any],
        approved_by: str,
        effective_from: datetime,
        status: TenantGovernancePolicyStatus = (TenantGovernancePolicyStatus.DRAFT),
        approval: ApprovalRecord | None = None,
    ) -> TenantGovernancePolicyRecord:
        approval_record = _require_approval(approval, tenant_id=tenant_id)
        existing_page = await self._repository.list_governance_policies(
            TenantGovernancePolicyQuery(policy_type=policy_type),
            expected_tenant_id=tenant_id,
        )
        existing = (
            max(existing_page.items, key=lambda item: item.version)
            if existing_page.items
            else None
        )
        version = 1 if existing is None else existing.version + 1
        policy_id = derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=policy_type,
            version=version,
        )
        now = _utcnow()
        previous_sha256 = existing.content_sha256 if existing is not None else None
        content_sha256 = _governance_policy_content_sha256(
            tenant_id=tenant_id,
            policy_type=policy_type,
            parameters=parameters,
            status=status,
            version=version,
            approved_by=approved_by,
            effective_from=effective_from,
            source_approval_id=approval_record.approval_id,
        )
        record = TenantGovernancePolicyRecord(
            policy_id=policy_id,
            tenant_id=tenant_id,
            policy_type=policy_type,
            parameters=dict(parameters),
            status=status,
            version=version,
            approved_by=approved_by,
            effective_from=effective_from,
            created_at=existing.created_at if existing is not None else now,
            source_approval_id=approval_record.approval_id,
            content_sha256=content_sha256,
            previous_version_sha256=previous_sha256,
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
        approval: ApprovalRecord | None = None,
    ) -> TenantGovernancePolicyRecord:
        approval_record = _require_approval(approval, tenant_id=tenant_id)
        existing = await self._require_policy(
            tenant_id=tenant_id,
            policy_id=policy_id,
        )
        next_parameters = (
            dict(parameters) if parameters is not None else dict(existing.parameters)
        )
        next_status = status if status is not None else existing.status
        next_effective_from = (
            effective_from if effective_from is not None else existing.effective_from
        )
        next_version = existing.version + 1
        next_policy_id = derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=existing.policy_type,
            version=next_version,
        )
        content_sha256 = _governance_policy_content_sha256(
            tenant_id=tenant_id,
            policy_type=existing.policy_type,
            parameters=next_parameters,
            status=next_status,
            version=next_version,
            approved_by=approved_by,
            effective_from=next_effective_from,
            source_approval_id=approval_record.approval_id,
        )
        record = replace(
            existing,
            policy_id=next_policy_id,
            parameters=next_parameters,
            status=next_status,
            version=next_version,
            approved_by=approved_by,
            effective_from=next_effective_from,
            source_approval_id=approval_record.approval_id,
            content_sha256=content_sha256,
            previous_version_sha256=existing.content_sha256,
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
        configured_by: str,
        status: TenantExecutionGovernanceStatus = TenantExecutionGovernanceStatus.DRAFT,
        approval: ApprovalRecord | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TenantExecutionGovernanceConfigurationRecord:
        approval_record = _require_approval(approval, tenant_id=tenant_id)
        page = await self._repository.list_execution_governance_configurations(
            TenantExecutionGovernanceConfigurationQuery(),
            expected_tenant_id=tenant_id,
        )
        existing = (
            max(page.items, key=lambda item: item.version)
            if page.items
            else None
        )
        version = 1 if existing is None else existing.version + 1
        config_id = derive_execution_governance_configuration_id(
            tenant_id=tenant_id,
            version=version,
        )
        now = _utcnow()
        record_metadata = dict(metadata or {})
        content_sha256 = _execution_governance_content_sha256(
            tenant_id=tenant_id,
            status=status,
            execution_quota=execution_quota,
            throughput_limit=throughput_limit,
            throughput_window_minutes=throughput_window_minutes,
            governance_budget_limit=governance_budget_limit,
            governance_budget_window_minutes=governance_budget_window_minutes,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_window_minutes=circuit_window_minutes,
            circuit_cooldown_minutes=circuit_cooldown_minutes,
            version=version,
            configured_by=configured_by,
            source_approval_id=approval_record.approval_id,
            metadata=record_metadata,
        )
        record = TenantExecutionGovernanceConfigurationRecord(
            config_id=config_id,
            tenant_id=tenant_id,
            status=status,
            execution_quota=execution_quota,
            throughput_limit=throughput_limit,
            throughput_window_minutes=throughput_window_minutes,
            governance_budget_limit=governance_budget_limit,
            governance_budget_window_minutes=governance_budget_window_minutes,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_window_minutes=circuit_window_minutes,
            circuit_cooldown_minutes=circuit_cooldown_minutes,
            version=version,
            configured_by=configured_by,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            metadata=record_metadata,
            source_approval_id=approval_record.approval_id,
            content_sha256=content_sha256,
            previous_version_sha256=(
                existing.content_sha256 if existing is not None else None
            ),
        )
        await self._repository.save_execution_governance_configuration(
            record,
            expected_tenant_id=tenant_id,
        )
        breaker = TenantExecutionCircuitBreakerRecord(
            breaker_id=derive_execution_circuit_breaker_id(
                tenant_id=tenant_id,
                config_id=config_id,
            ),
            tenant_id=tenant_id,
            config_id=config_id,
            state=TenantExecutionCircuitState.CLOSED,
            failure_count=0,
            opened_at=None,
            open_until=None,
            last_transition_at=now,
            reason=None,
            updated_at=now,
            metadata={"origin": "execution_governance_configuration"},
        )
        await self._repository.save_execution_circuit_breaker(
            breaker,
            expected_tenant_id=tenant_id,
        )
        return record

    async def get_execution_circuit_breaker(
        self,
        *,
        tenant_id: str,
        breaker_id: TenantExecutionCircuitBreakerId,
    ) -> TenantExecutionCircuitBreakerRecord | None:
        return await self._repository.get_execution_circuit_breaker(
            breaker_id,
            expected_tenant_id=tenant_id,
        )

    async def list_execution_governance_configurations(
        self,
        *,
        tenant_id: str,
        query: TenantExecutionGovernanceConfigurationQuery,
    ) -> TenantExecutionGovernanceConfigurationPage:
        return await self._repository.list_execution_governance_configurations(
            query,
            expected_tenant_id=tenant_id,
        )

    async def list_execution_circuit_breakers(
        self,
        *,
        tenant_id: str,
        query: TenantExecutionCircuitBreakerQuery,
    ) -> TenantExecutionCircuitBreakerPage:
        return await self._repository.list_execution_circuit_breakers(
            query,
            expected_tenant_id=tenant_id,
        )

    async def resolve_active_execution_governance_configuration(
        self,
        *,
        tenant_id: str,
    ) -> TenantExecutionGovernanceConfigurationRecord | None:
        return await self._repository.resolve_active_execution_governance_configuration(
            expected_tenant_id=tenant_id,
        )

    async def configure_topology(
        self,
        *,
        tenant_id: str,
        topology: CoordinationTopology,
        configured_by: str,
        topology_name: str | None = None,
        status: TenantTopologyStatus = TenantTopologyStatus.DRAFT,
    ) -> TenantTopologyConfigurationRecord:
        name = _normalize_text(topology_name or topology.name, "topology_name")
        _assert_topology_is_dag(topology)
        config_id = derive_topology_configuration_id(
            tenant_id=tenant_id,
            topology_name=name,
        )
        existing = await self._repository.get_topology_configuration(
            config_id,
            expected_tenant_id=tenant_id,
        )
        now = _utcnow()
        record = TenantTopologyConfigurationRecord(
            config_id=config_id,
            tenant_id=tenant_id,
            topology_name=name,
            status=status,
            topology=topology.to_dict(),
            version=1 if existing is None else existing.version + 1,
            configured_by=_normalize_text(configured_by, "configured_by"),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        await self._repository.save_topology_configuration(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def configure_topology_from_mapping(
        self,
        *,
        tenant_id: str,
        topology_name: str,
        topology: Mapping[str, Any],
        configured_by: str,
        status: TenantTopologyStatus = TenantTopologyStatus.DRAFT,
    ) -> TenantTopologyConfigurationRecord:
        return await self.configure_topology(
            tenant_id=tenant_id,
            topology=_coordination_topology_from_mapping(topology),
            configured_by=configured_by,
            topology_name=topology_name,
            status=status,
        )

    async def list_topology_configurations(
        self,
        *,
        tenant_id: str,
        query: TenantTopologyConfigurationQuery,
    ) -> TenantTopologyConfigurationPage:
        return await self._repository.list_topology_configurations(
            query,
            expected_tenant_id=tenant_id,
        )

    async def load_active_coordination_topology(
        self,
        *,
        tenant_id: str,
    ) -> CoordinationTopology | None:
        record = await self._repository.resolve_active_topology_configuration(
            expected_tenant_id=tenant_id,
        )
        if record is None:
            return None
        return _coordination_topology_from_mapping(record.topology)

    async def _require_topology(
        self,
        *,
        tenant_id: str,
        config_id: TenantTopologyConfigurationId,
    ) -> TenantTopologyConfigurationRecord:
        record = await self._repository.get_topology_configuration(
            config_id,
            expected_tenant_id=tenant_id,
        )
        if record is None:
            raise TenantConfigurationNotFoundError("topology configuration not found")
        return record

    def _require_credential_encryptor(self) -> TenantCredentialEncryptor:
        if self._credential_encryptor is None:
            raise TenantConfigurationError(
                "tenant credential encryptor is required for channel credentials"
            )
        return self._credential_encryptor

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
            raise TenantConfigurationNotFoundError("channel configuration not found")
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
            raise TenantConfigurationNotFoundError("knowledge document not found")
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
            raise TenantConfigurationNotFoundError("governance policy not found")
        return record


def _require_approval(
    approval: ApprovalRecord | None,
    *,
    tenant_id: str,
) -> ApprovalRecord:
    if approval is None:
        raise ApprovalRequiredError("tenant chronology mutation requires approval")
    if approval.tenant_id != tenant_id:
        raise ApprovalRequiredError("approval tenant does not match mutation tenant")
    if approval.status != "approved":
        raise ApprovalRequiredError("approval must be approved before mutation")
    return approval


def _knowledge_document_content_sha256(
    *,
    record: TenantKnowledgeDocumentRecord,
    source_approval_id: str,
    metadata: Mapping[str, Any],
) -> str:
    return canonical_sha256(
        {
            "tenant_id": record.tenant_id,
            "document_id": str(record.document_id),
            "version": record.version,
            "title": record.title,
            "content": record.content,
            "document_type": record.document_type.value,
            "status": record.status.value,
            "uploaded_by": record.uploaded_by,
            "source_approval_id": source_approval_id,
            "metadata": dict(metadata),
        }
    )


def _knowledge_version_content_sha256(
    record: TenantKnowledgeDocumentVersionRecord,
) -> str:
    return canonical_sha256(
        {
            "tenant_id": record.tenant_id,
            "document_id": str(record.document_id),
            "version": record.version,
            "title": record.title,
            "content": record.content,
            "document_type": record.document_type.value,
            "status": record.status.value,
            "uploaded_by": record.uploaded_by,
            "source_approval_id": record.source_approval_id,
            "metadata": dict(record.metadata),
        }
    )


def _governance_policy_content_sha256(
    *,
    tenant_id: str,
    policy_type: str,
    parameters: Mapping[str, Any],
    status: TenantGovernancePolicyStatus,
    version: int,
    approved_by: str,
    effective_from: datetime,
    source_approval_id: str,
) -> str:
    return canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": policy_type,
            "parameters": dict(parameters),
            "status": status.value,
            "version": version,
            "approved_by": approved_by,
            "effective_from": effective_from.isoformat(),
            "source_approval_id": source_approval_id,
        }
    )


def _execution_governance_content_sha256(
    *,
    tenant_id: str,
    status: TenantExecutionGovernanceStatus,
    execution_quota: int,
    throughput_limit: int,
    throughput_window_minutes: int,
    governance_budget_limit: int,
    governance_budget_window_minutes: int,
    circuit_failure_threshold: int,
    circuit_window_minutes: int,
    circuit_cooldown_minutes: int,
    version: int,
    configured_by: str,
    source_approval_id: str,
    metadata: Mapping[str, Any],
) -> str:
    return canonical_sha256(
        {
            "tenant_id": tenant_id,
            "status": status.value,
            "execution_quota": execution_quota,
            "throughput_limit": throughput_limit,
            "throughput_window_minutes": throughput_window_minutes,
            "governance_budget_limit": governance_budget_limit,
            "governance_budget_window_minutes": governance_budget_window_minutes,
            "circuit_failure_threshold": circuit_failure_threshold,
            "circuit_window_minutes": circuit_window_minutes,
            "circuit_cooldown_minutes": circuit_cooldown_minutes,
            "version": version,
            "configured_by": configured_by,
            "source_approval_id": source_approval_id,
            "metadata": dict(metadata),
        }
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _assert_topology_is_dag(topology: CoordinationTopology) -> None:
    graph: dict[TopologyNodeId, list[TopologyNodeId]] = {
        node.node_id: [] for node in topology.nodes
    }
    for edge in topology.edges:
        graph[edge.source_node_id].append(edge.target_node_id)

    visiting: set[TopologyNodeId] = set()
    visited: set[TopologyNodeId] = set()

    def visit(node_id: TopologyNodeId) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise TenantTopologyCycleError("tenant topology contains a directed cycle")
        visiting.add(node_id)
        for next_node_id in graph.get(node_id, []):
            visit(next_node_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in graph:
        visit(node_id)


def _coordination_topology_from_mapping(
    raw: Mapping[str, Any],
) -> CoordinationTopology:
    try:
        data = _as_mapping(raw, "topology")
        nodes = tuple(
            _node_from_mapping(_as_mapping(item, "nodes[]"))
            for item in _as_sequence(data.get("nodes"), "nodes")
        )
        edges = tuple(
            _edge_from_mapping(_as_mapping(item, "edges[]"))
            for item in _as_sequence(data.get("edges", ()), "edges")
        )
        paths = tuple(
            _path_from_mapping(_as_mapping(item, "paths[]"))
            for item in _as_sequence(data.get("paths", ()), "paths")
        )
        escalation_paths = tuple(
            _escalation_path_from_mapping(_as_mapping(item, "escalation_paths[]"))
            for item in _as_sequence(
                data.get("escalation_paths", ()), "escalation_paths"
            )
        )
        boundaries = tuple(
            _boundary_from_mapping(_as_mapping(item, "boundaries[]"))
            for item in _as_sequence(data.get("boundaries", ()), "boundaries")
        )
        return CoordinationTopology(
            topology_id=as_topology_id(_required_text(data, "topology_id")),
            name=_required_text(data, "name"),
            version=str(data.get("version", "v1")),
            max_chain_depth=int(data.get("max_chain_depth", 4)),
            description=str(data.get("description", "")),
            nodes=nodes,
            edges=edges,
            paths=paths,
            escalation_paths=escalation_paths,
            boundaries=boundaries,
            metadata=_metadata(data.get("metadata")),
        )
    except TenantConfigurationError:
        raise
    except (
        CoordinationTopologyConfigurationError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise TenantConfigurationError("invalid tenant topology declaration") from exc


def _node_from_mapping(raw: Mapping[str, Any]) -> CoordinationNode:
    return CoordinationNode(
        node_id=as_node_id(_required_text(raw, "node_id")),
        participant_id=_required_text(raw, "participant_id"),
        kind=TopologyNodeKind(_required_text(raw, "kind")),
        display_name=str(raw.get("display_name", "")),
        tenant_id=_optional_text(raw.get("tenant_id")),
        domain_id=_optional_text(raw.get("domain_id")),
        environment_id=_optional_text(raw.get("environment_id")),
        metadata=_metadata(raw.get("metadata")),
    )


def _edge_from_mapping(raw: Mapping[str, Any]) -> CoordinationEdge:
    direction_raw = raw.get("direction")
    direction = (
        None if direction_raw is None else CoordinationDirection(str(direction_raw))
    )
    return CoordinationEdge(
        edge_id=as_edge_id(_required_text(raw, "edge_id")),
        source_node_id=as_node_id(_required_text(raw, "source_node_id")),
        target_node_id=as_node_id(_required_text(raw, "target_node_id")),
        kind=TopologyEdgeKind(_required_text(raw, "kind")),
        direction=direction,
        allowed_message_types=tuple(
            CoordinationMessageType(str(item))
            for item in _as_sequence(
                raw.get("allowed_message_types", ()),
                "allowed_message_types",
            )
        ),
        crosses_boundary_id=_optional_text(raw.get("crosses_boundary_id")),
        description=str(raw.get("description", "")),
        priority=int(raw.get("priority", 100)),
        metadata=_metadata(raw.get("metadata")),
    )


def _path_from_mapping(raw: Mapping[str, Any]) -> CoordinationPath:
    return CoordinationPath(
        path_id=_required_text(raw, "path_id"),
        node_ids=tuple(
            as_node_id(str(item))
            for item in _as_sequence(raw.get("node_ids"), "node_ids")
        ),
        description=str(raw.get("description", "")),
        metadata=_metadata(raw.get("metadata")),
    )


def _escalation_path_from_mapping(
    raw: Mapping[str, Any],
) -> EscalationPath:
    return EscalationPath(
        path_id=_required_text(raw, "path_id"),
        node_ids=tuple(
            as_node_id(str(item))
            for item in _as_sequence(raw.get("node_ids"), "node_ids")
        ),
        seniority_ordering=tuple(
            str(item)
            for item in _as_sequence(
                raw.get("seniority_ordering", ()), "seniority_ordering"
            )
        ),
        description=str(raw.get("description", "")),
        metadata=_metadata(raw.get("metadata")),
    )


def _boundary_from_mapping(raw: Mapping[str, Any]) -> AuthorityBoundary:
    return AuthorityBoundary(
        boundary_id=_required_text(raw, "boundary_id"),
        kind=TopologyBoundaryKind(_required_text(raw, "kind")),
        display_name=str(raw.get("display_name", "")),
        member_node_ids=tuple(
            as_node_id(str(item))
            for item in _as_sequence(raw.get("member_node_ids", ()), "member_node_ids")
        ),
        crossing=TopologyBoundaryCrossing(
            str(raw.get("crossing", TopologyBoundaryCrossing.FORBIDDEN.value))
        ),
        allowed_crossing_pairs=tuple(
            _crossing_pair_from_sequence(item)
            for item in _as_sequence(
                raw.get("allowed_crossing_pairs", ()),
                "allowed_crossing_pairs",
            )
        ),
        metadata=_metadata(raw.get("metadata")),
    )


def _crossing_pair_from_sequence(
    raw: object,
) -> tuple[TopologyNodeId, TopologyNodeId]:
    pair = _as_sequence(raw, "allowed_crossing_pairs[]")
    if len(pair) != 2:
        raise TenantConfigurationError(
            "allowed crossing pairs must contain exactly two node ids"
        )
    return (as_node_id(str(pair[0])), as_node_id(str(pair[1])))


def _as_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TenantConfigurationError(f"{field_name} must be an object")
    return cast(Mapping[str, Any], value)


def _as_sequence(value: object, field_name: str) -> tuple[object, ...]:
    if value is None:
        raise TenantConfigurationError(f"{field_name} must be a list")
    if not isinstance(value, (list, tuple)):
        raise TenantConfigurationError(f"{field_name} must be a list")
    return tuple(cast(Sequence[object], value))


def _required_text(raw: Mapping[str, Any], field_name: str) -> str:
    if field_name not in raw:
        raise TenantConfigurationError(f"{field_name} is required")
    return _normalize_text(str(raw[field_name]), field_name)


def _normalize_text(raw: str, field_name: str) -> str:
    text = raw.strip()
    if not text:
        raise TenantConfigurationError(f"{field_name} must be non-empty")
    return text


def _optional_text(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _metadata(raw: object) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TenantConfigurationError("metadata must be an object")
    metadata = cast(Mapping[object, Any], raw)
    return {str(k): v for k, v in metadata.items()}


__all__ = ["TenantConfigurationRuntime"]
