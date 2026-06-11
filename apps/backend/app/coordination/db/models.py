"""Coordination substrate ORM rows.

One table — ``coordination_envelopes`` — mirroring the single
:class:`CoordinationRecord` apex shape. Every supplementary fact
(sender, sequence, lineage, governance link, payload) lives as a
column on the same row; the substrate's contract is "one envelope =
one record".

Doctrine notes
--------------
* **Nullable ``tenant_id``** — the record contract accepts
  ``tenant_id: str | None`` (system-level / broadcast envelopes
  may be tenantless). The table therefore does NOT use
  :class:`TenantScopedMixin`; tenant clamping is inlined in
  :class:`PostgresCoordinationPersistence` via the same
  ``WHERE tenant_id = $expected`` predicate used by the governance
  and session backends (NULL excluded via SQL three-valued logic).
* **No partitioning yet** — coordination is medium-volume relative
  to session events; Phase 5 may add ``NOT NULL`` + tenant
  partitioning if profiling warrants it.
* **Composite secondary index** on
  ``(runtime_instance_id, sequence)`` — the substrate's canonical
  global ordering. Every query result MUST be sorted by this
  composite, and the index lets Postgres satisfy that without a
  filesort.
* **JSONB blobs** for ``payload_body``, ``recipient_metadata``,
  ``payload_metadata``, ``message_metadata``, ``envelope_metadata``.
* **No FKs to other substrates** — ``governance_decision_id`` and
  ``governance_chain_id`` are join handles; coordination never
  cascades against the governance tables (replay tools assemble
  decisions by id without a relational chain).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_ENUM_WIDTH = 32
_HANDLE_WIDTH = 255


class CoordinationEnvelopeRow(Base):
    """ORM row for ``coordination_envelopes`` — write-once.

    The substrate raises :class:`CoordinationPersistenceError` on
    duplicate ``coordination_id``; Postgres raises a generic PK
    violation. :class:`PostgresCoordinationPersistence` converts
    the underlying ``IntegrityError`` so callers see a uniform
    exception type regardless of backend.
    """

    __tablename__ = "coordination_envelopes"

    coordination_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    sender_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    recipient_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    recipient_kind: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False
    )
    direction: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    message_type: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    runtime_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    parent_coordination_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    in_reply_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
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
    governance_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    governance_chain_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    payload_content_type: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False
    )
    payload_schema_version: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH),
        nullable=False,
        default="1",
        server_default=text("'1'"),
    )
    payload_body: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recipient_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    payload_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    message_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    # All four metadata bags use distinct attribute names so the
    # SQLAlchemy reserved-``metadata`` collision doesn't apply.
    envelope_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )

    __table_args__ = (
        # Canonical global ordering composite — every query result
        # MUST be sorted by this pair, so the supporting index is
        # critical for query latency.
        Index(
            "ix_coordination_envelopes_runtime_seq",
            "runtime_instance_id",
            "sequence",
        ),
    )


__all__ = ["CoordinationEnvelopeRow"]
