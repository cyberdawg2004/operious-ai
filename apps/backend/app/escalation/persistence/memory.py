"""In-memory escalation persistence."""

from __future__ import annotations

from app.escalation.exceptions import EscalationPersistenceError
from app.escalation.persistence.models import EscalationPage, EscalationQuery
from app.escalation.persistence.records import EscalationRecord


class InMemoryEscalationPersistence:
    """Reference escalation persistence implementation."""

    def __init__(self) -> None:
        self._records: dict[str, EscalationRecord] = {}
        self._governance_index: dict[str, str] = {}

    async def create_escalation(
        self,
        record: EscalationRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        if record.escalation_id in self._records:
            raise EscalationPersistenceError(
                f"escalation {record.escalation_id!r} already recorded"
            )
        if record.governance_decision_id in self._governance_index:
            raise EscalationPersistenceError(
                "escalation for governance decision "
                f"{record.governance_decision_id!r} already recorded"
            )
        self._records[record.escalation_id] = record
        self._governance_index[record.governance_decision_id] = (
            record.escalation_id
        )

    async def update_escalation(
        self,
        record: EscalationRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        existing = self._records.get(record.escalation_id)
        if existing is None:
            raise EscalationPersistenceError(
                f"unknown escalation {record.escalation_id!r}"
            )
        _enforce_expected_tenant(existing.tenant_id, expected_tenant_id)
        if existing.governance_decision_id != record.governance_decision_id:
            raise EscalationPersistenceError(
                "escalation governance_decision_id is immutable"
            )
        self._records[record.escalation_id] = record

    async def get_escalation(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationRecord | None:
        record = self._records.get(escalation_id)
        if record is None:
            return None
        if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
            return None
        return record

    async def get_escalation_for_governance_decision(
        self,
        governance_decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationRecord | None:
        escalation_id = self._governance_index.get(governance_decision_id)
        if escalation_id is None:
            return None
        return await self.get_escalation(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_escalations(
        self,
        query: EscalationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationPage:
        records = [
            record
            for record in self._records.values()
            if _matches(
                record,
                query=query,
                expected_tenant_id=expected_tenant_id,
            )
        ]
        records.sort(key=lambda r: (r.created_at, r.escalation_id))
        total = len(records)
        page = records[query.offset : query.offset + query.limit]
        return EscalationPage(items=tuple(page), total=total, offset=query.offset)


def _matches(
    record: EscalationRecord,
    *,
    query: EscalationQuery,
    expected_tenant_id: str | None,
) -> bool:
    if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
        return False
    if query.escalation_id is not None and record.escalation_id != query.escalation_id:
        return False
    if query.session_id is not None and record.session_id != query.session_id:
        return False
    if (
        query.governance_decision_id is not None
        and record.governance_decision_id != query.governance_decision_id
    ):
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.status is not None and record.status != query.status:
        return False
    return True


def _enforce_expected_tenant(
    tenant_id: str,
    expected_tenant_id: str | None,
) -> None:
    if expected_tenant_id is not None and tenant_id != expected_tenant_id:
        raise EscalationPersistenceError(
            "escalation tenant_id does not match expected_tenant_id"
        )


__all__ = ["InMemoryEscalationPersistence"]
