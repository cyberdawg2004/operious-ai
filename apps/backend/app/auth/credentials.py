"""Provider-agnostic credential carrier."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Credential:
    """Opaque credential presented by a caller.

    Two-tuple envelope ``(scheme, value)`` modelled on the HTTP
    ``Authorization`` header but not bound to it:

    * ``scheme`` identifies the credential class
      (e.g. ``"Bearer"``, ``"ApiKey"``, ``"mTLS"``).
    * ``value`` carries the scheme-specific payload (JWT string,
      API key, cert thumbprint, ...).

    The substrate does NOT parse ``value`` — that is the
    concrete :class:`AuthProvider`'s responsibility. Keeping the
    envelope abstract is what makes the substrate
    provider-agnostic.
    """

    scheme: str
    value: str


__all__ = ["Credential"]
