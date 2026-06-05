"""Work-order ORM rows."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, TENANT_ID_MAX_LENGTH
from app.execution.db import models as _execution_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.resolution.db import models as _resolution_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.session.db import models as _session_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.tenant.db import models as _tenant_models  # noqa: F401  # pyright: ignore[reportUnusedImport]

_ACTION_WIDTH = 96
_HANDLE_WIDTH = 255
_STATE_WIDTH = 32
_TARGET_WIDTH = 512


class WorkOrderRow(Base):
    """Generic tenant work-order ledger row."""

    __tablename__ = "work_order_records"

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operational_sessions.session_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolution_proposals.proposal_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_records.execution_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dispatch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(
        String(_ACTION_WIDTH),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(_HANDLE_WIDTH), nullable=False)
    connector_type: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
    )
    connector_config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    connector_config_content_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    connector_config_source_approval_id: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=False,
    )
    target_resource: Mapped[str] = mapped_column(
        String(_TARGET_WIDTH),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(_STATE_WIDTH),
        nullable=False,
        default="created",
        server_default=text("'created'"),
        index=True,
    )
    provider_work_order_id: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=True,
        index=True,
    )
    provider_status: Mapped[str | None] = mapped_column(
        String(_HANDLE_WIDTH),
        nullable=True,
    )
    last_transition_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    transition_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
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
        CheckConstraint("length(action_type) > 0", name="action_type_nonempty"),
        CheckConstraint("length(tool_name) > 0", name="tool_name_nonempty"),
        CheckConstraint(
            "length(connector_type) > 0",
            name="connector_type_nonempty",
        ),
        CheckConstraint(
            "connector_config_version >= 1",
            name="connector_config_version_positive",
        ),
        CheckConstraint(
            "length(connector_config_content_sha256) = 64",
            name="connector_config_content_sha256_len",
        ),
        CheckConstraint(
            "length(connector_config_source_approval_id) > 0",
            name="connector_config_source_approval_id_nonempty",
        ),
        CheckConstraint(
            "length(idempotency_key) > 0",
            name="idempotency_key_nonempty",
        ),
        CheckConstraint(
            "length(target_resource) > 0",
            name="target_resource_nonempty",
        ),
        CheckConstraint(
            "state IN ("
            "'created', 'dispatched', 'awaiting_fulfillment', "
            "'fulfilled', 'failed'"
            ")",
            name="work_order_state_valid",
        ),
        CheckConstraint(
            "jsonb_typeof(transition_history) = 'array'",
            name="transition_history_array",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="metadata_object",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_work_order_records_tenant_idempotency_key",
        ),
        Index(
            "ix_work_order_records_tenant_state",
            "tenant_id",
            "state",
        ),
        Index(
            "ix_work_order_records_tenant_action",
            "tenant_id",
            "action_type",
        ),
        Index(
            "ix_work_order_records_tenant_session",
            "tenant_id",
            "session_id",
        ),
        Index(
            "ix_work_order_records_tenant_provider",
            "tenant_id",
            "provider_work_order_id",
        ),
    )


__all__ = ["WorkOrderRow"]
