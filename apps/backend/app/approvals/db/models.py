"""Case approval queue ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_ENUM_WIDTH = 64
_PRINCIPAL_WIDTH = 255


class CaseApprovalRecordRow(Base):
    """Durable SME review + human approval queue row."""

    __tablename__ = "case_approval_records"

    approval_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operational_sessions.session_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    dispatch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    resolution_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolution_proposals.proposal_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    entry_category: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    ticket_ref: Mapped[str | None] = mapped_column(
        String(_PRINCIPAL_WIDTH), nullable=True, index=True
    )
    product: Mapped[str | None] = mapped_column(
        String(_PRINCIPAL_WIDTH), nullable=True
    )
    issue_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sme_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    recommended_action: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    guidance_round: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    guidance_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    governance_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_decisions.decision_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[str | None] = mapped_column(
        String(_PRINCIPAL_WIDTH), nullable=True, index=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_key: Mapped[str] = mapped_column(
        String(_PRINCIPAL_WIDTH), nullable=False
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
            "dedup_key",
            name="uq_case_approval_records_tenant_dedup",
        ),
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint("length(dedup_key) > 0", name="dedup_key_nonempty"),
        CheckConstraint(
            "entry_category IN ("
            "'resolution_require_approval', "
            "'resolution_needs_human_approval', "
            "'refund_warranty', "
            "'low_confidence', "
            "'coordination_human_review', "
            "'crisis_action')",
            name="case_approval_entry_category_valid",
        ),
        CheckConstraint(
            "status IN ("
            "'pending_sme_review', "
            "'awaiting_approval', "
            "'guidance_in_progress', "
            "'approved', "
            "'escalated', "
            "'failed')",
            name="case_approval_status_valid",
        ),
        CheckConstraint(
            "guidance_round IN (0, 1)",
            name="case_approval_guidance_round_valid",
        ),
        Index(
            "ix_case_approval_records_tenant_status_requested",
            "tenant_id",
            "status",
            "requested_at",
        ),
    )


class CaseApprovalOutboxRow(Base):
    """Durable publication state for approval queue notifications."""

    __tablename__ = "case_approval_outbox"

    outbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    approval_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("case_approval_records.approval_case_id", ondelete="CASCADE"),
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
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
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
            "approval_case_id",
            name="uq_case_approval_outbox_approval_case_id",
        ),
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'failed')",
            name="case_approval_outbox_status_valid",
        ),
        CheckConstraint(
            "republish_count >= 0",
            name="case_approval_outbox_republish_count_nonnegative",
        ),
        Index(
            "ix_case_approval_outbox_tenant_status",
            "tenant_id",
            "status",
        ),
    )


__all__ = ["CaseApprovalOutboxRow", "CaseApprovalRecordRow"]
