"""Pure helpers for translation-lineage construction."""

from __future__ import annotations

from app.boundary.translation.identity import (
    TranslationCorrelationId,
)
from app.boundary.translation.models.lineage import (
    TranslationLineage,
    TranslationLineageEntry,
)


def derive_lineage_seed(
    *,
    correlation_id: TranslationCorrelationId,
    direction: str,
    sequence: int,
) -> str:
    if not direction:
        raise ValueError(
            "derive_lineage_seed requires non-empty direction"
        )
    return f"{correlation_id}|{direction}|{sequence}"


def extend_lineage(
    lineage: TranslationLineage,
    new_entry: TranslationLineageEntry,
) -> TranslationLineage:
    if (
        lineage.entries
        and new_entry.sequence
        <= lineage.entries[-1].sequence
    ):
        raise ValueError(
            "extend_lineage: new entry must have strictly "
            "monotonic sequence"
        )
    return TranslationLineage(
        lineage_id=lineage.lineage_id,
        correlation_id=lineage.correlation_id,
        entries=lineage.entries + (new_entry,),
    )


__all__ = ["derive_lineage_seed", "extend_lineage"]
