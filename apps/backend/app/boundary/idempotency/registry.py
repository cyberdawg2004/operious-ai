"""`BoundaryIdempotencyRegistry` — replay-record store.

The registry is the substrate's **only** authority on what has
been seen. It maintains the canonical mapping
``replay_key → BoundaryReplayRecord``.

Replay-record discipline:

* The original `event_id` and `first_seen_at` NEVER change once
  written.
* Subsequent observations rebuild the record with an updated
  `last_seen_at`, `observation_count`, and `last_disposition`.
  The original fields are copied across — the registry NEVER
  rewrites them.
* `LINEAGE_DRIFT` detections are recorded but do NOT change the
  original `event_id`. Drifted retransmissions inherit the
  original lineage; the disposition surfaces the drift.

This layer is in-memory and async-safe (asyncio.Lock). Pluggable
durable backends would conform to the same contract.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Mapping

from app.boundary.enums import (
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import BoundaryEventId
from app.boundary.models.replay import BoundaryReplayRecord


class BoundaryIdempotencyRegistry:
    """Async-safe replay-record store.

    Methods:
        get(replay_key)
            Return the existing record or None.
        record_first_seen(...)
            Atomically register a brand-new replay key. Returns
            the persisted record. Raises ``ValueError`` if the key
            already exists.
        record_observation(...)
            Atomically rebuild the record with an updated
            disposition + last_seen + count. Raises ``KeyError``
            if the key was never seen.
        snapshot()
            Read-only mapping snapshot for inspection/test.
    """

    __slots__ = ("_records", "_lock")

    def __init__(self) -> None:
        self._records: dict[uuid.UUID, BoundaryReplayRecord] = {}
        self._lock = asyncio.Lock()

    async def get(
        self, replay_key: uuid.UUID
    ) -> BoundaryReplayRecord | None:
        return self._records.get(replay_key)

    async def record_first_seen(
        self,
        *,
        replay_key: uuid.UUID,
        event_id: BoundaryEventId,
        source_type: BoundarySourceType,
        external_message_id: str,
        tenant_id: str | None,
        content_fingerprint: str,
        seen_at: datetime | None = None,
    ) -> BoundaryReplayRecord:
        ts = seen_at or datetime.now(tz=timezone.utc)
        async with self._lock:
            if replay_key in self._records:
                raise ValueError(
                    f"replay key already registered: {replay_key}"
                )
            record = BoundaryReplayRecord(
                replay_key=replay_key,
                event_id=event_id,
                source_type=source_type,
                external_message_id=external_message_id,
                tenant_id=tenant_id,
                content_fingerprint=content_fingerprint,
                first_seen_at=ts,
                last_seen_at=ts,
                observation_count=1,
                last_disposition=BoundaryReplayDisposition.NEW,
            )
            self._records[replay_key] = record
            return record

    async def record_observation(
        self,
        *,
        replay_key: uuid.UUID,
        disposition: BoundaryReplayDisposition,
        observed_fingerprint: str,
        seen_at: datetime | None = None,
    ) -> BoundaryReplayRecord:
        ts = seen_at or datetime.now(tz=timezone.utc)
        async with self._lock:
            existing = self._records.get(replay_key)
            if existing is None:
                raise KeyError(
                    f"replay key not registered: {replay_key}"
                )
            updated = BoundaryReplayRecord(
                replay_key=existing.replay_key,
                # ─── These NEVER change. ────────────────────────────
                event_id=existing.event_id,
                source_type=existing.source_type,
                external_message_id=existing.external_message_id,
                tenant_id=existing.tenant_id,
                first_seen_at=existing.first_seen_at,
                # ─── These rebuild on each observation. ─────────────
                content_fingerprint=existing.content_fingerprint,
                last_seen_at=ts,
                observation_count=existing.observation_count + 1,
                last_disposition=disposition,
                metadata={
                    **existing.metadata,
                    f"observation.{existing.observation_count + 1}.fingerprint": (
                        observed_fingerprint
                    ),
                    f"observation.{existing.observation_count + 1}.disposition": (
                        disposition.value
                    ),
                },
            )
            self._records[replay_key] = updated
            return updated

    def snapshot(
        self,
    ) -> Mapping[uuid.UUID, BoundaryReplayRecord]:
        return dict(self._records)


__all__ = ["BoundaryIdempotencyRegistry"]
