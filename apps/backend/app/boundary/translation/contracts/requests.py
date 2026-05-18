"""Typed runtime requests for the translation substrate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.boundary.translation.localization.context import (
    LocalizationContext,
)
from app.boundary.translation.models.payload import (
    TranslationPayload,
)
from app.identity import AuthorityContext


def _check_authority_tenant_consistency(
    *,
    contract_name: str,
    authority: AuthorityContext | None,
    tenant_id: str | None,
) -> None:
    """Enforce the Wedge B2 coexistence invariant.

    Both fields may co-exist during the typed-ingress transition.
    When BOTH carry a value, they must agree. ``None`` on either
    side is permitted — legacy callers (tenant_id only) and typed
    callers (authority only) are both supported until a later wedge
    consolidates onto the typed surface.
    """
    if (
        authority is not None
        and authority.tenant_id is not None
        and tenant_id is not None
        and authority.tenant_id != tenant_id
    ):
        raise ValueError(
            f"{contract_name}: authority.tenant_id and tenant_id "
            f"must agree when both are supplied (got "
            f"authority.tenant_id={authority.tenant_id!r}, "
            f"tenant_id={tenant_id!r})"
        )


@dataclass(frozen=True, slots=True)
class IngressTranslateRequest:
    """Request to translate a customer-language payload to canonical English.

    Attributes:
        source:           Customer-language payload.
        seed:             Replay-safe deterministic seed.
        correlation_id:   Optional correlation handle.
        request_id:       Optional request handle.
        tenant_id:        Optional tenant scope (legacy str field;
                           preserved for runtime back-compat during
                           the Wedge B2 typed-ingress transition).
        authority:        Optional typed authority tuple. When both
                           ``authority`` and ``tenant_id`` are
                           supplied, they must agree.
        attributes:       Canonical metadata payload.
    """

    source: TranslationPayload
    seed: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    authority: AuthorityContext | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.seed:
            raise ValueError(
                "IngressTranslateRequest.seed must be non-empty"
            )
        _check_authority_tenant_consistency(
            contract_name="IngressTranslateRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


@dataclass(frozen=True, slots=True)
class EgressLocalizeRequest:
    """Request to localise a canonical-English payload to a customer language.

    Attributes:
        canonical:        Canonical-English payload.
        context:          Localisation context.
        seed:             Replay-safe deterministic seed.
        correlation_id:   Optional correlation handle.
        request_id:       Optional request handle.
        tenant_id:        Optional tenant scope (legacy str field;
                           preserved for runtime back-compat during
                           the Wedge B2 typed-ingress transition).
        authority:        Optional typed authority tuple. When both
                           ``authority`` and ``tenant_id`` are
                           supplied, they must agree.
        attributes:       Canonical metadata payload.
    """

    canonical: TranslationPayload
    context: LocalizationContext
    seed: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    authority: AuthorityContext | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.seed:
            raise ValueError(
                "EgressLocalizeRequest.seed must be non-empty"
            )
        _check_authority_tenant_consistency(
            contract_name="EgressLocalizeRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


__all__ = [
    "EgressLocalizeRequest",
    "IngressTranslateRequest",
]
