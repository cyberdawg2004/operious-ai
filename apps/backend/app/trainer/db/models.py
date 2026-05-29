"""Trainer substrate ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_STATUS_WIDTH = 32
_CATEGORY_WIDTH = 255


class TrainingRecommendationRow(Base):
    """Immutable recommendation content with mutable lifecycle status."""

    __tablename__ = "training_recommendations"

    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    qa_score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(
        String(_CATEGORY_WIDTH),
        nullable=False,
        index=True,
    )
    finding_summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(
        String(_STATUS_WIDTH),
        nullable=False,
        server_default=text("'medium'"),
    )
    status: Mapped[str] = mapped_column(
        String(_STATUS_WIDTH),
        nullable=False,
        server_default=text("'pending'"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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
        CheckConstraint("length(category) > 0", name="category_nonempty"),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="training_recommendation_priority_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'acknowledged', 'applied', 'dismissed')",
            name="training_recommendation_status_valid",
        ),
        Index(
            "ix_training_recs_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_training_recs_tenant_category_created",
            "tenant_id",
            "category",
            "created_at",
        ),
    )


__all__ = ["TrainingRecommendationRow"]
