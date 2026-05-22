"""Boundary substrate ORM rows (apex ingress / egress).

Two tables mirroring the two persistable record shapes:

* ``boundary_ingress``  — one row per ``ingest()`` outcome.
* ``boundary_egress``   — one row per ``emit()`` outcome.

Doctrine notes
--------------
* Nullable tenant_id (boundary may emit/ingest tenantless probes
  and unattributed adapter signals); inline clamp in
  ``PostgresBoundaryPersistence``.
* No partitioning yet.
* Composite ordering index ``(runtime_instance_id, sequence)`` on
  each table — the Protocol's canonical ordering contract.
* JSONB blobs for ``canonical_payload`` /
  ``payload_body`` / ``payload_headers`` / ``metadata``.
* No FK between ingress and egress — they are distinct emission
  paths; ``replay_key`` and ``correlation_id`` are the join handles
  audit tools use to correlate them.

Sub-substrates (translation / voice) have their own persistence
protocols and will land in a future PR. PR-B7 covers only the
apex boundary substrate.
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


class BoundaryIngressRow(Base):
    """ORM row for ``boundary_ingress`` — write-once."""

    __tablename__ = "boundary_ingress"

    ingress_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    direction: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    runtime_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    adapter_name: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    normalization_status: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    message_type: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    replay_disposition: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    replay_key: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    original_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    external_message_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    external_conversation_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    external_emitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    __table_args__ = (
        Index(
            "ix_boundary_ingress_runtime_seq",
            "runtime_instance_id",
            "sequence",
        ),
        Index(
            "uq_boundary_ingress_replay_key",
            "replay_key",
            unique=True,
            postgresql_where=text("replay_key IS NOT NULL"),
        ),
        Index(
            "uq_boundary_ingress_event_id",
            "event_id",
            unique=True,
            postgresql_where=text("event_id IS NOT NULL"),
        ),
    )


class BoundaryEgressRow(Base):
    """ORM row for ``boundary_egress`` — write-once."""

    __tablename__ = "boundary_egress"

    egress_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    direction: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    runtime_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    adapter_name: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    # ``payload_body`` is ``Any`` on the record (adapter-defined
    # shape); store as JSONB.
    payload_body: Mapped[Any] = mapped_column(
        JSONB, nullable=False
    )
    payload_content_type: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    payload_target_uri: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH * 4), nullable=True
    )
    payload_method: Mapped[str | None] = mapped_column(
        String(_ENUM_WIDTH), nullable=True
    )
    payload_headers: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    translated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    __table_args__ = (
        Index(
            "ix_boundary_egress_runtime_seq",
            "runtime_instance_id",
            "sequence",
        ),
    )


__all__ = ["BoundaryEgressRow", "BoundaryIngressRow"]
