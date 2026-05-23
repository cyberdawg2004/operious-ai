"""Tenant-scoped production hardening read surfaces."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

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


@dataclass(frozen=True, slots=True)
class TicketReplayTrace:
    ingress_id: str
    events: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TicketReplayResult:
    tenant_id: str
    ticket_id: str
    status: str
    boundary_ingress_count: int
    traces: tuple[TicketReplayTrace, ...]


class TenantProductionHardeningRuntime:
    """Tenant-scoped audit export and incident replay runtime."""

    def __init__(
        self,
        *,
        event_persistence: OperationalEventPersistenceProtocol,
        boundary_persistence: BoundaryPersistenceProtocol,
        audit_export_signing_key: str,
    ) -> None:
        if not audit_export_signing_key:
            raise ValueError("audit_export_signing_key must be non-empty")
        self._event_persistence = event_persistence
        self._boundary_persistence = boundary_persistence
        self._audit_export_signing_key = audit_export_signing_key

    async def create_audit_export(
        self,
        *,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> TenantAuditExport:
        page = await self._event_persistence.list_events(
            OperationalEventQuery(tenant_id=tenant_id, limit=limit, offset=offset),
            expected_tenant_id=tenant_id,
        )
        payload = {
            "tenant_id": tenant_id,
            "event_count": len(page.events),
            "events": [_event_payload(event) for event in page.events],
        }
        return TenantAuditExport(
            tenant_id=tenant_id,
            event_count=len(page.events),
            payload=payload,
            signature=sign_audit_export_payload(
                payload=payload,
                signing_key=self._audit_export_signing_key,
            ),
        )

    async def replay_ticket(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        limit: int = 100,
    ) -> TicketReplayResult:
        boundary_page = await self._boundary_persistence.list_ingress(
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
        event_page = await self._event_persistence.list_events(
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
    if isinstance(source_payload, Mapping) and (
        source_payload.get("ticket_id") == ticket_id
        or source_payload.get("message_id") == ticket_id
    ):
        return True

    source_metadata = metadata.get("source_metadata")
    if isinstance(source_metadata, Mapping) and (
        source_metadata.get("ticket.external_id") == ticket_id
        or source_metadata.get("ticket_id") == ticket_id
    ):
        return True

    return False


__all__ = [
    "TenantAuditExport",
    "TenantProductionHardeningRuntime",
    "TicketReplayResult",
    "TicketReplayTrace",
    "sign_audit_export_payload",
]
