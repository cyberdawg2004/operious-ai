"""Storage-agnostic escalation persistence protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.escalation.persistence.models import EscalationPage, EscalationQuery
from app.escalation.persistence.records import EscalationRecord


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


__all__ = ["EscalationPersistenceProtocol"]
