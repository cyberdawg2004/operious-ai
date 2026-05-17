"""Audit recorder — converts findings + status into a `HardeningAudit`."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from app.hardening.enums import (
    HardeningStatus,
    HardeningTraceKind,
    IntegrityStatus,
)
from app.hardening.identity import (
    HardeningAuditId,
    derive_audit_id,
)
from app.hardening.models.audit import HardeningAudit
from app.hardening.models.finding import HardeningFinding


class HardeningAuditRecorder:
    """Pure assembly helper for `HardeningAudit` records."""

    __slots__ = ()

    def assemble(
        self,
        *,
        seed: str,
        kind: HardeningTraceKind,
        status: HardeningStatus,
        findings: tuple[HardeningFinding, ...],
        started_at: datetime,
        ended_at: datetime,
        summary: str | None = None,
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> HardeningAudit:
        return HardeningAudit(
            audit_id=self._derive_audit_id(seed),
            seed=seed,
            kind=kind,
            status=status,
            findings=findings,
            started_at=started_at,
            ended_at=ended_at,
            summary=summary,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            metadata=metadata or {},
        )

    @staticmethod
    def _derive_audit_id(seed: str) -> HardeningAuditId:
        return derive_audit_id(seed=seed)

    @staticmethod
    def status_from_integrity(
        status: IntegrityStatus,
    ) -> HardeningStatus:
        if status is IntegrityStatus.PASSED:
            return HardeningStatus.COMPLETED
        if status is IntegrityStatus.FAILED:
            return HardeningStatus.COMPLETED
        return HardeningStatus.INCONCLUSIVE


__all__ = ["HardeningAuditRecorder"]
