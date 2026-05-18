"""Verified-identity contract + ``AuthorityContext`` bridge."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.identity import AuthorityContext


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """Identity claims after successful credential verification.

    Each identity axis (``tenant_id``, ``principal_id``,
    ``organization_id``, ``environment_id``) is OPTIONAL — a
    provider attests only the axes it has evidence for, and
    downstream policies (governance) decide whether unverified
    axes are tolerable (B5 doctrine).

    Audit attribution (kept separate from the identity surface so
    audit + replay can reconstruct provenance without inflating
    :class:`AuthorityContext`):

    * ``issuer``     — provider self-attribution (the provider's
      ``name`` by convention).
    * ``issued_at``  — verification timestamp.
    * ``expires_at`` — credential expiry when known.
    * ``claims``     — opaque provider-specific claim bag.
      Substrate code does NOT introspect; provider-aware adapters
      do, OUTSIDE this substrate.
    """

    tenant_id: str | None = None
    principal_id: str | None = None
    organization_id: str | None = None
    environment_id: str | None = None
    capabilities: frozenset[str] = frozenset()
    issuer: str | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    claims: Mapping[str, Any] = field(default_factory=dict)


def verified_identity_to_authority(
    identity: VerifiedIdentity,
) -> AuthorityContext:
    """Constitutional bridge: :class:`VerifiedIdentity` →
    :class:`AuthorityContext`.

    Routes the four identity axes through
    :meth:`AuthorityContext.from_raw` so the Wedge A
    ``coerce_*_id`` doctrine applies uniformly: whitespace
    stripped, empty / whitespace-only / non-string values raise
    :class:`app.identity.IdentityError`. Malformed claims are NOT
    silently coerced to ``None`` — that would re-introduce the
    fail-open pattern Wedge B5 closed in governance.

    Audit attribution (``issuer``, ``issued_at``, ``expires_at``,
    ``claims``) is intentionally NOT carried into
    ``AuthorityContext``. Callers that need provenance keep the
    ``VerifiedIdentity`` alongside the ``AuthorityContext`` for
    the duration of the request.
    """
    return AuthorityContext.from_raw(
        tenant_id=identity.tenant_id,
        principal_id=identity.principal_id,
        organization_id=identity.organization_id,
        environment_id=identity.environment_id,
        capabilities=identity.capabilities,
    )


__all__ = ["VerifiedIdentity", "verified_identity_to_authority"]
