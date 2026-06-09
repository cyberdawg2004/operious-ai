"""Durable dispatch intent outbox for captured boundary ingress."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, NewType, Protocol, cast

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult

from app.boundary.db.models import IngressDispatchOutboxRow
from app.boundary.enums import (
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import BoundaryIngressId
from app.boundary.persistence.records import BoundaryIngressRecord
from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page

IngressDispatchOutboxId = NewType("IngressDispatchOutboxId", uuid.UUID)
IngressDispatchClaimId = NewType("IngressDispatchClaimId", uuid.UUID)

_OUTBOX_NAMESPACE = uuid.UUID("69a1124a-3f94-4e5f-94b3-4c68a4c567a0")
_CLAIM_NAMESPACE = uuid.UUID("ab4ea0b5-a3f6-4ae7-8e51-a42ec5edc8f9")
_ALLOWED_CHANNELS = frozenset({"email", "whatsapp", "shopify"})
_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60
_DEFAULT_RETRY_BASE_SECONDS = 30
_MAX_RETRY_DELAY_SECONDS = 3600


class IngressDispatchOutboxStatus(StrEnum):
    """Lifecycle state of one captured-ingress dispatch intent."""

    PENDING = "pending"
    CLAIMED = "claimed"
    DISPATCHED = "dispatched"
    DEAD_LETTERED = "dead_lettered"


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class IngressDispatchOutboxRecord:
    outbox_id: IngressDispatchOutboxId
    ingress_id: BoundaryIngressId
    tenant_id: str
    channel: str
    status: IngressDispatchOutboxStatus
    created_at: datetime
    next_attempt_at: datetime | None = None
    claimed_at: datetime | None = None
    dispatched_at: datetime | None = None
    claim_id: IngressDispatchClaimId | None = None
    worker_id: str | None = None
    attempt_count: int = 0
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class IngressDispatchOutboxQuery:
    outbox_id: IngressDispatchOutboxId | None = None
    ingress_id: BoundaryIngressId | None = None
    tenant_id: str | None = None
    status: IngressDispatchOutboxStatus | None = None
    due_before_or_at: datetime | None = None
    claimed_before_or_at: datetime | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class IngressDispatchOutboxPage:
    records: tuple[IngressDispatchOutboxRecord, ...]
    total: int
    limit: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class IngressDispatchOutboxClaimResult:
    claimed: bool
    outbox: IngressDispatchOutboxRecord | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IngressDispatchOutboxRequeueResult:
    requeued: bool
    outbox: IngressDispatchOutboxRecord | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IngressDispatchOutboxSweepResult:
    scanned: int
    requeued: tuple[IngressDispatchOutboxRequeueResult, ...] = ()
    refused: tuple[IngressDispatchOutboxRequeueResult, ...] = ()
    dead_lettered: tuple[IngressDispatchOutboxRecord, ...] = ()

    @property
    def requeued_count(self) -> int:
        return len(self.requeued)

    @property
    def refused_count(self) -> int:
        return len(self.refused)

    @property
    def dead_lettered_count(self) -> int:
        return len(self.dead_lettered)


class IngressDispatchOutboxPersistenceProtocol(Protocol):
    async def create_outbox_for_ingress(
        self,
        record: BoundaryIngressRecord,
        *,
        created_at: datetime | None = None,
    ) -> IngressDispatchOutboxRecord | None: ...

    async def bulk_create_outbox_for_ingress(
        self,
        records: tuple[BoundaryIngressRecord, ...],
        *,
        created_at: datetime | None = None,
    ) -> tuple[IngressDispatchOutboxRecord, ...]: ...

    async def get_ingress_dispatch_outbox(
        self,
        outbox_id: IngressDispatchOutboxId,
    ) -> IngressDispatchOutboxRecord | None: ...

    async def get_ingress_dispatch_outbox_by_ingress(
        self,
        ingress_id: BoundaryIngressId,
    ) -> IngressDispatchOutboxRecord | None: ...

    async def list_ingress_dispatch_outbox(
        self,
        query: IngressDispatchOutboxQuery,
    ) -> IngressDispatchOutboxPage: ...

    async def claim_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        worker_id: str,
        claimed_at: datetime,
    ) -> IngressDispatchOutboxRecord | None: ...

    async def mark_ingress_dispatch_outbox_dispatched(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        dispatched_at: datetime,
    ) -> IngressDispatchOutboxRecord | None: ...

    async def reschedule_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        next_attempt_at: datetime,
        error: str,
    ) -> IngressDispatchOutboxRecord | None: ...

    async def dead_letter_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        error: str,
        dead_lettered_at: datetime,
    ) -> IngressDispatchOutboxRecord | None: ...

    async def requeue_stale_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
    ) -> IngressDispatchOutboxRecord | None: ...


class IngressDispatchOutboxRuntime:
    """State-transition facade for ingress dispatch outbox rows."""

    def __init__(
        self,
        *,
        persistence: IngressDispatchOutboxPersistenceProtocol,
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

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    async def get_outbox(
        self,
        outbox_id: IngressDispatchOutboxId | str | uuid.UUID,
    ) -> IngressDispatchOutboxRecord | None:
        return await self._persistence.get_ingress_dispatch_outbox(
            as_ingress_dispatch_outbox_id(outbox_id)
        )

    async def get_outbox_by_ingress(
        self,
        ingress_id: BoundaryIngressId | str | uuid.UUID,
    ) -> IngressDispatchOutboxRecord | None:
        return await self._persistence.get_ingress_dispatch_outbox_by_ingress(
            as_boundary_ingress_id(ingress_id)
        )

    async def list_outbox(
        self,
        query: IngressDispatchOutboxQuery,
    ) -> IngressDispatchOutboxPage:
        return await self._persistence.list_ingress_dispatch_outbox(query)

    async def claim_due_outbox(
        self,
        *,
        worker_id: str,
        claimed_at: datetime | None = None,
        outbox_id: IngressDispatchOutboxId | str | uuid.UUID | None = None,
        ingress_id: BoundaryIngressId | str | uuid.UUID | None = None,
        allow_exhausted: bool = False,
    ) -> IngressDispatchOutboxClaimResult:
        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        if outbox_id is None and ingress_id is None:
            raise ValueError("outbox_id or ingress_id is required")
        now = claimed_at or datetime.now(tz=timezone.utc)
        if outbox_id is not None:
            current = await self.get_outbox(outbox_id)
        else:
            if ingress_id is None:
                raise ValueError("outbox_id or ingress_id is required")
            current = await self.get_outbox_by_ingress(ingress_id)
        if current is None:
            return IngressDispatchOutboxClaimResult(
                claimed=False,
                outbox=None,
                reason="outbox_not_found",
            )
        if current.status is not IngressDispatchOutboxStatus.PENDING:
            return IngressDispatchOutboxClaimResult(
                claimed=False,
                outbox=current,
                reason=f"outbox_not_claimable:{current.status.value}",
            )
        if current.next_attempt_at is not None and current.next_attempt_at > now:
            return IngressDispatchOutboxClaimResult(
                claimed=False,
                outbox=current,
                reason="outbox_not_due",
            )
        if not allow_exhausted and self.should_dead_letter(current, now=now):
            return IngressDispatchOutboxClaimResult(
                claimed=False,
                outbox=current,
                reason="outbox_retry_budget_exhausted",
            )
        claim_id = derive_ingress_dispatch_claim_id(
            outbox_id=current.outbox_id,
            worker_id=worker_id,
            attempt_count=current.attempt_count + 1,
        )
        claimed = await self._persistence.claim_ingress_dispatch_outbox(
            outbox_id=current.outbox_id,
            claim_id=claim_id,
            worker_id=worker_id,
            claimed_at=now,
        )
        if claimed is not None:
            return IngressDispatchOutboxClaimResult(claimed=True, outbox=claimed)
        refreshed = await self.get_outbox(current.outbox_id)
        return IngressDispatchOutboxClaimResult(
            claimed=False,
            outbox=refreshed,
            reason=(
                "outbox_not_found"
                if refreshed is None
                else f"outbox_not_claimable:{refreshed.status.value}"
            ),
        )

    async def mark_dispatched(
        self,
        *,
        outbox_id: IngressDispatchOutboxId | str | uuid.UUID,
        claim_id: IngressDispatchClaimId | str | uuid.UUID,
        dispatched_at: datetime | None = None,
    ) -> IngressDispatchOutboxRecord | None:
        return await self._persistence.mark_ingress_dispatch_outbox_dispatched(
            outbox_id=as_ingress_dispatch_outbox_id(outbox_id),
            claim_id=as_ingress_dispatch_claim_id(claim_id),
            dispatched_at=dispatched_at or datetime.now(tz=timezone.utc),
        )

    async def reschedule(
        self,
        *,
        outbox: IngressDispatchOutboxRecord,
        claim_id: IngressDispatchClaimId | str | uuid.UUID,
        error: str,
        now: datetime | None = None,
        retry_after_seconds: int | None = None,
    ) -> IngressDispatchOutboxRecord | None:
        ts = now or datetime.now(tz=timezone.utc)
        seconds = (
            retry_after_seconds
            if retry_after_seconds is not None and retry_after_seconds > 0
            else self.retry_delay_seconds(outbox.attempt_count)
        )
        return await self._persistence.reschedule_ingress_dispatch_outbox(
            outbox_id=outbox.outbox_id,
            claim_id=as_ingress_dispatch_claim_id(claim_id),
            next_attempt_at=ts + timedelta(seconds=seconds),
            error=error,
        )

    async def dead_letter(
        self,
        *,
        outbox_id: IngressDispatchOutboxId | str | uuid.UUID,
        claim_id: IngressDispatchClaimId | str | uuid.UUID,
        error: str,
        dead_lettered_at: datetime | None = None,
    ) -> IngressDispatchOutboxRecord | None:
        return await self._persistence.dead_letter_ingress_dispatch_outbox(
            outbox_id=as_ingress_dispatch_outbox_id(outbox_id),
            claim_id=as_ingress_dispatch_claim_id(claim_id),
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
        reason: str = "ingress dispatch claim expired",
    ) -> IngressDispatchOutboxSweepResult:
        if limit < 1:
            raise ValueError("limit must be positive")
        page = await self.list_outbox(
            IngressDispatchOutboxQuery(
                tenant_id=tenant_id,
                status=IngressDispatchOutboxStatus.CLAIMED,
                claimed_before_or_at=stale_before,
                limit=limit,
            )
        )
        ts = requeued_at or datetime.now(tz=timezone.utc)
        requeued: list[IngressDispatchOutboxRequeueResult] = []
        refused: list[IngressDispatchOutboxRequeueResult] = []
        for outbox in page.records:
            updated = await self._persistence.requeue_stale_ingress_dispatch_outbox(
                outbox_id=outbox.outbox_id,
                stale_before=stale_before,
                requeued_at=ts,
                reason=reason,
            )
            result = IngressDispatchOutboxRequeueResult(
                requeued=updated is not None,
                outbox=updated or await self.get_outbox(outbox.outbox_id),
                reason=None if updated is not None else "outbox_not_stale",
            )
            if result.requeued:
                requeued.append(result)
            else:
                refused.append(result)
        return IngressDispatchOutboxSweepResult(
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
        reason: str = "ingress dispatch retry budget exhausted",
    ) -> IngressDispatchOutboxSweepResult:
        if limit < 1:
            raise ValueError("limit must be positive")
        ts = now or datetime.now(tz=timezone.utc)
        page = await self.list_outbox(
            IngressDispatchOutboxQuery(
                tenant_id=tenant_id,
                status=IngressDispatchOutboxStatus.PENDING,
                due_before_or_at=ts,
                limit=limit,
            )
        )
        dead_lettered: list[IngressDispatchOutboxRecord] = []
        for outbox in page.records:
            if not self.should_dead_letter(outbox, now=ts):
                continue
            claim = await self.claim_due_outbox(
                outbox_id=outbox.outbox_id,
                worker_id="reconciler:ingress-dispatch-dead-letter",
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
        return IngressDispatchOutboxSweepResult(
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
        outbox: IngressDispatchOutboxRecord,
        *,
        now: datetime | None = None,
    ) -> bool:
        ts = now or datetime.now(tz=timezone.utc)
        if outbox.attempt_count >= self._max_attempts:
            return True
        return outbox.created_at + timedelta(seconds=self._max_age_seconds) <= ts


class PostgresIngressDispatchOutboxPersistence(BaseRepository):
    """Postgres-backed ingress dispatch outbox persistence."""

    async def create_outbox_for_ingress(
        self,
        record: BoundaryIngressRecord,
        *,
        created_at: datetime | None = None,
    ) -> IngressDispatchOutboxRecord | None:
        created = make_ingress_dispatch_outbox_record(record, created_at=created_at)
        if created is None:
            return None
        stmt = (
            pg_insert(IngressDispatchOutboxRow)
            .values(_outbox_record_to_values(created))
            .on_conflict_do_nothing(index_elements=["ingress_id"])
            .returning(IngressDispatchOutboxRow)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return await self.get_ingress_dispatch_outbox_by_ingress(record.ingress_id)
        return _row_to_outbox_record(row)

    async def bulk_create_outbox_for_ingress(
        self,
        records: tuple[BoundaryIngressRecord, ...],
        *,
        created_at: datetime | None = None,
    ) -> tuple[IngressDispatchOutboxRecord, ...]:
        outbox_records = tuple(
            record
            for record in (
                make_ingress_dispatch_outbox_record(record, created_at=created_at)
                for record in records
            )
            if record is not None
        )
        if not outbox_records:
            return ()
        stmt = (
            pg_insert(IngressDispatchOutboxRow)
            .values([_outbox_record_to_values(record) for record in outbox_records])
            .on_conflict_do_nothing(index_elements=["ingress_id"])
            .returning(IngressDispatchOutboxRow)
        )
        rows = (await self.session.execute(stmt)).scalars().all()  # bounded
        return tuple(_row_to_outbox_record(row) for row in rows)

    async def get_ingress_dispatch_outbox(
        self,
        outbox_id: IngressDispatchOutboxId,
    ) -> IngressDispatchOutboxRecord | None:
        stmt = select(IngressDispatchOutboxRow).where(
            IngressDispatchOutboxRow.outbox_id == outbox_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_outbox_record(row)

    async def get_ingress_dispatch_outbox_by_ingress(
        self,
        ingress_id: BoundaryIngressId,
    ) -> IngressDispatchOutboxRecord | None:
        stmt = select(IngressDispatchOutboxRow).where(
            IngressDispatchOutboxRow.ingress_id == ingress_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_outbox_record(row)

    async def list_ingress_dispatch_outbox(
        self,
        query: IngressDispatchOutboxQuery,
    ) -> IngressDispatchOutboxPage:
        stmt = select(IngressDispatchOutboxRow)
        if query.outbox_id is not None:
            stmt = stmt.where(IngressDispatchOutboxRow.outbox_id == query.outbox_id)
        if query.ingress_id is not None:
            stmt = stmt.where(IngressDispatchOutboxRow.ingress_id == query.ingress_id)
        if query.tenant_id is not None:
            stmt = stmt.where(IngressDispatchOutboxRow.tenant_id == query.tenant_id)
        if query.status is not None:
            stmt = stmt.where(IngressDispatchOutboxRow.status == query.status.value)
        if query.due_before_or_at is not None:
            stmt = stmt.where(
                or_(
                    IngressDispatchOutboxRow.next_attempt_at.is_(None),
                    IngressDispatchOutboxRow.next_attempt_at <= query.due_before_or_at,
                )
            )
        if query.claimed_before_or_at is not None:
            stmt = stmt.where(
                IngressDispatchOutboxRow.claimed_at.is_not(None),
                IngressDispatchOutboxRow.claimed_at <= query.claimed_before_or_at,
            )
        stmt = stmt.order_by(
            IngressDispatchOutboxRow.next_attempt_at,
            IngressDispatchOutboxRow.created_at,
            IngressDispatchOutboxRow.outbox_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return IngressDispatchOutboxPage(
            records=tuple(_row_to_outbox_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def claim_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        worker_id: str,
        claimed_at: datetime,
    ) -> IngressDispatchOutboxRecord | None:
        stmt = (
            update(IngressDispatchOutboxRow)
            .where(
                IngressDispatchOutboxRow.outbox_id == outbox_id,
                IngressDispatchOutboxRow.status
                == IngressDispatchOutboxStatus.PENDING.value,
                or_(
                    IngressDispatchOutboxRow.next_attempt_at.is_(None),
                    IngressDispatchOutboxRow.next_attempt_at <= claimed_at,
                ),
            )
            .values(
                status=IngressDispatchOutboxStatus.CLAIMED.value,
                claimed_at=claimed_at,
                claim_id=claim_id,
                worker_id=worker_id,
                attempt_count=IngressDispatchOutboxRow.attempt_count + 1,
                last_error=None,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_ingress_dispatch_outbox(outbox_id)

    async def mark_ingress_dispatch_outbox_dispatched(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        dispatched_at: datetime,
    ) -> IngressDispatchOutboxRecord | None:
        stmt = (
            update(IngressDispatchOutboxRow)
            .where(
                IngressDispatchOutboxRow.outbox_id == outbox_id,
                IngressDispatchOutboxRow.status
                == IngressDispatchOutboxStatus.CLAIMED.value,
                IngressDispatchOutboxRow.claim_id == claim_id,
            )
            .values(
                status=IngressDispatchOutboxStatus.DISPATCHED.value,
                dispatched_at=dispatched_at,
                last_error=None,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_ingress_dispatch_outbox(outbox_id)

    async def reschedule_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        next_attempt_at: datetime,
        error: str,
    ) -> IngressDispatchOutboxRecord | None:
        existing = await self.get_ingress_dispatch_outbox(outbox_id)
        metadata = dict(existing.metadata) if existing is not None else {}
        stmt = (
            update(IngressDispatchOutboxRow)
            .where(
                IngressDispatchOutboxRow.outbox_id == outbox_id,
                IngressDispatchOutboxRow.status
                == IngressDispatchOutboxStatus.CLAIMED.value,
                IngressDispatchOutboxRow.claim_id == claim_id,
            )
            .values(
                status=IngressDispatchOutboxStatus.PENDING.value,
                claim_id=None,
                worker_id=None,
                claimed_at=None,
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
        return await self.get_ingress_dispatch_outbox(outbox_id)

    async def dead_letter_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        error: str,
        dead_lettered_at: datetime,
    ) -> IngressDispatchOutboxRecord | None:
        existing = await self.get_ingress_dispatch_outbox(outbox_id)
        metadata = dict(existing.metadata) if existing is not None else {}
        stmt = (
            update(IngressDispatchOutboxRow)
            .where(
                IngressDispatchOutboxRow.outbox_id == outbox_id,
                IngressDispatchOutboxRow.status
                == IngressDispatchOutboxStatus.CLAIMED.value,
                IngressDispatchOutboxRow.claim_id == claim_id,
            )
            .values(
                status=IngressDispatchOutboxStatus.DEAD_LETTERED.value,
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
        return await self.get_ingress_dispatch_outbox(outbox_id)

    async def requeue_stale_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
    ) -> IngressDispatchOutboxRecord | None:
        existing = await self.get_ingress_dispatch_outbox(outbox_id)
        metadata = dict(existing.metadata) if existing is not None else {}
        stmt = (
            update(IngressDispatchOutboxRow)
            .where(
                IngressDispatchOutboxRow.outbox_id == outbox_id,
                IngressDispatchOutboxRow.status
                == IngressDispatchOutboxStatus.CLAIMED.value,
                IngressDispatchOutboxRow.claimed_at.is_not(None),
                IngressDispatchOutboxRow.claimed_at <= stale_before,
            )
            .values(
                status=IngressDispatchOutboxStatus.PENDING.value,
                claim_id=None,
                worker_id=None,
                claimed_at=None,
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
        return await self.get_ingress_dispatch_outbox(outbox_id)


def derive_ingress_dispatch_outbox_id(
    *,
    ingress_id: BoundaryIngressId | uuid.UUID | str,
) -> IngressDispatchOutboxId:
    return IngressDispatchOutboxId(uuid.uuid5(_OUTBOX_NAMESPACE, str(ingress_id)))


def derive_ingress_dispatch_claim_id(
    *,
    outbox_id: IngressDispatchOutboxId | uuid.UUID | str,
    worker_id: str,
    attempt_count: int,
) -> IngressDispatchClaimId:
    if not worker_id:
        raise ValueError("worker_id is required")
    if attempt_count < 1:
        raise ValueError("attempt_count must be >= 1")
    return IngressDispatchClaimId(
        uuid.uuid5(_CLAIM_NAMESPACE, f"{outbox_id}|{worker_id}|{attempt_count}")
    )


def as_ingress_dispatch_outbox_id(
    value: IngressDispatchOutboxId | uuid.UUID | str,
) -> IngressDispatchOutboxId:
    if isinstance(value, uuid.UUID):
        return IngressDispatchOutboxId(value)
    return IngressDispatchOutboxId(uuid.UUID(str(value)))


def as_ingress_dispatch_claim_id(
    value: IngressDispatchClaimId | uuid.UUID | str,
) -> IngressDispatchClaimId:
    if isinstance(value, uuid.UUID):
        return IngressDispatchClaimId(value)
    return IngressDispatchClaimId(uuid.UUID(str(value)))


def as_boundary_ingress_id(
    value: BoundaryIngressId | uuid.UUID | str | object,
) -> BoundaryIngressId:
    if isinstance(value, uuid.UUID):
        return BoundaryIngressId(value)
    return BoundaryIngressId(uuid.UUID(str(value)))


def dispatch_channel_for_ingress(record: BoundaryIngressRecord) -> str | None:
    if record.source_type is BoundarySourceType.TWILIO_VOICE:
        return None
    for candidate in _channel_candidates(record):
        if candidate == "voice":
            return None
        if candidate in _ALLOWED_CHANNELS:
            return candidate
    if record.source_type in {
        BoundarySourceType.EMAIL,
        BoundarySourceType.WHATSAPP,
    }:
        return record.source_type.value
    return None


def is_dispatch_outbox_eligible(record: BoundaryIngressRecord) -> bool:
    return (
        record.tenant_id is not None
        and bool(record.tenant_id.strip())
        and record.normalization_status is BoundaryNormalizationStatus.OK
        and record.replay_disposition is BoundaryReplayDisposition.NEW
        and record.event_id is not None
        and dispatch_channel_for_ingress(record) is not None
    )


def make_ingress_dispatch_outbox_record(
    record: BoundaryIngressRecord,
    *,
    created_at: datetime | None = None,
) -> IngressDispatchOutboxRecord | None:
    if not is_dispatch_outbox_eligible(record):
        return None
    channel = dispatch_channel_for_ingress(record)
    if channel is None or record.tenant_id is None:
        return None
    ts = created_at or record.received_at
    return IngressDispatchOutboxRecord(
        outbox_id=derive_ingress_dispatch_outbox_id(ingress_id=record.ingress_id),
        ingress_id=record.ingress_id,
        tenant_id=record.tenant_id,
        channel=channel,
        status=IngressDispatchOutboxStatus.PENDING,
        created_at=ts,
        next_attempt_at=ts,
        metadata={
            "boundary.ingress_id": str(record.ingress_id),
            "boundary.event_id": (
                str(record.event_id) if record.event_id is not None else None
            ),
            "boundary.source_type": record.source_type.value,
            "boundary.external_message_id": record.external_message_id,
        },
    )


def _channel_candidates(record: BoundaryIngressRecord) -> tuple[str, ...]:
    values: list[str] = []
    for mapping in (record.metadata, record.canonical_payload):
        for key in (
            "tenant_channel.channel_type",
            "batch.channel_type",
            "ticket.channel",
            "channel_type",
            "channel",
        ):
            raw = mapping.get(key)
            if isinstance(raw, str):
                values.append(raw.strip().lower())
    values.append(record.source_type.value)
    return tuple(value for value in values if value)


def _outbox_record_to_values(
    record: IngressDispatchOutboxRecord,
) -> dict[str, Any]:
    return {
        "outbox_id": record.outbox_id,
        "ingress_id": record.ingress_id,
        "tenant_id": record.tenant_id,
        "channel": record.channel,
        "status": record.status.value,
        "claim_id": record.claim_id,
        "worker_id": record.worker_id,
        "attempt_count": record.attempt_count,
        "next_attempt_at": record.next_attempt_at,
        "created_at": record.created_at,
        "claimed_at": record.claimed_at,
        "dispatched_at": record.dispatched_at,
        "last_error": record.last_error,
        "metadata_json": dict(record.metadata),
    }


def _row_to_outbox_record(
    row: IngressDispatchOutboxRow,
) -> IngressDispatchOutboxRecord:
    return IngressDispatchOutboxRecord(
        outbox_id=IngressDispatchOutboxId(row.outbox_id),
        ingress_id=BoundaryIngressId(row.ingress_id),
        tenant_id=row.tenant_id,
        channel=row.channel,
        status=IngressDispatchOutboxStatus(row.status),
        claim_id=(
            IngressDispatchClaimId(row.claim_id) if row.claim_id is not None else None
        ),
        worker_id=row.worker_id,
        attempt_count=row.attempt_count,
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        claimed_at=row.claimed_at,
        dispatched_at=row.dispatched_at,
        last_error=row.last_error,
        metadata=dict(row.metadata_json or {}),
    )


__all__ = [
    "IngressDispatchClaimId",
    "IngressDispatchOutboxClaimResult",
    "IngressDispatchOutboxId",
    "IngressDispatchOutboxPage",
    "IngressDispatchOutboxPersistenceProtocol",
    "IngressDispatchOutboxQuery",
    "IngressDispatchOutboxRecord",
    "IngressDispatchOutboxRequeueResult",
    "IngressDispatchOutboxRuntime",
    "IngressDispatchOutboxStatus",
    "IngressDispatchOutboxSweepResult",
    "PostgresIngressDispatchOutboxPersistence",
    "as_boundary_ingress_id",
    "as_ingress_dispatch_claim_id",
    "as_ingress_dispatch_outbox_id",
    "derive_ingress_dispatch_claim_id",
    "derive_ingress_dispatch_outbox_id",
    "dispatch_channel_for_ingress",
    "is_dispatch_outbox_eligible",
    "make_ingress_dispatch_outbox_record",
]
