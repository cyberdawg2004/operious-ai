"""System-health domain entities.

Persistence-only structures. No API serialization concerns, no business
rules, no orchestration. Transport contracts for this domain live in
`app/api/v1/schemas/health.py`; orchestration lives in
`app/services/health_service.py`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class SystemHealthCheck(UUIDPrimaryKeyMixin, Base):
    """Operational record of a single dependency-health probe result.

    The table exists so the platform can persist (and later query) the
    history of its own readiness signals — a foundation for SLO
    dashboards, run-time anomaly detection, and post-incident review.
    Sprint C only wires the schema and the migration; downstream
    sprints will start writing rows from the readiness pipeline.
    """

    __tablename__ = "system_health_checks"

    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = ["SystemHealthCheck"]
