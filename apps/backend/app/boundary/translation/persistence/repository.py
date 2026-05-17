"""Translation persistence protocol — write-once."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.boundary.translation.identity import (
    TranslationCorrelationId,
    TranslationId,
)
from app.boundary.translation.models.lineage import (
    TranslationLineage,
    TranslationLineageEntry,
)
from app.boundary.translation.persistence.records import (
    EgressLocalizationRecord,
    IngressTranslationRecord,
)


@runtime_checkable
class TranslationPersistenceProtocol(Protocol):
    """Storage-agnostic protocol for translation artifacts."""

    async def write_ingress(
        self, record: IngressTranslationRecord
    ) -> None: ...

    async def get_ingress(
        self, translation_id: TranslationId
    ) -> IngressTranslationRecord | None: ...

    async def write_egress(
        self, record: EgressLocalizationRecord
    ) -> None: ...

    async def get_egress(
        self, translation_id: TranslationId
    ) -> EgressLocalizationRecord | None: ...

    async def list_lineage_entries(
        self, correlation_id: TranslationCorrelationId
    ) -> tuple[TranslationLineageEntry, ...]: ...

    async def reconstruct_lineage(
        self, correlation_id: TranslationCorrelationId
    ) -> TranslationLineage | None: ...


__all__ = ["TranslationPersistenceProtocol"]
