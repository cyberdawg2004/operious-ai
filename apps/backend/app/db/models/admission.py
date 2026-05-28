"""Operational admission-control ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdmissionRecordRow(Base):
    """Persisted admission decision requiring operational visibility.

    This is an operational capacity log with no tenant-facing read API in
    PR_T3, but it still carries tenant context and is protected by RLS.
    """

    __tablename__ = "admission_records"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queue_name: Mapped[str] = mapped_column(String(128), nullable=False)
    queue_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_age_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    redis_memory_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    db_pool_wait_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    retry_after_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
    )
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queue_depth_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    queue_age_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    redis_memory_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    telemetry_unavailable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    unavailable_reasons: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_admission_records_tenant_evaluated", "tenant_id", "evaluated_at"),
        Index("ix_admission_records_outcome", "outcome"),
    )


__all__ = ["AdmissionRecordRow"]
