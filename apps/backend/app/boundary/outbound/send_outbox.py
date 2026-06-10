"""Durable outbound customer-reply send outbox."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Mapping, NewType, Protocol, cast

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult

from app.boundary.db.models import OutboundSendOutboxRow
from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page

OutboundSendOutboxId = NewType("OutboundSendOutboxId", uuid.UUID)
OutboundSendClaimId = NewType("OutboundSendClaimId", uuid.UUID)

_OUTBOX_NAMESPACE = uuid.UUID("a4b45608-9bb9-4adf-85d9-1809f9e7bd8e")
_CLAIM_NAMESPACE = uuid.UUID("b94fe9d1-b4f0-47d9-81d8-7c25b0378c58")
_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_MAX_AGE_SECONDS = 60 * 60
_DEFAULT_RETRY_BASE_SECONDS = 30
_MAX_RETRY_DELAY_SECONDS = 3600


class OutboundSendOutboxStatus(StrEnum):
    """Lifecycle state of one auto-send intent."""

    PENDING = "pending"
    CLAIMED = "claimed"
    SENT = "sent"
    DEAD_LETTERED = "dead_lettered"


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class OutboundSendOutboxRecord:
    outbox_id: OutboundSendOutboxId
    tenant_id: str
    channel: str
    action: str
    draft_id: uuid.UUID
    proposal_id: uuid.UUID
    session_id: str
    dispatch_id: str
    governance_decision_id: uuid.UUID
    recipient: str
    draft_body_sha256: str
    status: OutboundSendOutboxStatus
    created_at: datetime
    updated_at: datetime
    next_attempt_at: datetime | None = None
    claimed_at: datetime | None = None
    sent_at: datetime | None = None
    claim_id: OutboundSendClaimId | None = None
    worker_id: str | None = None
    attempt_count: int = 0
    provider_message_id: str | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class OutboundSendOutboxQuery:
    outbox_id: OutboundSendOutboxId | None = None
    tenant_id: str | None = None
    draft_id: uuid.UUID | None = None
    proposal_id: uuid.UUID | None = None
    status: OutboundSendOutboxStatus | None = None
    channel: str | None = None
    due_before_or_at: datetime | None = None
    claimed_before_or_at: datetime | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OutboundSendOutboxPage:
    records: tuple[OutboundSendOutboxRecord, ...]
    total: int
    limit: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OutboundSendOutboxClaimResult:
    claimed: bool
    outbox: OutboundSendOutboxRecord | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class OutboundSendOutboxRequeueResult:
    requeued: bool
    outbox: OutboundSendOutboxRecord | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class OutboundSendOutboxSweepResult:
    scanned: int
    requeued: tuple[OutboundSendOutboxRequeueResult, ...] = ()
    refused: tuple[OutboundSendOutboxRequeueResult, ...] = ()
    dead_lettered: tuple[OutboundSendOutboxRecord, ...] = ()

    @property
    def requeued_count(self) -> int:
        return len(self.requeued)

    @property
    def dead_lettered_count(self) -> int:
        return len(self.dead_lettered)


class OutboundSendOutboxPersistenceProtocol(Protocol):
    async def create_outbound_send_outbox(
        self,
        record: OutboundSendOutboxRecord,
    ) -> OutboundSendOutboxRecord: ...

    async def get_outbound_send_outbox(
        self,
        outbox_id: OutboundSendOutboxId,
    ) -> OutboundSendOutboxRecord | None: ...

    async def list_outbound_send_outbox(
        self,
        query: OutboundSendOutboxQuery,
    ) -> OutboundSendOutboxPage: ...

    async def claim_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        worker_id: str,
        claimed_at: datetime,
    ) -> OutboundSendOutboxRecord | None: ...

    async def mark_outbound_send_outbox_sent(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        provider_message_id: str,
        sent_at: datetime,
    ) -> OutboundSendOutboxRecord | None: ...

    async def reschedule_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        next_attempt_at: datetime,
        error: str,
    ) -> OutboundSendOutboxRecord | None: ...

    async def dead_letter_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        error: str,
        dead_lettered_at: datetime,
    ) -> OutboundSendOutboxRecord | None: ...

    async def requeue_stale_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
    ) -> OutboundSendOutboxRecord | None: ...


class OutboundSendOutboxRuntime:
    """State-transition facade for outbound send outbox rows."""

    def __init__(
        self,
        *,
        persistence: OutboundSendOutboxPersistenceProtocol,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
        retry_base_seconds: int = _DEFAULT_RETRY_BASE_SECONDS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if max_age_seconds < 1:
            raise ValueError("max_age_seconds must be positive")
        if retry_base_seconds < 1:
            raise ValueError("retry_base_seconds must be positive")
        self._persistence = persistence
        self._max_attempts = max_attempts
        self._max_age_seconds = max_age_seconds
        self._retry_base_seconds = retry_base_seconds

    async def get_outbox(
        self,
        outbox_id: OutboundSendOutboxId | str | uuid.UUID,
    ) -> OutboundSendOutboxRecord | None:
        return await self._persistence.get_outbound_send_outbox(
            as_outbound_send_outbox_id(outbox_id)
        )

    async def list_outbox(
        self,
        query: OutboundSendOutboxQuery,
    ) -> OutboundSendOutboxPage:
        return await self._persistence.list_outbound_send_outbox(query)

    async def claim_due_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId | str | uuid.UUID,
        worker_id: str,
        claimed_at: datetime | None = None,
        allow_exhausted: bool = False,
    ) -> OutboundSendOutboxClaimResult:
        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        now = claimed_at or datetime.now(tz=timezone.utc)
        current = await self.get_outbox(outbox_id)
        if current is None:
            return OutboundSendOutboxClaimResult(
                claimed=False,
                outbox=None,
                reason="outbox_not_found",
            )
        if current.status is not OutboundSendOutboxStatus.PENDING:
            return OutboundSendOutboxClaimResult(
                claimed=False,
                outbox=current,
                reason=f"outbox_not_claimable:{current.status.value}",
            )
        if current.next_attempt_at is not None and current.next_attempt_at > now:
            return OutboundSendOutboxClaimResult(
                claimed=False,
                outbox=current,
                reason="outbox_not_due",
            )
        if not allow_exhausted and self.should_dead_letter(current, now=now):
            return OutboundSendOutboxClaimResult(
                claimed=False,
                outbox=current,
                reason="outbox_retry_budget_exhausted",
            )
        claim_id = derive_outbound_send_claim_id(
            outbox_id=current.outbox_id,
            worker_id=worker_id,
            attempt_count=current.attempt_count + 1,
        )
        claimed = await self._persistence.claim_outbound_send_outbox(
            outbox_id=current.outbox_id,
            claim_id=claim_id,
            worker_id=worker_id,
            claimed_at=now,
        )
        if claimed is not None:
            return OutboundSendOutboxClaimResult(claimed=True, outbox=claimed)
        refreshed = await self.get_outbox(current.outbox_id)
        return OutboundSendOutboxClaimResult(
            claimed=False,
            outbox=refreshed,
            reason=(
                "outbox_not_found"
                if refreshed is None
                else f"outbox_not_claimable:{refreshed.status.value}"
            ),
        )

    async def mark_sent(
        self,
        *,
        outbox_id: OutboundSendOutboxId | str | uuid.UUID,
        claim_id: OutboundSendClaimId | str | uuid.UUID,
        provider_message_id: str,
        sent_at: datetime | None = None,
    ) -> OutboundSendOutboxRecord | None:
        return await self._persistence.mark_outbound_send_outbox_sent(
            outbox_id=as_outbound_send_outbox_id(outbox_id),
            claim_id=as_outbound_send_claim_id(claim_id),
            provider_message_id=provider_message_id,
            sent_at=sent_at or datetime.now(tz=timezone.utc),
        )

    async def reschedule(
        self,
        *,
        outbox: OutboundSendOutboxRecord,
        claim_id: OutboundSendClaimId | str | uuid.UUID,
        error: str,
        now: datetime | None = None,
        retry_after_seconds: int | None = None,
    ) -> OutboundSendOutboxRecord | None:
        ts = now or datetime.now(tz=timezone.utc)
        seconds = (
            retry_after_seconds
            if retry_after_seconds is not None and retry_after_seconds > 0
            else self.retry_delay_seconds(outbox.attempt_count)
        )
        return await self._persistence.reschedule_outbound_send_outbox(
            outbox_id=outbox.outbox_id,
            claim_id=as_outbound_send_claim_id(claim_id),
            next_attempt_at=ts + timedelta(seconds=seconds),
            error=error,
        )

    async def dead_letter(
        self,
        *,
        outbox_id: OutboundSendOutboxId | str | uuid.UUID,
        claim_id: OutboundSendClaimId | str | uuid.UUID,
        error: str,
        dead_lettered_at: datetime | None = None,
    ) -> OutboundSendOutboxRecord | None:
        return await self._persistence.dead_letter_outbound_send_outbox(
            outbox_id=as_outbound_send_outbox_id(outbox_id),
            claim_id=as_outbound_send_claim_id(claim_id),
            error=error,
            dead_lettered_at=dead_lettered_at or datetime.now(tz=timezone.utc),
        )

    async def requeue_stale_claimed(
        self,
        *,
        stale_before: datetime,
        requeued_at: datetime | None = None,
        limit: int = 100,
        tenant_id: str | None = None,
        reason: str = "outbound send claim expired",
    ) -> OutboundSendOutboxSweepResult:
        page = await self.list_outbox(
            OutboundSendOutboxQuery(
                tenant_id=tenant_id,
                status=OutboundSendOutboxStatus.CLAIMED,
                claimed_before_or_at=stale_before,
                limit=limit,
            )
        )
        ts = requeued_at or datetime.now(tz=timezone.utc)
        requeued: list[OutboundSendOutboxRequeueResult] = []
        refused: list[OutboundSendOutboxRequeueResult] = []
        for outbox in page.records:
            updated = await self._persistence.requeue_stale_outbound_send_outbox(
                outbox_id=outbox.outbox_id,
                stale_before=stale_before,
                requeued_at=ts,
                reason=reason,
            )
            result = OutboundSendOutboxRequeueResult(
                requeued=updated is not None,
                outbox=updated or await self.get_outbox(outbox.outbox_id),
                reason=None if updated is not None else "outbox_not_stale",
            )
            if result.requeued:
                requeued.append(result)
            else:
                refused.append(result)
        return OutboundSendOutboxSweepResult(
            scanned=len(page.records),
            requeued=tuple(requeued),
            refused=tuple(refused),
        )

    async def dead_letter_exhausted_pending(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
        tenant_id: str | None = None,
        reason: str = "outbound send retry budget exhausted",
    ) -> OutboundSendOutboxSweepResult:
        ts = now or datetime.now(tz=timezone.utc)
        page = await self.list_outbox(
            OutboundSendOutboxQuery(
                tenant_id=tenant_id,
                status=OutboundSendOutboxStatus.PENDING,
                due_before_or_at=ts,
                limit=limit,
            )
        )
        dead_lettered: list[OutboundSendOutboxRecord] = []
        for outbox in page.records:
            if not self.should_dead_letter(outbox, now=ts):
                continue
            claim = await self.claim_due_outbox(
                outbox_id=outbox.outbox_id,
                worker_id="reconciler:outbound-send-dead-letter",
                claimed_at=ts,
                allow_exhausted=True,
            )
            if (
                not claim.claimed
                or claim.outbox is None
                or claim.outbox.claim_id is None
            ):
                continue
            updated = await self.dead_letter(
                outbox_id=claim.outbox.outbox_id,
                claim_id=claim.outbox.claim_id,
                error=reason,
                dead_lettered_at=ts,
            )
            if updated is not None:
                dead_lettered.append(updated)
        return OutboundSendOutboxSweepResult(
            scanned=len(page.records),
            dead_lettered=tuple(dead_lettered),
        )

    def retry_delay_seconds(self, attempt_count: int) -> int:
        exponent = max(attempt_count - 1, 0)
        return min(
            self._retry_base_seconds * (2**exponent),
            _MAX_RETRY_DELAY_SECONDS,
        )

    def should_dead_letter(
        self,
        outbox: OutboundSendOutboxRecord,
        *,
        now: datetime | None = None,
    ) -> bool:
        ts = now or datetime.now(tz=timezone.utc)
        if outbox.attempt_count >= self._max_attempts:
            return True
        return outbox.created_at + timedelta(seconds=self._max_age_seconds) <= ts


class PostgresOutboundSendOutboxPersistence(BaseRepository):
    """Postgres-backed outbound send outbox persistence."""

    async def create_outbound_send_outbox(
        self,
        record: OutboundSendOutboxRecord,
    ) -> OutboundSendOutboxRecord:
        stmt = (
            pg_insert(OutboundSendOutboxRow)
            .values(_outbox_record_to_values(record))
            .on_conflict_do_nothing(
                constraint="uq_outbound_send_outbox_tenant_draft_channel_recipient_action"
            )
            .returning(OutboundSendOutboxRow)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            return _row_to_outbox_record(row)
        page = await self.list_outbound_send_outbox(
            OutboundSendOutboxQuery(
                tenant_id=record.tenant_id,
                draft_id=record.draft_id,
                channel=record.channel,
                limit=100,
            )
        )
        for existing in page.records:
            if (
                existing.recipient == record.recipient
                and existing.action == record.action
            ):
                return existing
        raise RuntimeError("outbound send outbox conflict row not found")

    async def get_outbound_send_outbox(
        self,
        outbox_id: OutboundSendOutboxId,
    ) -> OutboundSendOutboxRecord | None:
        stmt = select(OutboundSendOutboxRow).where(
            OutboundSendOutboxRow.outbox_id == outbox_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_outbox_record(row)

    async def list_outbound_send_outbox(
        self,
        query: OutboundSendOutboxQuery,
    ) -> OutboundSendOutboxPage:
        stmt = select(OutboundSendOutboxRow)
        if query.outbox_id is not None:
            stmt = stmt.where(OutboundSendOutboxRow.outbox_id == query.outbox_id)
        if query.tenant_id is not None:
            stmt = stmt.where(OutboundSendOutboxRow.tenant_id == query.tenant_id)
        if query.draft_id is not None:
            stmt = stmt.where(OutboundSendOutboxRow.draft_id == query.draft_id)
        if query.proposal_id is not None:
            stmt = stmt.where(OutboundSendOutboxRow.proposal_id == query.proposal_id)
        if query.channel is not None:
            stmt = stmt.where(OutboundSendOutboxRow.channel == query.channel)
        if query.status is not None:
            stmt = stmt.where(OutboundSendOutboxRow.status == query.status.value)
        if query.due_before_or_at is not None:
            stmt = stmt.where(
                or_(
                    OutboundSendOutboxRow.next_attempt_at.is_(None),
                    OutboundSendOutboxRow.next_attempt_at <= query.due_before_or_at,
                )
            )
        if query.claimed_before_or_at is not None:
            stmt = stmt.where(
                OutboundSendOutboxRow.claimed_at.is_not(None),
                OutboundSendOutboxRow.claimed_at <= query.claimed_before_or_at,
            )
        stmt = stmt.order_by(
            OutboundSendOutboxRow.next_attempt_at,
            OutboundSendOutboxRow.created_at,
            OutboundSendOutboxRow.outbox_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return OutboundSendOutboxPage(
            records=tuple(_row_to_outbox_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def claim_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        worker_id: str,
        claimed_at: datetime,
    ) -> OutboundSendOutboxRecord | None:
        stmt = (
            update(OutboundSendOutboxRow)
            .where(
                OutboundSendOutboxRow.outbox_id == outbox_id,
                OutboundSendOutboxRow.status == OutboundSendOutboxStatus.PENDING.value,
                or_(
                    OutboundSendOutboxRow.next_attempt_at.is_(None),
                    OutboundSendOutboxRow.next_attempt_at <= claimed_at,
                ),
            )
            .values(
                status=OutboundSendOutboxStatus.CLAIMED.value,
                claimed_at=claimed_at,
                updated_at=claimed_at,
                claim_id=claim_id,
                worker_id=worker_id,
                attempt_count=OutboundSendOutboxRow.attempt_count + 1,
                last_error=None,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_outbound_send_outbox(outbox_id)

    async def mark_outbound_send_outbox_sent(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        provider_message_id: str,
        sent_at: datetime,
    ) -> OutboundSendOutboxRecord | None:
        stmt = (
            update(OutboundSendOutboxRow)
            .where(
                OutboundSendOutboxRow.outbox_id == outbox_id,
                OutboundSendOutboxRow.status == OutboundSendOutboxStatus.CLAIMED.value,
                OutboundSendOutboxRow.claim_id == claim_id,
            )
            .values(
                status=OutboundSendOutboxStatus.SENT.value,
                sent_at=sent_at,
                updated_at=sent_at,
                provider_message_id=provider_message_id,
                last_error=None,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_outbound_send_outbox(outbox_id)

    async def reschedule_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        next_attempt_at: datetime,
        error: str,
    ) -> OutboundSendOutboxRecord | None:
        existing = await self.get_outbound_send_outbox(outbox_id)
        metadata = dict(existing.metadata) if existing is not None else {}
        stmt = (
            update(OutboundSendOutboxRow)
            .where(
                OutboundSendOutboxRow.outbox_id == outbox_id,
                OutboundSendOutboxRow.status == OutboundSendOutboxStatus.CLAIMED.value,
                OutboundSendOutboxRow.claim_id == claim_id,
            )
            .values(
                status=OutboundSendOutboxStatus.PENDING.value,
                claim_id=None,
                worker_id=None,
                claimed_at=None,
                updated_at=next_attempt_at,
                next_attempt_at=next_attempt_at,
                last_error=error,
                metadata_json={
                    **metadata,
                    "retry.next_attempt_at": next_attempt_at.isoformat(),
                    "retry.last_error": error,
                },
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_outbound_send_outbox(outbox_id)

    async def dead_letter_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        error: str,
        dead_lettered_at: datetime,
    ) -> OutboundSendOutboxRecord | None:
        existing = await self.get_outbound_send_outbox(outbox_id)
        metadata = dict(existing.metadata) if existing is not None else {}
        stmt = (
            update(OutboundSendOutboxRow)
            .where(
                OutboundSendOutboxRow.outbox_id == outbox_id,
                OutboundSendOutboxRow.status == OutboundSendOutboxStatus.CLAIMED.value,
                OutboundSendOutboxRow.claim_id == claim_id,
            )
            .values(
                status=OutboundSendOutboxStatus.DEAD_LETTERED.value,
                updated_at=dead_lettered_at,
                last_error=error,
                metadata_json={
                    **metadata,
                    "dead_lettered_at": dead_lettered_at.isoformat(),
                    "dead_letter.reason": error,
                },
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_outbound_send_outbox(outbox_id)

    async def requeue_stale_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
    ) -> OutboundSendOutboxRecord | None:
        existing = await self.get_outbound_send_outbox(outbox_id)
        metadata = dict(existing.metadata) if existing is not None else {}
        stmt = (
            update(OutboundSendOutboxRow)
            .where(
                OutboundSendOutboxRow.outbox_id == outbox_id,
                OutboundSendOutboxRow.status == OutboundSendOutboxStatus.CLAIMED.value,
                OutboundSendOutboxRow.claimed_at.is_not(None),
                OutboundSendOutboxRow.claimed_at <= stale_before,
            )
            .values(
                status=OutboundSendOutboxStatus.PENDING.value,
                claim_id=None,
                worker_id=None,
                claimed_at=None,
                updated_at=requeued_at,
                last_error=reason,
                metadata_json={
                    **metadata,
                    "reconciler.reason": reason,
                    "reconciler.requeued_at": requeued_at.isoformat(),
                },
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_outbound_send_outbox(outbox_id)


class InMemoryOutboundSendOutboxPersistence:
    """In-memory outbound send outbox for focused tests."""

    def __init__(self) -> None:
        self._records: dict[OutboundSendOutboxId, OutboundSendOutboxRecord] = {}
        self._by_unique: dict[tuple[str, uuid.UUID, str, str, str], OutboundSendOutboxId]
        self._by_unique = {}
        self._lock = asyncio.Lock()

    async def create_outbound_send_outbox(
        self,
        record: OutboundSendOutboxRecord,
    ) -> OutboundSendOutboxRecord:
        key = _unique_key(record)
        async with self._lock:
            existing_id = self._by_unique.get(key)
            if existing_id is not None:
                return self._records[existing_id]
            self._records[record.outbox_id] = record
            self._by_unique[key] = record.outbox_id
            return record

    async def get_outbound_send_outbox(
        self,
        outbox_id: OutboundSendOutboxId,
    ) -> OutboundSendOutboxRecord | None:
        async with self._lock:
            return self._records.get(outbox_id)

    async def list_outbound_send_outbox(
        self,
        query: OutboundSendOutboxQuery,
    ) -> OutboundSendOutboxPage:
        async with self._lock:
            records = list(self._records.values())
        if query.outbox_id is not None:
            records = [r for r in records if r.outbox_id == query.outbox_id]
        if query.tenant_id is not None:
            records = [r for r in records if r.tenant_id == query.tenant_id]
        if query.draft_id is not None:
            records = [r for r in records if r.draft_id == query.draft_id]
        if query.proposal_id is not None:
            records = [r for r in records if r.proposal_id == query.proposal_id]
        if query.status is not None:
            records = [r for r in records if r.status is query.status]
        if query.channel is not None:
            records = [r for r in records if r.channel == query.channel]
        if query.due_before_or_at is not None:
            records = [
                r
                for r in records
                if r.next_attempt_at is None
                or r.next_attempt_at <= query.due_before_or_at
            ]
        if query.claimed_before_or_at is not None:
            records = [
                r
                for r in records
                if r.claimed_at is not None
                and r.claimed_at <= query.claimed_before_or_at
            ]
        records.sort(key=lambda r: (r.next_attempt_at or r.created_at, r.created_at))
        total = len(records)
        page = records[query.offset : query.offset + query.limit]
        return OutboundSendOutboxPage(
            records=tuple(page),
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    async def claim_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        worker_id: str,
        claimed_at: datetime,
    ) -> OutboundSendOutboxRecord | None:
        async with self._lock:
            current = self._records.get(outbox_id)
            if current is None or current.status is not OutboundSendOutboxStatus.PENDING:
                return None
            if current.next_attempt_at is not None and current.next_attempt_at > claimed_at:
                return None
            updated = replace(
                current,
                status=OutboundSendOutboxStatus.CLAIMED,
                claim_id=claim_id,
                worker_id=worker_id,
                claimed_at=claimed_at,
                updated_at=claimed_at,
                attempt_count=current.attempt_count + 1,
                last_error=None,
            )
            self._records[outbox_id] = updated
            return updated

    async def mark_outbound_send_outbox_sent(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        provider_message_id: str,
        sent_at: datetime,
    ) -> OutboundSendOutboxRecord | None:
        async with self._lock:
            current = self._matching_claim(outbox_id, claim_id)
            if current is None:
                return None
            updated = replace(
                current,
                status=OutboundSendOutboxStatus.SENT,
                sent_at=sent_at,
                updated_at=sent_at,
                provider_message_id=provider_message_id,
                last_error=None,
            )
            self._records[outbox_id] = updated
            return updated

    async def reschedule_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        next_attempt_at: datetime,
        error: str,
    ) -> OutboundSendOutboxRecord | None:
        async with self._lock:
            current = self._matching_claim(outbox_id, claim_id)
            if current is None:
                return None
            updated = replace(
                current,
                status=OutboundSendOutboxStatus.PENDING,
                claim_id=None,
                worker_id=None,
                claimed_at=None,
                updated_at=next_attempt_at,
                next_attempt_at=next_attempt_at,
                last_error=error,
                metadata={
                    **current.metadata,
                    "retry.next_attempt_at": next_attempt_at.isoformat(),
                    "retry.last_error": error,
                },
            )
            self._records[outbox_id] = updated
            return updated

    async def dead_letter_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
        error: str,
        dead_lettered_at: datetime,
    ) -> OutboundSendOutboxRecord | None:
        async with self._lock:
            current = self._matching_claim(outbox_id, claim_id)
            if current is None:
                return None
            updated = replace(
                current,
                status=OutboundSendOutboxStatus.DEAD_LETTERED,
                updated_at=dead_lettered_at,
                last_error=error,
                metadata={
                    **current.metadata,
                    "dead_lettered_at": dead_lettered_at.isoformat(),
                    "dead_letter.reason": error,
                },
            )
            self._records[outbox_id] = updated
            return updated

    async def requeue_stale_outbound_send_outbox(
        self,
        *,
        outbox_id: OutboundSendOutboxId,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
    ) -> OutboundSendOutboxRecord | None:
        async with self._lock:
            current = self._records.get(outbox_id)
            if current is None or current.status is not OutboundSendOutboxStatus.CLAIMED:
                return None
            if current.claimed_at is None or current.claimed_at > stale_before:
                return None
            updated = replace(
                current,
                status=OutboundSendOutboxStatus.PENDING,
                claim_id=None,
                worker_id=None,
                claimed_at=None,
                updated_at=requeued_at,
                last_error=reason,
                metadata={
                    **current.metadata,
                    "reconciler.reason": reason,
                    "reconciler.requeued_at": requeued_at.isoformat(),
                },
            )
            self._records[outbox_id] = updated
            return updated

    def _matching_claim(
        self,
        outbox_id: OutboundSendOutboxId,
        claim_id: OutboundSendClaimId,
    ) -> OutboundSendOutboxRecord | None:
        current = self._records.get(outbox_id)
        if current is None:
            return None
        if current.status is not OutboundSendOutboxStatus.CLAIMED:
            return None
        if current.claim_id != claim_id:
            return None
        return current


def make_outbound_send_outbox_record(
    *,
    tenant_id: str,
    channel: str,
    action: str,
    draft_id: str | uuid.UUID,
    proposal_id: str | uuid.UUID,
    session_id: str,
    dispatch_id: str,
    governance_decision_id: str | uuid.UUID,
    recipient: str,
    draft_body_sha256: str,
    created_at: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> OutboundSendOutboxRecord:
    tenant = _required_text("tenant_id", tenant_id)
    normalized_channel = _required_text("channel", channel).lower()
    normalized_action = _required_text("action", action)
    parsed_draft_id = _uuid("draft_id", draft_id)
    parsed_proposal_id = _uuid("proposal_id", proposal_id)
    parsed_decision_id = _uuid("governance_decision_id", governance_decision_id)
    recipient_text = _required_text("recipient", recipient)
    digest = _required_sha256(draft_body_sha256)
    outbox_id = derive_outbound_send_outbox_id(
        tenant_id=tenant,
        draft_id=parsed_draft_id,
        channel=normalized_channel,
        recipient=recipient_text,
        action=normalized_action,
    )
    now = created_at or datetime.now(tz=timezone.utc)
    return OutboundSendOutboxRecord(
        outbox_id=outbox_id,
        tenant_id=tenant,
        channel=normalized_channel,
        action=normalized_action,
        draft_id=parsed_draft_id,
        proposal_id=parsed_proposal_id,
        session_id=_required_text("session_id", session_id),
        dispatch_id=_required_text("dispatch_id", dispatch_id),
        governance_decision_id=parsed_decision_id,
        recipient=recipient_text,
        draft_body_sha256=digest,
        status=OutboundSendOutboxStatus.PENDING,
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )


def derive_outbound_send_outbox_id(
    *,
    tenant_id: str,
    draft_id: str | uuid.UUID,
    channel: str,
    recipient: str,
    action: str,
) -> OutboundSendOutboxId:
    seed = "|".join(
        (
            _required_text("tenant_id", tenant_id),
            str(_uuid("draft_id", draft_id)),
            _required_text("channel", channel).lower(),
            _required_text("recipient", recipient),
            _required_text("action", action),
        )
    )
    return OutboundSendOutboxId(uuid.uuid5(_OUTBOX_NAMESPACE, seed))


def derive_outbound_send_claim_id(
    *,
    outbox_id: OutboundSendOutboxId | uuid.UUID | str,
    worker_id: str,
    attempt_count: int,
) -> OutboundSendClaimId:
    if attempt_count < 1:
        raise ValueError("attempt_count must be positive")
    seed = "|".join(
        (
            str(_uuid("outbox_id", outbox_id)),
            _required_text("worker_id", worker_id),
            str(attempt_count),
        )
    )
    return OutboundSendClaimId(uuid.uuid5(_CLAIM_NAMESPACE, seed))


def as_outbound_send_outbox_id(
    value: OutboundSendOutboxId | uuid.UUID | str,
) -> OutboundSendOutboxId:
    return OutboundSendOutboxId(_uuid("outbox_id", value))


def as_outbound_send_claim_id(
    value: OutboundSendClaimId | uuid.UUID | str,
) -> OutboundSendClaimId:
    return OutboundSendClaimId(_uuid("claim_id", value))


def _outbox_record_to_values(record: OutboundSendOutboxRecord) -> dict[str, Any]:
    return {
        "outbox_id": record.outbox_id,
        "tenant_id": record.tenant_id,
        "channel": record.channel,
        "action": record.action,
        "draft_id": record.draft_id,
        "proposal_id": record.proposal_id,
        "session_id": record.session_id,
        "dispatch_id": record.dispatch_id,
        "governance_decision_id": record.governance_decision_id,
        "recipient": record.recipient,
        "draft_body_sha256": record.draft_body_sha256,
        "status": record.status.value,
        "claim_id": record.claim_id,
        "worker_id": record.worker_id,
        "attempt_count": record.attempt_count,
        "next_attempt_at": record.next_attempt_at,
        "claimed_at": record.claimed_at,
        "sent_at": record.sent_at,
        "provider_message_id": record.provider_message_id,
        "last_error": record.last_error,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "metadata_json": dict(record.metadata),
    }


def _row_to_outbox_record(row: OutboundSendOutboxRow) -> OutboundSendOutboxRecord:
    return OutboundSendOutboxRecord(
        outbox_id=OutboundSendOutboxId(row.outbox_id),
        tenant_id=row.tenant_id,
        channel=row.channel,
        action=row.action,
        draft_id=row.draft_id,
        proposal_id=row.proposal_id,
        session_id=row.session_id,
        dispatch_id=row.dispatch_id,
        governance_decision_id=row.governance_decision_id,
        recipient=row.recipient,
        draft_body_sha256=row.draft_body_sha256,
        status=OutboundSendOutboxStatus(row.status),
        claim_id=(
            OutboundSendClaimId(row.claim_id)
            if row.claim_id is not None
            else None
        ),
        worker_id=row.worker_id,
        attempt_count=row.attempt_count,
        next_attempt_at=row.next_attempt_at,
        claimed_at=row.claimed_at,
        sent_at=row.sent_at,
        provider_message_id=row.provider_message_id,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=dict(row.metadata_json),
    )


def _unique_key(
    record: OutboundSendOutboxRecord,
) -> tuple[str, uuid.UUID, str, str, str]:
    return (
        record.tenant_id,
        record.draft_id,
        record.channel,
        record.recipient,
        record.action,
    )


def _required_text(name: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _uuid(name: str, value: str | uuid.UUID) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid UUID") from exc


def _required_sha256(value: str) -> str:
    text = _required_text("draft_body_sha256", value).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError("draft_body_sha256 must be a lowercase sha256 hex digest")
    return text


__all__ = [
    "InMemoryOutboundSendOutboxPersistence",
    "OutboundSendClaimId",
    "OutboundSendOutboxClaimResult",
    "OutboundSendOutboxId",
    "OutboundSendOutboxPage",
    "OutboundSendOutboxPersistenceProtocol",
    "OutboundSendOutboxQuery",
    "OutboundSendOutboxRecord",
    "OutboundSendOutboxRuntime",
    "OutboundSendOutboxStatus",
    "OutboundSendOutboxSweepResult",
    "PostgresOutboundSendOutboxPersistence",
    "as_outbound_send_claim_id",
    "as_outbound_send_outbox_id",
    "derive_outbound_send_claim_id",
    "derive_outbound_send_outbox_id",
    "make_outbound_send_outbox_record",
]
