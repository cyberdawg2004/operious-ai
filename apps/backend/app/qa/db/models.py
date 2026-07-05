"""QA substrate ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_ENUM_WIDTH = 64


class QAScoreRow(Base):
    """Durable QA score for one supervisor inspection."""

    __tablename__ = "qa_score_records"

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    inspection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "supervisor_inspections.inspection_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH), nullable=False, index=True
    )
    tenant_authority_source: Mapped[str | None] = mapped_column(
        String(_ENUM_WIDTH), nullable=True
    )
    diagnostic_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    policy_compliance: Mapped[float] = mapped_column(Float, nullable=False)
    timeline_integrity: Mapped[float] = mapped_column(Float, nullable=False)
    resolution_quality: Mapped[float] = mapped_column(Float, nullable=False)
    # MVP-6: semantic grounding score from SemanticQAAgent. 0.0 = not yet scored.
    semantic_grounding: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.0")
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    supervisor_decision_kind: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    escalation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
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
            "inspection_id",
            name="uq_qa_score_records_inspection_id",
        ),
        CheckConstraint(
            "length(tenant_id) > 0",
            name="tenant_id_nonempty",
        ),
        CheckConstraint(
            "diagnostic_accuracy >= 0 AND diagnostic_accuracy <= 1",
            name="diagnostic_accuracy_bounds",
        ),
        CheckConstraint(
            "policy_compliance >= 0 AND policy_compliance <= 1",
            name="policy_compliance_bounds",
        ),
        CheckConstraint(
            "timeline_integrity >= 0 AND timeline_integrity <= 1",
            name="timeline_integrity_bounds",
        ),
        CheckConstraint(
            "resolution_quality >= 0 AND resolution_quality <= 1",
            name="resolution_quality_bounds",
        ),
        CheckConstraint(
            "semantic_grounding >= 0 AND semantic_grounding <= 1",
            name="semantic_grounding_bounds",
        ),
        CheckConstraint(
            "overall_score >= 0 AND overall_score <= 1",
            name="overall_score_bounds",
        ),
    )


__all__ = ["QAScoreRow"]
