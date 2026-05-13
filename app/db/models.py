"""ORM models.

Sprint B intentionally contains only one trivial model whose sole
purpose is to prove that migrations, the async engine, and the session
lifecycle all work end-to-end. Business entities will land here (or in
domain-specific submodules) in later sprints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemHealthCheck(Base):
    """Smoke-test row written by readiness probes / migrations checks."""

    __tablename__ = "system_health_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = ["SystemHealthCheck"]
