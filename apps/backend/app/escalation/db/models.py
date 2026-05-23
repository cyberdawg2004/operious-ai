"""Escalation substrate ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Boolean,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_ENUM_WIDTH = 32
_PRINCIPAL_WIDTH = 255


class EscalationRecordRow(Base):
    """Durable human approval queue record."""

    __tablename__ = "escalation_records"

    escalation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "operational_sessions.session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    governance_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "governance_decisions.decision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(
        String(_PRINCIPAL_WIDTH), nullable=True, index=True
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
            "governance_decision_id",
            name="uq_escalation_records_governance_decision_id",
        ),
        CheckConstraint(
            "length(tenant_id) > 0",
            name="tenant_id_nonempty",
        ),
        CheckConstraint(
            "status IN ('pending', 'reviewed', 'approved', 'rejected')",
            name="status_valid",
        ),
    )


class EscalationOutboxRow(Base):
    """Durable escalation publication state."""

    __tablename__ = "escalation_outbox"

    outbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    escalation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("escalation_records.escalation_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    publisher_id: Mapped[str | None] = mapped_column(
        String(_PRINCIPAL_WIDTH), nullable=True, index=True
    )
    republish_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dead_letter: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        UniqueConstraint(
            "escalation_id",
            name="uq_escalation_outbox_escalation_id",
        ),
        CheckConstraint(
            "length(tenant_id) > 0",
            name="tenant_id_nonempty",
        ),
        CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'failed')",
            name="status_valid",
        ),
        CheckConstraint(
            "republish_count >= 0",
            name="republish_count_nonnegative",
        ),
        Index(
            "ix_escalation_outbox_tenant_status",
            "tenant_id",
            "status",
        ),
    )


__all__ = ["EscalationOutboxRow", "EscalationRecordRow"]
