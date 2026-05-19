"""Session substrate ORM rows.

Three tables, one per persistable record shape in
``app/session/persistence/records.py``:

* ``operational_sessions``   — apex session records (revision-monotonic).
* ``session_events``         — append-only timeline events with
                               contiguous per-session sequence.
* ``session_correlations``   — cross-substrate correlation observations.

Doctrine notes
--------------

* **Nullable ``tenant_id``** — the ``SessionRecord`` contract
  declares ``tenant_id: str | None``. In practice every
  production-runtime session carries a tenant id resolved from
  ``AuthorityContext``, but the persistence layer does not assume
  that (the in-memory implementation accepts ``None`` too). The
  column is therefore ``nullable=True`` and the table does NOT
  inherit :class:`TenantScopedMixin`. Tenant-scoped reads use the
  inline ``WHERE tenant_id = $expected`` predicate which excludes
  ``NULL`` via SQL three-valued logic, so tenantless rows remain
  invisible to a scoped reader. Phase 5 may tighten the schema
  (``NOT NULL`` + partitioning) once the runtime contract forbids
  tenantless sessions.
* **No tenant partitioning (yet)** — partitioning by tenant requires
  a NOT NULL partition key. When the runtime contract tightens,
  PR-B3 can be followed by a migration that adds NOT NULL and
  recreates the table partitioned.
* **Append-only events** — uniqueness of ``event_id`` plus the
  per-session contiguous sequence invariant are enforced at
  application level (see :class:`PostgresSessionPersistence`).
  The composite ``UNIQUE (session_id, sequence)`` constraint on
  ``session_events`` is the database-level backstop against
  concurrent producers landing duplicate sequences.
* **RESTRICT FKs** — events and correlations reference the owning
  session with ``ON DELETE RESTRICT`` so an apex session can never
  be silently orphaned.
* **JSONB blobs** — tuple / mapping fields
  (``ancestor_session_ids``, ``context_labels``,
  ``context_attributes``, ``payload``, ``attributes``,
  ``metadata``) are stored as JSONB. Discrete columns hold every
  field the substrate filters on directly.
* **Attribute name collision** — ``metadata`` collides with
  SQLAlchemy's declarative base; the column is stored under SQL
  name ``metadata`` and exposed as ``metadata_json`` on the Python
  class, identical to the governance ORM pattern.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# ─── Column-shape constants ──────────────────────────────────────────────

_ENUM_WIDTH = 32
"""``SessionScope`` / ``SessionLifecyclePhase`` / event kinds are short."""

_HANDLE_WIDTH = 255
"""External handle / tenant id / principal id width."""


# ─── operational_sessions ────────────────────────────────────────────────


class SessionRow(Base):
    """ORM row for ``operational_sessions``.

    One row per ``SessionRecord``. Revision-monotonic at the
    substrate layer — :class:`PostgresSessionPersistence`
    increments-or-rejects on save.
    """

    __tablename__ = "operational_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False
    )
    external_handle: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    principal_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    lifecycle_phase: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    lifecycle_recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    lifecycle_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # Lineage scaffolding — see app/session/lineage/.
    lineage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    root_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    parent_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Ancestor list serialised as a JSONB array of UUID strings.
    # Stored as a JSONB rather than a dedicated relation because
    # ancestors are read-mostly and almost always traversed by
    # session_id (the relation would add a join with no payoff).
    ancestor_session_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    lineage_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_head: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    # Context fields — operational labels, attributes, notes.
    context_environment: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    context_labels: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    context_attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    context_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


# ─── session_events ──────────────────────────────────────────────────────


class SessionEventRow(Base):
    """ORM row for ``session_events``.

    Append-only. ``UNIQUE (session_id, sequence)`` is the database
    backstop against concurrent producers landing duplicate
    sequences; the substrate layer additionally enforces that
    sequences within a session are contiguous starting from 0.
    """

    __tablename__ = "session_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "operational_sessions.session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    continuity_mode: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    annotation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 2.5-G3 governance join axes.
    governance_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    governance_chain_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "sequence",
            name="uq_session_events_session_id_sequence",
        ),
    )


# ─── session_correlations ────────────────────────────────────────────────


class SessionCorrelationRow(Base):
    """ORM row for ``session_correlations``.

    Sub-record N:1 with ``operational_sessions``. Tenant scope
    inherits from the owning session (substrate refuses to
    duplicate ``tenant_id`` on this table — source of truth lives
    on the apex session row).
    """

    __tablename__ = "session_correlations"

    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "operational_sessions.session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    external_correlation_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    annotation: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


__all__ = [
    "SessionCorrelationRow",
    "SessionEventRow",
    "SessionRow",
]
