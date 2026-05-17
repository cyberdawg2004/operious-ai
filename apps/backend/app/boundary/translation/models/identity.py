"""`TranslationIdentity` — replay-safe identity bundle."""

from __future__ import annotations

from dataclasses import dataclass

from app.boundary.translation.identity import (
    TranslationCorrelationId,
    TranslationId,
    TranslationLineageId,
)


@dataclass(frozen=True, slots=True)
class TranslationIdentity:
    """Replay-safe identity bundle attached to a translation event."""

    translation_id: TranslationId
    lineage_id: TranslationLineageId
    correlation_id: TranslationCorrelationId
    seed: str
    request_id: str | None = None
    tenant_id: str | None = None

    def __post_init__(self) -> None:
        if not self.seed:
            raise ValueError(
                "TranslationIdentity.seed must be non-empty"
            )


__all__ = ["TranslationIdentity"]
