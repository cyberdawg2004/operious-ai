"""Voice-substrate ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TENANT_ID_MAX_LENGTH

_ENUM_WIDTH = 64
_MODEL_WIDTH = 128


class VoiceIngressRecordRow(Base):
    """Durable voice ingress record."""

    __tablename__ = "voice_ingress_records"

    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    direction: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    status: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_handle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    provider_kind: Mapped[str | None] = mapped_column(
        String(_ENUM_WIDTH), nullable=True
    )
    provider_model: Mapped[str | None] = mapped_column(
        String(_MODEL_WIDTH), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    lineage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    runtime_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        Index(
            "ix_voice_ingress_records_tenant_session",
            "tenant_id",
            "session_id",
        ),
        Index(
            "ix_voice_ingress_records_tenant_created_at",
            "tenant_id",
            text("created_at DESC"),
        ),
    )


class VoiceEgressRecordRow(Base):
    """Durable voice egress record."""

    __tablename__ = "voice_egress_records"

    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    direction: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    status: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False)
    synthesis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_handle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    provider_kind: Mapped[str | None] = mapped_column(
        String(_ENUM_WIDTH), nullable=True
    )
    provider_model: Mapped[str | None] = mapped_column(
        String(_MODEL_WIDTH), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    lineage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    runtime_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    governance_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        Index(
            "ix_voice_egress_records_tenant_session",
            "tenant_id",
            "session_id",
        ),
        Index(
            "ix_voice_egress_records_tenant_created_at",
            "tenant_id",
            text("created_at DESC"),
        ),
    )


__all__ = [
    "VoiceEgressRecordRow",
    "VoiceIngressRecordRow",
]
