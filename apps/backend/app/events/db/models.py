"""Operational event fabric ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_ENUM_WIDTH = 96
_HANDLE_WIDTH = 255


class OperationalEventRow(Base):
    """Durable append-only row for one canonical operational event."""

    __tablename__ = "operational_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    operational_act: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    substrate: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )

    root_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    parent_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    causality_depth: Mapped[int] = mapped_column(Integer, nullable=False)

    runtime_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    tenant_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    principal_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    environment_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    tenant_authority_source: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )

    governance_decision: Mapped[str | None] = mapped_column(
        String(_ENUM_WIDTH), nullable=True
    )
    governance_decision_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
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
            "runtime_instance_id",
            "sequence",
            name="uq_operational_events_runtime_sequence",
        ),
    )


__all__ = ["OperationalEventRow"]
