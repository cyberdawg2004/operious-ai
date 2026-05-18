"""Canonical HTTP authority extraction middleware.

Wedge B8 established the single, deterministic, traceable ingress
site where HTTP headers converge into a typed
:class:`app.identity.AuthorityContext`. Wedge C2 extends that site
with optional :class:`app.auth.AuthProvider` integration so the
ingress can VERIFY presented credentials (Authorization header)
instead of only TRUSTING upstream-stamped identity headers.

After this middleware runs, the authority for the request lives in:

1. ``request.state.authority``         — the typed AuthorityContext.
2. ``request.state.authority_source``  — one of
   :data:`AUTHORITY_SOURCE_VERIFIED`,
   :data:`AUTHORITY_SOURCE_HEADER`,
   :data:`AUTHORITY_SOURCE_ANONYMOUS` for downstream attribution
   (B6/B7 pattern at the HTTP boundary).
3. The :func:`app.identity.get_request_authority` ContextVar.

Singularity of authority source
───────────────────────────────
A request may carry **at most one** authority source:

* an ``Authorization`` header (with a configured AuthProvider) → verified
* canonical ``X-*-ID`` headers → unverified, upstream-attested
* neither → anonymous

A request that presents BOTH an Authorization header AND any
``X-*-ID`` header is structurally ambiguous (the same constitutional
class as DR-3/DR-4 silent coalescing closed by B6/B7). The
middleware rejects such requests with ``400 authority_source_conflict``.
This preserves the "ingress authority is singular" invariant from
B8 across the new verified path.

Constitutional positioning (unchanged from B8)
──────────────────────────────────────────────
* This module owns the SINGLE permitted parse of the canonical
  identity headers AND the SINGLE permitted parse of the
  Authorization header into a :class:`Credential`. No other site
  parses either.
* Concrete providers (JWT, OIDC, mTLS, ...) live OUTSIDE
  ``app.auth`` per Wedge C1 doctrine. This middleware consumes the
  protocol abstractly.
* RBAC remains parked behind ``SubjectKind.CAPABILITY`` (out of
  scope).

Ordering note (unchanged)
─────────────────────────
Registered AFTER :class:`RequestContextMiddleware` in
``app.main.create_app`` so request id is bound BEFORE authority
extraction logs / returns errors.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Final, Mapping

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.auth import (
    AuthenticationError,
    AuthProvider,
    Credential,
    verified_identity_to_authority,
)
from app.identity.authority import AuthorityContext
from app.identity.primitives import IdentityError
from app.identity.runtime import (
    reset_request_authority,
    set_request_authority,
)

logger = logging.getLogger(__name__)


# ─── Canonical header names ────────────────────────────────────────

TENANT_HEADER: Final[str] = "X-Tenant-ID"
PRINCIPAL_HEADER: Final[str] = "X-Principal-ID"
ORGANIZATION_HEADER: Final[str] = "X-Organization-ID"
ENVIRONMENT_HEADER: Final[str] = "X-Environment-ID"
AUTHORIZATION_HEADER: Final[str] = "Authorization"

#: Stable ordering — used by the middleware to walk headers and by
#: tests to enumerate the canonical surface.
AUTHORITY_HEADERS: Final[tuple[str, ...]] = (
    TENANT_HEADER,
    PRINCIPAL_HEADER,
    ORGANIZATION_HEADER,
    ENVIRONMENT_HEADER,
)

#: Maps each canonical header to its corresponding
#: ``AuthorityContext.from_raw`` keyword.
HEADER_TO_FIELD: Final[Mapping[str, str]] = {
    TENANT_HEADER: "tenant_id",
    PRINCIPAL_HEADER: "principal_id",
    ORGANIZATION_HEADER: "organization_id",
    ENVIRONMENT_HEADER: "environment_id",
}

# ─── Authority source attribution constants ────────────────────────
# Surfaces the provenance of the AuthorityContext bound to a
# request so downstream code can distinguish verified from
# upstream-trusted from anonymous. Mirrors the B6/B7
# ``AuthoritySource`` doctrine at the HTTP boundary.

AUTHORITY_SOURCE_VERIFIED: Final[str] = "verified"
AUTHORITY_SOURCE_HEADER: Final[str] = "header"
AUTHORITY_SOURCE_ANONYMOUS: Final[str] = "anonymous"

AUTHORITY_SOURCES: Final[tuple[str, ...]] = (
    AUTHORITY_SOURCE_VERIFIED,
    AUTHORITY_SOURCE_HEADER,
    AUTHORITY_SOURCE_ANONYMOUS,
)


# ─── Middleware ────────────────────────────────────────────────────


class AuthorityContextMiddleware(BaseHTTPMiddleware):
    """Build and bind one :class:`AuthorityContext` per request.

    Algorithm:

    1. Parse the ``Authorization`` header into a
       :class:`Credential` (None if absent; ``400`` on malformed).
    2. Read each canonical ``X-*-ID`` header (``400`` on
       whitespace-only).
    3. Reject ``400 authority_source_conflict`` if both a
       credential AND any legacy identity header are present.
    4. If credential present and ``auth_provider`` configured →
       verify, translate via
       :func:`verified_identity_to_authority`, source = ``verified``.
       Failure modes:

       * provider raises :class:`AuthenticationError` →
         ``401 verification_failed``.
       * provider returns malformed claim →
         :class:`IdentityError` → ``400 malformed_verified_claim``.

    5. If credential present and NO provider configured →
       ``401 verification_unavailable`` (fail-closed per B5).
    6. If only legacy headers present → existing B8 path,
       source = ``header``.
    7. Otherwise → empty :class:`AuthorityContext`, source =
       ``anonymous``.
    8. Stash ``authority`` + ``authority_source`` on
       ``request.state`` and bind the ContextVar (paired reset in
       ``finally``).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        auth_provider: AuthProvider | None = None,
    ) -> None:
        super().__init__(app)
        self._auth_provider = auth_provider

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # 1. Authorization header.
        try:
            credential = self._parse_authorization(request)
        except _AuthorizationParseError as err:
            logger.warning(
                "authority_authorization_malformed",
                extra={"reason": err.reason},
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": "malformed_authorization_header",
                    "header": AUTHORIZATION_HEADER,
                    "reason": err.reason,
                },
            )

        # 2. Legacy X-*-ID headers.
        try:
            legacy_raw = self._extract_legacy_headers(request)
        except _AuthorityHeaderError as err:
            logger.warning(
                "authority_header_malformed",
                extra={"header": err.header, "reason": err.reason},
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": "malformed_authority_header",
                    "header": err.header,
                    "field": HEADER_TO_FIELD[err.header],
                    "reason": err.reason,
                },
            )
        has_legacy = any(v is not None for v in legacy_raw.values())

        # 3. Source singularity.
        if credential is not None and has_legacy:
            logger.warning("authority_source_conflict")
            return JSONResponse(
                status_code=400,
                content={
                    "error": "authority_source_conflict",
                    "reason": (
                        "request presents both an Authorization "
                        "header and X-*-ID identity headers; "
                        "authority source must be singular"
                    ),
                },
            )

        # 4–7. Resolve source-specific AuthorityContext.
        if credential is not None:
            if self._auth_provider is None:
                logger.warning("authority_verification_unavailable")
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "verification_unavailable",
                        "reason": (
                            "no auth provider configured; cannot "
                            "verify presented credential"
                        ),
                    },
                )
            try:
                verified = await self._auth_provider.verify(credential)
            except AuthenticationError as err:
                logger.warning(
                    "authority_verification_failed",
                    extra={"reason": str(err)},
                )
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "verification_failed",
                        "reason": str(err),
                    },
                )
            try:
                authority = verified_identity_to_authority(verified)
            except IdentityError as err:
                logger.warning(
                    "authority_verified_claim_malformed",
                    extra={"reason": str(err)},
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "malformed_verified_claim",
                        "reason": str(err),
                    },
                )
            source = AUTHORITY_SOURCE_VERIFIED
        elif has_legacy:
            try:
                authority = AuthorityContext.from_raw(**legacy_raw)
            except IdentityError as err:
                offending_header = _identify_offending_header(
                    legacy_raw, err
                )
                logger.warning(
                    "authority_header_malformed",
                    extra={
                        "header": offending_header,
                        "reason": str(err),
                    },
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "malformed_authority_header",
                        "header": offending_header,
                        "field": HEADER_TO_FIELD[offending_header],
                        "reason": str(err),
                    },
                )
            source = AUTHORITY_SOURCE_HEADER
        else:
            authority = AuthorityContext()
            source = AUTHORITY_SOURCE_ANONYMOUS

        # 8. Bind.
        request.state.authority = authority
        request.state.authority_source = source
        token = set_request_authority(authority)
        try:
            response: Response = await call_next(request)
        finally:
            reset_request_authority(token)
        return response

    # ─── Parsers ──────────────────────────────────────────────────

    @staticmethod
    def _parse_authorization(
        request: Request,
    ) -> Credential | None:
        """Parse the ``Authorization`` header into a
        :class:`Credential`.

        Returns ``None`` when no Authorization header is present.
        Raises :class:`_AuthorizationParseError` on:

        * empty / whitespace-only header value,
        * missing scheme or value (no whitespace separator,
          single-token, or empty after split).

        Scheme case is PRESERVED (audit fidelity) — providers are
        expected to compare case-insensitively per RFC 7235.
        """
        raw = request.headers.get(AUTHORIZATION_HEADER)
        if raw is None:
            return None
        stripped = raw.strip()
        if not stripped:
            raise _AuthorizationParseError(
                reason="value is empty or whitespace-only"
            )
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            raise _AuthorizationParseError(
                reason="expected '<scheme> <value>', got single token"
            )
        scheme, value = parts[0], parts[1].strip()
        if not scheme or not value:
            raise _AuthorizationParseError(
                reason="scheme or value is empty after split"
            )
        return Credential(scheme=scheme, value=value)

    @staticmethod
    def _extract_legacy_headers(
        request: Request,
    ) -> dict[str, str | None]:
        """Extract the four ``X-*-ID`` headers into raw kwargs for
        :meth:`AuthorityContext.from_raw`.

        Raises :class:`_AuthorityHeaderError` when any present
        header is whitespace-only (audit needs the exact header
        name, not just the field name).
        """
        raw: dict[str, str | None] = {}
        for header in AUTHORITY_HEADERS:
            value = request.headers.get(header)
            field = HEADER_TO_FIELD[header]
            if value is None:
                raw[field] = None
                continue
            if not value.strip():
                raise _AuthorityHeaderError(
                    header=header,
                    reason="value is empty or whitespace-only",
                )
            raw[field] = value
        return raw


