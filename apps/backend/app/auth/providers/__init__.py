"""Concrete :class:`app.auth.AuthProvider` implementations.

Lives OUTSIDE the substrate root (``app/auth/``) so the protocol
surface stays neutral. Each provider self-classifies:

* :class:`StaticTokenProvider` — in-memory mapping of opaque
  bearer tokens to :class:`VerifiedIdentity`. Dependency-free.
  Use as a test fixture, dev-environment default, or composition
  target for a higher-level provider.
* :class:`JWTProvider` — RFC 7519 verification via PyJWT.
  Supports HS256 and RS256 (extensible). Maps JWT claims to
  identity axes via a configurable :class:`ClaimMapping`.
"""

from app.auth.providers.jwt import (
    ClaimMapping,
    DEFAULT_CLAIM_MAPPING,
    JWTProvider,
)
from app.auth.providers.static import StaticTokenProvider

__all__ = [
    "ClaimMapping",
    "DEFAULT_CLAIM_MAPPING",
    "JWTProvider",
    "StaticTokenProvider",
]
