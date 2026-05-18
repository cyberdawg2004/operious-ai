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
from app.identity import (
    AuthorityContext,
    check_tenant_authority_coexistence,
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
        check_tenant_authority_coexistence(
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
        check_tenant_authority_coexistence(
            contract_name="EgressLocalizeRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


__all__ = [
    "EgressLocalizeRequest",
    "IngressTranslateRequest",
]
