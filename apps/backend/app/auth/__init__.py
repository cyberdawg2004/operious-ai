"""Auth substrate — provider-agnostic verified-identity attestation.

Provides the canonical interface (:class:`AuthProvider`) that
verifies a :class:`Credential` and produces a
:class:`VerifiedIdentity`, plus the substrate-level translator
:func:`verified_identity_to_authority` that bridges the verified
identity to the typed :class:`app.identity.AuthorityContext`
already consumed downstream.

Architectural position
──────────────────────
* Sits ABOVE :mod:`app.identity` (its sole sibling dependency)
  and BELOW any HTTP / orchestration consumer.
* Concrete provider adapters (JWT, OIDC, mTLS, ...) live OUTSIDE
  this substrate to keep the interface neutral.
* The B8 HTTP ingress middleware does NOT yet consume this
  substrate — wiring is a follow-up wedge.

Leaf-up-one invariant: every ``.py`` under ``app/auth/`` must
import only from ``app.identity`` and stdlib. Pinned by
``tests/test_auth_substrate.py``.
"""

from app.auth.credentials import Credential
from app.auth.errors import AuthenticationError
from app.auth.identity import (
    VerifiedIdentity,
    verified_identity_to_authority,
)
from app.auth.protocols import AuthProvider, NullAuthProvider

__all__ = [
    "AuthProvider",
    "AuthenticationError",
    "Credential",
    "NullAuthProvider",
    "VerifiedIdentity",
    "verified_identity_to_authority",
]
