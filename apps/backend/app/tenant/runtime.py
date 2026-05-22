"""Tenant configuration runtime boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, cast

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
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantTopologyStatus,
)
from app.tenant.exceptions import (
    TenantConfigurationError,
    TenantConfigurationNotFoundError,
    TenantTopologyCycleError,
)
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
    TenantTopologyConfigurationId,
    derive_channel_configuration_id,
    derive_governance_policy_id,
    derive_knowledge_document_id,
    derive_knowledge_document_version_id,
    derive_topology_configuration_id,
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
    TenantKnowledgeDocumentVersionRecord,
    TenantTopologyConfigurationPage,
    TenantTopologyConfigurationQuery,
    TenantTopologyConfigurationRecord,
)


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
                existing.vector_indexed_at if existing is not None else None
            ),
            created_at=existing.created_at if existing is not None else now,
        )
        await self._repository.save_knowledge_document(
            record,
            expected_tenant_id=tenant_id,
        )
        if existing is not None:
            await self._record_knowledge_document_version(
                replace(existing, status=TenantKnowledgeDocumentStatus.ARCHIVED),
                source_approval_id=None,
                metadata={"archived_by_document_version": record.version},
            )
        await self._record_knowledge_document_version(
            record,
            source_approval_id=None,
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
        await self._record_knowledge_document_version(
            replace(existing, status=TenantKnowledgeDocumentStatus.ARCHIVED),
            source_approval_id=None,
            metadata={"archived_by_document_version": record.version},
        )
        await self._record_knowledge_document_version(
            record,
            source_approval_id=None,
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

    async def _record_knowledge_document_version(
        self,
        record: TenantKnowledgeDocumentRecord,
        *,
        source_approval_id: str | None,
        metadata: Mapping[str, Any],
    ) -> None:
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
                dict(parameters) if parameters is not None else existing.parameters
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
