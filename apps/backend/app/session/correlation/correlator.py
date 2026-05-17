"""Pure correlation construction helper.

`build_correlation(...)` deterministically derives a
`SessionCorrelationId` from `(session_id, kind, external_id)` so
the same observation appended twice produces the SAME correlation
id — that's the foundation of replay-equivalent correlation
recording.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from app.session.enums import SessionCorrelationKind
from app.session.identity import (
    SessionId,
    derive_correlation_id,
)
from app.session.models.correlation import SessionCorrelation
from app.session.serializers.canonical import (
    canonicalize_attributes,
)


def build_correlation(
    *,
    session_id: SessionId,
    kind: SessionCorrelationKind,
    external_id: str,
    recorded_at: datetime,
    external_correlation_id: str | None = None,
    annotation: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> SessionCorrelation:
    """Construct an immutable, deterministically-keyed correlation record."""
    return SessionCorrelation(
        correlation_id=derive_correlation_id(
            session_id=session_id,
            kind=kind.value,
            external_id=external_id,
        ),
        session_id=session_id,
        kind=kind,
        external_id=external_id,
        recorded_at=recorded_at,
        external_correlation_id=external_correlation_id,
        annotation=annotation,
        attributes=canonicalize_attributes(attributes or {}),
    )


__all__ = ["build_correlation"]
