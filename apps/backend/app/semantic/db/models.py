"""ORM models for semantic infrastructure."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SemanticCircuitEventRow(Base):
    """Append-only audit event for semantic circuit state changes."""

    __tablename__ = "semantic_circuit_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    cluster_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    similarity_threshold: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    __table_args__ = (
        Index(
            "ix_semantic_circuit_events_tenant_channel",
            "tenant_id",
            "channel",
            "occurred_at",
        ),
    )


__all__ = ["SemanticCircuitEventRow"]
