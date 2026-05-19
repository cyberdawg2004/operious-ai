"""Concrete :class:`app.auth.AuthProvider` implementations.

Lives OUTSIDE the substrate root (``app/auth/``) so the protocol
surface stays neutral. Each provider self-classifies:

* :class:`StaticTokenProvider` — in-memory mapping of opaque
  bearer tokens to :class:`VerifiedIdentity`. Dependency-free.
  Use as a test fixture, dev-environment default, or composition
  target for a higher-level provider.
* :class:`JWTProvider` — RFC 7519 verification via PyJWT against
  a static signing key (HS256, RS256, …). Maps JWT claims to
  identity axes via a configurable :class:`ClaimMapping`.
* :class:`JWKSAuthProvider` — RFC 7519 verification against a
  remote JWKS (RFC 7517) endpoint. The IdP standard for Auth0,
  Cognito, Keycloak, Clerk, etc. Inherits the claim-mapping +
  audience / issuer / leeway surface from :class:`JWTProvider`;
  adds lazy JWKS fetch + TTL-cached key resolution.
"""

from app.auth.providers.jwks import JWKSAuthProvider
from app.auth.providers.jwt import (
    ClaimMapping,
    DEFAULT_CLAIM_MAPPING,
    JWTProvider,
)
from app.auth.providers.static import StaticTokenProvider

__all__ = [
    "ClaimMapping",
    "DEFAULT_CLAIM_MAPPING",
    "JWKSAuthProvider",
    "JWTProvider",
    "StaticTokenProvider",
]
