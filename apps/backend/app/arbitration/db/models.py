"""Arbitration substrate ORM rows.

Single table ``arbitration_evaluations`` — one row per apex
:class:`ArbitrationRecord`. Nested ``findings``, ``conflicts``,
``deadlock_witnesses`` live as JSONB arrays on the same row
(the in-memory backend stores the whole nested structure
together; the Postgres backend mirrors that contract).

Doctrine
--------
* **Nullable tenant_id** — arbitration MAY persist tenantless
  evaluations (system-level arbitration over cross-tenant
  signals). The table does NOT use TenantScopedMixin; the
  Postgres repo inlines ``WHERE tenant_id = $expected``.
* **No tenant partitioning** — arbitration is low-volume.
* **Composite ordering index** ``(runtime_instance_id, sequence)``
  matches the Protocol's canonical ordering contract.
* **JSONB blobs** for findings / conflicts / deadlock_witnesses /
  evaluator_names / metadata. The nested structure round-trips
  losslessly because every nested record is itself a frozen
  dataclass with deterministic to_dict-style serialisation
  performed in ``PostgresArbitrationPersistence``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_ENUM_WIDTH = 64
_HANDLE_WIDTH = 255


class ArbitrationEvaluationRow(Base):
    """ORM row for ``arbitration_evaluations``."""

    __tablename__ = "arbitration_evaluations"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    chain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    runtime_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    prevailing_authority_level: Mapped[str | None] = mapped_column(
        String(_ENUM_WIDTH), nullable=True
    )
    prevailing_authority_source_substrate: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    prevailing_authority_source_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    prevailing_authority_verdict: Mapped[str | None] = mapped_column(
        String(_ENUM_WIDTH), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evaluator_names: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    findings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    conflicts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    deadlock_witnesses: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    iteration_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    max_iterations: Mapped[int] = mapped_column(
        Integer, nullable=False
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
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    governance_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    governance_chain_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
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
            "ix_arbitration_evaluations_runtime_seq",
            "runtime_instance_id",
            "sequence",
        ),
    )


__all__ = ["ArbitrationEvaluationRow"]
