"""In-memory boundary persistence (test + dev backend)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from app.boundary.exceptions import (
    BoundaryPersistenceError,
    WebhookReplayError,
)
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryIngressId,
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
        "_egress",
        "_webhook_nonces",
        "_lock",
    )

    def __init__(self) -> None:
        self._ingress: dict[
            BoundaryIngressId, BoundaryIngressRecord
        ] = {}
        self._ingress_by_replay_key: dict[
            uuid.UUID, BoundaryIngressId
        ] = {}
        self._ingress_by_event_id: dict[
            uuid.UUID, BoundaryIngressId
        ] = {}
        self._egress: dict[
            BoundaryEgressId, BoundaryEgressRecord
        ] = {}
        self._webhook_nonces: dict[
            tuple[str, str, str], WebhookNonceRecord
        ] = {}
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
                self._ingress_by_replay_key[record.replay_key] = (
                    record.ingress_id
                )
            if record.event_id is not None:
                self._ingress_by_event_id[record.event_id] = (
                    record.ingress_id
                )
            return record

    async def save_egress(
        self, record: BoundaryEgressRecord
    ) -> None:
        async with self._lock:
            if record.egress_id in self._egress:
                raise BoundaryPersistenceError(
                    "duplicate egress record: "
                    f"egress_id={record.egress_id}"
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
        if (
            expected_tenant_id is not None
            and record.tenant_id != expected_tenant_id
        ):
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
        if (
            expected_tenant_id is not None
            and record.tenant_id != expected_tenant_id
        ):
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
            rows = [
                r for r in rows if r.tenant_id == expected_tenant_id
            ]
        if query.ingress_id is not None:
            rows = [
                r for r in rows if r.ingress_id == query.ingress_id
            ]
        if query.event_id is not None:
            rows = [r for r in rows if r.event_id == query.event_id]
        if query.replay_key is not None:
            rows = [
                r for r in rows if r.replay_key == query.replay_key
            ]
        if query.source_type is not None:
            rows = [
                r for r in rows if r.source_type == query.source_type
            ]
        if query.normalization_status is not None:
            rows = [
                r
                for r in rows
                if r.normalization_status
                == query.normalization_status
            ]
        if query.replay_disposition is not None:
            rows = [
                r
                for r in rows
                if r.replay_disposition == query.replay_disposition
            ]
        if query.correlation_id is not None:
            rows = [
                r
                for r in rows
                if r.correlation_id == query.correlation_id
            ]
        if query.request_id is not None:
            rows = [
                r for r in rows if r.request_id == query.request_id
            ]
        if query.tenant_id is not None:
            rows = [
                r for r in rows if r.tenant_id == query.tenant_id
            ]
        rows.sort(
            key=lambda r: (str(r.runtime_instance_id), r.sequence)
        )
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return BoundaryRecordPage(
            ingress=tuple(rows), total=total
        )

    async def list_egress(
        self,
        query: BoundaryEgressQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryRecordPage:
        rows = list(self._egress.values())
        if expected_tenant_id is not None:
            rows = [
                r for r in rows if r.tenant_id == expected_tenant_id
            ]
        if query.egress_id is not None:
            rows = [r for r in rows if r.egress_id == query.egress_id]
        if query.source_type is not None:
            rows = [
                r for r in rows if r.source_type == query.source_type
            ]
        if query.correlation_id is not None:
            rows = [
                r
                for r in rows
                if r.correlation_id == query.correlation_id
            ]
        if query.request_id is not None:
            rows = [
                r for r in rows if r.request_id == query.request_id
            ]
        if query.tenant_id is not None:
            rows = [
                r for r in rows if r.tenant_id == query.tenant_id
            ]
        rows.sort(
            key=lambda r: (str(r.runtime_instance_id), r.sequence)
        )
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return BoundaryRecordPage(
            egress=tuple(rows), total=total
        )

    async def record_webhook_nonce(
        self,
        record: WebhookNonceRecord,
    ) -> None:
        key = _webhook_nonce_key(record)
        async with self._lock:
            self._delete_expired_webhook_nonces_locked(now=record.received_at)
            existing = self._webhook_nonces.get(key)
            if existing is not None:
                raise WebhookReplayError(
                    "webhook nonce has already been accepted"
                )
            self._webhook_nonces[key] = record

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
            existing_id = self._ingress_by_replay_key.get(
                record.replay_key
            )
            if existing_id is not None:
                return self._ingress[existing_id]
        if record.event_id is not None:
            existing_id = self._ingress_by_event_id.get(
                record.event_id
            )
            if existing_id is not None:
                return self._ingress[existing_id]
        return None

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
    return (
        record.tenant_id,
        record.channel_type.strip().lower(),
        record.nonce,
    )


__all__ = ["InMemoryBoundaryPersistence"]
