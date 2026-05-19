"""``JWKSAuthProvider`` — RS256 verification against a remote JWKS.

The constitutional counterpart to :class:`JWTProvider` for token
issuers that publish their public keys via a JSON Web Key Set
(RFC 7517) endpoint instead of distributing the verification
material out-of-band. Auth0, Cognito, Keycloak, Clerk, and every
other modern OIDC-compatible IdP follow this pattern.

Determinism contract (inherits from :class:`JWTProvider`)
─────────────────────────────────────────────────────────
Same token + same JWKS state → byte-equal :class:`VerifiedIdentity`
(modulo ``issued_at``, which is stamped with the verification
clock). The JWKS itself is fetched lazily and cached in-process;
once a ``kid`` resolves to a key, subsequent decodes for tokens
signed by that key are pure functions of the input.

Failure modes (all → :class:`AuthenticationError`)
──────────────────────────────────────────────────
* scheme not Bearer
* JWKS unreachable / 4xx / 5xx
* JWT header missing ``kid``
* ``kid`` not present in the published JWKS
* signature failure
* expired token (with configured leeway)
* issuer not in allowlist
* audience mismatch
* algorithm not in allowlist
* required claim missing

Asynchronous adapter
────────────────────
PyJWT's :class:`PyJWKClient` is synchronous (it uses
``urllib.request`` under the hood). The substrate-wide
:class:`AuthProvider` Protocol is ``async`` so the network fetch
is wrapped in :func:`asyncio.to_thread` — keeping the asyncio
event loop responsive while still benefiting from PyJWT's built-in
JWKS cache. Cached lookups are ~µs-level so the thread hop is
amortised across requests.

Test injection
──────────────
Production callers construct via
``JWKSAuthProvider(jwks_uri=..., audience=..., issuer=...)``.
Tests construct via :meth:`JWKSAuthProvider.with_jwk_client`,
passing a pre-populated :class:`PyJWKClient` so no network call
is issued. This keeps the test surface offline-deterministic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

import jwt
from jwt import (
    InvalidAlgorithmError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    PyJWKClient,
    PyJWKClientError,
)

from app.auth.credentials import Credential
from app.auth.errors import AuthenticationError
from app.auth.identity import VerifiedIdentity
from app.auth.providers.jwt import (
    DEFAULT_CLAIM_MAPPING,
    ClaimMapping,
)


# Default JWKS cache TTL — 1 hour. Auth0 documentation recommends
# fetching JWKS at most once per hour; key rotation is rare and
# pre-announced. Override at construction time for IdPs with
# different recommendations.
_DEFAULT_JWKS_TTL_SECONDS: float = 3600.0


@dataclass(frozen=True, slots=True)
class _DecodeOptions:
    issuer: str | tuple[str, ...] | None = None
    audience: str | tuple[str, ...] | None = None
    leeway: float = 0.0
    options: Mapping[str, Any] = field(default_factory=dict)


class JWKSAuthProvider:
    """Verify JWT bearer tokens against a remote JWKS endpoint.

    Parameters
    ----------
    jwks_uri
        URL of the JWKS endpoint (``.well-known/jwks.json`` on
        Auth0; equivalent paths on other OIDC IdPs). The provider
        fetches lazily on first verification and caches the result
        in-process for :attr:`jwks_ttl_seconds`.
    audience
        Single audience string or tuple of acceptable audiences.
        The verifier requires the JWT's ``aud`` claim to match.
        Mandatory in production — an unconfigured audience opens
        the substrate to token-replay across services that share
        the same issuer.
    issuer
        Single issuer URL or tuple of acceptable issuers. Auth0
        issuers include a trailing slash (e.g.
        ``"https://operious-dev.uk.auth0.com/"``); the substrate
        does NOT normalise — pass the value exactly as Auth0
        publishes it.
    algorithms
        Algorithm allowlist for the signature verification step.
        Defaults to ``("RS256",)`` — the IdP standard. Caller
        MUST NOT include ``"none"`` (PyJWT rejects it anyway).
    name
        Self-attribution string written into
        :attr:`VerifiedIdentity.issuer`. Defaults to ``"jwks"``;
        callers typically pass the IdP name (``"auth0"``,
        ``"cognito"``, etc.).
    leeway
        Clock-skew tolerance (in seconds) for ``exp`` / ``nbf``
        validation. Default 0 — tighten production deployments
        only as far as the IdP's published clock skew warrants.
    claim_mapping
        Maps JWT claim names to :class:`VerifiedIdentity` axes.
        Default mirrors :class:`JWTProvider` (``sub`` →
        ``principal_id``, etc.). Auth0 deployments that put
        custom claims under namespaced URIs (e.g.
        ``"https://operious.ai/tenant_id"``) pass a custom
        :class:`ClaimMapping` here.
    require_claims
        Tuple of claim names that MUST be present in the decoded
        payload. Defaults to ``()`` — the substrate only enforces
        what the configured mapping needs.
    jwks_ttl_seconds
        TTL for the JWKS response cache. Defaults to 3600s.
        Per-key LRU cache (Tier 2) is also enabled — once a
        ``kid`` resolves it stays cached until the LRU evicts it.
    """

    _accepted_schemes: ClassVar[frozenset[str]] = frozenset({"bearer"})

    def __init__(
        self,
        *,
        jwks_uri: str,
        audience: str | tuple[str, ...],
        issuer: str | tuple[str, ...],
        algorithms: tuple[str, ...] = ("RS256",),
        name: str = "jwks",
        leeway: float = 0.0,
        claim_mapping: ClaimMapping = DEFAULT_CLAIM_MAPPING,
        require_claims: tuple[str, ...] = (),
        jwks_ttl_seconds: float = _DEFAULT_JWKS_TTL_SECONDS,
    ) -> None:
        if not jwks_uri:
            raise ValueError(
                "JWKSAuthProvider requires a non-empty jwks_uri"
            )
        if not audience:
            raise ValueError(
                "JWKSAuthProvider requires an audience — empty audience "
                "opens the substrate to token-replay across services"
            )
        if not issuer:
            raise ValueError(
                "JWKSAuthProvider requires an issuer allowlist"
            )
        if not algorithms:
            raise ValueError(
                "JWKSAuthProvider requires a non-empty algorithms "
                "allowlist"
            )
        if "none" in (alg.lower() for alg in algorithms):
            raise ValueError(
                "JWKSAuthProvider refuses 'none' algorithm — would "
                "accept unsigned tokens"
            )
        self.name = name
        self._jwks_uri = jwks_uri
        self._algorithms = tuple(algorithms)
        self._claim_mapping = claim_mapping
        self._require_claims = tuple(require_claims)
        self._decode = _DecodeOptions(
            issuer=issuer,
            audience=audience,
            leeway=leeway,
        )
        self._jwk_client: PyJWKClient = PyJWKClient(
            jwks_uri,
            cache_keys=True,
            max_cached_keys=16,
            cache_jwk_set=True,
            lifespan=jwks_ttl_seconds,
        )

    @classmethod
    def with_jwk_client(
        cls,
        *,
        jwk_client: PyJWKClient,
        audience: str | tuple[str, ...],
        issuer: str | tuple[str, ...],
        algorithms: tuple[str, ...] = ("RS256",),
        name: str = "jwks",
        leeway: float = 0.0,
        claim_mapping: ClaimMapping = DEFAULT_CLAIM_MAPPING,
        require_claims: tuple[str, ...] = (),
    ) -> "JWKSAuthProvider":
        """Construct with a pre-configured ``PyJWKClient``.

        Test-only factory. Production callers MUST use the default
        constructor so the JWKS-fetching contract (URL, TTL,
        caches) is enforced at one site. The factory exists so
        tests can inject a client built from an in-memory JWK
        set — see ``tests/test_auth_provider_jwks.py``.
        """
        instance = cls.__new__(cls)
        instance.name = name
        instance._jwks_uri = jwk_client.uri
        instance._algorithms = tuple(algorithms)
        instance._claim_mapping = claim_mapping
        instance._require_claims = tuple(require_claims)
        instance._decode = _DecodeOptions(
            issuer=issuer,
            audience=audience,
            leeway=leeway,
        )
        instance._jwk_client = jwk_client
        return instance

    @property
    def jwks_uri(self) -> str:
        """The JWKS endpoint this provider verifies against."""
        return self._jwks_uri

    async def verify(self, credential: Credential) -> VerifiedIdentity:
        if credential.scheme.lower() not in self._accepted_schemes:
            raise AuthenticationError(
                f"JWKSAuthProvider only accepts Bearer credentials "
                f"(got scheme={credential.scheme!r})"
            )
        token = credential.value
        signing_key = await self._resolve_signing_key(token)
        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=list(self._algorithms),
                issuer=self._decode.issuer,
                audience=self._decode.audience,
                leeway=self._decode.leeway,
            )
        except InvalidAlgorithmError as err:
            raise AuthenticationError(
                f"unsupported algorithm: {err}"
            ) from err
        except InvalidIssuerError as err:
            raise AuthenticationError(
                f"issuer not allowed: {err}"
            ) from err
        except InvalidAudienceError as err:
            raise AuthenticationError(
                f"audience mismatch: {err}"
            ) from err
        except InvalidTokenError as err:
            raise AuthenticationError(
                f"invalid token: {err}"
            ) from err

        if not isinstance(claims, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise AuthenticationError(
                "JWT payload is not a JSON object"
            )

        for required in self._require_claims:
            if required not in claims:
                raise AuthenticationError(
                    f"required claim missing: {required!r}"
                )

        identity_axes: dict[str, str | None] = {}
        for axis, claim_name in (
            ("tenant_id", self._claim_mapping.tenant_id),
            ("principal_id", self._claim_mapping.principal_id),
            ("organization_id", self._claim_mapping.organization_id),
            ("environment_id", self._claim_mapping.environment_id),
        ):
            if claim_name is None:
                identity_axes[axis] = None
                continue
            value = claims.get(claim_name)
            if value is None:
                identity_axes[axis] = None
                continue
            if not isinstance(value, str):
                raise AuthenticationError(
                    f"claim {claim_name!r} must be a string "
                    f"(got {type(value).__name__})"
                )
            identity_axes[axis] = value

        exp = claims.get("exp")
        expires_at: datetime | None
        if isinstance(exp, (int, float)):
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        else:
            expires_at = None

        capabilities = self._extract_capabilities(claims)

        return VerifiedIdentity(
            tenant_id=identity_axes["tenant_id"],
            principal_id=identity_axes["principal_id"],
            organization_id=identity_axes["organization_id"],
            environment_id=identity_axes["environment_id"],
            capabilities=capabilities,
            issuer=self.name,
            issued_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            claims=dict(claims),
        )

    async def _resolve_signing_key(self, token: str) -> Any:
        """Look up the verification key for ``token`` from the JWKS.

        PyJWT's ``get_signing_key_from_jwt`` reads the header's
        ``kid`` and (a) returns from cache when present, or (b)
        fetches the JWKS over HTTP, populates the cache, and
        returns the matching key. Network I/O is sync, hence the
        :func:`asyncio.to_thread` hop.

        Every failure mode is normalised to
        :class:`AuthenticationError` so callers branch on a single
        exception type regardless of network / key-not-found /
        malformed-header failure cause.
        """
        try:
            signing_key = await asyncio.to_thread(
                self._jwk_client.get_signing_key_from_jwt, token
            )
        except PyJWKClientError as err:
            # Covers: JWKS fetch failure, missing kid in JWKS,
            # malformed JWKS, header parse errors.
            raise AuthenticationError(
                f"JWKS key resolution failed: {err}"
            ) from err
        except InvalidTokenError as err:
            raise AuthenticationError(
                f"malformed token header: {err}"
            ) from err
        return signing_key.key

    def _extract_capabilities(
        self, claims: dict[str, Any]
    ) -> frozenset[str]:
        claim_name = self._claim_mapping.capabilities
        if claim_name is None:
            return frozenset()
        raw = claims.get(claim_name)
        if raw is None:
            return frozenset()
        if isinstance(raw, str):
            # OAuth2 ``scope`` style — space-separated.
            return frozenset(token for token in raw.split() if token)
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if not isinstance(item, str):
                    raise AuthenticationError(
                        f"capabilities claim {claim_name!r} must be "
                        f"a string or array of strings (got element "
                        f"of type {type(item).__name__})"
                    )
            return frozenset(raw)
        raise AuthenticationError(
            f"capabilities claim {claim_name!r} must be a string or "
            f"array of strings (got {type(raw).__name__})"
        )


__all__ = ["JWKSAuthProvider"]
