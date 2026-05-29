"""`SessionContext` — declarative continuity metadata.

Strict semantic discipline: the context contains METADATA, not
DIRECTIVES. It MUST NOT contain executable instructions, callable
references, or anything that implies "what the system should do
next". The substrate enforces non-callability of all values at
construction time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Continuity metadata bound to a session.

    Attributes:
        environment:   Logical environment the session inhabits
                        (e.g. ``"production"``, ``"staging"``,
                        ``"sandbox"``).
        labels:         Free-form string labels (sorted on
                        canonicalisation).
        attributes:    Free-form key/value mapping. Values are
                        validated to be non-callable.
        notes:         Free-form audit annotation.

    Raises:
        ValueError: when any attribute value is callable.
    """

    environment: str | None = None
    labels: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])
    notes: str | None = None

    def __post_init__(self) -> None:
        for key, value in self.attributes.items():
            if callable(value):
                raise ValueError(
                    f"SessionContext.attributes[{key!r}] must not "
                    f"be callable; the context is metadata, not "
                    f"behaviour."
                )


__all__ = ["SessionContext"]
