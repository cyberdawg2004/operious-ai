"""Auth substrate error types."""

from __future__ import annotations


class AuthenticationError(Exception):
    """Raised by an :class:`AuthProvider` when a credential cannot
    be verified (signature failure, expiry, issuer mismatch, any
    refusal to attest).

    Constitutionally distinct from
    :class:`app.identity.IdentityError`:

    * ``AuthenticationError`` — a PROVIDER refused to attest.
    * ``IdentityError``       — a typed identity primitive was
      structurally malformed at the substrate-level translation
      step (:func:`app.auth.verified_identity_to_authority`).

    The two categories must never collapse — audit and forensic
    reconstruction rely on the distinction.
    """


__all__ = ["AuthenticationError"]
