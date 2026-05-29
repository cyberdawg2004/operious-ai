"""Localisation context — descriptive metadata only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.boundary.translation.enums import (
    LocalizationFormality,
)


@dataclass(frozen=True, slots=True)
class LocalizationContext:
    """Inputs to egress localisation.

    The context is descriptive — it MUST NOT change governance
    semantics. The localisation runtime hands it to the provider
    as guidance.
    """

    target_language: str
    formality: LocalizationFormality
    timezone: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.target_language:
            raise ValueError(
                "LocalizationContext.target_language must be "
                "non-empty"
            )


def derive_formality(
    *,
    base_language: str,
) -> LocalizationFormality:
    """Conservative deterministic formality default.

    The default is NEUTRAL — the runtime never invents formality
    on the customer's behalf. Production deployments may layer
    their own formality policy on top.
    """
    if not base_language:
        raise ValueError(
            "derive_formality.base_language must be non-empty"
        )
    return LocalizationFormality.NEUTRAL


__all__ = ["LocalizationContext", "derive_formality"]
