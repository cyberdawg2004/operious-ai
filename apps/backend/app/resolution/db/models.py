"""Resolution proposal ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
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
        String(TENANT_ID_MAX_LENGTH), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
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
    )


__all__ = ["ResolutionProposalRow"]
