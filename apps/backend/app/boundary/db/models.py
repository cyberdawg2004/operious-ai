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
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
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


class BoundaryIngressRow(Base):
    """ORM row for ``boundary_ingress`` — write-once."""

    __tablename__ = "boundary_ingress"

    ingress_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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
    tenant_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
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
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
    source_language: Mapped[str] = mapped_column(
        String(16), nullable=False, default="en", server_default=text("'en'")
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
        Index(
            "ix_boundary_ingress_tenant_language",
            "tenant_id",
            "source_language",
            postgresql_where=text("source_language != 'en'"),
        ),
    )


class IngressDispatchOutboxRow(Base):
    """Durable dispatch intent for a captured boundary ingress row."""

    __tablename__ = "ingress_dispatch_outbox"

    outbox_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ingress_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False, index=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        CheckConstraint(
            "length(tenant_id) > 0",
            name="ck_ingress_dispatch_outbox_tenant_id_nonempty",
        ),
        CheckConstraint(
            "channel IN ('email', 'whatsapp', 'shopify')",
            name="ck_ingress_dispatch_outbox_channel_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'dispatched', 'dead_lettered')",
            name="ck_ingress_dispatch_outbox_status_valid",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_ingress_dispatch_outbox_attempt_nonnegative",
        ),
        ForeignKeyConstraint(
            ["ingress_id"],
            ["boundary_ingress.ingress_id"],
            name="fk_ingress_dispatch_outbox_ingress_id_boundary_ingress",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "ingress_id",
            name="uq_ingress_dispatch_outbox_ingress_id",
        ),
        Index(
            "ix_ingress_dispatch_outbox_status_next_attempt",
            "status",
            "next_attempt_at",
        ),
        Index(
            "ix_ingress_dispatch_outbox_tenant_status",
            "tenant_id",
            "status",
        ),
    )


class BoundaryEgressRow(Base):
    """ORM row for ``boundary_egress`` — write-once."""

    __tablename__ = "boundary_egress"

    egress_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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
    tenant_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    adapter_name: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    # ``payload_body`` is ``Any`` on the record (adapter-defined
    # shape); store as JSONB.
    payload_body: Mapped[Any] = mapped_column(JSONB, nullable=False)
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
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True, index=True
    )
    # Nullable for pre-PR_RT-SAFE-2 historical rows. Runtime-created
    # rows require a persisted ALLOW governance decision before insert.
    governance_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
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
        Index(
            "ix_boundary_egress_tenant_governance_decision",
            "tenant_id",
            "governance_decision_id",
        ),
    )


class WebhookNonceRecordRow(Base):
    """Tenant-scoped nonce ledger for channel webhook replay defense."""

    __tablename__ = "webhook_nonce_records"

    tenant_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        primary_key=True,
        nullable=False,
    )
    channel_type: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH),
        primary_key=True,
        nullable=False,
    )
    nonce: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH * 4),
        primary_key=True,
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(tenant_id) > 0",
            name="tenant_id_nonempty",
        ),
        CheckConstraint(
            "length(channel_type) > 0",
            name="channel_type_nonempty",
        ),
        CheckConstraint(
            "length(nonce) > 0",
            name="nonce_nonempty",
        ),
        CheckConstraint(
            "expires_at > received_at",
            name="expires_after_received",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "channel_type",
            "nonce",
            name="uq_webhook_nonce_records_tenant_channel_nonce",
        ),
        Index(
            "ix_webhook_nonce_records_tenant_channel",
            "tenant_id",
            "channel_type",
        ),
    )


