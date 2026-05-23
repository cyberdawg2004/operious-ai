"""Runtime ORM rows."""

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
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_HANDLE_WIDTH = 255
_STATE_WIDTH = 32


class ProviderCircuitStateRow(Base):
    """Per-tenant/provider circuit-breaker state."""

    __tablename__ = "provider_circuit_states"

    state_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_name: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(_STATE_WIDTH), nullable=False, index=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    open_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    half_open_trial_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_reason: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    last_transition_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
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
        CheckConstraint("length(provider_name) > 0", name="provider_name_nonempty"),
        CheckConstraint(
            "state IN ('closed', 'open', 'half_open')",
            name="provider_circuit_state_valid",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="consecutive_failures_nonnegative",
        ),
        CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"),
        UniqueConstraint(
            "tenant_id",
            "provider_name",
            name="uq_provider_circuit_states_tenant_provider",
        ),
        Index(
            "ix_provider_circuit_states_tenant_state",
            "tenant_id",
            "state",
        ),
    )


class DeadLetterTaskRow(Base):
    """Durable record for worker tasks that exhausted their retry budget."""

    __tablename__ = "dead_letter_tasks"

    dead_letter_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    task_name: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "execution_records.execution_id",
            name="fk_dead_letter_tasks_execution_id_execution_records",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
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
        CheckConstraint("length(task_name) > 0", name="task_name_nonempty"),
        CheckConstraint("length(task_id) > 0", name="task_id_nonempty"),
        CheckConstraint("length(reason) > 0", name="reason_nonempty"),
        CheckConstraint("retry_count >= 0", name="dead_letter_retry_nonnegative"),
        UniqueConstraint(
            "task_name",
            "task_id",
            name="uq_dead_letter_tasks_task_name_task_id",
        ),
        Index(
            "ix_dead_letter_tasks_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )


__all__ = ["DeadLetterTaskRow", "ProviderCircuitStateRow"]
