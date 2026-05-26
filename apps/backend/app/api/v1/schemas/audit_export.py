"""Transport contracts for signed audit exports."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.runtime.tenant_production_hardening import (
    AuditExportVerification,
    TenantAuditExport,
)


class AuditExportSignatureResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    algorithm: Literal["HMAC-SHA256"] = "HMAC-SHA256"
    value: str
    key_hint: str


class AuditExportResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    exported_at: str
    from_timestamp: str
    to_timestamp: str
    event_count: int
    total_available: int
    truncated: bool
    events: list[dict[str, Any]]
    signature: AuditExportSignatureResponse

    @classmethod
    def from_export(cls, export: TenantAuditExport) -> "AuditExportResponse":
        events = _event_list(export.payload.get("events"))
        return cls(
            tenant_id=export.tenant_id,
            exported_at=export.exported_at,
            from_timestamp=export.from_timestamp,
            to_timestamp=export.to_timestamp,
            event_count=export.event_count,
            total_available=export.total_available,
            truncated=export.truncated,
            events=events,
            signature=AuditExportSignatureResponse(
                value=export.signature,
                key_hint=export.key_hint,
            ),
        )


class AuditExportVerifyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    export: dict[str, Any] = Field(..., min_length=1)


class AuditExportVerifyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    tenant_id: str | None
    event_count: int | None
    exported_at: str | None

    @classmethod
    def from_verification(
        cls,
        result: AuditExportVerification,
    ) -> "AuditExportVerifyResponse":
        return cls(
            valid=result.valid,
            tenant_id=result.tenant_id,
            event_count=result.event_count,
            exported_at=result.exported_at,
        )


__all__ = [
    "AuditExportResponse",
    "AuditExportSignatureResponse",
    "AuditExportVerifyRequest",
    "AuditExportVerifyResponse",
]


def _event_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    events: list[dict[str, Any]] = []
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            continue
        raw_event = cast(dict[object, object], item)
        event: dict[str, Any] = {}
        for key, event_value in raw_event.items():
            if isinstance(key, str):
                event[key] = event_value
        events.append(event)
    return events