# ─── Internals ─────────────────────────────────────────────────────


class _AuthorityHeaderError(Exception):
    """Internal carrier for one malformed ``X-*-ID`` header."""

    def __init__(self, *, header: str, reason: str) -> None:
        super().__init__(f"{header}: {reason}")
        self.header = header
        self.reason = reason


class _AuthorizationParseError(Exception):
    """Internal carrier for malformed ``Authorization`` header."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _identify_offending_header(
    raw: Mapping[str, str | None],
    err: IdentityError,
) -> str:
    """Best-effort attribution of ``IdentityError`` to a header."""
    message = str(err)
    for header, field in HEADER_TO_FIELD.items():
        if message.startswith(field):
            return header
    for header in AUTHORITY_HEADERS:
        if raw.get(HEADER_TO_FIELD[header]) is not None:
            return header
    return AUTHORITY_HEADERS[0]


__all__ = [
    "AUTHORITY_HEADERS",
    "AUTHORITY_SOURCES",
    "AUTHORITY_SOURCE_ANONYMOUS",
    "AUTHORITY_SOURCE_HEADER",
    "AUTHORITY_SOURCE_VERIFIED",
    "AUTHORIZATION_HEADER",
    "AuthorityContextMiddleware",
    "ENVIRONMENT_HEADER",
    "HEADER_TO_FIELD",
    "ORGANIZATION_HEADER",
    "PRINCIPAL_HEADER",
    "TENANT_HEADER",
]
