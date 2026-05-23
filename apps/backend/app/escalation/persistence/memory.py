"""In-memory escalation persistence."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from app.escalation.enums import EscalationOutboxStatus
from app.escalation.exceptions import EscalationPersistenceError
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


class InMemoryEscalationPersistence:
    """Reference escalation persistence implementation."""

    def __init__(self) -> None:
        self._records: dict[str, EscalationRecord] = {}
        self._governance_index: dict[str, str] = {}
        self._outbox: dict[str, EscalationOutboxRecord] = {}
        self._outbox_by_escalation: dict[str, str] = {}

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

    async def save_escalation_outbox(
        self,
        record: EscalationOutboxRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        existing_id = self._outbox_by_escalation.get(record.escalation_id)
        if existing_id is not None:
            return self._outbox[existing_id]
        if record.outbox_id in self._outbox:
            raise EscalationPersistenceError(
                f"escalation outbox {record.outbox_id!r} already recorded"
            )
        self._outbox[record.outbox_id] = record
        self._outbox_by_escalation[record.escalation_id] = record.outbox_id
        return record

    async def get_escalation_outbox(
        self,
        outbox_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None:
        record = self._outbox.get(outbox_id)
        if record is None:
            return None
        if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
            return None
        return record

    async def get_escalation_outbox_by_escalation(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None:
        outbox_id = self._outbox_by_escalation.get(escalation_id)
        if outbox_id is None:
            return None
        return await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def claim_escalation_outbox(
        self,
        *,
        escalation_id: str,
        publisher_id: str,
        claimed_at: datetime,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None:
        record = await self.get_escalation_outbox_by_escalation(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None or record.status is not EscalationOutboxStatus.PENDING:
            return record
        claimed = replace(
            record,
            status=EscalationOutboxStatus.PUBLISHING,
            claimed_at=claimed_at,
            publisher_id=publisher_id,
            republish_count=record.republish_count + 1,
            last_error=None,
        )
        self._outbox[claimed.outbox_id] = claimed
        return claimed

    async def mark_escalation_outbox_published(
        self,
        *,
        outbox_id: str,
        published_at: datetime,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord:
        record = await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise EscalationPersistenceError(
                f"unknown escalation outbox {outbox_id!r}"
            )
        updated = replace(
            record,
            status=EscalationOutboxStatus.PUBLISHED,
            published_at=published_at,
            dead_letter=False,
            last_error=None,
        )
        self._outbox[updated.outbox_id] = updated
        return updated

    async def mark_escalation_outbox_failed(
        self,
        *,
        outbox_id: str,
        error: str,
        failed_at: datetime,
        dead_letter: bool = False,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord:
        record = await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise EscalationPersistenceError(
                f"unknown escalation outbox {outbox_id!r}"
            )
        updated = replace(
            record,
            status=EscalationOutboxStatus.FAILED,
            dead_letter=dead_letter,
            last_error=error,
            metadata={
                **dict(record.metadata),
                "failed_at": failed_at.isoformat(),
            },
        )
        self._outbox[updated.outbox_id] = updated
        return updated

    async def requeue_stale_escalation_outbox(
        self,
        *,
        outbox_id: str,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None:
        record = await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if (
            record is None
            or record.status is not EscalationOutboxStatus.PUBLISHING
            or record.claimed_at is None
            or record.claimed_at >= stale_before
        ):
            return None
        updated = replace(
            record,
            status=EscalationOutboxStatus.PENDING,
            claimed_at=None,
            publisher_id=None,
            last_error=reason,
            metadata={
                **dict(record.metadata),
                "requeued_at": requeued_at.isoformat(),
                "requeue_reason": reason,
            },
        )
        self._outbox[updated.outbox_id] = updated
        return updated

    async def list_escalation_outbox(
        self,
        query: EscalationOutboxQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxPage:
        records = [
            record
            for record in self._outbox.values()
            if _outbox_matches(
                record,
                query=query,
                expected_tenant_id=expected_tenant_id,
            )
        ]
        records.sort(key=lambda r: (r.created_at, r.outbox_id))
        total = len(records)
        page = records[query.offset : query.offset + query.limit]
        return EscalationOutboxPage(
            items=tuple(page),
            total=total,
            limit=query.limit,
            offset=query.offset,
        )


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


def _outbox_matches(
    record: EscalationOutboxRecord,
    *,
    query: EscalationOutboxQuery,
    expected_tenant_id: str | None,
) -> bool:
    if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
        return False
    if query.outbox_id is not None and record.outbox_id != query.outbox_id:
        return False
    if query.escalation_id is not None and record.escalation_id != query.escalation_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.status is not None and record.status is not query.status:
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
