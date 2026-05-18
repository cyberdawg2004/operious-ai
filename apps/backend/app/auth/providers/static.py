"""``StaticTokenProvider`` — in-memory bearer-token provider.

Dependency-free reference implementation: a frozen mapping from
opaque token strings to :class:`VerifiedIdentity`. Useful as a
test fixture, dev-environment default, or composition target.

Constitutional positioning:

* Deterministic by construction: same token → same
  :class:`VerifiedIdentity`. Replay-safe for ingress.
* Fail-closed: unknown token → :class:`AuthenticationError`.
* Scheme-restricted: only ``Bearer`` (case-insensitive) accepted;
  other schemes raise to preserve the "one provider, one
  scheme" contract at the substrate level.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import ClassVar

from app.auth.credentials import Credential
from app.auth.errors import AuthenticationError
from app.auth.identity import VerifiedIdentity


class StaticTokenProvider:
    """Verify bearer tokens against an in-memory mapping.

    Construction:

        provider = StaticTokenProvider(
            tokens={"alice-token": VerifiedIdentity(tenant_id="acme", principal_id="alice")},
            issuer="static",
        )

    Stamps :attr:`VerifiedIdentity.issuer` with the provider's
    ``name`` and :attr:`VerifiedIdentity.issued_at` with the
    verification time so audit can attribute every successful
    verification.
    """

    name: ClassVar[str] = "static_token"
    _accepted_schemes: ClassVar[frozenset[str]] = frozenset({"bearer"})

    def __init__(
        self,
        *,
        tokens: Mapping[str, VerifiedIdentity],
        issuer: str | None = None,
    ) -> None:
        # Defensive copy so callers cannot mutate the mapping
        # after construction (preserves determinism).
        self._tokens: dict[str, VerifiedIdentity] = dict(tokens)
        self._issuer = issuer or self.name

    async def verify(self, credential: Credential) -> VerifiedIdentity:
        if credential.scheme.lower() not in self._accepted_schemes:
            raise AuthenticationError(
                f"StaticTokenProvider only accepts Bearer credentials "
                f"(got scheme={credential.scheme!r})"
            )
        identity = self._tokens.get(credential.value)
        if identity is None:
            raise AuthenticationError("unknown token")
        return replace(
            identity,
            issuer=identity.issuer or self._issuer,
            issued_at=identity.issued_at or datetime.now(timezone.utc),
        )


__all__ = ["StaticTokenProvider"]
