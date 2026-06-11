"""Governance substrate ORM rows.

Three tables, one per apex persistable record shape in
``app/governance/persistence/records.py``:

* ``governance_decisions``         — apex decision verdicts.
* ``governance_traces``            — apex per-evaluation traces.
* ``governance_enforcement_actions``— per-handler execution records.

Doctrine notes
--------------

* **Nullable ``tenant_id``** — governance is one of the substrates
  that legitimately hosts tenantless rows (system-level decisions,
  health-driven self-checks, admin operations). The column is
  therefore ``nullable=True`` and the table does NOT inherit
  :class:`TenantScopedMixin`. Tenant-scoped reads use the canonical
  ``TenantScopedRepository._clamp_tenant`` helper — the
  ``WHERE tenant_id = $expected`` predicate it emits correctly
  excludes ``NULL`` via SQL three-valued logic so tenantless rows
  remain invisible to a scoped reader.
* **No tenant partitioning** — partitioning by tenant requires a
  ``NOT NULL`` partition key. Governance is also read-rare relative
  to session-event ingest, so the partitioning win would be small.
  The table stays single-physical until evidence proves otherwise.
* **JSONB columns** — ``violations``, ``restrictions``,
  ``evaluated_rules``, ``policy_traces``, and ``metadata`` are stored
  as JSONB so the record's nested structure round-trips losslessly
  through the existing ``to_dict`` / ``from_dict`` machinery without
  a side normalisation table. The Postgres JSONB type is mapped to
  ``JSON`` for SQLite via the compile shim in ``tests/conftest.py``.
* **Attribute names** — SQLAlchemy reserves ``metadata`` on
  declarative classes; the column is stored under the SQL name
  ``metadata`` but exposed on the Python class as ``metadata_json``
  to avoid the collision.
* **Decision-id is a string UUID at the substrate boundary** — the
  records carry ``decision_id: str`` so JSON round-trips are
  transparent. Storage uses the native Postgres ``UUID`` type for
  index compactness; serialisation back to the record converts to
  ``str`` at the boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# ─── Column-shape constants ──────────────────────────────────────────────

_DECISION_ENUM_WIDTH = 32
"""``Decision`` / ``EnforcementStage`` / ``status`` are short string enums."""

_CHAIN_ID_WIDTH = 255
"""``policy_chain_id`` is operator-supplied; bound is generous."""

_GOVERNANCE_VERSION_WIDTH = 128
"""``governance_version`` is operator-supplied build identifier."""

_HANDLER_NAME_WIDTH = 255
"""Enforcement handler name (operator-defined)."""


# ─── governance_decisions ─────────────────────────────────────────────────


class CrisisDeploymentRow(Base):
    """ORM row for Redis-backed crisis deployments."""

    __tablename__ = "crisis_deployments"

    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(_CHAIN_ID_WIDTH),
        nullable=False,
        index=True,
    )
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    ttl_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    deployed_by: Mapped[str] = mapped_column(String(_CHAIN_ID_WIDTH), nullable=False)
    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default=text("'active'"),
        index=True,
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
            "ix_crisis_deployments_tenant_status",
            "tenant_id",
            "status",
        ),
    )


class CrisisEventRow(Base):
    """Append-only audit event for crisis deployment lifecycle changes."""

    __tablename__ = "crisis_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(_CHAIN_ID_WIDTH),
        nullable=False,
        index=True,
    )
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "crisis_deployments.deployment_id",
            name="fk_crisis_events_deployment_id_crisis_deployments",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    ttl_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    actor: Mapped[str] = mapped_column(String(_CHAIN_ID_WIDTH), nullable=False)
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
            "ix_crisis_events_tenant_occurred",
            "tenant_id",
            "occurred_at",
        ),
        Index(
            "ix_crisis_events_deployment",
            "deployment_id",
        ),
    )


class GovernanceDecisionRow(Base):
    """ORM row for ``governance_decisions``.

    One row per ``GovernanceDecisionRecord``. The ``decision_id``
    PRIMARY KEY is the substrate's apex join axis — every trace
    and every enforcement-action row references it. Write-once at
    the substrate layer (enforced by
    :class:`PostgresGovernanceRepository`).
    """

    __tablename__ = "governance_decisions"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    decision: Mapped[str] = mapped_column(
        String(_DECISION_ENUM_WIDTH), nullable=False
    )
    stage: Mapped[str] = mapped_column(
        String(_DECISION_ENUM_WIDTH), nullable=False
    )
    policy_chain_id: Mapped[str] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=True, index=True
    )
    # Nullable by doctrine: governance MAY persist tenantless
    # (system-level) decisions. See module docstring.
    tenant_id: Mapped[str] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=False, index=True
    )
    subject_kind: Mapped[str] = mapped_column(
        String(_DECISION_ENUM_WIDTH),
        nullable=False,
        default="generic",
        server_default=text("'generic'"),
    )
    governance_version: Mapped[str] = mapped_column(
        String(_GOVERNANCE_VERSION_WIDTH),
        nullable=False,
        default="unversioned",
        server_default=text("'unversioned'"),
    )
    # JSONB blobs preserve the nested record shape losslessly so the
    # repository can rehydrate the record without a side table per
    # nested struct. The lists carry already-serialised dicts (see
    # PostgresGovernanceRepository.record_decision).
    violations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    restrictions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    evaluated_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    # SQLAlchemy reserves ``metadata`` on the declarative class;
    # store under SQL name "metadata" but expose as ``metadata_json``
    # on the Python attribute.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    __table_args__ = (
        # Common audit lookup pattern: "every decision for this
        # tenant in this time range" (e.g. compliance reports).
        Index(
            "ix_governance_decisions_tenant_id_decided_at",
            "tenant_id",
            "decided_at",
        ),
    )


# ─── governance_traces ────────────────────────────────────────────────────


class GovernanceTraceRow(Base):
    """ORM row for ``governance_traces``.

    One row per ``GovernanceTraceRecord``, joined 1:1 with the
    apex ``GovernanceDecisionRow`` on ``decision_id`` (which is
    therefore both the primary key and the foreign key).

    Latency / status fields are stored as discrete columns so
    operational-metric queries don't have to crack open JSONB.
    Per-policy invocation traces live in the ``policy_traces``
    JSONB blob — they are forensic-only and the substrate never
    aggregates over them at the DB layer.
    """

    __tablename__ = "governance_traces"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "governance_decisions.decision_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=True, index=True
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=True, index=True
    )
    stage: Mapped[str] = mapped_column(
        String(_DECISION_ENUM_WIDTH), nullable=False
    )
    action: Mapped[str] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=False
    )
    resource: Mapped[str] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=False
    )
    actor: Mapped[str] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=False, index=True
    )
    subject_kind: Mapped[str] = mapped_column(
        String(_DECISION_ENUM_WIDTH),
        nullable=False,
        default="generic",
        server_default=text("'generic'"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    latency_ms: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(_DECISION_ENUM_WIDTH), nullable=False
    )
    final_decision: Mapped[str] = mapped_column(
        String(_DECISION_ENUM_WIDTH), nullable=False
    )
    policy_chain_id: Mapped[str] = mapped_column(
        String(_CHAIN_ID_WIDTH), nullable=False
    )
    rule_count: Mapped[int] = mapped_column(nullable=False)
    violation_count: Mapped[int] = mapped_column(nullable=False)
    restriction_count: Mapped[int] = mapped_column(nullable=False)
    enforcement_handler: Mapped[str | None] = mapped_column(
        String(_HANDLER_NAME_WIDTH), nullable=True
    )
    enforcement_status: Mapped[str | None] = mapped_column(
        String(_DECISION_ENUM_WIDTH), nullable=True
    )
    enforcement_latency_ms: Mapped[float | None] = mapped_column(
        nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_traces: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )


# ─── governance_enforcement_actions ──────────────────────────────────────


class EnforcementActionRow(Base):
    """ORM row for ``governance_enforcement_actions``.

    N:1 with ``governance_decisions`` on ``decision_id`` — one
    decision may produce zero, one, or many enforcement-action
    records (different handlers, retries, etc.). Tenant scope
    inherits from the owning decision (the substrate refuses to
    duplicate ``tenant_id`` on this table — the source of truth is
    the parent decision row).
    """

    __tablename__ = "governance_enforcement_actions"

    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "governance_decisions.decision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    handler_name: Mapped[str] = mapped_column(
        String(_HANDLER_NAME_WIDTH), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(
        String(_DECISION_ENUM_WIDTH), nullable=False
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    detail: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )


__all__ = [
    "EnforcementActionRow",
    "GovernanceDecisionRow",
    "GovernanceTraceRow",
]
