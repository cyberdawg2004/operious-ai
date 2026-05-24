"""Storage-agnostic escalation persistence protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from datetime import datetime

from app.escalation.persistence.models import (
    EscalationOutboxPage,
    EscalationOutboxQuery,
    EscalationPage,
    EscalationQuery,
)
from app.escalation.persistence.records import (
    EscalationOutboxRecord,
    EscalationRecord,
)


@runtime_checkable
class EscalationPersistenceProtocol(Protocol):
    """Durable escalation record store."""

    async def create_escalation(
        self,
        record: EscalationRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> None: ...

    async def update_escalation(
        self,
        record: EscalationRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> None: ...

    async def get_escalation(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationRecord | None: ...

    async def get_escalation_for_governance_decision(
        self,
        governance_decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationRecord | None: ...

    async def list_escalations(
        self,
        query: EscalationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationPage: ...

    async def save_escalation_outbox(
        self,
        record: EscalationOutboxRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord: ...

    async def get_escalation_outbox(
        self,
        outbox_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None: ...

    async def get_escalation_outbox_by_escalation(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None: ...

    async def claim_escalation_outbox(
        self,
        *,
        escalation_id: str,
        publisher_id: str,
        claim_id: str,
        claimed_at: datetime,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None: ...

    async def mark_escalation_outbox_published(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        published_at: datetime,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord: ...

    async def mark_escalation_outbox_failed(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        error: str,
        failed_at: datetime,
        dead_letter: bool = False,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord: ...

    async def requeue_stale_escalation_outbox(
        self,
        *,
        outbox_id: str,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None: ...

    async def list_escalation_outbox(
        self,
        query: EscalationOutboxQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxPage: ...


__all__ = ["EscalationPersistenceProtocol"]
