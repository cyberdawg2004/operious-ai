"""Runtime ORM rows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Float,
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
    queue: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    replayed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    replay_state: Mapped[str] = mapped_column(
        String(_STATE_WIDTH),
        nullable=False,
        default="none",
        server_default=text("'none'"),
        index=True,
    )
    replay_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    replay_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    replay_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    replay_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    replayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replayed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        CheckConstraint(
            "replay_state IN ('none', 'claimed', 'published', 'failed')",
            name="dead_letter_replay_state_valid",
        ),
        CheckConstraint(
            "replay_attempt_count >= 0",
            name="dead_letter_replay_attempt_nonnegative",
        ),
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
        Index(
            "ix_dead_letter_tasks_replayed",
            "replayed",
            "tenant_id",
        ),
        Index(
            "ix_dead_letter_tasks_replay_state_tenant",
            "replay_state",
            "tenant_id",
        ),
    )


class SOPFailurePatternRow(Base):
    """Detected repeated failures that may indicate an SOP gap."""

    __tablename__ = "sop_failure_patterns"

    pattern_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        nullable=False,
        index=True,
    )
    pattern_source: Mapped[str] = mapped_column(
        String(_STATE_WIDTH), nullable=False
    )
    category: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    threshold_used: Mapped[int] = mapped_column(Integer, nullable=False)
    sop_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(_STATE_WIDTH),
        nullable=False,
        default="detected",
        server_default=text("'detected'"),
    )
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
        CheckConstraint(
            "pattern_source IN ('dlq', 'admission', 'combined')",
            name="sop_failure_pattern_source_valid",
        ),
        CheckConstraint("length(category) > 0", name="category_nonempty"),
        CheckConstraint(
            "failure_count >= 0",
            name="sop_failure_pattern_count_nonnegative",
        ),
        CheckConstraint("window_hours >= 1", name="sop_failure_window_positive"),
        CheckConstraint(
            "threshold_used >= 1",
            name="sop_failure_threshold_positive",
        ),
        CheckConstraint(
            "status IN ('detected', 'proposed', 'acknowledged')",
            name="sop_failure_pattern_status_valid",
        ),
        Index(
            "ix_sop_failure_patterns_tenant_category",
            "tenant_id",
            "category",
            "created_at",
        ),
    )


class DefectClusterRow(Base):
    """Detected diagnostic-category cluster over completed executions."""

    __tablename__ = "defect_cluster_records"

    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH), nullable=False, index=True
    )
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    threshold_used: Mapped[int] = mapped_column(Integer, nullable=False)
    sku_hint: Mapped[str | None] = mapped_column(String(_HANDLE_WIDTH), nullable=True)
    failure_step_hint: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(_STATE_WIDTH),
        nullable=False,
        default="detected",
        server_default=text("'detected'"),
    )
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
        CheckConstraint("length(category) > 0", name="category_nonempty"),
        CheckConstraint(
            "execution_count >= 0",
            name="defect_cluster_execution_count_nonnegative",
        ),
        CheckConstraint("window_hours >= 1", name="defect_cluster_window_positive"),
        CheckConstraint(
            "threshold_used >= 1",
            name="defect_cluster_threshold_positive",
        ),
        CheckConstraint(
            "status IN ('detected', 'reported', 'resolved')",
            name="defect_cluster_status_valid",
        ),
        Index(
            "ix_defect_clusters_tenant_category",
            "tenant_id",
            "category",
            "created_at",
        ),
    )


class DefectReportRow(Base):
    """LLM-synthesized engineering report for a detected defect cluster."""

    __tablename__ = "defect_report_records"

    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "defect_cluster_records.cluster_id",
            name="fk_defect_report_records_cluster_id_defect_cluster_records",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    failure_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    customer_impact: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_actions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_quality: Mapped[str] = mapped_column(String(16), nullable=False)
    incident_count: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    governance_status: Mapped[str] = mapped_column(
        String(_STATE_WIDTH),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cognition_audit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="defect_report_confidence_range",
        ),
        CheckConstraint(
            "incident_count >= 1",
            name="defect_report_incident_count_positive",
        ),
        CheckConstraint(
            "evidence_quality IN ('high', 'medium', 'low')",
            name="defect_report_evidence_quality_valid",
        ),
        CheckConstraint(
            "governance_status IN ('pending', 'allowed', 'blocked')",
            name="defect_report_governance_status_valid",
        ),
        Index(
            "ix_defect_reports_tenant_cluster",
            "tenant_id",
            "cluster_id",
        ),
    )


class OutboundDispatchRow(Base):
    """Delivery attempt ledger for governed outbound defect reports."""

    __tablename__ = "outbound_dispatch_records"

    dispatch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "defect_report_records.report_id",
            name="fk_outbound_dispatch_records_report_id_defect_report_records",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    channel_type: Mapped[str] = mapped_column(String(_STATE_WIDTH), nullable=False)
    target_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    status: Mapped[str] = mapped_column(
        String(_STATE_WIDTH),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
        CheckConstraint("length(channel_type) > 0", name="channel_type_nonempty"),
        CheckConstraint("length(target_url) > 0", name="target_url_nonempty"),
        CheckConstraint(
            "attempt_number >= 1",
            name="outbound_dispatch_attempt_positive",
        ),
        CheckConstraint(
            "status IN ('pending', 'success', 'failed', 'dead_lettered')",
            name="outbound_dispatch_status_valid",
        ),
        Index(
            "ix_outbound_dispatch_report_id",
            "report_id",
            "attempt_number",
        ),
        Index(
            "ix_outbound_dispatch_tenant_status",
            "tenant_id",
            "status",
        ),
    )


__all__ = [
    "DeadLetterTaskRow",
    "DefectClusterRow",
    "DefectReportRow",
    "OutboundDispatchRow",
    "ProviderCircuitStateRow",
    "SOPFailurePatternRow",
]
