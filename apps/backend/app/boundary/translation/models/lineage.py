"""`TranslationLineage` — append-only translation ancestry."""

from __future__ import annotations

from dataclasses import dataclass

from app.boundary.translation.enums import TranslationDirection
from app.boundary.translation.identity import (
    TranslationCorrelationId,
    TranslationLineageId,
)


@dataclass(frozen=True, slots=True)
class TranslationLineageEntry:
    """One immutable lineage entry."""

    sequence: int
    direction: TranslationDirection
    canonical_fingerprint: str
    boundary_fingerprint: str
    provider_name: str
    seed: str

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError(
                "TranslationLineageEntry.sequence must be >= 0"
            )
        if not self.canonical_fingerprint:
            raise ValueError(
                "TranslationLineageEntry.canonical_fingerprint "
                "must be non-empty"
            )
        if not self.boundary_fingerprint:
            raise ValueError(
                "TranslationLineageEntry.boundary_fingerprint "
                "must be non-empty"
            )
        if not self.provider_name:
            raise ValueError(
                "TranslationLineageEntry.provider_name must be "
                "non-empty"
            )
        if not self.seed:
            raise ValueError(
                "TranslationLineageEntry.seed must be non-empty"
            )


@dataclass(frozen=True, slots=True)
class TranslationLineage:
    """Append-only lineage of translation events.

    Translation lineage records the sequence of ingress/egress
    operations on the same correlation handle. Lineage is
    write-once per entry; full reconstruction requires fetching
    persisted entries.
    """

    lineage_id: TranslationLineageId
    correlation_id: TranslationCorrelationId
    entries: tuple[TranslationLineageEntry, ...]

    def __post_init__(self) -> None:
        prev = -1
        for e in self.entries:
            if e.sequence <= prev:
                raise ValueError(
                    "TranslationLineage.entries must be strictly "
                    "monotonic by sequence"
                )
            prev = e.sequence


__all__ = [
    "TranslationLineage",
    "TranslationLineageEntry",
]
