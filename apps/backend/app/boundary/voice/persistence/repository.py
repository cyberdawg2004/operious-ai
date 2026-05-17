"""Voice persistence protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.boundary.voice.identity import (
    VoiceCorrelationId,
    VoiceEventId,
)
from app.boundary.voice.models.lineage import (
    VoiceLineage,
    VoiceLineageEntry,
)
from app.boundary.voice.persistence.records import (
    VoiceEgressRecord,
    VoiceIngressRecord,
)


@runtime_checkable
class VoicePersistenceProtocol(Protocol):
    async def write_ingress(
        self, record: VoiceIngressRecord
    ) -> None: ...

    async def get_ingress(
        self, event_id: VoiceEventId
    ) -> VoiceIngressRecord | None: ...

    async def write_egress(
        self, record: VoiceEgressRecord
    ) -> None: ...

    async def get_egress(
        self, event_id: VoiceEventId
    ) -> VoiceEgressRecord | None: ...

    async def list_lineage_entries(
        self, correlation_id: VoiceCorrelationId
    ) -> tuple[VoiceLineageEntry, ...]: ...

    async def reconstruct_lineage(
        self, correlation_id: VoiceCorrelationId
    ) -> VoiceLineage | None: ...


__all__ = ["VoicePersistenceProtocol"]
