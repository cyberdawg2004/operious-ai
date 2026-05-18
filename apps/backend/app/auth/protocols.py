"""Auth provider protocol + fail-closed reference implementation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.auth.credentials import Credential
from app.auth.errors import AuthenticationError
from app.auth.identity import VerifiedIdentity


@runtime_checkable
class AuthProvider(Protocol):
    """Verify a :class:`Credential` and produce a
    :class:`VerifiedIdentity`.

    Concrete implementations (JWT, OIDC, mTLS, opaque API key,
    ...) live OUTSIDE this substrate so the interface stays
    neutral. They are required to:

    * be deterministic with respect to their inputs once
      construction-time configuration (signing keys, JWKS URI,
      issuer allowlist, ...) is fixed — same credential + same
      provider state → byte-equal :class:`VerifiedIdentity`. This
      preserves ingress replay determinism.
    * raise :class:`AuthenticationError` on any refusal to attest
      (signature failure, expiry, issuer mismatch, ...).
    * NOT raise :class:`app.identity.IdentityError` — that is
      reserved for the substrate-level translation step
      :func:`app.auth.verified_identity_to_authority`. Providers
      attest claims; the substrate types them.
    * populate :attr:`VerifiedIdentity.issuer` with their own
      :attr:`name` so audit can attribute verification.
    """

    name: str

    async def verify(self, credential: Credential) -> VerifiedIdentity: ...


class NullAuthProvider:
    """Fail-closed reference provider.

    Refuses every credential with :class:`AuthenticationError`.
    Use as:

    * the default provider in compositions where no concrete
      provider has been wired yet (preserves B5 fail-closed
      doctrine — no provider configured is NOT a permissive
      default);
    * a test fixture for code paths that exercise the failure
      branch of an :class:`AuthProvider` consumer.
    """

    name: str = "null"

    async def verify(
        self, credential: Credential
    ) -> VerifiedIdentity:  # noqa: ARG002 — interface signature
        raise AuthenticationError(
            f"NullAuthProvider rejects every credential "
            f"(scheme={credential.scheme!r})"
        )


__all__ = ["AuthProvider", "NullAuthProvider"]
