"""Supervisor substrate ORM rows.

Four tables mirroring the four apex persistable record shapes:

* ``supervisor_inspections``  — apex; one per ``inspect()`` call.
* ``supervisor_findings``     — N:1 with inspections.
* ``supervisor_evaluations``  — N:1 with inspections;
                                 ``(inspection_id, evaluator_name)``
                                 composite uniqueness (no own id).
* ``supervisor_escalations``  — N:1 with inspections.

Doctrine:
* Nullable tenant_id on apex; sub-records inherit scope from the
  parent via FK lookup.
* No partitioning.
* JSONB blobs for the embedded SupervisorDecisionRecord on the
  apex row, EvaluationEvidenceRecord on each finding, and every
  metadata bag.
* RESTRICT FKs from sub-records to apex.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_ENUM_WIDTH = 64
_HANDLE_WIDTH = 255


class SupervisorInspectionRow(Base):
    """Apex inspection row."""

    __tablename__ = "supervisor_inspections"

    inspection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    runtime_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    tenant_authority_source: Mapped[str | None] = mapped_column(
        String(_ENUM_WIDTH), nullable=True
    )
    inspection_mode: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    decision: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    decision_kind: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    evaluator_names: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )


class SupervisorFindingRow(Base):
    """Per-finding row. Parent inspection_id is a column (extracted
    from the in-memory record's metadata at write time)."""

    __tablename__ = "supervisor_findings"

    finding_id: Mapped[uuid.UUID] = mapped_column(
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
    evaluator_name: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False
    )
    category: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False
    )
    severity: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )


class SupervisorEvaluationRow(Base):
    """Per-evaluator output row. Composite PK
    ``(inspection_id, evaluator_name)`` mirrors the in-memory
    uniqueness contract."""

    __tablename__ = "supervisor_evaluations"

    inspection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "supervisor_inspections.inspection_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    evaluator_name: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    finding_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )


class SupervisorEscalationRow(Base):
    """Per-escalation row."""

    __tablename__ = "supervisor_escalations"

    escalation_id: Mapped[uuid.UUID] = mapped_column(
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
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    triggering_finding_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    __table_args__ = (
        UniqueConstraint(
            "inspection_id",
            "escalation_id",
            name="uq_supervisor_escalations_inspection_escalation",
        ),
    )


__all__ = [
    "SupervisorEscalationRow",
    "SupervisorEvaluationRow",
    "SupervisorFindingRow",
    "SupervisorInspectionRow",
]
