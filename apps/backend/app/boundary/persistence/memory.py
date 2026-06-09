"""In-memory boundary persistence (test + dev backend)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from app.boundary.exceptions import (
    BoundaryPersistenceError,
    WebhookReplayError,
)
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryIngressId,
)
from app.boundary.ingress_dispatch_outbox import (
    IngressDispatchClaimId,
    IngressDispatchOutboxId,
    IngressDispatchOutboxPage,
    IngressDispatchOutboxQuery,
    IngressDispatchOutboxRecord,
    IngressDispatchOutboxStatus,
    make_ingress_dispatch_outbox_record,
)
from app.boundary.persistence.models import (
    BoundaryEgressQuery,
    BoundaryIngressQuery,
    BoundaryRecordPage,
)
from app.boundary.persistence.records import (
    BoundaryEgressRecord,
    BoundaryIngressRecord,
    WebhookNonceRecord,
)


class InMemoryBoundaryPersistence:
    """Write-once, deterministically ordered in-memory implementation."""

    __slots__ = (
        "_ingress",
        "_ingress_by_event_id",
        "_ingress_by_replay_key",
        "_ingress_dispatch_outbox",
        "_ingress_dispatch_outbox_by_ingress",
        "_egress",
        "_webhook_nonces",
        "_lock",
    )

    def __init__(self) -> None:
        self._ingress: dict[BoundaryIngressId, BoundaryIngressRecord] = {}
        self._ingress_by_replay_key: dict[uuid.UUID, BoundaryIngressId] = {}
        self._ingress_by_event_id: dict[uuid.UUID, BoundaryIngressId] = {}
        self._ingress_dispatch_outbox: dict[
            IngressDispatchOutboxId, IngressDispatchOutboxRecord
        ] = {}
        self._ingress_dispatch_outbox_by_ingress: dict[
            BoundaryIngressId, IngressDispatchOutboxId
        ] = {}
        self._egress: dict[BoundaryEgressId, BoundaryEgressRecord] = {}
        self._webhook_nonces: dict[tuple[str, str, str], WebhookNonceRecord] = {}
        self._lock = asyncio.Lock()

    async def save_ingress(
        self, record: BoundaryIngressRecord
    ) -> BoundaryIngressRecord:
        async with self._lock:
            existing = self._resolve_duplicate_ingress(record)
            if existing is not None:
                return existing
            self._ingress[record.ingress_id] = record
            if record.replay_key is not None:
                self._ingress_by_replay_key[record.replay_key] = record.ingress_id
            if record.event_id is not None:
                self._ingress_by_event_id[record.event_id] = record.ingress_id
            self._create_ingress_dispatch_outbox_locked(record)
            return record

    async def get_existing_ingress_ids(
        self,
        ingress_ids: Sequence[BoundaryIngressId],
        *,
        expected_tenant_id: str,
    ) -> set[BoundaryIngressId]:
        ids = set(ingress_ids)
        async with self._lock:
            return {
                ingress_id
                for ingress_id, record in self._ingress.items()
                if ingress_id in ids and record.tenant_id == expected_tenant_id
            }

    async def bulk_insert_ingress_records(
        self,
        records: Sequence[BoundaryIngressRecord],
    ) -> set[BoundaryIngressId]:
        inserted: set[BoundaryIngressId] = set()
        async with self._lock:
            for record in records:
                if self._resolve_duplicate_ingress(record) is not None:
                    continue
                self._ingress[record.ingress_id] = record
                if record.replay_key is not None:
                    self._ingress_by_replay_key[record.replay_key] = record.ingress_id
                if record.event_id is not None:
                    self._ingress_by_event_id[record.event_id] = record.ingress_id
                self._create_ingress_dispatch_outbox_locked(record)
                inserted.add(record.ingress_id)
        return inserted

    async def create_outbox_for_ingress(
        self,
        record: BoundaryIngressRecord,
        *,
        created_at: datetime | None = None,
    ) -> IngressDispatchOutboxRecord | None:
        async with self._lock:
            return self._create_ingress_dispatch_outbox_locked(
                record,
                created_at=created_at,
            )

    async def bulk_create_outbox_for_ingress(
        self,
        records: tuple[BoundaryIngressRecord, ...],
        *,
        created_at: datetime | None = None,
    ) -> tuple[IngressDispatchOutboxRecord, ...]:
        created: list[IngressDispatchOutboxRecord] = []
        async with self._lock:
            for record in records:
                outbox = self._create_ingress_dispatch_outbox_locked(
                    record,
                    created_at=created_at,
                )
                if outbox is not None:
                    created.append(outbox)
        return tuple(created)

    async def get_ingress_dispatch_outbox(
        self,
        outbox_id: IngressDispatchOutboxId,
    ) -> IngressDispatchOutboxRecord | None:
        async with self._lock:
            return self._ingress_dispatch_outbox.get(outbox_id)

    async def get_ingress_dispatch_outbox_by_ingress(
        self,
        ingress_id: BoundaryIngressId,
    ) -> IngressDispatchOutboxRecord | None:
        async with self._lock:
            outbox_id = self._ingress_dispatch_outbox_by_ingress.get(ingress_id)
            if outbox_id is None:
                return None
            return self._ingress_dispatch_outbox.get(outbox_id)

    async def list_ingress_dispatch_outbox(
        self,
        query: IngressDispatchOutboxQuery,
    ) -> IngressDispatchOutboxPage:
        async with self._lock:
            records = list(self._ingress_dispatch_outbox.values())
        if query.outbox_id is not None:
            records = [r for r in records if r.outbox_id == query.outbox_id]
        if query.ingress_id is not None:
            records = [r for r in records if r.ingress_id == query.ingress_id]
        if query.tenant_id is not None:
            records = [r for r in records if r.tenant_id == query.tenant_id]
        if query.status is not None:
            records = [r for r in records if r.status is query.status]
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
        records.sort(
            key=lambda r: (
                r.next_attempt_at or r.created_at,
                r.created_at,
                str(r.outbox_id),
            )
        )
        total = len(records)
        if query.offset:
            records = records[query.offset :]
        records = records[: query.limit]
        return IngressDispatchOutboxPage(
            records=tuple(records),
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    async def claim_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        worker_id: str,
        claimed_at: datetime,
    ) -> IngressDispatchOutboxRecord | None:
        async with self._lock:
            current = self._ingress_dispatch_outbox.get(outbox_id)
            if current is None:
                return None
            if current.status is not IngressDispatchOutboxStatus.PENDING:
                return None
            if (
                current.next_attempt_at is not None
                and current.next_attempt_at > claimed_at
            ):
                return None
            updated = _replace_outbox(
                current,
                status=IngressDispatchOutboxStatus.CLAIMED,
                claim_id=claim_id,
                worker_id=worker_id,
                claimed_at=claimed_at,
                attempt_count=current.attempt_count + 1,
                last_error=None,
            )
            self._ingress_dispatch_outbox[outbox_id] = updated
            return updated

    async def mark_ingress_dispatch_outbox_dispatched(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        dispatched_at: datetime,
    ) -> IngressDispatchOutboxRecord | None:
        async with self._lock:
            current = self._matching_claim_locked(outbox_id, claim_id)
            if current is None:
                return None
            updated = _replace_outbox(
                current,
                status=IngressDispatchOutboxStatus.DISPATCHED,
                dispatched_at=dispatched_at,
                last_error=None,
            )
            self._ingress_dispatch_outbox[outbox_id] = updated
            return updated

    async def reschedule_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        next_attempt_at: datetime,
        error: str,
    ) -> IngressDispatchOutboxRecord | None:
        async with self._lock:
            current = self._matching_claim_locked(outbox_id, claim_id)
            if current is None:
                return None
            updated = _replace_outbox(
                current,
                status=IngressDispatchOutboxStatus.PENDING,
                claim_id=None,
                worker_id=None,
                claimed_at=None,
                next_attempt_at=next_attempt_at,
                last_error=error,
                metadata={
                    **dict(current.metadata),
                    "retry.next_attempt_at": next_attempt_at.isoformat(),
                    "retry.last_error": error,
                },
            )
            self._ingress_dispatch_outbox[outbox_id] = updated
            return updated

    async def dead_letter_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
        error: str,
        dead_lettered_at: datetime,
    ) -> IngressDispatchOutboxRecord | None:
        async with self._lock:
            current = self._matching_claim_locked(outbox_id, claim_id)
            if current is None:
                return None
            updated = _replace_outbox(
                current,
                status=IngressDispatchOutboxStatus.DEAD_LETTERED,
                last_error=error,
                metadata={
                    **dict(current.metadata),
                    "dead_lettered_at": dead_lettered_at.isoformat(),
                    "dead_letter.reason": error,
                },
            )
            self._ingress_dispatch_outbox[outbox_id] = updated
            return updated

    async def requeue_stale_ingress_dispatch_outbox(
        self,
        *,
        outbox_id: IngressDispatchOutboxId,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
    ) -> IngressDispatchOutboxRecord | None:
        async with self._lock:
            current = self._ingress_dispatch_outbox.get(outbox_id)
            if current is None:
                return None
            if current.status is not IngressDispatchOutboxStatus.CLAIMED:
                return None
            if current.claimed_at is None or current.claimed_at > stale_before:
                return None
            updated = _replace_outbox(
                current,
                status=IngressDispatchOutboxStatus.PENDING,
                claim_id=None,
                worker_id=None,
                claimed_at=None,
                last_error=reason,
                metadata={
                    **dict(current.metadata),
                    "reconciler.reason": reason,
                    "reconciler.requeued_at": requeued_at.isoformat(),
                },
            )
            self._ingress_dispatch_outbox[outbox_id] = updated
            return updated

    async def save_egress(self, record: BoundaryEgressRecord) -> None:
        async with self._lock:
            if record.governance_decision_id is None:
                raise BoundaryPersistenceError(
                    "new egress rows require governance_decision_id"
                )
            if record.egress_id in self._egress:
                raise BoundaryPersistenceError(
                    "duplicate egress record: " f"egress_id={record.egress_id}"
                )
            self._egress[record.egress_id] = record

    async def get_ingress(
        self,
        ingress_id: BoundaryIngressId,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryIngressRecord | None:
        # PR-B7: tenant-scoped row-level isolation.
        record = self._ingress.get(ingress_id)
        if record is None:
            return None
        if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
            return None
        return record

    async def get_egress(
        self,
        egress_id: BoundaryEgressId,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryEgressRecord | None:
        record = self._egress.get(egress_id)
        if record is None:
            return None
        if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list_ingress(
        self,
        query: BoundaryIngressQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryRecordPage:
        rows = list(self._ingress.values())
        # PR-B7: system tenant scope is the strict outer bound
        # applied before the caller-supplied query filter.
        if expected_tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == expected_tenant_id]
        if query.ingress_id is not None:
            rows = [r for r in rows if r.ingress_id == query.ingress_id]
        if query.event_id is not None:
            rows = [r for r in rows if r.event_id == query.event_id]
        if query.replay_key is not None:
            rows = [r for r in rows if r.replay_key == query.replay_key]
        if query.source_type is not None:
            rows = [r for r in rows if r.source_type == query.source_type]
        if query.normalization_status is not None:
            rows = [
                r for r in rows if r.normalization_status == query.normalization_status
            ]
        if query.replay_disposition is not None:
            rows = [r for r in rows if r.replay_disposition == query.replay_disposition]
        if query.correlation_id is not None:
            rows = [r for r in rows if r.correlation_id == query.correlation_id]
        if query.request_id is not None:
            rows = [r for r in rows if r.request_id == query.request_id]
        if query.tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == query.tenant_id]
        rows.sort(key=lambda r: (str(r.runtime_instance_id), r.sequence))
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return BoundaryRecordPage(ingress=tuple(rows), total=total)

    async def list_egress(
        self,
        query: BoundaryEgressQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryRecordPage:
        rows = list(self._egress.values())
        if expected_tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == expected_tenant_id]
        if query.egress_id is not None:
            rows = [r for r in rows if r.egress_id == query.egress_id]
        if query.source_type is not None:
            rows = [r for r in rows if r.source_type == query.source_type]
        if query.correlation_id is not None:
            rows = [r for r in rows if r.correlation_id == query.correlation_id]
        if query.request_id is not None:
            rows = [r for r in rows if r.request_id == query.request_id]
        if query.tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == query.tenant_id]
        rows.sort(key=lambda r: (str(r.runtime_instance_id), r.sequence))
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return BoundaryRecordPage(egress=tuple(rows), total=total)

    async def record_webhook_nonce(
        self,
        record: WebhookNonceRecord,
    ) -> None:
        key = _webhook_nonce_key(record)
        async with self._lock:
            self._delete_expired_webhook_nonces_locked(now=record.received_at)
            existing = self._webhook_nonces.get(key)
            if existing is not None:
                raise WebhookReplayError("webhook nonce has already been accepted")
            self._webhook_nonces[key] = record

    async def webhook_nonce_exists(
        self,
        *,
        tenant_id: str,
        channel_type: str,
        nonce: str,
        now: datetime,
    ) -> bool:
        key = _webhook_nonce_key_from_parts(
            tenant_id=tenant_id,
            channel_type=channel_type,
            nonce=nonce,
        )
        async with self._lock:
            self._delete_expired_webhook_nonces_locked(now=now)
            return key in self._webhook_nonces

    async def delete_expired_webhook_nonces(
        self,
        *,
        now: datetime,
        limit: int = 1000,
    ) -> int:
        if limit < 1:
            raise ValueError("limit must be positive")
        async with self._lock:
            return self._delete_expired_webhook_nonces_locked(
                now=now,
                limit=limit,
            )

    def _resolve_duplicate_ingress(
        self, record: BoundaryIngressRecord
    ) -> BoundaryIngressRecord | None:
        existing = self._ingress.get(record.ingress_id)
        if existing is not None:
            return existing
        if record.replay_key is not None:
            existing_id = self._ingress_by_replay_key.get(record.replay_key)
            if existing_id is not None:
                return self._ingress[existing_id]
        if record.event_id is not None:
            existing_id = self._ingress_by_event_id.get(record.event_id)
            if existing_id is not None:
                return self._ingress[existing_id]
        return None

    def _create_ingress_dispatch_outbox_locked(
        self,
        record: BoundaryIngressRecord,
        *,
        created_at: datetime | None = None,
    ) -> IngressDispatchOutboxRecord | None:
        existing_id = self._ingress_dispatch_outbox_by_ingress.get(record.ingress_id)
        if existing_id is not None:
            return self._ingress_dispatch_outbox.get(existing_id)
        outbox = make_ingress_dispatch_outbox_record(
            record,
            created_at=created_at,
        )
        if outbox is None:
            return None
        self._ingress_dispatch_outbox[outbox.outbox_id] = outbox
        self._ingress_dispatch_outbox_by_ingress[record.ingress_id] = outbox.outbox_id
        return outbox

    def _matching_claim_locked(
        self,
        outbox_id: IngressDispatchOutboxId,
        claim_id: IngressDispatchClaimId,
    ) -> IngressDispatchOutboxRecord | None:
        current = self._ingress_dispatch_outbox.get(outbox_id)
        if current is None:
            return None
        if current.status is not IngressDispatchOutboxStatus.CLAIMED:
            return None
        if current.claim_id != claim_id:
            return None
        return current

    def _delete_expired_webhook_nonces_locked(
        self,
        *,
        now: datetime,
        limit: int | None = None,
    ) -> int:
        expired = [
            key
            for key, row in sorted(
                self._webhook_nonces.items(),
                key=lambda item: item[1].expires_at,
            )
            if row.expires_at <= now
        ]
        if limit is not None:
            expired = expired[:limit]
        for key in expired:
            del self._webhook_nonces[key]
        return len(expired)


def _webhook_nonce_key(
    record: WebhookNonceRecord,
) -> tuple[str, str, str]:
    return _webhook_nonce_key_from_parts(
        tenant_id=record.tenant_id,
        channel_type=record.channel_type,
        nonce=record.nonce,
    )


def _webhook_nonce_key_from_parts(
    *,
    tenant_id: str,
    channel_type: str,
    nonce: str,
) -> tuple[str, str, str]:
    return (
        tenant_id,
        channel_type.strip().lower(),
        nonce,
    )


def _replace_outbox(
    record: IngressDispatchOutboxRecord,
    **changes: Any,
) -> IngressDispatchOutboxRecord:
    return replace(record, **changes)


__all__ = ["InMemoryBoundaryPersistence"]