class WhatsAppCustomerReplyDeliveryRow(Base):
    """Tenant-scoped idempotency ledger for customer WhatsApp replies."""

    __tablename__ = "whatsapp_customer_reply_deliveries"

    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    governance_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    phone_number_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    recipient_phone_number: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    draft_body_sha256: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        server_default=text("'pending'"),
    )
    provider_message_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=True,
        index=True,
    )
    provider_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        CheckConstraint(
            "length(tenant_id) > 0",
            name="whatsapp_delivery_tenant_id_nonempty",
        ),
        CheckConstraint(
            "length(phone_number_id) > 0",
            name="whatsapp_delivery_phone_number_id_nonempty",
        ),
        CheckConstraint(
            "length(recipient_phone_number) > 0",
            name="whatsapp_delivery_recipient_nonempty",
        ),
        CheckConstraint(
            "length(draft_body_sha256) = 64",
            name="whatsapp_delivery_draft_body_sha256_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="whatsapp_delivery_status_valid",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["draft_id"],
            ["resolution_outbound_drafts.draft_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proposal_id"],
            ["resolution_proposals.proposal_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["governance_decision_id"],
            ["governance_decisions.decision_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "draft_id",
            "governance_decision_id",
            name="uq_whatsapp_delivery_tenant_draft_governance",
        ),
        Index(
            "ix_whatsapp_delivery_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_whatsapp_delivery_tenant_recipient",
            "tenant_id",
            "recipient_phone_number",
        ),
        Index(
            "uq_whatsapp_delivery_tenant_provider_message",
            "tenant_id",
            "provider_message_id",
            unique=True,
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
    )


class EmailCustomerReplyDeliveryRow(Base):
    """Tenant-scoped idempotency ledger for customer email replies."""

    __tablename__ = "email_customer_reply_deliveries"

    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    governance_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    source_email_address: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    recipient_email_address: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    draft_body_sha256: Mapped[str] = mapped_column(
        String(_ENUM_WIDTH),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    in_reply_to_message_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH * 4),
        nullable=True,
    )
    references_header: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        server_default=text("'pending'"),
    )
    provider_message_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=True,
        index=True,
    )
    provider_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        CheckConstraint(
            "length(tenant_id) > 0",
            name="email_delivery_tenant_id_nonempty",
        ),
        CheckConstraint(
            "length(source_email_address) > 0",
            name="email_delivery_source_nonempty",
        ),
        CheckConstraint(
            "length(recipient_email_address) > 0",
            name="email_delivery_recipient_nonempty",
        ),
        CheckConstraint(
            "length(draft_body_sha256) = 64",
            name="email_delivery_draft_body_sha256_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="email_delivery_status_valid",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["draft_id"],
            ["resolution_outbound_drafts.draft_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proposal_id"],
            ["resolution_proposals.proposal_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["governance_decision_id"],
            ["governance_decisions.decision_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "draft_id",
            "governance_decision_id",
            name="uq_email_delivery_tenant_draft_governance",
        ),
        Index(
            "ix_email_delivery_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_email_delivery_tenant_recipient",
            "tenant_id",
            "recipient_email_address",
        ),
        Index(
            "uq_email_delivery_tenant_provider_message",
            "tenant_id",
            "provider_message_id",
            unique=True,
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
    )


class OutboundSendOutboxRow(Base):
    """Durable, claimable auto-send intent for governed customer replies."""

    __tablename__ = "outbound_send_outbox"

    outbox_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    dispatch_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    governance_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    recipient: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
        index=True,
    )
    draft_body_sha256: Mapped[str] = mapped_column(String(_ENUM_WIDTH), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        server_default=text("'pending'"),
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    worker_id: Mapped[str | None] = mapped_column(String(_HANDLE_WIDTH), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    send_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    provider_message_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=True,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
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
        CheckConstraint(
            "length(tenant_id) > 0",
            name="ck_outbound_send_outbox_tenant_id_nonempty",
        ),
        CheckConstraint(
            "channel IN ('email', 'whatsapp')",
            name="ck_outbound_send_outbox_channel_valid",
        ),
        CheckConstraint(
            "length(action) > 0",
            name="ck_outbound_send_outbox_action_nonempty",
        ),
        CheckConstraint(
            "length(session_id) > 0",
            name="ck_outbound_send_outbox_session_id_nonempty",
        ),
        CheckConstraint(
            "length(dispatch_id) > 0",
            name="ck_outbound_send_outbox_dispatch_id_nonempty",
        ),
        CheckConstraint(
            "length(recipient) > 0",
            name="ck_outbound_send_outbox_recipient_nonempty",
        ),
        CheckConstraint(
            "length(draft_body_sha256) = 64",
            name="ck_outbound_send_outbox_draft_body_sha256_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'sent', 'dead_lettered', 'needs_reconciliation')",
            name="ck_outbound_send_outbox_status_valid",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_outbound_send_outbox_attempt_count_nonnegative",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["draft_id"],
            ["resolution_outbound_drafts.draft_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proposal_id"],
            ["resolution_proposals.proposal_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["governance_decision_id"],
            ["governance_decisions.decision_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "draft_id",
            "channel",
            "recipient",
            "action",
            name="uq_outbound_send_outbox_tenant_draft_channel_recipient_action",
        ),
        Index("ix_outbound_send_outbox_status_next_attempt", "status", "next_attempt_at"),
        Index("ix_outbound_send_outbox_tenant_status", "tenant_id", "status"),
    )


__all__ = [
    "BoundaryEgressRow",
    "BoundaryIngressRow",
    "EmailCustomerReplyDeliveryRow",
    "IngressDispatchOutboxRow",
    "OutboundSendOutboxRow",
    "WhatsAppCustomerReplyDeliveryRow",
    "WebhookNonceRecordRow",
]
