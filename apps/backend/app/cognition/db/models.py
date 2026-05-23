"""Cognition ORM models."""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_HANDLE_WIDTH = 255


class CognitionLLMUsageRow(Base):
    """ORM row for tenant-attributed model usage."""

    __tablename__ = "cognition_llm_usage_records"

    usage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    dispatch_id: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    session_id: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    provider: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    model: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_micro_usd: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False, index=True)
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
        CheckConstraint("length(execution_id) > 0", name="execution_id_nonempty"),
        CheckConstraint("length(dispatch_id) > 0", name="dispatch_id_nonempty"),
        CheckConstraint("length(session_id) > 0", name="session_id_nonempty"),
        CheckConstraint("length(provider) > 0", name="provider_nonempty"),
        CheckConstraint("length(model) > 0", name="model_nonempty"),
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_nonnegative"),
        CheckConstraint(
            "completion_tokens >= 0",
            name="completion_tokens_nonnegative",
        ),
        CheckConstraint("total_tokens >= 0", name="total_tokens_nonnegative"),
        CheckConstraint(
            "estimated_cost_micro_usd >= 0",
            name="estimated_cost_micro_usd_nonnegative",
        ),
        CheckConstraint(
            "status IN ('accepted', 'rejected', 'failed')",
            name="cognition_llm_usage_status_valid",
        ),
        Index(
            "ix_cognition_llm_usage_records_tenant_execution",
            "tenant_id",
            "execution_id",
        ),
        Index(
            "ix_cognition_llm_usage_records_tenant_model",
            "tenant_id",
            "provider",
            "model",
        ),
    )


class CognitionAuditRecordRow(Base):
    """Encrypted prompt/completion forensic snapshot row."""

    __tablename__ = "cognition_audit_records"

    audit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    usage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    prompt_full: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    completion_full: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    completion_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    model_name: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    token_usage: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("length(execution_id) > 0", name="execution_id_nonempty"),
        CheckConstraint("length(model_name) > 0", name="model_name_nonempty"),
        CheckConstraint("length(prompt_sha256) = 64", name="prompt_sha256_width"),
        CheckConstraint(
            "length(completion_sha256) = 64",
            name="completion_sha256_width",
        ),
        Index(
            "ix_cognition_audit_records_tenant_execution",
            "tenant_id",
            "execution_id",
        ),
    )


__all__ = ["CognitionAuditRecordRow", "CognitionLLMUsageRow"]
