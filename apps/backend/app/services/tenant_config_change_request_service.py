"""Tenant config dual-control change-request service."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from ipaddress import ip_address
from enum import StrEnum
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    ActionPolicyParseError,
    validate_action_tools_policy_parameters,
)
from app.runtime.resolution_autonomy_policy import (
    RESOLUTION_AUTONOMY_POLICY_TYPE,
    ResolutionAutonomyPolicyParseError,
    validate_resolution_autonomy_policy_parameters,
)
from app.runtime.resolution_taxonomy_policy import (
    RESOLUTION_TAXONOMY_POLICY_TYPE,
    UNCLASSIFIED_CATEGORY_ID,
    ResolutionTaxonomyPolicyParseError,
    parse_resolution_taxonomy_policy,
    validate_resolution_taxonomy_policy_parameters,
)
from app.runtime.warranty_refund_policy import (
    WARRANTY_REFUND_RULES_POLICY_TYPE,
    WarrantyRefundPolicyParseError,
    parse_warranty_refund_policy,
    validate_warranty_refund_policy_parameters,
)
from app.events import EventCausality, EventChronology, EventId, OperationalEvent
from app.events.appender import OperationalEventAppender
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.sop_intelligence import ApprovalRecord, ApprovalStatus
from app.tenant.change_requests import (
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeRequestNotFoundError,
    TenantConfigChangeRequestPage,
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestRepository,
    TenantConfigChangeRequestSeparationError,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
    TenantConfigChangeRequestValidationError,
    derive_tenant_config_change_request_id,
)
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantExecutionGovernanceStatus,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
    TenantTopologyStatus,
)
from app.tenant.credentials import validate_channel_credentials
from app.tenant.template_placeholders import (
    TemplatePlaceholderError,
    validate_template_placeholders,
)
from app.tenant.identity import (
    as_channel_configuration_id,
    as_governance_policy_id,
    as_knowledge_document_id,
    derive_channel_configuration_id,
)
from app.services.tenant_configuration_service import TenantConfigurationService
from app.agents.tools.connectors.credentials import (
    ConnectorCredentialCodec,
    ConnectorCredentialRecord,
    ConnectorCredentialRepository,
    encrypt_connector_credentials,
)

_LEDGER_APPROVAL_NAMESPACE = uuid.UUID("b61074c6-a757-51f4-ae19-947742f31705")
_CHANGE_EVENT_NAMESPACE = uuid.UUID("01f77264-1518-5a56-9327-0472414e7dc0")
_SCHEMA_VERSION = "1"


def _validated_mcp_tools(
    raw_tools: object,
    *,
    missing_reason: str,
    empty_reason: str,
) -> list[dict[str, Any]]:
    if not isinstance(raw_tools, list):
        raise TenantConfigChangeRequestLifecycleError(missing_reason)
    typed_raw_tools = cast(list[object], raw_tools)
    if not typed_raw_tools:
        raise TenantConfigChangeRequestLifecycleError(
            empty_reason
        )
    typed_mcp_tools: list[dict[str, Any]] = []
    for i, tool in enumerate(typed_raw_tools):
        if not isinstance(tool, dict):
            raise TenantConfigChangeRequestLifecycleError(
                f"mcp_tools[{i}] must be an object"
            )
        typed_mcp_tools.append(cast(dict[str, Any], tool))
    return typed_mcp_tools


class _KnowledgeReindexPublisherProtocol(Protocol):
    def publish_reindex(self, *, document_id: str, tenant_id: str) -> None: ...


class TenantConfigChangeRequestService:
    """Application service for durable propose/approve/apply config changes."""

    def __init__(
        self,
        *,
        repository: TenantConfigChangeRequestRepository,
        tenant_configuration_service: TenantConfigurationService,
        event_appender: OperationalEventAppender,
        session: AsyncSession,
        knowledge_reindex_publisher: _KnowledgeReindexPublisherProtocol | None = None,
        connector_credential_repository: ConnectorCredentialRepository | None = None,
        connector_credential_codec: ConnectorCredentialCodec | None = None,
    ) -> None:
        self._repository = repository
        self._tenant_configuration = tenant_configuration_service
        self._events = event_appender
        self._session = session
        self._knowledge_reindex_publisher = knowledge_reindex_publisher
        self._connector_credential_repository = connector_credential_repository
        self._connector_credential_codec = connector_credential_codec

    async def propose(
        self,
        *,
        tenant_id: str,
        change_type: TenantConfigChangeType | str,
        payload: Mapping[str, Any],
        proposed_by: str,
    ) -> TenantConfigChangeRequestRecord:
        change = _change_type(change_type)
        proposed_payload = _versioned_payload(payload)
        await _validate_payload(
            change,
            proposed_payload,
            tenant_configuration=self._tenant_configuration,
            tenant_id=tenant_id,
        )
        now = _utcnow()
        record = TenantConfigChangeRequestRecord(
            change_request_id=derive_tenant_config_change_request_id(
                tenant_id=tenant_id,
                change_type=change,
                proposed_payload=proposed_payload,
                proposed_by=proposed_by,
            ),
            tenant_id=tenant_id,
            change_type=change,
            proposed_payload=proposed_payload,
            status=TenantConfigChangeRequestStatus.PROPOSED,
            proposed_by=proposed_by,
            proposed_at=now,
        )
        persisted = await self._repository.create(
            record,
            expected_tenant_id=tenant_id,
        )
        await self._append_status_event(persisted)
        await self._session.commit()
        return persisted

    async def approve(
        self,
        *,
        change_request_id: uuid.UUID | str,
        approved_by: str,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        record = await self._require(
            change_request_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record.status is not TenantConfigChangeRequestStatus.PROPOSED:
            raise TenantConfigChangeRequestLifecycleError(
                "only PROPOSED tenant config change requests can be approved"
            )
        if approved_by == record.proposed_by:
            raise TenantConfigChangeRequestSeparationError(
                "tenant config approver must differ from proposer"
            )
        approved = replace(
            record,
            status=TenantConfigChangeRequestStatus.APPROVED,
            approved_by=approved_by,
            approved_at=_utcnow(),
        )
        persisted = await self._repository.update(
            approved,
            expected_tenant_id=expected_tenant_id,
        )
        await self._append_status_event(persisted)
        await self._session.commit()
        return persisted

    async def reject(
        self,
        *,
        change_request_id: uuid.UUID | str,
        rejected_by: str,
        reason: str,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        record = await self._require(
            change_request_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record.status is not TenantConfigChangeRequestStatus.PROPOSED:
            raise TenantConfigChangeRequestLifecycleError(
                "only PROPOSED tenant config change requests can be rejected"
            )
        rejected = replace(
            record,
            status=TenantConfigChangeRequestStatus.REJECTED,
            rejected_by=rejected_by,
            rejected_at=_utcnow(),
            rejection_reason=reason,
        )
        persisted = await self._repository.update(
            rejected,
            expected_tenant_id=expected_tenant_id,
        )
        await self._append_status_event(persisted)
        await self._session.commit()
        return persisted

    async def apply(
        self,
        *,
        change_request_id: uuid.UUID | str,
        expected_tenant_id: str,
        applied_by: str,
    ) -> TenantConfigChangeRequestRecord:
        if not applied_by or not applied_by.strip():
            raise TenantConfigChangeRequestLifecycleError(
                "applied_by must identify the principal who applied the change"
            )
        record = await self._require(
            change_request_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record.status is not TenantConfigChangeRequestStatus.APPROVED:
            raise TenantConfigChangeRequestLifecycleError(
                f"cannot apply a {record.status.value} change request; "
                "only APPROVED requests can be applied"
            )
        if record.approved_by is None:
            raise TenantConfigChangeRequestLifecycleError(
                "approved tenant config change request is missing approved_by"
            )
        outcome = await self._apply_config_mutation(record)
        applied = replace(
            record,
            status=TenantConfigChangeRequestStatus.APPLIED,
            applied_at=_utcnow(),
            applied_by=applied_by,
            outcome_payload=outcome,
        )
        persisted = await self._repository.update(
            applied,
            expected_tenant_id=expected_tenant_id,
        )
        await self._append_status_event(persisted)
        await self._session.commit()
        if record.change_type is TenantConfigChangeType.POLICY:
            await self._tenant_configuration.publish_governance_policy_invalidation(
                tenant_id=expected_tenant_id
            )
        elif (
            record.change_type is TenantConfigChangeType.KNOWLEDGE
            and outcome.get("operation") == "create"
            and self._knowledge_reindex_publisher is not None
        ):
            try:
                self._knowledge_reindex_publisher.publish_reindex(
                    document_id=str(outcome["document_id"]),
                    tenant_id=expected_tenant_id,
                )
            except Exception as exc:  # noqa: BLE001 - reindex enqueue is best-effort
                from app.core.logging import get_logger as _get_logger
                _get_logger(__name__).warning(
                    "knowledge_reindex_enqueue_failed",
                    extra={
                        "document_id": outcome.get("document_id"),
                        "tenant_id": expected_tenant_id,
                        "error": str(exc),
                    },
                )
        return persisted

    async def revoke(
        self,
        *,
        change_request_id: uuid.UUID | str,
        expected_tenant_id: str,
        revoked_by: str,
    ) -> TenantConfigChangeRequestRecord:
        """Revoke an APPROVED change request before it is applied.

        Only APPROVED requests can be revoked; APPLIED, REJECTED, and
        already-REVOKED requests raise
        :class:`TenantConfigChangeRequestLifecycleError`. Any principal
        holding the ``tenant.config.approve`` capability may revoke — there
        is no additional same-principal restriction (revocation undoes a grant,
        it is not a new approval).
        """
        if not revoked_by or not revoked_by.strip():
            raise TenantConfigChangeRequestLifecycleError(
                "revoked_by must identify the principal who revoked the change"
            )
        record = await self._require(
            change_request_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record.status is not TenantConfigChangeRequestStatus.APPROVED:
            raise TenantConfigChangeRequestLifecycleError(
                f"cannot revoke a {record.status.value} change request; "
                "only APPROVED requests can be revoked"
            )
        revoked = replace(
            record,
            status=TenantConfigChangeRequestStatus.REVOKED,
            revoked_by=revoked_by,
            revoked_at=_utcnow(),
        )
        persisted = await self._repository.update(
            revoked,
            expected_tenant_id=expected_tenant_id,
        )
        await self._append_status_event(persisted)
        await self._session.commit()
        return persisted

    async def get(
        self,
        *,
        change_request_id: uuid.UUID | str,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        return await self._require(change_request_id, expected_tenant_id=expected_tenant_id)

    async def list(
        self,
        *,
        expected_tenant_id: str,
        status: TenantConfigChangeRequestStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TenantConfigChangeRequestPage:
        return await self._repository.list(
            expected_tenant_id=expected_tenant_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def _require(
        self,
        change_request_id: uuid.UUID | str,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        request_id = (
            change_request_id
            if isinstance(change_request_id, uuid.UUID)
            else uuid.UUID(str(change_request_id))
        )
        record = await self._repository.get(
            request_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise TenantConfigChangeRequestNotFoundError(
                "tenant config change request not found"
            )
        return record

    async def _apply_config_mutation(
        self,
        record: TenantConfigChangeRequestRecord,
    ) -> dict[str, Any]:
        approval = _approval_for_record(record)
        payload = dict(record.proposed_payload)
        change = record.change_type
        await _validate_payload(
            change,
            payload,
            tenant_configuration=self._tenant_configuration,
            tenant_id=record.tenant_id,
        )
        if change is TenantConfigChangeType.KNOWLEDGE:
            return await self._apply_knowledge(record, payload, approval)
        if change is TenantConfigChangeType.POLICY:
            return await self._apply_policy(record, payload, approval)
        if change is TenantConfigChangeType.EXECUTION_GOVERNANCE:
            return await self._apply_execution_governance(record, payload, approval)
        if change is TenantConfigChangeType.TOPOLOGY:
            return await self._apply_topology(record, payload)
        if change is TenantConfigChangeType.CHANNEL:
            return await self._apply_channel(record, payload)
        if change is TenantConfigChangeType.CONNECTOR:
            return await self._apply_connector(record, payload, approval)
        if change is TenantConfigChangeType.CREDENTIAL_UPDATE:
            return await self._apply_credential_update(record, payload)
        if change is TenantConfigChangeType.CONNECTOR_CREDENTIAL:
            return await self._apply_connector_credential(record, payload, approval)
        if change is TenantConfigChangeType.MCP_SERVER:
            return await self._apply_mcp_server(record, payload, approval)
        if change is TenantConfigChangeType.MCP_OAUTH_TOKEN:
            return await self._apply_mcp_oauth_token(record, payload, approval)
        raise TenantConfigChangeRequestLifecycleError(
            f"unsupported tenant config change type: {change.value}"
        )

    async def _apply_knowledge(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
        approval: ApprovalRecord,
    ) -> dict[str, Any]:
        operation = _operation(payload, default="create")
        if operation == "create":
            result = await self._tenant_configuration.create_knowledge_document(
                tenant_id=record.tenant_id,
                title=_str(payload, "title"),
                content=_str(payload, "content"),
                document_type=TenantKnowledgeDocumentType(
                    _str(payload, "document_type")
                ),
                status=TenantKnowledgeDocumentStatus(
                    str(
                        payload.get("status")
                        or TenantKnowledgeDocumentStatus.PENDING_INDEX.value
                    )
                ),
                # Applying the governance flow (propose → approve → apply) is
                # the two-person sign-off for the document; auto-approve here.
                uploaded_by=record.approved_by or record.proposed_by,
                approval=approval,
                bypass_direct_apply_gate=True,
                commit=False,
                template_purpose=_optional_str(payload, "template_purpose"),
                template_channel=_optional_str(payload, "template_channel"),
            )
            return {
                "kind": "knowledge_document",
                "operation": operation,
                "document_id": str(result.document_id),
                "version": result.version,
            }
        if operation == "update":
            result = await self._tenant_configuration.update_knowledge_document(
                tenant_id=record.tenant_id,
                document_id=as_knowledge_document_id(_str(payload, "document_id")),
                content=_optional_str(payload, "content"),
                status=(
                    None
                    if payload.get("status") is None
                    else TenantKnowledgeDocumentStatus(_str(payload, "status"))
                ),
                review_status=(
                    None
                    if payload.get("review_status") is None
                    else TenantKnowledgeReviewStatus(_str(payload, "review_status"))
                ),
                uploaded_by=record.approved_by or record.proposed_by,
                approval=approval,
                bypass_direct_apply_gate=True,
                commit=False,
            )
            return {
                "kind": "knowledge_document",
                "operation": operation,
                "document_id": str(result.document_id),
                "version": result.version,
            }
        raise TenantConfigChangeRequestLifecycleError(
            f"unsupported knowledge change operation: {operation}"
        )

    async def _apply_policy(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
        approval: ApprovalRecord,
    ) -> dict[str, Any]:
        operation = _operation(payload, default="create")
        if operation == "create":
            result = await self._tenant_configuration.create_governance_policy(
                tenant_id=record.tenant_id,
                policy_type=_str(payload, "policy_type"),
                parameters=_mapping(payload, "parameters", default={}),
                status=TenantGovernancePolicyStatus(
                    str(
                        payload.get("status")
                        or TenantGovernancePolicyStatus.DRAFT.value
                    )
                ),
                approved_by=record.approved_by or record.proposed_by,
                effective_from=_datetime(payload, "effective_from"),
                approval=approval,
                bypass_direct_apply_gate=True,
                commit=False,
            )
            return {
                "kind": "governance_policy",
                "operation": operation,
                "policy_id": str(result.policy_id),
                "version": result.version,
            }
        if operation == "update":
            result = await self._tenant_configuration.update_governance_policy(
                tenant_id=record.tenant_id,
                policy_id=as_governance_policy_id(_str(payload, "policy_id")),
                parameters=_optional_mapping(payload, "parameters"),
                status=(
                    None
                    if payload.get("status") is None
                    else TenantGovernancePolicyStatus(_str(payload, "status"))
                ),
                approved_by=record.approved_by or record.proposed_by,
                effective_from=(
                    None
                    if payload.get("effective_from") is None
                    else _datetime(payload, "effective_from")
                ),
                approval=approval,
                bypass_direct_apply_gate=True,
                commit=False,
            )
            return {
                "kind": "governance_policy",
                "operation": operation,
                "policy_id": str(result.policy_id),
                "version": result.version,
            }
        raise TenantConfigChangeRequestLifecycleError(
            f"unsupported policy change operation: {operation}"
        )

    async def _apply_execution_governance(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
        approval: ApprovalRecord,
    ) -> dict[str, Any]:
        result = await self._tenant_configuration.configure_execution_governance(
            tenant_id=record.tenant_id,
            execution_quota=_int(payload, "execution_quota"),
            throughput_limit=_int(payload, "throughput_limit"),
            throughput_window_minutes=_int(payload, "throughput_window_minutes"),
            governance_budget_limit=_int(payload, "governance_budget_limit"),
            governance_budget_window_minutes=_int(
                payload, "governance_budget_window_minutes"
            ),
            circuit_failure_threshold=_int(payload, "circuit_failure_threshold"),
            circuit_window_minutes=_int(payload, "circuit_window_minutes"),
            circuit_cooldown_minutes=_int(payload, "circuit_cooldown_minutes"),
            status=TenantExecutionGovernanceStatus(
                str(
                    payload.get("status") or TenantExecutionGovernanceStatus.DRAFT.value
                )
            ),
            configured_by=record.approved_by or record.proposed_by,
            metadata=_mapping(payload, "metadata", default={}),
            approval=approval,
            bypass_direct_apply_gate=True,
            commit=False,
        )
        return {
            "kind": "execution_governance",
            "operation": "configure",
            "config_id": str(result.config_id),
            "version": result.version,
        }

    async def _apply_topology(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = await self._tenant_configuration.configure_topology(
            tenant_id=record.tenant_id,
            topology_name=_str(payload, "topology_name"),
            topology=_mapping(payload, "topology", default={}),
            status=TenantTopologyStatus(
                str(payload.get("status") or TenantTopologyStatus.DRAFT.value)
            ),
            configured_by=record.approved_by or record.proposed_by,
            bypass_direct_apply_gate=True,
            commit=False,
        )
        return {
            "kind": "topology",
            "operation": "configure",
            "config_id": str(result.config_id),
            "version": result.version,
        }

    async def _apply_channel(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        operation = _operation(payload, default="configure")
        if operation == "configure":
            result = await self._tenant_configuration.configure_channel(
                tenant_id=record.tenant_id,
                channel_type=TenantChannelType(_str(payload, "channel_type")),
                routing_address=_str(payload, "routing_address"),
                credentials=_mapping(payload, "credentials", default={}),
                webhook_secret=_str(payload, "webhook_secret"),
                status=TenantChannelStatus(
                    str(
                        payload.get("status")
                        or TenantChannelStatus.PENDING_VALIDATION.value
                    )
                ),
                self_service_config=_mapping(
                    payload,
                    "self_service_config",
                    default={},
                ),
                last_validation_error=_optional_str(
                    payload,
                    "last_validation_error",
                ),
                validation_evidence=_mapping(
                    payload,
                    "validation_evidence",
                    default={},
                ),
                bypass_direct_apply_gate=True,
                commit=False,
            )
            return {
                "kind": "channel",
                "operation": operation,
                "config_id": str(result.config_id),
                "channel_type": result.channel_type.value,
            }
        if operation == "update":
            result = await self._tenant_configuration.update_channel(
                tenant_id=record.tenant_id,
                config_id=as_channel_configuration_id(_str(payload, "config_id")),
                routing_address=_optional_str(payload, "routing_address"),
                credentials=_optional_mapping(payload, "credentials"),
                webhook_secret=_optional_str(payload, "webhook_secret"),
                status=(
                    None
                    if payload.get("status") is None
                    else TenantChannelStatus(_str(payload, "status"))
                ),
                self_service_config=_optional_mapping(
                    payload,
                    "self_service_config",
                ),
                last_validation_error=_optional_str(
                    payload,
                    "last_validation_error",
                ),
                validation_evidence=_optional_mapping(
                    payload,
                    "validation_evidence",
                ),
                bypass_direct_apply_gate=True,
                commit=False,
            )
            return {
                "kind": "channel",
                "operation": operation,
                "config_id": str(result.config_id),
                "channel_type": result.channel_type.value,
            }
        if operation == "verify":
            result = await self._tenant_configuration.verify_channel(
                tenant_id=record.tenant_id,
                config_id=as_channel_configuration_id(_str(payload, "config_id")),
                bypass_direct_apply_gate=True,
                commit=False,
            )
            return {
                "kind": "channel",
                "operation": operation,
                "config_id": str(result.config_id),
                "channel_type": result.channel_type.value,
                "status": result.status.value,
            }
        raise TenantConfigChangeRequestLifecycleError(
            f"unsupported channel change operation: {operation}"
        )

    async def propose_oms_credential_update(
        self,
        *,
        tenant_id: str,
        credentials: Mapping[str, Any],
        proposed_by: str,
    ) -> TenantConfigChangeRequestRecord:
        """Propose an OMS credential update through the dual-control workflow.

        Credentials are encrypted immediately at propose time via OPCRED2 and
        stored in tenant_channel_configurations with status=PENDING_VALIDATION.
        The change-request proposed_payload stores ONLY a SHA-256 sentinel of
        the ciphertext — never plaintext or the envelope itself.
        """
        # Shape-validate before touching any storage.
        validate_channel_credentials(TenantChannelType.OMS, credentials)

        # Guard: rotation (existing ACTIVE row) is not supported in PR 1.
        config_id = derive_channel_configuration_id(
            tenant_id=tenant_id,
            channel_type=TenantChannelType.OMS,
        )
        existing = await self._tenant_configuration.get_channel_configuration(
            tenant_id=tenant_id,
            config_id=config_id,
        )
        if existing is not None and existing.status is TenantChannelStatus.ACTIVE:
            raise TenantConfigChangeRequestLifecycleError(
                "OMS credential rotation is not yet supported; "
                "an active credential already exists for this tenant"
            )

        # Write encrypted envelope to tenant_channel_configurations.
        # The runtime's configure_channel() calls encryptor.encrypt() internally,
        # which runs validate_channel_credentials() again and produces the OPCRED2
        # envelope stored in credentials_enc.
        channel_record = await self._tenant_configuration.configure_channel(
            tenant_id=tenant_id,
            channel_type=TenantChannelType.OMS,
            routing_address="",
            credentials=dict(credentials),
            webhook_secret="",
            status=TenantChannelStatus.PENDING_VALIDATION,
            bypass_direct_apply_gate=True,
            commit=False,
        )

        # Hash the actually-stored ciphertext so apply() can verify integrity.
        # Plaintext credentials are in memory only; never written to any table.
        credential_hash = hashlib.sha256(channel_record.credentials_enc).hexdigest()
        sentinel: dict[str, Any] = {
            "channel": TenantChannelType.OMS.value,
            "credential_hash": credential_hash,
        }
        now = _utcnow()
        versioned = _versioned_payload(sentinel)
        record = TenantConfigChangeRequestRecord(
            change_request_id=derive_tenant_config_change_request_id(
                tenant_id=tenant_id,
                change_type=TenantConfigChangeType.CREDENTIAL_UPDATE,
                proposed_payload=versioned,
                proposed_by=proposed_by,
            ),
            tenant_id=tenant_id,
            change_type=TenantConfigChangeType.CREDENTIAL_UPDATE,
            proposed_payload=versioned,
            status=TenantConfigChangeRequestStatus.PROPOSED,
            proposed_by=proposed_by,
            proposed_at=now,
        )
        persisted = await self._repository.create(
            record,
            expected_tenant_id=tenant_id,
        )
        await self._append_status_event(persisted)
        await self._session.commit()
        return persisted

    async def propose_connector_credential(
        self,
        *,
        tenant_id: str,
        connector_id: str,
        credentials: Mapping[str, Any],
        proposed_by: str,
    ) -> TenantConfigChangeRequestRecord:
        """Propose a per-connector credential through the dual-control workflow.

        Credentials are encrypted immediately at propose time via OPCRED2 and
        stored in connector_credentials with status='pending_validation'.
        The change-request proposed_payload stores ONLY a SHA-256 sentinel of
        the ciphertext — never plaintext or the envelope itself.

        Domain-agnostic: works for any connector_id (account.freeze, service.suspend,
        refund.request, etc.) — not limited to OMS channel connectors.
        """
        repo = self._connector_credential_repository
        codec = self._connector_credential_codec
        if repo is None or codec is None:
            raise TenantConfigChangeRequestLifecycleError(
                "connector credential store is not configured on this service instance"
            )
        if not connector_id or not connector_id.strip():
            raise TenantConfigChangeRequestLifecycleError(
                "connector_id is required"
            )
        if not credentials:
            raise TenantConfigChangeRequestLifecycleError(
                "credentials are required"
            )

        # Encrypt and store the credential immediately (pending_validation).
        ciphertext, credential_hash = encrypt_connector_credentials(
            tenant_id=tenant_id,
            connector_id=connector_id,
            credentials=dict(credentials),
            codec=codec,
        )
        now = _utcnow()
        credential_record = ConnectorCredentialRecord(
            tenant_id=tenant_id,
            connector_id=connector_id,
            credentials_enc=ciphertext,
            credential_hash=credential_hash,
            status="pending_validation",
            configured_by=proposed_by,
            source_approval_id="pending",
            created_at=now,
            updated_at=now,
        )
        await repo.upsert(credential_record, expected_tenant_id=tenant_id)

        # Build sentinel — only the hash goes into the change-request payload.
        sentinel: dict[str, Any] = {
            "connector_id": connector_id,
            "credential_hash": credential_hash,
        }
        versioned = _versioned_payload(sentinel)
        change_record = TenantConfigChangeRequestRecord(
            change_request_id=derive_tenant_config_change_request_id(
                tenant_id=tenant_id,
                change_type=TenantConfigChangeType.CONNECTOR_CREDENTIAL,
                proposed_payload=versioned,
                proposed_by=proposed_by,
            ),
            tenant_id=tenant_id,
            change_type=TenantConfigChangeType.CONNECTOR_CREDENTIAL,
            proposed_payload=versioned,
            status=TenantConfigChangeRequestStatus.PROPOSED,
            proposed_by=proposed_by,
            proposed_at=now,
        )
        persisted = await self._repository.create(
            change_record,
            expected_tenant_id=tenant_id,
        )
        await self._append_status_event(persisted)
        await self._session.commit()
        return persisted

    async def _apply_connector(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
        approval: ApprovalRecord,
    ) -> dict[str, Any]:
        result = await self._tenant_configuration.configure_connector(
            tenant_id=record.tenant_id,
            connector_type=_str(payload, "connector_type"),
            tool_name=_str(payload, "tool_name"),
            http_method=_str(payload, "http_method"),
            endpoint_template=_str(payload, "endpoint_template"),
            endpoint_host=_str(payload, "endpoint_host"),
            field_mappings=_mapping(payload, "field_mappings", default={}),
            idempotency_header_name=_str(payload, "idempotency_header_name"),
            response_parse=_mapping(payload, "response_parse", default={}),
            success_status_codes=_success_status_codes(payload),
            status=str(payload.get("status") or "active"),
            configured_by=record.approved_by or record.proposed_by,
            approval=approval,
            bypass_direct_apply_gate=True,
            commit=False,
        )
        return {
            "kind": "connector_config",
            "operation": "configure",
            "connector_type": result.connector_type,
            "tool_name": result.tool_name,
            "version": result.version,
            "content_sha256": result.content_sha256,
        }

    async def _apply_credential_update(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        channel = _str(payload, "channel")
        if channel != TenantChannelType.OMS.value:
            raise TenantConfigChangeRequestLifecycleError(
                f"unsupported credential_update channel: {channel!r}"
            )
        expected_hash = _str(payload, "credential_hash")

        # Load the pending OMS credential row written at propose time.
        config_id = derive_channel_configuration_id(
            tenant_id=record.tenant_id,
            channel_type=TenantChannelType.OMS,
        )
        channel_record = await self._tenant_configuration.get_channel_configuration(
            tenant_id=record.tenant_id,
            config_id=config_id,
        )
        if channel_record is None:
            raise TenantConfigChangeRequestLifecycleError(
                "OMS channel configuration not found; "
                "pending credential may have been cleared"
            )
        if channel_record.status is not TenantChannelStatus.PENDING_VALIDATION:
            raise TenantConfigChangeRequestLifecycleError(
                "OMS credential is not in pending state "
                f"(status={channel_record.status.value})"
            )

        # Integrity: hash of stored ciphertext must match sentinel.
        # Detects tampering between propose and apply.
        actual_hash = hashlib.sha256(channel_record.credentials_enc).hexdigest()
        if actual_hash != expected_hash:
            raise TenantConfigChangeRequestLifecycleError(
                "OMS credential hash mismatch; "
                "stored ciphertext does not match proposal sentinel"
            )

        # Activate: update status to ACTIVE; credentials_enc is unchanged.
        result = await self._tenant_configuration.update_channel(
            tenant_id=record.tenant_id,
            config_id=channel_record.config_id,
            routing_address=None,
            credentials=None,
            webhook_secret=None,
            status=TenantChannelStatus.ACTIVE,
            bypass_direct_apply_gate=True,
            commit=False,
        )
        return {
            "kind": "oms_credential",
            "operation": "activate",
            "channel": TenantChannelType.OMS.value,
            "config_id": str(result.config_id),
            "status": result.status.value,
        }

    async def _apply_connector_credential(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
        approval: ApprovalRecord,
    ) -> dict[str, Any]:
        repo = self._connector_credential_repository
        if repo is None:
            raise TenantConfigChangeRequestLifecycleError(
                "connector credential store is not configured on this service instance"
            )
        connector_id = _str(payload, "connector_id")
        expected_hash = _str(payload, "credential_hash")

        # Load the pending credential row written at propose time.
        cred = await repo.get(
            tenant_id=record.tenant_id,
            connector_id=connector_id,
            expected_tenant_id=record.tenant_id,
        )
        if cred is None:
            raise TenantConfigChangeRequestLifecycleError(
                f"connector credential not found for connector {connector_id!r}; "
                "pending credential may have been cleared"
            )
        if cred.status != "pending_validation":
            raise TenantConfigChangeRequestLifecycleError(
                f"connector credential is not in pending state "
                f"(status={cred.status!r})"
            )

        # Integrity: hash of stored ciphertext must match sentinel.
        import hashlib as _hashlib
        actual_hash = _hashlib.sha256(cred.credentials_enc).hexdigest()
        if actual_hash != expected_hash:
            raise TenantConfigChangeRequestLifecycleError(
                "connector credential hash mismatch; "
                "stored ciphertext does not match proposal sentinel"
            )

        # Activate: write updated record with status=active and approval id.
        activated = ConnectorCredentialRecord(
            tenant_id=cred.tenant_id,
            connector_id=cred.connector_id,
            credentials_enc=cred.credentials_enc,
            credential_hash=cred.credential_hash,
            status="active",
            configured_by=record.approved_by or record.proposed_by,
            source_approval_id=approval.approval_id,
            created_at=cred.created_at,
            updated_at=_utcnow(),
        )
        await repo.upsert(activated, expected_tenant_id=record.tenant_id)
        return {
            "kind": "connector_credential",
            "operation": "activate",
            "connector_id": connector_id,
            "status": "active",
        }

    async def _apply_mcp_server(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
        approval: ApprovalRecord,
    ) -> dict[str, Any]:
        """Apply an MCP_SERVER change: create/update a ConnectorConfigRecord.

        The MCP server is stored as a connector_type="mcp_server" record.
        tool_name = mcp_server_id (the tenant's chosen identifier).
        endpoint_template = endpoint_url (MCP server base URL).
        field_mappings = {mcp_tools: [...], timeout_seconds: N}.

        The governance gate looks up MCP tools from the action_tools policy
        (declared separately via the POLICY change type), not from this record.
        This record is the runtime wiring; the policy is the governance declaration.
        """
        mcp_server_id = _str(payload, "mcp_server_id")
        endpoint_url = _str(payload, "endpoint_url")
        mcp_tools_raw = payload.get("mcp_tools")
        typed_mcp_tools = _validated_mcp_tools(
            mcp_tools_raw,
            missing_reason="mcp_server payload must include mcp_tools as a list",
            empty_reason="mcp_server payload must include at least one tool declaration",
        )
        # Validate each tool entry has required fields.
        for i, typed_tool in enumerate(typed_mcp_tools):
            if not typed_tool.get("tool_name"):
                raise TenantConfigChangeRequestLifecycleError(
                    f"mcp_tools[{i}].tool_name is required"
                )
            if not typed_tool.get("commitment_kind"):
                raise TenantConfigChangeRequestLifecycleError(
                    f"mcp_tools[{i}].commitment_kind is required"
                )
            if not typed_tool.get("execution_policy"):
                raise TenantConfigChangeRequestLifecycleError(
                    f"mcp_tools[{i}].execution_policy is required "
                    "(auto_execute or operious_approval)"
                )

        # Parse endpoint host for the ConnectorConfigRecord.
        from urllib.parse import urlparse as _urlparse
        parsed_host = (_urlparse(endpoint_url).hostname or "").lower()
        if not parsed_host:
            raise TenantConfigChangeRequestLifecycleError(
                "mcp_server endpoint_url must be a valid HTTPS URL with a hostname"
            )

        timeout_seconds = float(payload.get("timeout_seconds") or 15.0)
        field_mappings: dict[str, Any] = {
            "mcp_tools": list(typed_mcp_tools),
            "timeout_seconds": timeout_seconds,
        }

        result = await self._tenant_configuration.configure_connector(
            tenant_id=record.tenant_id,
            connector_type="mcp_server",
            tool_name=mcp_server_id,
            http_method="POST",
            endpoint_template=endpoint_url,
            endpoint_host=parsed_host,
            field_mappings=field_mappings,
            idempotency_header_name="Idempotency-Key",
            response_parse={},
            success_status_codes=(200, 201, 202),
            status="active",
            configured_by=record.approved_by or record.proposed_by,
            approval=approval,
            bypass_direct_apply_gate=True,
            commit=False,
        )
        return {
            "kind": "mcp_server",
            "operation": "configure",
            "mcp_server_id": mcp_server_id,
            "tool_count": len(typed_mcp_tools),
            "version": result.version,
            "content_sha256": result.content_sha256,
        }

    async def _apply_mcp_oauth_token(
        self,
        record: TenantConfigChangeRequestRecord,
        payload: Mapping[str, Any],
        approval: ApprovalRecord,
    ) -> dict[str, Any]:
        """Apply an MCP_OAUTH_TOKEN change: activate the pending credential.

        The encrypted OAuth token was stored in connector_credentials at
        propose time (status='pending_validation'). This apply step:
        1. Verifies the stored ciphertext hash matches the sentinel.
        2. Activates the credential (status='active', source_approval_id set).

        connector_id for OAuth tokens is the mcp_server_id, so the
        ConnectorScopedCredentialRuntime resolves them transparently.
        """
        repo = self._connector_credential_repository
        if repo is None:
            raise TenantConfigChangeRequestLifecycleError(
                "connector credential store is not configured on this service instance"
            )
        mcp_server_id = _str(payload, "mcp_server_id")
        expected_hash = _str(payload, "token_hash")

        cred = await repo.get(
            tenant_id=record.tenant_id,
            connector_id=mcp_server_id,
            expected_tenant_id=record.tenant_id,
        )
        if cred is None:
            raise TenantConfigChangeRequestLifecycleError(
                f"mcp oauth token not found for server {mcp_server_id!r}; "
                "pending token may have been cleared"
            )
        if cred.status != "pending_validation":
            raise TenantConfigChangeRequestLifecycleError(
                f"mcp oauth token is not in pending state (status={cred.status!r})"
            )

        import hashlib as _hashlib
        actual_hash = _hashlib.sha256(cred.credentials_enc).hexdigest()
        if actual_hash != expected_hash:
            raise TenantConfigChangeRequestLifecycleError(
                "mcp oauth token hash mismatch; "
                "stored ciphertext does not match proposal sentinel"
            )

        activated = ConnectorCredentialRecord(
            tenant_id=cred.tenant_id,
            connector_id=cred.connector_id,
            credentials_enc=cred.credentials_enc,
            credential_hash=cred.credential_hash,
            status="active",
            configured_by=record.approved_by or record.proposed_by,
            source_approval_id=approval.approval_id,
            created_at=cred.created_at,
            updated_at=_utcnow(),
        )
        await repo.upsert(activated, expected_tenant_id=record.tenant_id)
        return {
            "kind": "mcp_oauth_token",
            "operation": "activate",
            "mcp_server_id": mcp_server_id,
            "status": "active",
        }

    def propose_mcp_server(
        self,
        *,
        tenant_id: str,
        mcp_server_id: str,
        endpoint_url: str,
        mcp_tools: list[dict[str, Any]],
        proposed_by: str,
        timeout_seconds: float = 15.0,
    ) -> "TenantConfigChangeRequestRecord":
        """Build (but do not persist) an MCP_SERVER change-request record.

        Callers must call .create() on the repository and .commit() on the session.
        Used by the API router to keep propose logic out of the service.
        """
        payload: dict[str, Any] = {
            "mcp_server_id": mcp_server_id,
            "endpoint_url": endpoint_url,
            "mcp_tools": mcp_tools,
            "timeout_seconds": timeout_seconds,
        }
        from datetime import datetime as _dt, timezone as _tz
        versioned = _versioned_payload(payload)
        from app.tenant.change_requests import derive_tenant_config_change_request_id as _derive
        return TenantConfigChangeRequestRecord(
            change_request_id=_derive(
                tenant_id=tenant_id,
                change_type=TenantConfigChangeType.MCP_SERVER,
                proposed_payload=versioned,
                proposed_by=proposed_by,
            ),
            tenant_id=tenant_id,
            change_type=TenantConfigChangeType.MCP_SERVER,
            proposed_payload=versioned,
            status=TenantConfigChangeRequestStatus.PROPOSED,
            proposed_by=proposed_by,
            proposed_at=_dt.now(_tz.utc),
        )

    async def _append_status_event(
        self,
        record: TenantConfigChangeRequestRecord,
    ) -> None:
        event = _event_for_record(record)
        await self._events.append_event(event, expected_tenant_id=record.tenant_id)


def _approval_for_record(record: TenantConfigChangeRequestRecord) -> ApprovalRecord:
    if record.status is not TenantConfigChangeRequestStatus.APPROVED:
        raise TenantConfigChangeRequestLifecycleError(
            "approval record can only be built for APPROVED requests"
        )
    if record.approved_by is None:
        raise TenantConfigChangeRequestLifecycleError(
            "approved request is missing approved_by"
        )
    material_hash = canonical_sha256(
        {
            "change_request_id": str(record.change_request_id),
            "tenant_id": record.tenant_id,
            "change_type": record.change_type.value,
            "proposed_payload": dict(record.proposed_payload),
            "proposed_by": record.proposed_by,
            "approved_by": record.approved_by,
        }
    )
    approval_id = uuid.uuid5(
        _LEDGER_APPROVAL_NAMESPACE,
        f"{record.change_request_id}|{material_hash}",
    )
    return ApprovalRecord(
        approval_id=str(approval_id),
        tenant_id=record.tenant_id,
        document_id=str(record.change_request_id),
        proposed_change=f"tenant_config:{record.change_type.value}",
        evidence_sessions=(),
        confidence=1.0,
        status=ApprovalStatus.APPROVED.value,
        proposed_by=record.proposed_by,
        reviewed_by=record.approved_by,
        created_at=(record.approved_at or _utcnow()).isoformat(),
        metadata={
            "approval_source": "tenant_config_change_request_ledger",
            "change_request_id": str(record.change_request_id),
            "material_sha256": material_hash,
        },
    )


def _event_for_record(record: TenantConfigChangeRequestRecord) -> OperationalEvent:
    sequence = _sequence_for_status(record.status)
    event_id = EventId(
        str(
            uuid.uuid5(
                _CHANGE_EVENT_NAMESPACE,
                f"{record.change_request_id}|{record.status.value}",
            )
        )
    )
    root_event_id = EventId(
        str(
            uuid.uuid5(
                _CHANGE_EVENT_NAMESPACE,
                f"{record.change_request_id}|"
                f"{TenantConfigChangeRequestStatus.PROPOSED.value}",
            )
        )
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=_act_for_status(record.status),
        substrate=OperationalSubstrate.GOVERNANCE,
        causality=EventCausality(
            root_event_id=root_event_id,
            parent_event_id=(
                None
                if record.status is TenantConfigChangeRequestStatus.PROPOSED
                else root_event_id
            ),
            depth=sequence,
        ),
        chronology=EventChronology(
            runtime_instance_id=record.change_request_id,
            sequence=sequence,
            occurred_at=_timestamp_for_status(record),
        ),
        tenant_id=record.tenant_id,
        principal_id=_principal_for_status(record),
        metadata={
            "projection_source": "tenant_config_change_request",
            "change_request_id": str(record.change_request_id),
            "change_type": record.change_type.value,
            "status": record.status.value,
            "proposed_by": record.proposed_by,
            "approved_by": record.approved_by,
            "rejected_by": record.rejected_by,
            "payload_sha256": canonical_sha256(dict(record.proposed_payload)),
            "outcome_payload": (
                None if record.outcome_payload is None else dict(record.outcome_payload)
            ),
        },
    )


def _act_for_status(status: TenantConfigChangeRequestStatus) -> OperationalAct:
    return {
        TenantConfigChangeRequestStatus.PROPOSED: (
            OperationalAct.TENANT_CONFIG_CHANGE_PROPOSE
        ),
        TenantConfigChangeRequestStatus.APPROVED: (
            OperationalAct.TENANT_CONFIG_CHANGE_APPROVE
        ),
        TenantConfigChangeRequestStatus.REJECTED: (
            OperationalAct.TENANT_CONFIG_CHANGE_REJECT
        ),
        TenantConfigChangeRequestStatus.APPLIED: (
            OperationalAct.TENANT_CONFIG_CHANGE_APPLY
        ),
        TenantConfigChangeRequestStatus.REVOKED: (
            OperationalAct.TENANT_CONFIG_CHANGE_REVOKE
        ),
    }[status]


def _sequence_for_status(status: TenantConfigChangeRequestStatus) -> int:
    return {
        TenantConfigChangeRequestStatus.PROPOSED: 0,
        TenantConfigChangeRequestStatus.APPROVED: 1,
        TenantConfigChangeRequestStatus.REJECTED: 1,
        TenantConfigChangeRequestStatus.APPLIED: 2,
        TenantConfigChangeRequestStatus.REVOKED: 2,
    }[status]


def _timestamp_for_status(record: TenantConfigChangeRequestRecord) -> datetime:
    if record.status is TenantConfigChangeRequestStatus.APPROVED:
        return record.approved_at or record.proposed_at
    if record.status is TenantConfigChangeRequestStatus.REJECTED:
        return record.rejected_at or record.proposed_at
    if record.status is TenantConfigChangeRequestStatus.APPLIED:
        return record.applied_at or record.approved_at or record.proposed_at
    if record.status is TenantConfigChangeRequestStatus.REVOKED:
        return record.revoked_at or record.approved_at or record.proposed_at
    return record.proposed_at


def _principal_for_status(record: TenantConfigChangeRequestRecord) -> str:
    if record.status is TenantConfigChangeRequestStatus.APPROVED:
        return record.approved_by or record.proposed_by
    if record.status is TenantConfigChangeRequestStatus.REJECTED:
        return record.rejected_by or record.proposed_by
    if record.status is TenantConfigChangeRequestStatus.APPLIED:
        return record.applied_by or record.approved_by or record.proposed_by
    if record.status is TenantConfigChangeRequestStatus.REVOKED:
        return record.revoked_by or record.approved_by or record.proposed_by
    return record.proposed_by


def _versioned_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    versioned = dict(payload)
    versioned.setdefault("_schema_version", _SCHEMA_VERSION)
    return versioned


async def _validate_payload(
    change_type: TenantConfigChangeType,
    payload: Mapping[str, Any],
    *,
    tenant_configuration: TenantConfigurationService,
    tenant_id: str,
) -> None:
    if payload.get("_schema_version") != _SCHEMA_VERSION:
        raise TenantConfigChangeRequestLifecycleError(
            "tenant config change payload _schema_version must be '1'"
        )
    operation = _operation(payload, default="")
    if change_type is TenantConfigChangeType.KNOWLEDGE:
        if operation == "update":
            required = ("document_id",)
            _validate_uuid_field(payload, "document_id")
            _validate_enum_field(
                payload,
                "review_status",
                TenantKnowledgeReviewStatus,
            )
        elif payload.get("document_type") == TenantKnowledgeDocumentType.TEMPLATE.value:
            required = (
                "title",
                "content",
                "document_type",
                "template_purpose",
                "template_channel",
            )
            _validate_template_placeholders_payload(payload)
        else:
            required = ("title", "content", "document_type")
        _validate_enum_field(
            payload,
            "document_type",
            TenantKnowledgeDocumentType,
            required=operation != "update",
        )
        _validate_enum_field(payload, "status", TenantKnowledgeDocumentStatus)
    elif change_type is TenantConfigChangeType.POLICY:
        required = (
            ("policy_type", "effective_from")
            if operation != "update"
            else ("policy_id",)
        )
        _validate_enum_field(payload, "status", TenantGovernancePolicyStatus)
        _validate_datetime_field(
            payload,
            "effective_from",
            required=operation != "update",
        )
        if operation == "update":
            _validate_uuid_field(payload, "policy_id")
        _validate_action_policy_payload(payload)
        await _validate_resolution_autonomy_policy_payload(
            payload,
            tenant_configuration=tenant_configuration,
            tenant_id=tenant_id,
        )
        _validate_resolution_taxonomy_policy_payload(payload)
        _validate_warranty_refund_policy_payload(payload)
        await _validate_warranty_refund_role_field_references(
            payload,
            tenant_configuration=tenant_configuration,
            tenant_id=tenant_id,
        )
        await _validate_taxonomy_schema_role_consistency(
            payload,
            tenant_configuration=tenant_configuration,
            tenant_id=tenant_id,
        )
    elif change_type is TenantConfigChangeType.EXECUTION_GOVERNANCE:
        required = (
            "execution_quota",
            "throughput_limit",
            "throughput_window_minutes",
            "governance_budget_limit",
            "governance_budget_window_minutes",
            "circuit_failure_threshold",
            "circuit_window_minutes",
            "circuit_cooldown_minutes",
        )
        _validate_enum_field(payload, "status", TenantExecutionGovernanceStatus)
    elif change_type is TenantConfigChangeType.TOPOLOGY:
        required = ("topology_name", "topology")
        _validate_enum_field(payload, "status", TenantTopologyStatus)
    elif change_type is TenantConfigChangeType.CONNECTOR:
        if _operation(payload, default="configure") != "configure":
            raise TenantConfigChangeRequestLifecycleError(
                "unsupported connector change operation"
            )
        required = (
            "connector_type",
            "tool_name",
            "http_method",
            "endpoint_template",
            "endpoint_host",
            "field_mappings",
            "idempotency_header_name",
            "response_parse",
            "success_status_codes",
        )
        _validate_connector_payload(payload)
    elif change_type is TenantConfigChangeType.CREDENTIAL_UPDATE:
        # Sentinel-only validation: payload must contain only the hash and channel.
        # Plaintext credentials must never appear here.
        required = ("channel", "credential_hash")
        _validate_credential_update_sentinel(payload)
    elif change_type is TenantConfigChangeType.CONNECTOR_CREDENTIAL:
        # Sentinel-only validation: payload must contain only the hash and connector_id.
        # Plaintext credentials must never appear here.
        required = ("connector_id", "credential_hash")
        _validate_connector_credential_sentinel(payload)
    elif change_type is TenantConfigChangeType.MCP_SERVER:
        required = ("mcp_server_id", "endpoint_url", "mcp_tools")
        _validate_mcp_server_payload(payload)
    elif change_type is TenantConfigChangeType.MCP_OAUTH_TOKEN:
        # Sentinel-only: payload must contain only mcp_server_id and token_hash.
        # Plaintext / ciphertext token must never appear here.
        required = ("mcp_server_id", "token_hash")
        _validate_mcp_oauth_token_sentinel(payload)
    else:
        required = (
            ("config_id",)
            if operation in {"update", "verify"}
            else ("channel_type", "routing_address", "credentials", "webhook_secret")
        )
        _validate_enum_field(
            payload,
            "status",
            TenantChannelStatus,
        )
        if operation in {"update", "verify"}:
            _validate_uuid_field(payload, "config_id")
        else:
            _validate_enum_field(
                payload,
                "channel_type",
                TenantChannelType,
                required=True,
            )
    missing = [field for field in required if payload.get(field) is None]
    if missing:
        raise TenantConfigChangeRequestLifecycleError(
            "tenant config change payload missing required field(s): "
            + ", ".join(missing)
        )


def _validate_action_policy_payload(payload: Mapping[str, Any]) -> None:
    parameters = payload.get("parameters")
    policy_type = payload.get("policy_type")
    if policy_type != ACTION_TOOLS_POLICY_TYPE:
        return
    if not isinstance(parameters, Mapping):
        raise TenantConfigChangeRequestLifecycleError(
            "action_tools policy parameters must be an object"
        )
    try:
        validate_action_tools_policy_parameters(
            _dict_from_mapping(cast(Mapping[Any, Any], parameters))
        )
    except ActionPolicyParseError as exc:
        raise TenantConfigChangeRequestLifecycleError(
            f"invalid action_tools policy parameters: {exc}"
        ) from exc


async def _validate_resolution_autonomy_policy_payload(
    payload: Mapping[str, Any],
    *,
    tenant_configuration: TenantConfigurationService,
    tenant_id: str,
) -> None:
    parameters = payload.get("parameters")
    policy_type = payload.get("policy_type")
    if policy_type != RESOLUTION_AUTONOMY_POLICY_TYPE:
        return
    if not isinstance(parameters, Mapping):
        raise TenantConfigChangeRequestLifecycleError(
            "resolution_autonomy policy parameters must be an object"
        )
    parameters_dict = _dict_from_mapping(cast(Mapping[Any, Any], parameters))
    try:
        validate_resolution_autonomy_policy_parameters(parameters_dict)
    except ResolutionAutonomyPolicyParseError as exc:
        raise TenantConfigChangeRequestLifecycleError(
            f"invalid resolution_autonomy policy parameters: {exc}"
        ) from exc

    reply_auto_send = parameters_dict.get("reply_auto_send")
    category_allowlist: object = (
        cast(Mapping[str, object], reply_auto_send).get("category_allowlist")
        if isinstance(reply_auto_send, Mapping)
        else None
    )
    if not isinstance(category_allowlist, Sequence) or isinstance(
        category_allowlist, str | bytes
    ):
        return

    taxonomy_record = await tenant_configuration.resolve_active_governance_policy(
        tenant_id=tenant_id,
        policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
    )
    if taxonomy_record is None:
        return
    try:
        taxonomy = parse_resolution_taxonomy_policy(taxonomy_record)
    except ResolutionTaxonomyPolicyParseError:
        return

    allowlist = {str(category) for category in cast("Iterable[Any]", category_allowlist)}
    if UNCLASSIFIED_CATEGORY_ID in allowlist:
        raise TenantConfigChangeRequestLifecycleError(
            "resolution_autonomy category_allowlist must not contain the "
            f"reserved category {UNCLASSIFIED_CATEGORY_ID!r}"
        )
    unknown_categories = allowlist - taxonomy.category_ids()
    if unknown_categories:
        raise TenantConfigChangeRequestLifecycleError(
            "resolution_autonomy category_allowlist contains categories not "
            "present in the active resolution_taxonomy: "
            + ", ".join(sorted(unknown_categories))
        )


def _validate_resolution_taxonomy_policy_payload(payload: Mapping[str, Any]) -> None:
    parameters = payload.get("parameters")
    policy_type = payload.get("policy_type")
    if policy_type != RESOLUTION_TAXONOMY_POLICY_TYPE:
        return
    if not isinstance(parameters, Mapping):
        raise TenantConfigChangeRequestLifecycleError(
            "resolution_taxonomy policy parameters must be an object"
        )
    try:
        validate_resolution_taxonomy_policy_parameters(
            _dict_from_mapping(cast(Mapping[Any, Any], parameters))
        )
    except ResolutionTaxonomyPolicyParseError as exc:
        raise TenantConfigChangeRequestLifecycleError(
            f"invalid resolution_taxonomy policy parameters: {exc}"
        ) from exc


def _validate_warranty_refund_policy_payload(payload: Mapping[str, Any]) -> None:
    parameters = payload.get("parameters")
    policy_type = payload.get("policy_type")
    if policy_type != WARRANTY_REFUND_RULES_POLICY_TYPE:
        return
    if not isinstance(parameters, Mapping):
        raise TenantConfigChangeRequestLifecycleError(
            "warranty_refund_rules policy parameters must be an object"
        )
    try:
        validate_warranty_refund_policy_parameters(
            _dict_from_mapping(cast(Mapping[Any, Any], parameters))
        )
    except WarrantyRefundPolicyParseError as exc:
        raise TenantConfigChangeRequestLifecycleError(
            f"invalid warranty_refund_rules policy parameters: {exc}"
        ) from exc


async def _validate_warranty_refund_role_field_references(
    payload: Mapping[str, Any],
    *,
    tenant_configuration: "TenantConfigurationService",
    tenant_id: str,
) -> None:
    """Cross-policy guard (money-path integrity): reject a warranty_refund_rules
    change whose eligibility_field_mappings reference a field name not declared
    in the current active resolution_taxonomy extraction_schema.

    A dangling role→field reference causes every eligibility evaluation to
    produce CANNOT_DETERMINE silently, routing all eligible tickets to human
    review with no actionable error.  Better to reject at propose time.

    Skip the check when:
    - No custom eligibility_field_mappings are present (defaults are always valid).
    - No active resolution_taxonomy policy exists (cannot validate against nothing).
    - The active taxonomy has no extraction_schema (legacy e-commerce defaults
      are always valid; the two default role values purchase_date/seller exist
      in the legacy field set by construction).
    """
    if payload.get("policy_type") != WARRANTY_REFUND_RULES_POLICY_TYPE:
        return
    parameters = payload.get("parameters")
    if not isinstance(parameters, Mapping):
        return
    _parameters_typed: Mapping[str, Any] = cast("Mapping[str, Any]", parameters)
    eligibility_mappings = _parameters_typed.get("eligibility_field_mappings")
    if not isinstance(eligibility_mappings, Mapping) or not eligibility_mappings:
        return
    eligibility_mappings_typed: Mapping[str, Any] = cast("Mapping[str, Any]", eligibility_mappings)

    taxonomy_record = await tenant_configuration.resolve_active_governance_policy(
        tenant_id=tenant_id,
        policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
    )
    if taxonomy_record is None:
        return
    try:
        taxonomy = parse_resolution_taxonomy_policy(taxonomy_record)
    except ResolutionTaxonomyPolicyParseError:
        return
    if taxonomy.extraction_schema is None:
        return

    declared = taxonomy.extraction_schema.field_names()
    for role_key, mapped_field in eligibility_mappings_typed.items():
        if not isinstance(mapped_field, str) or not mapped_field.strip():
            continue
        field = mapped_field.strip()
        if field not in declared:
            raise TenantConfigChangeRequestLifecycleError(
                f"eligibility_field_mappings.{role_key} references field "
                f"{field!r} which is not declared in the active "
                f"resolution_taxonomy extraction_schema "
                f"(declared: {', '.join(sorted(declared))}). "
                f"Add {field!r} to the extraction schema first, or map "
                f"the role to an existing field."
            )


async def _validate_taxonomy_schema_role_consistency(
    payload: Mapping[str, Any],
    *,
    tenant_configuration: "TenantConfigurationService",
    tenant_id: str,
) -> None:
    """Cross-policy guard (money-path integrity): reject a resolution_taxonomy
    change that would leave the active warranty_refund_rules
    eligibility_field_mappings with a dangling field reference.

    A tenant removing field 'transaction_date' from their extraction_schema
    while their warranty_refund_rules maps purchase_timestamp →
    'transaction_date' would silently break eligibility for every subsequent
    ticket.  Catch it here at taxonomy-change propose time.

    Skip when:
    - The proposed parameters omit extraction_schema (removing the schema
      entirely reverts to legacy defaults, which are always valid).
    - No active warranty_refund_rules policy exists.
    - The warranty policy uses only the two legacy default values
      (purchase_date / seller) — those are always valid.
    """
    if payload.get("policy_type") != RESOLUTION_TAXONOMY_POLICY_TYPE:
        return
    parameters = payload.get("parameters")
    if not isinstance(parameters, Mapping):
        return
    _parameters_typed2: Mapping[str, Any] = cast("Mapping[str, Any]", parameters)
    proposed_schema = _parameters_typed2.get("extraction_schema")
    if proposed_schema is None:
        return
    if not isinstance(proposed_schema, Mapping):
        return

    proposed_field_names: frozenset[str] = frozenset(
        str(k) for k in cast("Mapping[Any, Any]", proposed_schema).keys()
    )

    warranty_record = await tenant_configuration.resolve_active_governance_policy(
        tenant_id=tenant_id,
        policy_type=WARRANTY_REFUND_RULES_POLICY_TYPE,
    )
    if warranty_record is None:
        return
    try:
        warranty_policy = parse_warranty_refund_policy(warranty_record)
    except WarrantyRefundPolicyParseError:
        return

    _LEGACY_DEFAULTS = frozenset({"purchase_date", "seller"})
    for role_key, mapped_field in warranty_policy.eligibility_field_mappings.items():
        if mapped_field in _LEGACY_DEFAULTS:
            continue
        if mapped_field not in proposed_field_names:
            raise TenantConfigChangeRequestLifecycleError(
                f"The proposed extraction_schema does not include field "
                f"{mapped_field!r}, which is referenced by the active "
                f"warranty_refund_rules eligibility_field_mappings "
                f"(role: {role_key!r}). Update the eligibility role mapping "
                f"first, or include {mapped_field!r} in the proposed schema."
            )


def _validate_template_placeholders_payload(payload: Mapping[str, Any]) -> None:
    """Reject a proposed template that references a placeholder outside
    the fillable set at the earliest possible point — before a change
    request can even be PROPOSED, let alone approved. Without this, an
    unknown placeholder was never caught anywhere and would silently
    render as a literal "[missing: name]" string in a customer-facing
    reply."""
    content = payload.get("content")
    if not isinstance(content, str):
        return  # the required-fields check above already covers this
    try:
        validate_template_placeholders(content)
    except TemplatePlaceholderError as exc:
        raise TenantConfigChangeRequestLifecycleError(str(exc)) from exc


def _validate_connector_payload(payload: Mapping[str, Any]) -> None:
    forbidden = sorted(
        key
        for key in (
            "access_token",
            "api_key",
            "auth_header",
            "bearer_token",
            "credential",
            "credentials",
            "credentials_enc",
            "webhook_secret",
        )
        if key in payload
    )
    if forbidden:
        raise TenantConfigChangeRequestLifecycleError(
            "connector config credentials must use the channel credential path; "
            "forbidden field(s): "
            + ", ".join(forbidden)
        )
    connector_type = _str(payload, "connector_type")
    if not connector_type or not connector_type.strip():
        raise TenantConfigChangeRequestLifecycleError(
            "connector_type is required"
        )
    method = _str(payload, "http_method").upper()
    if method not in {"DELETE", "GET", "PATCH", "POST", "PUT"}:
        raise TenantConfigChangeRequestLifecycleError(
            "http_method must be one of DELETE, GET, PATCH, POST, PUT"
        )
    endpoint_host = _str(payload, "endpoint_host").lower()
    _validate_public_host_shape(endpoint_host)
    parsed = urlparse(_str(payload, "endpoint_template"))
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise TenantConfigChangeRequestLifecycleError(
            "endpoint_template must be an absolute HTTPS URL"
        )
    template_host = (parsed.hostname or "").lower()
    if template_host != endpoint_host:
        raise TenantConfigChangeRequestLifecycleError(
            "endpoint_template host must match endpoint_host"
        )
    _mapping(payload, "field_mappings", default={})
    _mapping(payload, "response_parse", default={})
    header_name = _str(payload, "idempotency_header_name")
    if any(ch.isspace() for ch in header_name):
        raise TenantConfigChangeRequestLifecycleError(
            "idempotency_header_name must not contain whitespace"
        )
    status = str(payload.get("status") or "active")
    if status not in {"active", "disabled"}:
        raise TenantConfigChangeRequestLifecycleError(
            "connector status must be active or disabled"
        )
    _success_status_codes(payload)


_CREDENTIAL_UPDATE_SENTINEL_KEYS: frozenset[str] = frozenset(
    {"channel", "credential_hash", "_schema_version"}
)
_CREDENTIAL_SENTINEL_FORBIDDEN_KEYS: tuple[str, ...] = (
    "access_token",
    "api_key",
    "auth_header",
    "bearer_token",
    "credential",
    "credentials",
    "credentials_enc",
    "password",
    "token",
    "webhook_secret",
)


def _validate_credential_update_sentinel(payload: Mapping[str, Any]) -> None:
    forbidden = sorted(k for k in _CREDENTIAL_SENTINEL_FORBIDDEN_KEYS if k in payload)
    if forbidden:
        raise TenantConfigChangeRequestLifecycleError(
            "credential_update payload must not contain credential fields; "
            "forbidden field(s): " + ", ".join(forbidden)
        )
    unknown = sorted(
        k for k in payload if k not in _CREDENTIAL_UPDATE_SENTINEL_KEYS
    )
    if unknown:
        raise TenantConfigChangeRequestLifecycleError(
            "credential_update payload contains unexpected field(s): "
            + ", ".join(unknown)
        )
    channel = _str(payload, "channel")
    if channel != TenantChannelType.OMS.value:
        raise TenantConfigChangeRequestLifecycleError(
            f"credential_update channel must be {TenantChannelType.OMS.value!r}; "
            f"got {channel!r}"
        )
    credential_hash = _str(payload, "credential_hash")
    if len(credential_hash) != 64 or not all(
        c in "0123456789abcdef" for c in credential_hash
    ):
        raise TenantConfigChangeRequestLifecycleError(
            "credential_update credential_hash must be a 64-character hex SHA-256"
        )


_CONNECTOR_CREDENTIAL_SENTINEL_KEYS: frozenset[str] = frozenset(
    {"connector_id", "credential_hash", "_schema_version"}
)


def _validate_connector_credential_sentinel(payload: Mapping[str, Any]) -> None:
    """Validate connector_credential change-request sentinel payload.

    Plaintext credentials must NEVER appear here — only the connector_id
    (non-secret) and SHA-256 hash of the encrypted ciphertext.
    """
    forbidden = sorted(k for k in _CREDENTIAL_SENTINEL_FORBIDDEN_KEYS if k in payload)
    if forbidden:
        raise TenantConfigChangeRequestLifecycleError(
            "connector_credential payload must not contain credential fields; "
            "forbidden field(s): " + ", ".join(forbidden)
        )
    unknown = sorted(
        k for k in payload if k not in _CONNECTOR_CREDENTIAL_SENTINEL_KEYS
    )
    if unknown:
        raise TenantConfigChangeRequestLifecycleError(
            "connector_credential payload contains unexpected field(s): "
            + ", ".join(unknown)
        )
    connector_id = _str(payload, "connector_id")
    if not connector_id.strip():
        raise TenantConfigChangeRequestLifecycleError(
            "connector_credential connector_id must be non-empty"
        )
    credential_hash = _str(payload, "credential_hash")
    if len(credential_hash) != 64 or not all(
        c in "0123456789abcdef" for c in credential_hash
    ):
        raise TenantConfigChangeRequestLifecycleError(
            "connector_credential credential_hash must be a 64-character hex SHA-256"
        )


_VALID_COMMITMENT_KINDS: frozenset[str] = frozenset(
    {"none", "record_update", "money", "goods", "service_commitment"}
)
_VALID_EXECUTION_POLICIES: frozenset[str] = frozenset(
    {"auto_execute", "operious_approval"}
)
_MCP_OAUTH_TOKEN_SENTINEL_KEYS: frozenset[str] = frozenset(
    {"mcp_server_id", "token_hash", "_schema_version"}
)


def _validate_mcp_server_payload(payload: Mapping[str, Any]) -> None:
    """Validate MCP_SERVER change-request payload.

    Required: mcp_server_id (non-empty), endpoint_url (HTTPS), mcp_tools (list).
    Each tool must have: tool_name, commitment_kind, execution_policy.
    """
    mcp_server_id = payload.get("mcp_server_id")
    if not isinstance(mcp_server_id, str) or not mcp_server_id.strip():
        raise TenantConfigChangeRequestLifecycleError(
            "mcp_server payload mcp_server_id must be a non-empty string"
        )
    endpoint_url = payload.get("endpoint_url")
    if not isinstance(endpoint_url, str) or not endpoint_url.strip():
        raise TenantConfigChangeRequestLifecycleError(
            "mcp_server payload endpoint_url must be a non-empty string"
        )
    if not endpoint_url.strip().lower().startswith("https://"):
        raise TenantConfigChangeRequestLifecycleError(
            "mcp_server endpoint_url must use HTTPS"
        )
    typed_mcp_tools = _validated_mcp_tools(
        payload.get("mcp_tools"),
        missing_reason="mcp_server payload mcp_tools must be a non-empty list",
        empty_reason="mcp_server payload mcp_tools must be a non-empty list",
    )
    for i, typed_tool in enumerate(typed_mcp_tools):
        tool_name = typed_tool.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise TenantConfigChangeRequestLifecycleError(
                f"mcp_tools[{i}].tool_name is required and must be a non-empty string"
            )
        commitment_kind = str(typed_tool.get("commitment_kind") or "").lower()
        if commitment_kind not in _VALID_COMMITMENT_KINDS:
            raise TenantConfigChangeRequestLifecycleError(
                f"mcp_tools[{i}].commitment_kind {commitment_kind!r} is not valid; "
                f"must be one of: {', '.join(sorted(_VALID_COMMITMENT_KINDS))}"
            )
        execution_policy = str(typed_tool.get("execution_policy") or "").lower()
        if execution_policy not in _VALID_EXECUTION_POLICIES:
            raise TenantConfigChangeRequestLifecycleError(
                f"mcp_tools[{i}].execution_policy {execution_policy!r} is not valid; "
                f"must be one of: auto_execute, operious_approval"
            )


def _validate_mcp_oauth_token_sentinel(payload: Mapping[str, Any]) -> None:
    """Validate MCP_OAUTH_TOKEN sentinel payload.

    Only mcp_server_id and token_hash (SHA-256 hex) are permitted.
    Actual access_token / refresh_token must NEVER appear here.
    """
    forbidden = sorted(k for k in _CREDENTIAL_SENTINEL_FORBIDDEN_KEYS if k in payload)
    if forbidden:
        raise TenantConfigChangeRequestLifecycleError(
            "mcp_oauth_token payload must not contain token fields; "
            "forbidden field(s): " + ", ".join(forbidden)
        )
    mcp_server_id = payload.get("mcp_server_id")
    if not isinstance(mcp_server_id, str) or not mcp_server_id.strip():
        raise TenantConfigChangeRequestLifecycleError(
            "mcp_oauth_token mcp_server_id must be a non-empty string"
        )
    token_hash = payload.get("token_hash")
    if not isinstance(token_hash, str):
        raise TenantConfigChangeRequestLifecycleError(
            "mcp_oauth_token token_hash must be a string"
        )
    if len(token_hash) != 64 or not all(c in "0123456789abcdef" for c in token_hash):
        raise TenantConfigChangeRequestLifecycleError(
            "mcp_oauth_token token_hash must be a 64-character hex SHA-256"
        )


def _validate_public_host_shape(host: str) -> None:
    if "://" in host or "/" in host or any(ch.isspace() for ch in host):
        raise TenantConfigChangeRequestLifecycleError(
            "endpoint_host must be a bare host name"
        )
    try:
        address = ip_address(host)
    except ValueError:
        _validate_dns_host_shape(host)
        return
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise TenantConfigChangeRequestLifecycleError(
            "endpoint_host must not be a private or reserved IP"
        )


def _validate_dns_host_shape(host: str) -> None:
    labels = host.split(".")
    if len(labels) < 2:
        raise TenantConfigChangeRequestLifecycleError(
            "endpoint_host must include a public DNS suffix"
        )
    for label in labels:
        if not label or len(label) > 63:
            raise TenantConfigChangeRequestLifecycleError(
                "endpoint_host contains an invalid DNS label"
            )
        if label.startswith("-") or label.endswith("-"):
            raise TenantConfigChangeRequestLifecycleError(
                "endpoint_host contains an invalid DNS label"
            )
        for ch in label:
            if not (ch.isascii() and (ch.isalnum() or ch == "-")):
                raise TenantConfigChangeRequestLifecycleError(
                    "endpoint_host contains an invalid DNS label"
                )


def _change_type(value: TenantConfigChangeType | str) -> TenantConfigChangeType:
    return (
        value
        if isinstance(value, TenantConfigChangeType)
        else TenantConfigChangeType(str(value))
    )


def _operation(payload: Mapping[str, Any], *, default: str) -> str:
    return str(payload.get("operation") or default)


def _str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None or str(value) == "":
        raise TenantConfigChangeRequestLifecycleError(f"{key} is required")
    return str(value)


def _optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return None if value is None else str(value)


def _int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if value is None:
        raise TenantConfigChangeRequestLifecycleError(f"{key} is required")
    return int(value)


def _mapping(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value = payload.get(key)
    if value is None and default is not None:
        return _dict_from_mapping(default)
    if not isinstance(value, Mapping):
        raise TenantConfigChangeRequestLifecycleError(f"{key} must be an object")
    return _dict_from_mapping(cast(Mapping[Any, Any], value))


def _optional_mapping(
    payload: Mapping[str, Any],
    key: str,
) -> dict[str, Any] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TenantConfigChangeRequestLifecycleError(f"{key} must be an object")
    return _dict_from_mapping(cast(Mapping[Any, Any], value))


def _datetime(payload: Mapping[str, Any], key: str) -> datetime:
    value = payload.get(key)
    if isinstance(value, datetime):
        return value
    if value is None:
        raise TenantConfigChangeRequestLifecycleError(f"{key} is required")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _validate_enum_field(
    payload: Mapping[str, Any],
    key: str,
    enum_type: type[StrEnum],
    *,
    required: bool = False,
) -> None:
    value = payload.get(key)
    if value is None:
        if required:
            raise TenantConfigChangeRequestValidationError(f"{key} is required")
        return
    try:
        enum_type(str(value))
    except ValueError as exc:
        allowed = ", ".join(repr(member.value) for member in enum_type)
        raise TenantConfigChangeRequestValidationError(
            f"{key} must be one of [{allowed}]; got {value!r}"
        ) from exc


def _validate_datetime_field(
    payload: Mapping[str, Any],
    key: str,
    *,
    required: bool = False,
) -> None:
    value = payload.get(key)
    if value is None:
        if required:
            raise TenantConfigChangeRequestValidationError(f"{key} is required")
        return
    try:
        if not isinstance(value, datetime):
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TenantConfigChangeRequestValidationError(
            f"{key} must be an ISO 8601 datetime; got {value!r}"
        ) from exc


def _validate_uuid_field(payload: Mapping[str, Any], key: str) -> None:
    value = payload.get(key)
    if value is None:
        return
    try:
        uuid.UUID(str(value))
    except ValueError as exc:
        raise TenantConfigChangeRequestValidationError(
            f"{key} must be a valid UUID; got {value!r}"
        ) from exc


def _success_status_codes(payload: Mapping[str, Any]) -> tuple[int, ...]:
    raw = payload.get("success_status_codes")
    if not isinstance(raw, (list, tuple)):
        raise TenantConfigChangeRequestLifecycleError(
            "success_status_codes must be a non-empty list"
        )
    codes: list[int] = []
    for item in cast(Sequence[Any], raw):
        if isinstance(item, bool) or not isinstance(item, int):
            raise TenantConfigChangeRequestLifecycleError(
                "success_status_codes must contain integers"
            )
        if item < 100 or item > 599:
            raise TenantConfigChangeRequestLifecycleError(
                "success_status_codes must be HTTP status codes"
            )
        codes.append(item)
    if not codes:
        raise TenantConfigChangeRequestLifecycleError(
            "success_status_codes must be non-empty"
        )
    return tuple(codes)


def _dict_from_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["TenantConfigChangeRequestService"]
