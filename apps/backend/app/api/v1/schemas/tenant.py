"""Transport contracts for tenant-owned configuration endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantExecutionCircuitState,
    TenantExecutionGovernanceStatus,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
    TenantStatus,
    TenantTopologyStatus,
)
from app.tenant.change_requests import (
    TenantConfigChangeRequestPage as LedgerPage,
)
from app.tenant.change_requests import (
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
)
from app.tenant.persistence import (
    TenantChannelConfigurationRecord,
    TenantConnectorConfigurationRecord,
    TenantExecutionCircuitBreakerRecord,
    TenantExecutionGovernanceConfigurationRecord,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
    TenantTopologyConfigurationRecord,
)
from app.tenant.lifecycle import (
    TenantAdminProvisioningRecord,
    TenantLifecyclePage as LifecyclePage,
    TenantLifecycleRecord,
)


_SENSITIVE_CHANGE_PAYLOAD_KEYS = frozenset(
    {
        "access_token",
        "access_key_id",
        "api_key",
        "app_secret",
        "auth_header",
        "aws_access_key_id",
        "aws_secret_access_key",
        "bearer_token",
        "client_secret",
        "credential",
        "credentials",
        "credentials_enc",
        "graph_api_access_token",
        "secret",
        "secret_access_key",
        "session_token",
        "system_user_token",
        "token",
        "webhook_secret",
        "webhook_verify_token",
    }
)


def _redact_sensitive_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        mapping = cast(Mapping[Any, Any], value)
        for key, item in mapping.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_CHANGE_PAYLOAD_KEYS:
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = _redact_sensitive_payload(item)
        return redacted
    if isinstance(value, list):
        items = cast(list[Any], value)
        return [_redact_sensitive_payload(item) for item in items]
    return value


def _require_self_service_channel_status(status: TenantChannelStatus) -> None:
    allowed = {
        TenantChannelStatus.DRAFT,
        TenantChannelStatus.PENDING_VALIDATION,
        TenantChannelStatus.VALIDATION_FAILED,
        TenantChannelStatus.ACTIVE,
        TenantChannelStatus.DISABLED,
    }
    if status not in allowed:
        raise ValueError(
            "status must be draft, pending_validation, validation_failed, "
            "active, or disabled"
        )


class TenantChannelCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel_type: TenantChannelType
    routing_address: str = Field(min_length=1)
    credentials: dict[str, Any]
    webhook_secret: str = Field(min_length=1)
    status: TenantChannelStatus = TenantChannelStatus.PENDING_VALIDATION
    self_service_config: dict[str, Any] = Field(default_factory=dict)


class TenantLifecycleCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(min_length=1, max_length=255)


class TenantAdminProvisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    email: str = Field(min_length=3, max_length=320)


class TenantLifecycleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    status: TenantStatus
    created_at: datetime

    @classmethod
    def from_record(
        cls,
        record: TenantLifecycleRecord,
    ) -> "TenantLifecycleResponse":
        return cls(
            tenant_id=record.tenant_id,
            status=record.status,
            created_at=record.created_at,
        )


class TenantLifecyclePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantLifecycleResponse] = []
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: LifecyclePage,
    ) -> "TenantLifecyclePage":
        return cls(
            items=[
                TenantLifecycleResponse.from_record(record)
                for record in page.items
            ],
            total=page.total,
            offset=page.offset,
        )


class TenantAdminProvisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    email: str
    auth0_user_id: str
    roles_granted: list[str]
    capabilities_granted: list[str]
    created_user: bool
    updated_claims: bool
    assigned_roles: bool
    outcome: str
    event_id: str
    provisioned_at: datetime

    @classmethod
    def from_record(
        cls,
        record: TenantAdminProvisioningRecord,
    ) -> "TenantAdminProvisionResponse":
        return cls(
            tenant_id=record.tenant_id,
            email=record.email,
            auth0_user_id=record.auth0_user_id,
            roles_granted=list(record.roles_granted),
            capabilities_granted=list(record.capabilities_granted),
            created_user=record.created_user,
            updated_claims=record.updated_claims,
            assigned_roles=record.assigned_roles,
            outcome=record.outcome,
            event_id=record.event_id,
            provisioned_at=record.provisioned_at,
        )


class TenantChannelUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    routing_address: str | None = Field(default=None, min_length=1)
    credentials: dict[str, Any] | None = None
    webhook_secret: str | None = Field(default=None, min_length=1)
    status: TenantChannelStatus | None = None
    self_service_config: dict[str, Any] | None = None


class TenantWhatsAppSelfServiceRequest(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    waba_id: str | None = Field(default=None, min_length=1)
    phone_number_id: str = Field(min_length=1)
    business_account_id: str | None = Field(default=None, min_length=1)
    graph_api_version: str = Field(default="v25.0", min_length=2)
    app_id: str | None = Field(default=None, min_length=1)
    meta_config_id: str | None = Field(
        default=None,
        alias="config_id",
        min_length=1,
    )
    access_token: str | None = Field(default=None, min_length=1)
    system_user_token: str | None = Field(default=None, min_length=1)
    webhook_verify_token: str | None = Field(default=None, min_length=1)
    app_secret: str | None = Field(default=None, min_length=1)
    status: TenantChannelStatus = TenantChannelStatus.PENDING_VALIDATION

    @model_validator(mode="after")
    def _validate_status(self) -> "TenantWhatsAppSelfServiceRequest":
        _require_self_service_channel_status(self.status)
        return self


class TenantSesSelfServiceRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["managed", "byo_role", "byo_access_key"]
    region: str = Field(min_length=1)
    source_email: str | None = Field(default=None, min_length=3)
    source_domain: str | None = Field(default=None, min_length=3)
    inbound_address: str | None = Field(default=None, min_length=3)
    inbound_domain: str | None = Field(default=None, min_length=3)
    topic_arn: str | None = Field(default=None, min_length=1)
    receipt_rule_set: str | None = Field(default=None, min_length=1)
    receipt_rule_name: str | None = Field(default=None, min_length=1)
    role_arn: str | None = Field(default=None, min_length=1)
    external_id: str | None = Field(default=None, min_length=1)
    access_key_id: str | None = Field(default=None, min_length=1)
    aws_access_key_id: str | None = Field(default=None, min_length=1)
    secret_access_key: str | None = Field(default=None, min_length=1)
    aws_secret_access_key: str | None = Field(default=None, min_length=1)
    session_token: str | None = Field(default=None, min_length=1)
    status: TenantChannelStatus = TenantChannelStatus.PENDING_VALIDATION

    @model_validator(mode="after")
    def _validate_ses_shape(self) -> "TenantSesSelfServiceRequest":
        _require_self_service_channel_status(self.status)
        if not any(
            (
                self.source_email,
                self.source_domain,
                self.inbound_address,
                self.inbound_domain,
            )
        ):
            raise ValueError(
                "one of source_email, source_domain, inbound_address, "
                "or inbound_domain is required"
            )
        if self.mode == "byo_role" and (
            not self.role_arn or not self.external_id
        ):
            raise ValueError("role_arn and external_id are required for byo_role")
        return self


class TenantChannelConfigurationResponse(BaseModel):
    """Credential-redacted channel response."""

    model_config = ConfigDict(frozen=True)

    config_id: str
    channel_type: TenantChannelType
    routing_address: str
    status: TenantChannelStatus
    verified_at: str | None = None
    credential_rotated_at: str | None = None
    credential_rotation_expires_at: str | None = None
    self_service_config: dict[str, Any] = Field(default_factory=dict)
    last_validation_error: str | None = None
    validation_evidence: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls,
        record: TenantChannelConfigurationRecord,
    ) -> "TenantChannelConfigurationResponse":
        return cls(
            config_id=str(record.config_id),
            channel_type=record.channel_type,
            routing_address=record.routing_address,
            status=record.status,
            verified_at=(
                record.verified_at.isoformat()
                if record.verified_at is not None
                else None
            ),
            credential_rotated_at=(
                record.credential_rotated_at.isoformat()
                if record.credential_rotated_at is not None
                else None
            ),
            credential_rotation_expires_at=(
                record.credential_rotation_expires_at.isoformat()
                if record.credential_rotation_expires_at is not None
                else None
            ),
            self_service_config=dict(record.self_service_config),
            last_validation_error=record.last_validation_error,
            validation_evidence=dict(record.validation_evidence),
        )


class TenantChannelConfigurationPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantChannelConfigurationResponse] = []
    total: int
    offset: int


class TenantConnectorConfigurationResponse(BaseModel):
    """Credential-free connector configuration response."""

    model_config = ConfigDict(frozen=True)

    connector_type: str
    tool_name: str
    http_method: str
    endpoint_template: str
    endpoint_host: str
    field_mappings: dict[str, Any] = Field(default_factory=dict)
    idempotency_header_name: str
    response_parse: dict[str, Any] = Field(default_factory=dict)
    success_status_codes: list[int]
    status: str
    version: int
    configured_by: str
    source_approval_id: str
    content_sha256: str
    previous_version_sha256: str | None = None
    created_at: str
    updated_at: str

    @classmethod
    def from_record(
        cls,
        record: TenantConnectorConfigurationRecord,
    ) -> "TenantConnectorConfigurationResponse":
        return cls(
            connector_type=record.connector_type,
            tool_name=record.tool_name,
            http_method=record.http_method,
            endpoint_template=record.endpoint_template,
            endpoint_host=record.endpoint_host,
            field_mappings=dict(record.field_mappings),
            idempotency_header_name=record.idempotency_header_name,
            response_parse=dict(record.response_parse),
            success_status_codes=list(record.success_status_codes),
            status=record.status,
            version=record.version,
            configured_by=record.configured_by,
            source_approval_id=record.source_approval_id,
            content_sha256=record.content_sha256,
            previous_version_sha256=record.previous_version_sha256,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )


class TenantConnectorConfigurationPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantConnectorConfigurationResponse] = []
    total: int
    offset: int


class TenantKnowledgeCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    document_type: TenantKnowledgeDocumentType
    status: TenantKnowledgeDocumentStatus = TenantKnowledgeDocumentStatus.PENDING_INDEX


class TenantKnowledgeUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str | None = Field(default=None, min_length=1)
    status: TenantKnowledgeDocumentStatus | None = None
    review_status: TenantKnowledgeReviewStatus | None = None


class TenantKnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    title: str
    content: str
    document_type: TenantKnowledgeDocumentType
    status: TenantKnowledgeDocumentStatus
    review_status: TenantKnowledgeReviewStatus
    version: int
    uploaded_by: str
    vector_indexed_at: str | None = None
    created_at: str

    @classmethod
    def from_record(
        cls,
        record: TenantKnowledgeDocumentRecord,
    ) -> "TenantKnowledgeDocumentResponse":
        return cls(
            document_id=str(record.document_id),
            title=record.title,
            content=record.content,
            document_type=record.document_type,
            status=record.status,
            review_status=record.review_status,
            version=record.version,
            uploaded_by=record.uploaded_by,
            vector_indexed_at=(
                record.vector_indexed_at.isoformat()
                if record.vector_indexed_at is not None
                else None
            ),
            created_at=record.created_at.isoformat(),
        )


class TenantKnowledgeDocumentPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantKnowledgeDocumentResponse] = []
    total: int
    offset: int


class TenantGovernancePolicyCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_type: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: TenantGovernancePolicyStatus = TenantGovernancePolicyStatus.DRAFT
    effective_from: datetime


class TenantGovernancePolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    parameters: dict[str, Any] | None = None
    status: TenantGovernancePolicyStatus | None = None
    effective_from: datetime | None = None


class TenantGovernancePolicyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str
    policy_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: TenantGovernancePolicyStatus
    version: int
    approved_by: str
    effective_from: str
    created_at: str

    @classmethod
    def from_record(
        cls,
        record: TenantGovernancePolicyRecord,
    ) -> "TenantGovernancePolicyResponse":
        return cls(
            policy_id=str(record.policy_id),
            policy_type=record.policy_type,
            parameters=dict(record.parameters),
            status=record.status,
            version=record.version,
            approved_by=record.approved_by,
            effective_from=record.effective_from.isoformat(),
            created_at=record.created_at.isoformat(),
        )


class TenantGovernancePolicyPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantGovernancePolicyResponse] = []
    total: int
    offset: int


class TenantExecutionGovernanceCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    execution_quota: int = Field(ge=1)
    throughput_limit: int = Field(ge=1)
    throughput_window_minutes: int = Field(ge=1)
    governance_budget_limit: int = Field(ge=1)
    governance_budget_window_minutes: int = Field(ge=1)
    circuit_failure_threshold: int = Field(ge=1)
    circuit_window_minutes: int = Field(ge=1)
    circuit_cooldown_minutes: int = Field(ge=1)
    status: TenantExecutionGovernanceStatus = TenantExecutionGovernanceStatus.DRAFT
    metadata: dict[str, Any] = Field(default_factory=dict)


class TenantExecutionGovernanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    config_id: str
    status: TenantExecutionGovernanceStatus
    execution_quota: int
    throughput_limit: int
    throughput_window_minutes: int
    governance_budget_limit: int
    governance_budget_window_minutes: int
    circuit_failure_threshold: int
    circuit_window_minutes: int
    circuit_cooldown_minutes: int
    version: int
    configured_by: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str

    @classmethod
    def from_record(
        cls,
        record: TenantExecutionGovernanceConfigurationRecord,
    ) -> "TenantExecutionGovernanceResponse":
        return cls(
            config_id=str(record.config_id),
            status=record.status,
            execution_quota=record.execution_quota,
            throughput_limit=record.throughput_limit,
            throughput_window_minutes=record.throughput_window_minutes,
            governance_budget_limit=record.governance_budget_limit,
            governance_budget_window_minutes=(record.governance_budget_window_minutes),
            circuit_failure_threshold=record.circuit_failure_threshold,
            circuit_window_minutes=record.circuit_window_minutes,
            circuit_cooldown_minutes=record.circuit_cooldown_minutes,
            version=record.version,
            configured_by=record.configured_by,
            metadata=dict(record.metadata),
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )


class TenantExecutionGovernancePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantExecutionGovernanceResponse] = []
    total: int
    offset: int


class TenantExecutionCircuitBreakerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    breaker_id: str
    config_id: str
    state: TenantExecutionCircuitState
    failure_count: int
    opened_at: str | None = None
    open_until: str | None = None
    last_transition_at: str
    reason: str | None = None
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls,
        record: TenantExecutionCircuitBreakerRecord,
    ) -> "TenantExecutionCircuitBreakerResponse":
        return cls(
            breaker_id=str(record.breaker_id),
            config_id=str(record.config_id),
            state=record.state,
            failure_count=record.failure_count,
            opened_at=(
                record.opened_at.isoformat() if record.opened_at is not None else None
            ),
            open_until=(
                record.open_until.isoformat() if record.open_until is not None else None
            ),
            last_transition_at=record.last_transition_at.isoformat(),
            reason=record.reason,
            updated_at=record.updated_at.isoformat(),
            metadata=dict(record.metadata),
        )


class TenantExecutionCircuitBreakerPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantExecutionCircuitBreakerResponse] = []
    total: int
    offset: int


class TenantTopologyConfigurationCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    topology_name: str = Field(min_length=1)
    topology: dict[str, Any]
    status: TenantTopologyStatus = TenantTopologyStatus.DRAFT


class TenantTopologyConfigurationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    config_id: str
    topology_name: str
    topology: dict[str, Any]
    status: TenantTopologyStatus
    version: int
    configured_by: str
    created_at: str
    updated_at: str

    @classmethod
    def from_record(
        cls,
        record: TenantTopologyConfigurationRecord,
    ) -> "TenantTopologyConfigurationResponse":
        return cls(
            config_id=str(record.config_id),
            topology_name=record.topology_name,
            topology=dict(record.topology),
            status=record.status,
            version=record.version,
            configured_by=record.configured_by,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )


class TenantTopologyConfigurationPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantTopologyConfigurationResponse] = []
    total: int
    offset: int


class TenantConfigChangeRequestCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_type: TenantConfigChangeType
    payload: dict[str, Any]


class TenantConfigChangeRequestRejectRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str = Field(min_length=1)


class TenantConfigChangeRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_request_id: str
    tenant_id: str
    change_type: TenantConfigChangeType
    proposed_payload: dict[str, Any]
    status: TenantConfigChangeRequestStatus
    proposed_by: str
    proposed_at: str
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    applied_at: str | None = None
    applied_by: str | None = None       # principal who applied (#5)
    revoked_by: str | None = None       # principal who revoked (#22)
    revoked_at: str | None = None       # when revoked (#22)
    rejection_reason: str | None = None
    outcome_payload: dict[str, Any] | None = None

    @classmethod
    def from_record(
        cls,
        record: TenantConfigChangeRequestRecord,
    ) -> "TenantConfigChangeRequestResponse":
        return cls(
            change_request_id=str(record.change_request_id),
            tenant_id=record.tenant_id,
            change_type=record.change_type,
            proposed_payload=_redact_sensitive_payload(record.proposed_payload),
            status=record.status,
            proposed_by=record.proposed_by,
            proposed_at=record.proposed_at.isoformat(),
            approved_by=record.approved_by,
            approved_at=(
                None if record.approved_at is None else record.approved_at.isoformat()
            ),
            rejected_by=record.rejected_by,
            rejected_at=(
                None if record.rejected_at is None else record.rejected_at.isoformat()
            ),
            applied_at=(
                None if record.applied_at is None else record.applied_at.isoformat()
            ),
            applied_by=record.applied_by,
            revoked_by=record.revoked_by,
            revoked_at=(
                None if record.revoked_at is None else record.revoked_at.isoformat()
            ),
            rejection_reason=record.rejection_reason,
            outcome_payload=(
                None
                if record.outcome_payload is None
                else _redact_sensitive_payload(record.outcome_payload)
            ),
        )


class TenantConfigChangeRequestPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantConfigChangeRequestResponse] = []
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: LedgerPage,
    ) -> "TenantConfigChangeRequestPage":
        return cls(
            items=[
                TenantConfigChangeRequestResponse.from_record(record)
                for record in page.items
            ],
            total=page.total,
            offset=page.offset,
        )


__all__ = [
    "TenantConfigChangeRequestCreateRequest",
    "TenantConfigChangeRequestPage",
    "TenantConfigChangeRequestRejectRequest",
    "TenantConfigChangeRequestResponse",
    "TenantChannelConfigurationPage",
    "TenantChannelConfigurationResponse",
    "TenantChannelCreateRequest",
    "TenantChannelUpdateRequest",
    "TenantConnectorConfigurationPage",
    "TenantConnectorConfigurationResponse",
    "TenantExecutionCircuitBreakerPage",
    "TenantExecutionCircuitBreakerResponse",
    "TenantExecutionGovernanceCreateRequest",
    "TenantExecutionGovernancePage",
    "TenantExecutionGovernanceResponse",
    "TenantGovernancePolicyCreateRequest",
    "TenantGovernancePolicyPage",
    "TenantGovernancePolicyResponse",
    "TenantGovernancePolicyUpdateRequest",
    "TenantKnowledgeCreateRequest",
    "TenantKnowledgeDocumentPage",
    "TenantKnowledgeDocumentResponse",
    "TenantKnowledgeUpdateRequest",
    "TenantLifecycleCreateRequest",
    "TenantLifecyclePage",
    "TenantLifecycleResponse",
    "TenantTopologyConfigurationCreateRequest",
    "TenantTopologyConfigurationPage",
    "TenantTopologyConfigurationResponse",
]
