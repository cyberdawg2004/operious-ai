"""Resolution proposal ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_ENUM_WIDTH = 64


class ResolutionProposalRow(Base):
    """ORM row for ``resolution_proposals``."""

    __tablename__ = "resolution_proposals"

    proposal_id: Mapped[uuid.UUID] = mapped_column(
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
        ForeignKey("operational_sessions.session_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_records.execution_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dispatch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    diagnostic_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    proposed_customer_reply: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    source_language: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH),
        nullable=False,
        default="en",
        server_default=text("'en'"),
    )
    resolution_category: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    supervisor_verdict: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    governance_verdict: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    governance_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("governance_decisions.decision_id", ondelete="SET NULL"),
        nullable=True,
    )
    autonomy_decision: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
        CheckConstraint(
            "length(proposed_customer_reply) > 0",
            name="resolution_proposal_reply_nonempty",
        ),
        CheckConstraint(
            "length(resolution_category) > 0",
            name="resolution_proposal_category_nonempty",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="resolution_proposal_confidence_bounds",
        ),
        CheckConstraint(
            "autonomy_decision IN "
            "('auto_approved', 'needs_customer_info', "
            "'needs_human_approval', 'denied')",
            name="resolution_proposal_autonomy_decision_valid",
        ),
        CheckConstraint(
            "status IN "
            "('proposed', 'auto_approved', 'send_eligible', "
            "'pending_human_approval', 'denied', 'failed')",
            name="resolution_proposal_status_valid",
        ),
        CheckConstraint(
            "supervisor_verdict IN "
            "('pass', 'needs_human_review', 'fail')",
            name="resolution_proposal_supervisor_verdict_valid",
        ),
        CheckConstraint(
            "governance_verdict IN "
            "('allow', 'require_approval', 'escalate', 'deny', "
            "'degrade', 'redact')",
            name="resolution_proposal_governance_verdict_valid",
        ),
        Index(
            "ix_resolution_proposals_tenant_session",
            "tenant_id",
            "session_id",
        ),
        Index(
            "ix_resolution_proposals_tenant_execution",
            "tenant_id",
            "execution_id",
        ),
        Index(
            "ix_resolution_proposals_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_resolution_proposals_tenant_created_at",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_resolution_proposals_tenant_governance_decision",
            "tenant_id",
            "governance_decision_id",
        ),
    )


class ResolutionOutboundDraftRow(Base):
    """ORM row for ``resolution_outbound_drafts``."""

    __tablename__ = "resolution_outbound_drafts"

    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    execution_id: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    dispatch_id: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    diagnostic_event_id: Mapped[str | None] = mapped_column(
        String(_ENUM_WIDTH), nullable=True, index=True
    )
    governance_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    draft_body: Mapped[str] = mapped_column(Text, nullable=False)
    draft_body_sha256: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    resolution_category: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(tenant_id) > 0", name="draft_tenant_id_nonempty"),
        CheckConstraint(
            "length(session_id) > 0",
            name="resolution_outbound_draft_session_id_nonempty",
        ),
        CheckConstraint(
            "length(execution_id) > 0",
            name="resolution_outbound_draft_execution_id_nonempty",
        ),
        CheckConstraint(
            "length(dispatch_id) > 0",
            name="resolution_outbound_draft_dispatch_id_nonempty",
        ),
        CheckConstraint(
            "status IN "
            "('ready', 'pending_human_approval', 'denied', 'failed')",
            name="resolution_outbound_draft_status_valid",
        ),
        CheckConstraint(
            "length(draft_body) > 0",
            name="resolution_outbound_draft_body_nonempty",
        ),
        CheckConstraint(
            "length(draft_body_sha256) = 64",
            name="resolution_outbound_draft_body_sha256_valid",
        ),
        CheckConstraint(
            "length(resolution_category) > 0",
            name="resolution_outbound_draft_category_nonempty",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="resolution_outbound_draft_confidence_bounds",
        ),
        Index(
            "ix_resolution_outbound_drafts_tenant_proposal",
            "tenant_id",
            "proposal_id",
        ),
        Index(
            "ix_resolution_outbound_drafts_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_resolution_outbound_drafts_tenant_created_at",
            "tenant_id",
            "created_at",
        ),
    )


__all__ = ["ResolutionOutboundDraftRow", "ResolutionProposalRow"]
