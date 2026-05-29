"""Tenant-scoped production hardening read surfaces."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Mapping, cast

from app.boundary.persistence import (
    BoundaryIngressQuery,
    BoundaryIngressRecord,
    BoundaryPersistenceProtocol,
)
from app.events import (
    OperationalEvent,
    OperationalEventPersistenceProtocol,
    OperationalEventQuery,
)


@dataclass(frozen=True, slots=True)
class TenantAuditExport:
    tenant_id: str
    event_count: int
    payload: Mapping[str, Any]
    signature: str
    from_timestamp: str
    to_timestamp: str
    total_available: int
    truncated: bool
    exported_at: str
    key_hint: str


@dataclass(frozen=True, slots=True)
class TicketReplayTrace:
    ingress_id: str
    events: tuple[Mapping[str, Any], ...]
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class TicketReplayResult:
    tenant_id: str
    ticket_id: str
    status: str
    boundary_ingress_count: int
    traces: tuple[TicketReplayTrace, ...]


@dataclass(frozen=True, slots=True)
class AuditExportVerification:
    valid: bool
    tenant_id: str | None
    event_count: int | None
    exported_at: str | None


AUDIT_EXPORT_UNCONFIGURED_SIGNING_KEY: Final[str] = (
    "__operious_audit_export_not_configured__"
)
_AUDIT_EXPORT_LIMIT = 500
_DEFAULT_EXPORT_WINDOW_DAYS = 30


class AuditExportNotConfiguredError(RuntimeError):
    """Raised when audit export signing is requested without key material."""


class TenantProductionHardeningRuntime:
    """Tenant-scoped audit export and incident replay runtime."""

    def __init__(
        self,
        *,
        event_persistence: OperationalEventPersistenceProtocol | None = None,
        boundary_persistence: BoundaryPersistenceProtocol | None = None,
        audit_export_signing_key: str,
    ) -> None:
        self._event_persistence = event_persistence
        self._boundary_persistence = boundary_persistence
        self._audit_export_signing_key = audit_export_signing_key

    def bind_persistence(
        self,
        *,
        event_persistence: OperationalEventPersistenceProtocol,
        boundary_persistence: BoundaryPersistenceProtocol,
    ) -> "TenantProductionHardeningRuntime":
        return TenantProductionHardeningRuntime(
            event_persistence=event_persistence,
            boundary_persistence=boundary_persistence,
            audit_export_signing_key=self._audit_export_signing_key,
        )

    async def create_audit_export(
        self,
        *,
        tenant_id: str,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
        limit: int = _AUDIT_EXPORT_LIMIT,
        offset: int = 0,
    ) -> TenantAuditExport:
        signing_key = self._require_signing_key()
        event_persistence = self._require_event_persistence()
        exported_at_dt = datetime.now(timezone.utc)
        to_dt = _normalise_timestamp(to_timestamp) or exported_at_dt
        from_dt = _normalise_timestamp(from_timestamp) or (
            to_dt - timedelta(days=_DEFAULT_EXPORT_WINDOW_DAYS)
        )
        export_limit = min(max(limit, 1), _AUDIT_EXPORT_LIMIT)

        count_page = await event_persistence.list_events(
            OperationalEventQuery(
                tenant_id=tenant_id,
                occurred_after_or_at=from_dt,
                occurred_before_or_at=to_dt,
                limit=1,
                offset=0,
            ),
            expected_tenant_id=tenant_id,
        )
        total_available = count_page.total
        latest_offset = max(total_available - export_limit, 0)
        page = await event_persistence.list_events(
            OperationalEventQuery(
                tenant_id=tenant_id,
                occurred_after_or_at=from_dt,
                occurred_before_or_at=to_dt,
                limit=export_limit,
                offset=latest_offset + offset,
            ),
            expected_tenant_id=tenant_id,
        )
        events = tuple(page.events)
        exported_at = _isoformat(exported_at_dt)
        from_iso = _isoformat(from_dt)
        to_iso = _isoformat(to_dt)
        truncated = total_available > len(events)
        payload = {
            "tenant_id": tenant_id,
            "exported_at": exported_at,
            "from_timestamp": from_iso,
            "to_timestamp": to_iso,
            "event_count": len(events),
            "total_available": total_available,
            "truncated": truncated,
            "events": [_event_payload(event) for event in events],
        }
        return TenantAuditExport(
            tenant_id=tenant_id,
            event_count=len(events),
            payload=payload,
            signature=sign_audit_export_payload(
                payload=payload,
                signing_key=signing_key,
            ),
            from_timestamp=from_iso,
            to_timestamp=to_iso,
            total_available=total_available,
            truncated=truncated,
            exported_at=exported_at,
            key_hint=_key_hint(signing_key),
        )

    def verify_audit_export(
        self,
        *,
        export: Mapping[str, Any],
    ) -> AuditExportVerification:
        signing_key = self._require_signing_key()
        payload = signed_audit_export_payload(export)
        signature = _signature_value(export)
        valid = False
        if signature is not None:
            expected = sign_audit_export_payload(
                payload=payload,
                signing_key=signing_key,
            )
            valid = hmac.compare_digest(signature, expected)
        return AuditExportVerification(
            valid=valid,
            tenant_id=_string_value(payload.get("tenant_id")),
            event_count=_int_value(payload.get("event_count")),
            exported_at=_string_value(payload.get("exported_at")),
        )

    def _require_signing_key(self) -> str:
        if (
            not self._audit_export_signing_key
            or self._audit_export_signing_key
            == AUDIT_EXPORT_UNCONFIGURED_SIGNING_KEY
        ):
            raise AuditExportNotConfiguredError("audit_export_not_configured")
        return self._audit_export_signing_key

    def _require_event_persistence(self) -> OperationalEventPersistenceProtocol:
        if self._event_persistence is None:
            raise RuntimeError("event persistence is not bound")
        return self._event_persistence

    def _require_boundary_persistence(self) -> BoundaryPersistenceProtocol:
        if self._boundary_persistence is None:
            raise RuntimeError("boundary persistence is not bound")
        return self._boundary_persistence

    async def replay_ticket(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        limit: int = 100,
    ) -> TicketReplayResult:
        boundary_persistence = self._require_boundary_persistence()
        event_persistence = self._require_event_persistence()
        boundary_page = await boundary_persistence.list_ingress(
            BoundaryIngressQuery(tenant_id=tenant_id, limit=limit),
            expected_tenant_id=tenant_id,
        )
        ingress_records = tuple(
            record
            for record in boundary_page.ingress
            if record.external_message_id == ticket_id
            or record.external_conversation_id == ticket_id
            or record.metadata.get("ticket.external_id") == ticket_id
            or record.canonical_payload.get("ticket_id") == ticket_id
        )
        event_page = await event_persistence.list_events(
            OperationalEventQuery(tenant_id=tenant_id, limit=limit),
            expected_tenant_id=tenant_id,
        )
        traces = tuple(
            TicketReplayTrace(
                ingress_id=str(record.ingress_id),
                events=tuple(
                    _event_payload(event)
                    for event in event_page.events
                    if _event_matches_ingress(
                        event=event,
                        ingress=record,
                        ticket_id=ticket_id,
                    )
                ),
                metadata={
                    "external_message_id": record.external_message_id,
                    "external_conversation_id": record.external_conversation_id,
                    "ticket_id": ticket_id,
                },
            )
            for record in ingress_records
        )
        status = "complete" if traces else "not_found"
        return TicketReplayResult(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            status=status,
            boundary_ingress_count=len(ingress_records),
            traces=traces,
        )


def sign_audit_export_payload(
    *,
    payload: Mapping[str, Any],
    signing_key: str,
) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hmac.new(signing_key.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def signed_audit_export_payload(export: Mapping[str, Any]) -> dict[str, Any]:
    events = export.get("events")
    return {
        "tenant_id": export.get("tenant_id"),
        "exported_at": export.get("exported_at"),
        "from_timestamp": export.get("from_timestamp"),
        "to_timestamp": export.get("to_timestamp"),
        "event_count": export.get("event_count"),
        "total_available": export.get("total_available"),
        "truncated": export.get("truncated"),
        "events": events if isinstance(events, list) else [],
    }


def _signature_value(export: Mapping[str, Any]) -> str | None:
    signature = export.get("signature")
    if not isinstance(signature, Mapping):
        return None
    signature_map = cast(Mapping[str, object], signature)
    value = signature_map.get("value")
    return value if isinstance(value, str) else None


def _event_payload(event: OperationalEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "tenant_id": event.tenant_id,
        "operational_act": event.operational_act.value,
        "substrate": event.substrate.value,
        "root_event_id": str(event.causality.root_event_id),
        "parent_event_id": (
            str(event.causality.parent_event_id)
            if event.causality.parent_event_id is not None
            else None
        ),
        "occurred_at": event.chronology.occurred_at.isoformat(),
        "runtime_instance_id": str(event.chronology.runtime_instance_id),
        "sequence": event.chronology.sequence,
        "metadata": dict(event.metadata),
    }


def _normalise_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    normalised = _normalise_timestamp(value)
    assert normalised is not None
    return normalised.isoformat().replace("+00:00", "Z")


def _key_hint(signing_key: str) -> str:
    return hashlib.sha256(signing_key.encode("utf-8")).hexdigest()[:8]


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int_value(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _event_matches_ingress(
    *,
    event: OperationalEvent,
    ingress: BoundaryIngressRecord,
    ticket_id: str,
) -> bool:
    metadata = event.metadata
    if event.tenant_id != ingress.tenant_id:
        return False
    direct_matches = (
        metadata.get("ticket_id"),
        metadata.get("ticket.external_id"),
        metadata.get("source_ingress_id"),
        metadata.get("source_external_message_id"),
        metadata.get("source_external_conversation_id"),
        metadata.get("source_correlation_id"),
        metadata.get("source_request_id"),
    )
    if ticket_id in {str(value) for value in direct_matches if value is not None}:
        return True
    if str(ingress.ingress_id) in {
        str(value) for value in direct_matches if value is not None
    }:
        return True

    source_payload = metadata.get("source_canonical_payload")
    if isinstance(source_payload, Mapping):
        typed_source_payload = cast(Mapping[str, Any], source_payload)
        if (
            typed_source_payload.get("ticket_id") == ticket_id
            or typed_source_payload.get("message_id") == ticket_id
        ):
            return True

    source_metadata = metadata.get("source_metadata")
    if isinstance(source_metadata, Mapping):
        typed_source_metadata = cast(Mapping[str, Any], source_metadata)
        if (
            typed_source_metadata.get("ticket.external_id") == ticket_id
            or typed_source_metadata.get("ticket_id") == ticket_id
        ):
            return True

    return False


__all__ = [
    "AUDIT_EXPORT_UNCONFIGURED_SIGNING_KEY",
    "AuditExportNotConfiguredError",
    "AuditExportVerification",
    "TenantAuditExport",
    "TenantProductionHardeningRuntime",
    "TicketReplayResult",
    "TicketReplayTrace",
    "sign_audit_export_payload",
    "signed_audit_export_payload",
]
