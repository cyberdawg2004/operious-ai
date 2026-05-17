"""`SessionCorrelation` — cross-substrate audit link.

Substrate-isolation discipline: the session substrate never
imports the typed identifiers of sibling runtimes. Cross-substrate
links are recorded as ``(kind, external_id)`` pairs where
`external_id` is the foreign substrate's identifier rendered to a
string. The session substrate treats them as opaque.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.session.enums import SessionCorrelationKind
from app.session.identity import (
    SessionCorrelationId,
    SessionId,
)


@dataclass(frozen=True, slots=True)
class SessionCorrelation:
    """One immutable cross-substrate correlation observation.

    Attributes:
        correlation_id:        Stable correlation identifier.
        session_id:            Session this correlation anchors.
        kind:                  Which sibling substrate is being
                                referenced.
        external_id:           Opaque sibling-substrate identifier
                                (string).
        recorded_at:           Wall-clock timestamp.
        external_correlation_id: Optional sibling-substrate trace
                                /correlation handle for richer
                                cross-substrate audit.
        annotation:            Free-form human-readable note.
        attributes:            Free-form audit payload (canonicalised).
    """

    correlation_id: SessionCorrelationId
    session_id: SessionId
    kind: SessionCorrelationKind
    external_id: str
    recorded_at: datetime
    external_correlation_id: str | None = None
    annotation: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.external_id:
            raise ValueError(
                "SessionCorrelation.external_id must be a non-empty"
                " string"
            )


__all__ = ["SessionCorrelation"]
