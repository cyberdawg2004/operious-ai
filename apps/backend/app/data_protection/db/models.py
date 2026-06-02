"""Data protection ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime

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
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_SCOPE_WIDTH = 32
_HANDLE_WIDTH = 255


class DataProtectionDataKeyRow(Base):
    """Stored random data key encrypted by a versioned master key."""

    __tablename__ = "data_protection_data_keys"

    data_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope: Mapped[str] = mapped_column(String(_SCOPE_WIDTH), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    master_key_version: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    rewrapped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="data_key_tenant_nonempty"),
        CheckConstraint("scope IN ('tenant', 'subject')", name="data_key_scope_valid"),
        CheckConstraint("length(scope_id) > 0", name="data_key_scope_id_nonempty"),
        UniqueConstraint(
            "tenant_id",
            "scope",
            "scope_id",
            name="uq_data_protection_data_keys_scope",
        ),
        Index(
            "ix_data_protection_data_keys_tenant_scope",
            "tenant_id",
            "scope",
            "scope_id",
        ),
    )


class TenantDataRetentionPolicyRow(Base):
    """Per-tenant retention override for protected customer content."""

    __tablename__ = "tenant_data_retention_policies"

    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        primary_key=True,
    )
    retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("90")
    )
    updated_by: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="retention_tenant_nonempty"),
        CheckConstraint("retention_days >= 1", name="retention_days_positive"),
    )


class DataProtectionLegalHoldRow(Base):
    """Tenant, subject, or session-scoped legal hold."""

    __tablename__ = "data_protection_legal_holds"

    hold_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scope: Mapped[str] = mapped_column(String(_SCOPE_WIDTH), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lifted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifted_by: Mapped[str | None] = mapped_column(String(_HANDLE_WIDTH), nullable=True)

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="legal_hold_tenant_nonempty"),
        CheckConstraint(
            "scope IN ('tenant', 'subject', 'session')",
            name="legal_hold_scope_valid",
        ),
        CheckConstraint("length(scope_id) > 0", name="legal_hold_scope_id_nonempty"),
        Index(
            "ix_data_protection_legal_holds_active_scope",
            "tenant_id",
            "scope",
            "scope_id",
            postgresql_where=text("lifted_at IS NULL"),
        ),
    )


class DataProtectionErasureRequestRow(Base):
    """Durable DSAR/erasure request ledger."""

    __tablename__ = "data_protection_erasure_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    status: Mapped[str] = mapped_column(String(_SCOPE_WIDTH), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_by: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_by: Mapped[str | None] = mapped_column(String(_HANDLE_WIDTH), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="erasure_tenant_nonempty"),
        CheckConstraint("length(subject_id) > 0", name="erasure_subject_nonempty"),
        CheckConstraint("length(reason) > 0", name="erasure_reason_nonempty"),
        CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected', 'executed')",
            name="erasure_status_valid",
        ),
        CheckConstraint(
            "approved_by IS NULL OR approved_by != proposed_by",
            name="erasure_approver_distinct",
        ),
        Index(
            "ix_data_protection_erasure_requests_subject",
            "tenant_id",
            "subject_id",
            "proposed_at",
        ),
    )


__all__ = [
    "DataProtectionDataKeyRow",
    "DataProtectionErasureRequestRow",
    "DataProtectionLegalHoldRow",
    "TenantDataRetentionPolicyRow",
]
