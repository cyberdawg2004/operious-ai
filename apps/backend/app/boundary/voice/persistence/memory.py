"""In-memory voice persistence."""

from __future__ import annotations

import asyncio

from app.boundary.voice.exceptions import VoicePersistenceError
from app.boundary.voice.identity import (
    VoiceCorrelationId,
    VoiceEventId,
    derive_lineage_id,
)
from app.boundary.voice.models.lineage import (
    VoiceLineage,
    VoiceLineageEntry,
)
from app.boundary.voice.persistence.records import (
    VoiceEgressRecord,
    VoiceIngressRecord,
)
from app.boundary.voice.persistence.repository import (
    VoicePersistenceProtocol,
)


class InMemoryVoicePersistence(VoicePersistenceProtocol):
    """In-memory voice persistence (write-once, async-safe)."""

    def __init__(self) -> None:
        self._ingress: dict[
            VoiceEventId, VoiceIngressRecord
        ] = {}
        self._egress: dict[
            VoiceEventId, VoiceEgressRecord
        ] = {}
        self._lineage: dict[
            VoiceCorrelationId, list[VoiceLineageEntry]
        ] = {}
        self._lock = asyncio.Lock()

    async def write_ingress(
        self, record: VoiceIngressRecord
    ) -> None:
        async with self._lock:
            eid = record.identity.event_id
            if eid in self._ingress:
                raise VoicePersistenceError(
                    "ingress voice record is write-once"
                )
            self._ingress[eid] = record
            self._append_lineage_unlocked(
                record.identity.correlation_id,
                record.lineage_entry,
            )

    async def get_ingress(
        self, event_id: VoiceEventId
    ) -> VoiceIngressRecord | None:
        async with self._lock:
            return self._ingress.get(event_id)

    async def write_egress(
        self, record: VoiceEgressRecord
    ) -> None:
        async with self._lock:
            eid = record.identity.event_id
            if eid in self._egress:
                raise VoicePersistenceError(
                    "egress voice record is write-once"
                )
            self._egress[eid] = record
            self._append_lineage_unlocked(
                record.identity.correlation_id,
                record.lineage_entry,
            )

    async def get_egress(
        self, event_id: VoiceEventId
    ) -> VoiceEgressRecord | None:
        async with self._lock:
            return self._egress.get(event_id)

    async def list_lineage_entries(
        self, correlation_id: VoiceCorrelationId
    ) -> tuple[VoiceLineageEntry, ...]:
        async with self._lock:
            return tuple(self._lineage.get(correlation_id, []))

    async def reconstruct_lineage(
        self, correlation_id: VoiceCorrelationId
    ) -> VoiceLineage | None:
        async with self._lock:
            entries = self._lineage.get(correlation_id)
            if not entries:
                return None
            return VoiceLineage(
                lineage_id=derive_lineage_id(
                    seed=str(correlation_id)
                ),
                correlation_id=correlation_id,
                entries=tuple(entries),
            )

    def _append_lineage_unlocked(
        self,
        correlation_id: VoiceCorrelationId,
        entry: VoiceLineageEntry,
    ) -> None:
        existing = self._lineage.setdefault(correlation_id, [])
        if existing and entry.sequence <= existing[-1].sequence:
            raise VoicePersistenceError(
                "voice lineage sequence must be strictly monotonic"
            )
        existing.append(entry)


__all__ = ["InMemoryVoicePersistence"]
