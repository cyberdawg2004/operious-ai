"""Service boundary for signed audit exports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.runtime.tenant_production_hardening import (
    AuditExportNotConfiguredError,
    AuditExportVerification,
    TenantAuditExport,
    TenantProductionHardeningRuntime,
)


class AuditExportService:
    """Tenant-scoped audit export application service."""

    def __init__(
        self,
        *,
        runtime: TenantProductionHardeningRuntime,
    ) -> None:
        self._runtime = runtime

    async def create_export(
        self,
        *,
        tenant_id: str,
        from_timestamp: datetime | None,
        to_timestamp: datetime | None,
    ) -> TenantAuditExport:
        return await self._runtime.create_audit_export(
            tenant_id=tenant_id,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )

    def verify_export(
        self,
        *,
        export: Mapping[str, Any],
    ) -> AuditExportVerification:
        return self._runtime.verify_audit_export(export=export)


__all__ = ["AuditExportNotConfiguredError", "AuditExportService"]
