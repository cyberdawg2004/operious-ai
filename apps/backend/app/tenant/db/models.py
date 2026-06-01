"""Tenant-owned configuration ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_ENUM_WIDTH = 64
_HANDLE_WIDTH = 255
_ROUTING_WIDTH = 1020


class TenantRow(Base):
    """Minimal tenant registry used as the FK anchor for owned config."""

    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
    )


class TenantChannelConfigurationRow(Base):
    """ORM row for ``tenant_channel_configurations``."""

    __tablename__ = "tenant_channel_configurations"

    config_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel_type: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False, index=True)
    routing_address: Mapped[str] = mapped_column(String(_ROUTING_WIDTH), nullable=False)
    credentials_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    webhook_secret: Mapped[str] = mapped_column(Text, nullable=False)
    previous_credentials_enc: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    previous_webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    credential_rotation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        UniqueConstraint(
            "tenant_id",
            "channel_type",
            name="uq_tenant_channel_configurations_tenant_channel",
        ),
        Index(
            "ix_tenant_channel_configurations_tenant_status",
            "tenant_id",
            "status",
        ),
    )


class TenantKnowledgeDocumentRow(Base):
    """ORM row for ``tenant_knowledge_documents``."""

    __tablename__ = "tenant_knowledge_documents"

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(_HANDLE_WIDTH * 2), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False, index=True)
    review_status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH),
        nullable=False,
        server_default=text("'quarantined'"),
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    vector_indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "review_status IN ('quarantined', 'approved', 'rejected')",
            name="knowledge_document_review_status_valid",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_type",
            "title",
            name="uq_tenant_knowledge_documents_tenant_type_title",
        ),
        Index(
            "ix_tenant_knowledge_documents_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_tenant_knowledge_documents_tenant_review_status",
            "tenant_id",
            "review_status",
        ),
    )


class TenantKnowledgeDocumentVersionRow(Base):
    """ORM row for ``tenant_knowledge_document_versions``."""

    __tablename__ = "tenant_knowledge_document_versions"

    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_knowledge_documents.document_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(_HANDLE_WIDTH * 2), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False, index=True)
    uploaded_by: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    source_approval_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_version_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "status IN ('active', 'archived', 'pending_index', 'indexing')",
            name="knowledge_document_version_status_valid",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "version",
            name="uq_tenant_knowledge_document_versions_tenant_doc_version",
        ),
        Index(
            "ix_tenant_knowledge_document_versions_tenant_document",
            "tenant_id",
            "document_id",
        ),
        Index(
            "ix_tenant_knowledge_document_versions_tenant_status",
            "tenant_id",
            "status",
        ),
    )


class TenantGovernancePolicyRow(Base):
    """ORM row for ``tenant_governance_policies``."""

    __tablename__ = "tenant_governance_policies"

    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    policy_type: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_approval_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_version_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint(
            "tenant_id",
            "policy_type",
            "version",
            name="uq_tenant_governance_policies_tenant_type_version",
        ),
        Index(
            "ix_tenant_governance_policies_tenant_status",
            "tenant_id",
            "status",
        ),
    )


class TenantExecutionGovernanceConfigurationRow(Base):
    """ORM row for execution governance configuration versions."""

    __tablename__ = "tenant_execution_governance_configurations"

    config_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False, index=True)
    execution_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    throughput_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    throughput_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_budget_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_budget_window_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    circuit_failure_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    circuit_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    circuit_cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    configured_by: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    source_approval_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_version_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="exec_gov_tenant_id_nonempty"),
        CheckConstraint("version >= 1", name="exec_gov_version_positive"),
        UniqueConstraint(
            "tenant_id",
            "version",
            name="uq_tenant_execution_governance_configurations_tenant_version",
        ),
        Index(
            "ix_tenant_execution_governance_configurations_tenant_status",
            "tenant_id",
            "status",
        ),
    )


class TenantExecutionCircuitBreakerRow(Base):
    """ORM row for tenant execution circuit breaker state."""

    __tablename__ = "tenant_execution_circuit_breakers"

    breaker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tenant_execution_governance_configurations.config_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    state: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False, index=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    open_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_transition_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "config_id",
            name="uq_tenant_execution_circuit_breakers_tenant_config",
        ),
    )


class TenantTopologyConfigurationRow(Base):
    """ORM row for ``tenant_topology_configurations``."""

    __tablename__ = "tenant_topology_configurations"

    config_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    topology_name: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False, index=True)
    topology: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    configured_by: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint(
            "tenant_id",
            "topology_name",
            name="uq_tenant_topology_configurations_tenant_name",
        ),
        Index(
            "ix_tenant_topology_configurations_tenant_status",
            "tenant_id",
            "status",
        ),
    )


class TenantConfigChangeRequestRow(Base):
    """Durable dual-control ledger row for tenant config changes."""

    __tablename__ = "tenant_config_change_requests"

    change_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    change_type: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    proposed_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH),
        nullable=False,
        server_default=text("'PROPOSED'"),
        index=True,
    )
    proposed_by: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_by: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_by: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    revoked_by: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "change_type IN ("
            "'knowledge', 'policy', 'execution_governance', "
            "'topology', 'channel'"
            ")",
            name="change_type_valid",
        ),
        CheckConstraint(
            "status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'APPLIED', 'REVOKED')",
            name="status_valid",
        ),
        CheckConstraint(
            "approved_by IS NULL OR approved_by != proposed_by",
            name="approver_distinct",
        ),
        CheckConstraint(
            "status != 'APPLIED' OR applied_by IS NOT NULL",
            name="chk_applied_by_when_applied",
        ),
        CheckConstraint(
            "status != 'REVOKED' OR revoked_by IS NOT NULL",
            name="chk_revoked_by_when_revoked",
        ),
        Index(
            "ix_tenant_config_change_requests_tenant_status",
            "tenant_id",
            "status",
        ),
    )


__all__ = [
    "TenantChannelConfigurationRow",
    "TenantConfigChangeRequestRow",
    "TenantExecutionCircuitBreakerRow",
    "TenantExecutionGovernanceConfigurationRow",
    "TenantGovernancePolicyRow",
    "TenantKnowledgeDocumentRow",
    "TenantKnowledgeDocumentVersionRow",
    "TenantRow",
    "TenantTopologyConfigurationRow",
]
