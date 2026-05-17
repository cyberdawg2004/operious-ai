"""In-memory translation persistence."""

from __future__ import annotations

import asyncio

from app.boundary.translation.exceptions import (
    TranslationPersistenceError,
)
from app.boundary.translation.identity import (
    TranslationCorrelationId,
    TranslationId,
    derive_lineage_id,
)
from app.boundary.translation.models.lineage import (
    TranslationLineage,
    TranslationLineageEntry,
)
from app.boundary.translation.persistence.records import (
    EgressLocalizationRecord,
    IngressTranslationRecord,
)
from app.boundary.translation.persistence.repository import (
    TranslationPersistenceProtocol,
)


class InMemoryTranslationPersistence(
    TranslationPersistenceProtocol
):
    """In-memory translation persistence (write-once, async-safe)."""

    def __init__(self) -> None:
        self._ingress: dict[
            TranslationId, IngressTranslationRecord
        ] = {}
        self._egress: dict[
            TranslationId, EgressLocalizationRecord
        ] = {}
        self._lineage_entries: dict[
            TranslationCorrelationId,
            list[TranslationLineageEntry],
        ] = {}
        self._lock = asyncio.Lock()

    async def write_ingress(
        self, record: IngressTranslationRecord
    ) -> None:
        async with self._lock:
            tid = record.identity.translation_id
            if tid in self._ingress:
                raise TranslationPersistenceError(
                    "ingress translation is write-once"
                )
            self._ingress[tid] = record
            self._append_lineage_unlocked(
                record.identity.correlation_id,
                record.lineage_entry,
            )

    async def get_ingress(
        self, translation_id: TranslationId
    ) -> IngressTranslationRecord | None:
        async with self._lock:
            return self._ingress.get(translation_id)

    async def write_egress(
        self, record: EgressLocalizationRecord
    ) -> None:
        async with self._lock:
            tid = record.identity.translation_id
            if tid in self._egress:
                raise TranslationPersistenceError(
                    "egress translation is write-once"
                )
            self._egress[tid] = record
            self._append_lineage_unlocked(
                record.identity.correlation_id,
                record.lineage_entry,
            )

    async def get_egress(
        self, translation_id: TranslationId
    ) -> EgressLocalizationRecord | None:
        async with self._lock:
            return self._egress.get(translation_id)

    async def list_lineage_entries(
        self, correlation_id: TranslationCorrelationId
    ) -> tuple[TranslationLineageEntry, ...]:
        async with self._lock:
            return tuple(
                self._lineage_entries.get(correlation_id, [])
            )

    async def reconstruct_lineage(
        self, correlation_id: TranslationCorrelationId
    ) -> TranslationLineage | None:
        async with self._lock:
            entries = self._lineage_entries.get(
                correlation_id
            )
            if not entries:
                return None
            return TranslationLineage(
                lineage_id=derive_lineage_id(
                    seed=str(correlation_id)
                ),
                correlation_id=correlation_id,
                entries=tuple(entries),
            )

    def _append_lineage_unlocked(
        self,
        correlation_id: TranslationCorrelationId,
        entry: TranslationLineageEntry,
    ) -> None:
        existing = self._lineage_entries.setdefault(
            correlation_id, []
        )
        if existing and entry.sequence <= existing[-1].sequence:
            raise TranslationPersistenceError(
                "lineage sequence must be strictly monotonic"
            )
        existing.append(entry)


__all__ = ["InMemoryTranslationPersistence"]
