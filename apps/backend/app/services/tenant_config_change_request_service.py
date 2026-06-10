"""Tenant config dual-control change-request service."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any, cast
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    ActionPolicyParseError,
    validate_action_tools_policy_parameters,
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
from app.tenant.identity import (
    as_channel_configuration_id,
    as_governance_policy_id,
    as_knowledge_document_id,
)
from app.services.tenant_configuration_service import TenantConfigurationService

_LEDGER_APPROVAL_NAMESPACE = uuid.UUID("b61074c6-a757-51f4-ae19-947742f31705")
_CHANGE_EVENT_NAMESPACE = uuid.UUID("01f77264-1518-5a56-9327-0472414e7dc0")
_SCHEMA_VERSION = "1"


class TenantConfigChangeRequestService:
    """Application service for durable propose/approve/apply config changes."""

    def __init__(
        self,
        *,
        repository: TenantConfigChangeRequestRepository,
        tenant_configuration_service: TenantConfigurationService,
        event_appender: OperationalEventAppender,
        session: AsyncSession,
    ) -> None:
        self._repository = repository
        self._tenant_configuration = tenant_configuration_service
        self._events = event_appender
        self._session = session

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
        _validate_payload(change, proposed_payload)
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
        _validate_payload(change, payload)
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


def _validate_payload(
    change_type: TenantConfigChangeType,
    payload: Mapping[str, Any],
) -> None:
    if payload.get("_schema_version") != _SCHEMA_VERSION:
        raise TenantConfigChangeRequestLifecycleError(
            "tenant config change payload _schema_version must be '1'"
        )
    operation = _operation(payload, default="")
    if change_type is TenantConfigChangeType.KNOWLEDGE:
        required = (
            ("title", "content", "document_type")
            if operation != "update"
            else ("document_id",)
        )
    elif change_type is TenantConfigChangeType.POLICY:
        required = (
            ("policy_type", "effective_from")
            if operation != "update"
            else ("policy_id",)
        )
        _validate_action_policy_payload(payload)
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
    elif change_type is TenantConfigChangeType.TOPOLOGY:
        required = ("topology_name", "topology")
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
    else:
        required = (
            ("config_id",)
            if operation in {"update", "verify"}
            else ("channel_type", "routing_address", "credentials", "webhook_secret")
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
    try:
        TenantChannelType(_str(payload, "connector_type"))
    except ValueError as exc:
        raise TenantConfigChangeRequestLifecycleError(
            "connector_type must map to a tenant channel type"
        ) from exc
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
