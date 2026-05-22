"""Transport contracts for tenant-owned configuration endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.persistence import (
    TenantChannelConfigurationRecord,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
)


class TenantChannelCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel_type: TenantChannelType
    routing_address: str = Field(min_length=1)
    credentials: dict[str, Any]
    webhook_secret: str = Field(min_length=1)
    status: TenantChannelStatus = TenantChannelStatus.PENDING_VERIFICATION


class TenantChannelUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    routing_address: str | None = Field(default=None, min_length=1)
    credentials: dict[str, Any] | None = None
    webhook_secret: str | None = Field(default=None, min_length=1)
    status: TenantChannelStatus | None = None


class TenantChannelConfigurationResponse(BaseModel):
    """Credential-redacted channel response."""

    model_config = ConfigDict(frozen=True)

    config_id: str
    channel_type: TenantChannelType
    routing_address: str
    status: TenantChannelStatus
    verified_at: str | None = None

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
        )


class TenantChannelConfigurationPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TenantChannelConfigurationResponse] = Field(
        default_factory=list
    )
    total: int
    offset: int


class TenantKnowledgeCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    document_type: TenantKnowledgeDocumentType
    status: TenantKnowledgeDocumentStatus = (
        TenantKnowledgeDocumentStatus.PENDING_INDEX
    )


class TenantKnowledgeUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str | None = Field(default=None, min_length=1)
    status: TenantKnowledgeDocumentStatus | None = None


class TenantKnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    title: str
    content: str
    document_type: TenantKnowledgeDocumentType
    status: TenantKnowledgeDocumentStatus
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

    items: list[TenantKnowledgeDocumentResponse] = Field(
        default_factory=list
    )
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

    items: list[TenantGovernancePolicyResponse] = Field(
        default_factory=list
    )
    total: int
    offset: int


__all__ = [
    "TenantChannelConfigurationPage",
    "TenantChannelConfigurationResponse",
    "TenantChannelCreateRequest",
    "TenantChannelUpdateRequest",
    "TenantGovernancePolicyCreateRequest",
    "TenantGovernancePolicyPage",
    "TenantGovernancePolicyResponse",
    "TenantGovernancePolicyUpdateRequest",
    "TenantKnowledgeCreateRequest",
    "TenantKnowledgeDocumentPage",
    "TenantKnowledgeDocumentResponse",
    "TenantKnowledgeUpdateRequest",
]
