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
from app.tenant.credentials import TenantCredentialCodec
from app.tenant.chronology import ChronologyVerificationResult, canonical_sha256
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
    TenantKnowledgeUploadId,
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
    TenantConnectorConfigurationPage,
    TenantConnectorConfigurationQuery,
    TenantConnectorConfigurationRecord,
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
    TenantKnowledgeUploadRecord,
    TenantTopologyConfigurationPage,
    TenantTopologyConfigurationQuery,
    TenantTopologyConfigurationRecord,
    TenantWebhookRoutingSecretRecord,
)

if TYPE_CHECKING:
    from app.sop_intelligence import ApprovalRecord

_ACTION_TOOLS_POLICY_TYPE = "action_tools"


class TenantConfigurationRuntime:
    """Runtime authority for tenant-owned configuration records."""

    def __init__(
        self,
        *,
        repository: TenantConfigurationRepository,
        credential_encryptor: TenantCredentialCodec | None = None,
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
        status: TenantChannelStatus = (TenantChannelStatus.PENDING_VALIDATION),
        self_service_config: Mapping[str, Any] | None = None,
        last_validation_error: str | None = None,
        validation_evidence: Mapping[str, Any] | None = None,
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
                channel_type=channel_type,
                credentials=credentials,
            ),
            webhook_secret=webhook_secret,
            self_service_config=(
                dict(self_service_config)
                if self_service_config is not None
                else (
                    dict(existing.self_service_config)
                    if existing is not None
                    else {}
                )
            ),
            last_validation_error=(
                last_validation_error
                if last_validation_error is not None
                else (
                    existing.last_validation_error
                    if existing is not None
                    else None
                )
            ),
            validation_evidence=(
                _credential_free_validation_evidence(validation_evidence)
                if validation_evidence is not None
                else (
                    dict(existing.validation_evidence)
                    if existing is not None
                    else {}
                )
            ),
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
        self_service_config: Mapping[str, Any] | None = None,
        last_validation_error: str | None = None,
        validation_evidence: Mapping[str, Any] | None = None,
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
                    channel_type=existing.channel_type,
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
            self_service_config=(
                dict(self_service_config)
                if self_service_config is not None
                else existing.self_service_config
            ),
            last_validation_error=(
                last_validation_error
                if last_validation_error is not None
                else existing.last_validation_error
            ),
            validation_evidence=(
                _credential_free_validation_evidence(validation_evidence)
                if validation_evidence is not None
                else existing.validation_evidence
            ),
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
                channel_type=existing.channel_type,
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
        validation_evidence: Mapping[str, Any] | None = None,
        validation_error: str | None = None,
    ) -> TenantChannelConfigurationRecord:
        existing = await self._require_channel(
            tenant_id=tenant_id,
            config_id=config_id,
        )
        now = _utcnow()
        evidence = _credential_free_validation_evidence(validation_evidence)
        validated = _validation_evidence_is_success(evidence)
        status = (
            TenantChannelStatus.ACTIVE
            if validated
            else TenantChannelStatus.PENDING_VALIDATION
        )
        error = None if validated else (
            validation_error or "provider validation evidence is required"
        )
        record = replace(
            existing,
            status=status,
            verified_at=now if validated else existing.verified_at,
            last_validation_error=error,
            validation_evidence=evidence,
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

    async def get_channel_configuration(
        self,
        *,
        tenant_id: str,
        config_id: TenantChannelConfigurationId,
    ) -> TenantChannelConfigurationRecord | None:
        return await self._repository.get_channel_configuration(
            config_id,
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
        channel_type: TenantChannelType,
        routing_address: str,
    ) -> str | None:
        # PRIVILEGED_PATH: this resolver is called before tenant
        # authentication to discover tenant scope for incoming webhooks.
        # The SQL function is SECURITY DEFINER. It must only be called
        # for webhook routing. No other call site is permitted.
        return await self._repository.resolve_tenant_by_routing_address(
            channel_type=channel_type.value,
            routing_address=routing_address
        )

    async def resolve_webhook_routing_secret(
        self,
        *,
        channel_type: TenantChannelType,
        routing_address: str,
    ) -> TenantWebhookRoutingSecretRecord | None:
        # PRIVILEGED_PATH: this single pre-auth query returns only
        # routing scope and webhook secrets required for immediate HMAC
        # validation. Full tenant configuration is loaded after the
        # signature passes and tenant context is set.
        return await self._repository.resolve_webhook_routing_secret(
            channel_type=channel_type.value,
            routing_address=routing_address,
        )

    async def resolve_webhook_routing_secret_by_topic_arn(
        self,
        *,
        channel_type: TenantChannelType,
        topic_arn: str,
    ) -> TenantWebhookRoutingSecretRecord | None:
        # PRIVILEGED_PATH: SES/SNS subscription confirmations have a
        # TopicArn but no recipient address. This returns only routing scope
        # and non-decrypted webhook topic metadata for immediate SNS
        # signature validation.
        return await self._repository.resolve_webhook_routing_secret_by_topic_arn(
            channel_type=channel_type.value,
            topic_arn=topic_arn,
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
            channel_type=channel_type,
            encrypted_credentials=record.credentials_enc,
        )

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
        success_status_codes: Sequence[int],
        status: str,
        configured_by: str,
        approval: ApprovalRecord | None = None,
    ) -> TenantConnectorConfigurationRecord:
        approval_record = _require_approval(approval, tenant_id=tenant_id)
        normalized_connector_type = _normalize_text(
            connector_type,
            "connector_type",
        )
        normalized_tool_name = _normalize_text(tool_name, "tool_name")
        page = await self._repository.list_connector_configurations(
            TenantConnectorConfigurationQuery(
                connector_type=normalized_connector_type,
                tool_name=normalized_tool_name,
            ),
            expected_tenant_id=tenant_id,
        )
        existing = (
            max(page.items, key=lambda item: item.version)
            if page.items
            else None
        )
        version = 1 if existing is None else existing.version + 1
        now = _utcnow()
        created_at = existing.created_at if existing is not None else now
        normalized_status = _connector_status(status)
        normalized_codes = _connector_success_status_codes(success_status_codes)
        normalized_field_mappings = _json_object(field_mappings, "field_mappings")
        normalized_response_parse = _json_object(response_parse, "response_parse")
        normalized_http_method = _normalize_text(http_method, "http_method").upper()
        normalized_endpoint_template = _normalize_text(
            endpoint_template,
            "endpoint_template",
        )
        normalized_endpoint_host = _normalize_text(
            endpoint_host,
            "endpoint_host",
        ).lower()
        normalized_idempotency_header_name = _normalize_text(
            idempotency_header_name,
            "idempotency_header_name",
        )
        normalized_configured_by = _normalize_text(configured_by, "configured_by")
        if normalized_status == "active":
            action_policy = await self.resolve_active_governance_policy(
                tenant_id=tenant_id,
                policy_type=_ACTION_TOOLS_POLICY_TYPE,
            )
            if action_policy is None:
                raise TenantConfigurationError(
                    "active connector requires an active action_tools policy"
                )
        content_sha256 = _connector_configuration_content_sha256(
            tenant_id=tenant_id,
            connector_type=normalized_connector_type,
            tool_name=normalized_tool_name,
            http_method=normalized_http_method,
            endpoint_template=normalized_endpoint_template,
            endpoint_host=normalized_endpoint_host,
            field_mappings=normalized_field_mappings,
            idempotency_header_name=normalized_idempotency_header_name,
            response_parse=normalized_response_parse,
            success_status_codes=normalized_codes,
            status=normalized_status,
            version=version,
            configured_by=normalized_configured_by,
            source_approval_id=approval_record.approval_id,
        )
        record = TenantConnectorConfigurationRecord(
            tenant_id=tenant_id,
            connector_type=normalized_connector_type,
            tool_name=normalized_tool_name,
            http_method=normalized_http_method,
            endpoint_template=normalized_endpoint_template,
            endpoint_host=normalized_endpoint_host,
            field_mappings=normalized_field_mappings,
            idempotency_header_name=normalized_idempotency_header_name,
            response_parse=normalized_response_parse,
            success_status_codes=normalized_codes,
            status=normalized_status,
            version=version,
            configured_by=normalized_configured_by,
            source_approval_id=approval_record.approval_id,
            content_sha256=content_sha256,
            previous_version_sha256=(
                existing.content_sha256 if existing is not None else None
            ),
            created_at=created_at,
            updated_at=now,
        )
        await self._repository.save_connector_configuration(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def get_connector_configuration(
        self,
        *,
        tenant_id: str,
        connector_type: str,
        tool_name: str,
        version: int,
    ) -> TenantConnectorConfigurationRecord | None:
        return await self._repository.get_connector_configuration(
            connector_type=connector_type,
            tool_name=tool_name,
            version=version,
            expected_tenant_id=tenant_id,
        )

    async def list_connector_configurations(
        self,
        *,
        tenant_id: str,
        query: TenantConnectorConfigurationQuery,
    ) -> TenantConnectorConfigurationPage:
        return await self._repository.list_connector_configurations(
            query,
            expected_tenant_id=tenant_id,
        )

    async def resolve_active_connector_configuration(
        self,
        *,
        tenant_id: str,
        tool_name: str,
    ) -> TenantConnectorConfigurationRecord | None:
        return await self._repository.resolve_active_connector_configuration(
            tool_name=tool_name,
            expected_tenant_id=tenant_id,
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
        template_purpose: str | None = None,
        template_channel: str | None = None,
    ) -> TenantKnowledgeDocumentRecord:
        approval_record = _require_approval(approval, tenant_id=tenant_id)
        template_purpose, template_channel = _validated_template_fields(
            document_type=document_type,
            template_purpose=template_purpose,
            template_channel=template_channel,
        )
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
            review_status=TenantKnowledgeReviewStatus.QUARANTINED,
            version=1 if existing is None else existing.version + 1,
            uploaded_by=uploaded_by,
            vector_indexed_at=(
                existing.vector_indexed_at if existing is not None else None
            ),
            created_at=existing.created_at if existing is not None else now,
            template_purpose=template_purpose,
            template_channel=template_channel,
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
        review_status: TenantKnowledgeReviewStatus | None = None,
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
            review_status=(
                TenantKnowledgeReviewStatus.QUARANTINED
                if content is not None
                else review_status
                if review_status is not None
                else existing.review_status
            ),
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

    async def get_approved_template(
        self,
        *,
        tenant_id: str,
        purpose: str,
        channel: str,
    ) -> TenantKnowledgeDocumentRecord | None:
        """Exact-match (tenant, purpose, channel) template lookup.

        Returns ``None`` on no match — a missing or not-yet-approved
        template is never silently substituted with a default; the
        caller (a future probe-dispatch workflow) must handle absence
        explicitly. Only ``review_status=APPROVED`` rows are
        returned — a QUARANTINED or REJECTED template is invisible
        here, mirroring SOP/POLICY document retrieval.
        """
        page = await self._repository.list_knowledge_documents(
            TenantKnowledgeDocumentQuery(
                document_type=TenantKnowledgeDocumentType.TEMPLATE,
                review_status=TenantKnowledgeReviewStatus.APPROVED,
                template_purpose=purpose,
                template_channel=channel,
                limit=1,
            ),
            expected_tenant_id=tenant_id,
        )
        return page.items[0] if page.items else None

    async def save_knowledge_upload(
        self,
        record: TenantKnowledgeUploadRecord,
        *,
        tenant_id: str,
    ) -> None:
        await self._repository.save_knowledge_upload(
            record,
            expected_tenant_id=tenant_id,
        )

    async def get_knowledge_upload(
        self,
        upload_id: TenantKnowledgeUploadId,
        *,
        tenant_id: str,
    ) -> TenantKnowledgeUploadRecord | None:
        return await self._repository.get_knowledge_upload(
            upload_id,
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
        version_metadata = {
            **dict(metadata),
            "review_status": record.review_status.value,
        }
        content_sha256 = _knowledge_document_content_sha256(
            record=record,
            source_approval_id=source_approval_id,
            metadata=version_metadata,
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
                metadata=version_metadata,
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

    async def resolve_active_governance_policy(
        self,
        *,
        tenant_id: str,
        policy_type: str,
    ) -> TenantGovernancePolicyRecord | None:
        return await self._repository.resolve_active_governance_policy(
            policy_type=policy_type,
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

    def _require_credential_encryptor(self) -> TenantCredentialCodec:
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


def _validated_template_fields(
    *,
    document_type: TenantKnowledgeDocumentType,
    template_purpose: str | None,
    template_channel: str | None,
) -> tuple[str | None, str | None]:
    """Fail closed on the TEMPLATE <-> (purpose, channel) invariant the DB
    CHECK constraint (migration 0090) also enforces — raising here gives a
    clear application-level error instead of an IntegrityError surfacing
    from a failed INSERT."""
    if document_type is TenantKnowledgeDocumentType.TEMPLATE:
        purpose = (template_purpose or "").strip()
        channel = (template_channel or "").strip()
        if not purpose or not channel:
            raise TenantConfigurationError(
                "template_purpose and template_channel are required when "
                "document_type is TEMPLATE"
            )
        return purpose, channel
    if template_purpose is not None or template_channel is not None:
        raise TenantConfigurationError(
            "template_purpose/template_channel are only valid when "
            "document_type is TEMPLATE"
        )
    return None, None


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


def _connector_configuration_content_sha256(
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
    success_status_codes: Sequence[int],
    status: str,
    version: int,
    configured_by: str,
    source_approval_id: str,
) -> str:
    return canonical_sha256(
        {
            "tenant_id": tenant_id,
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
            "version": version,
            "configured_by": configured_by,
            "source_approval_id": source_approval_id,
        }
    )


def _connector_status(value: str) -> str:
    status = _normalize_text(value, "status")
    if status not in {"active", "disabled"}:
        raise TenantConfigurationError("connector status must be active or disabled")
    return status


def _connector_success_status_codes(values: Sequence[object]) -> tuple[int, ...]:
    codes: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TenantConfigurationError(
                "connector success_status_codes must contain integers"
            )
        if value < 100 or value > 599:
            raise TenantConfigurationError(
                "connector success_status_codes must be HTTP status codes"
            )
        codes.append(value)
    if not codes:
        raise TenantConfigurationError(
            "connector success_status_codes must be non-empty"
        )
    return tuple(codes)


def _json_object(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TenantConfigurationError(f"{field_name} must be an object")
    mapping = cast(Mapping[Any, Any], value)
    return {str(key): item for key, item in mapping.items()}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_VALIDATION_EVIDENCE_SENSITIVE_KEYS = frozenset(
    {
        "access_key_id",
        "access_token",
        "api_key",
        "app_secret",
        "aws_access_key_id",
        "aws_secret_access_key",
        "bearer_token",
        "business_token",
        "client_secret",
        "credential",
        "credentials",
        "credentials_enc",
        "graph_api_access_token",
        "secret",
        "secret_access_key",
        "session_token",
        "token",
        "webhook_secret",
        "webhook_verify_token",
    }
)


def _credential_free_validation_evidence(
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if evidence is None:
        return {}
    return cast(dict[str, Any], _strip_validation_evidence(evidence))


def _strip_validation_evidence(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        mapping = cast(Mapping[Any, Any], value)
        for raw_key, raw_item in mapping.items():
            key = str(raw_key)
            if key.lower() in _VALIDATION_EVIDENCE_SENSITIVE_KEYS:
                continue
            sanitized[key] = _strip_validation_evidence(raw_item)
        return sanitized
    if isinstance(value, list):
        items = cast(list[Any], value)
        return [_strip_validation_evidence(item) for item in items]
    return value


def _validation_evidence_is_success(evidence: Mapping[str, Any]) -> bool:
    result = str(evidence.get("result") or evidence.get("status") or "").casefold()
    return result in {"ok", "success", "validated", "active"} and bool(
        evidence.get("provider") or evidence.get("validator")
    )


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
