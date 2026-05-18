"""Canonical HTTP authority extraction middleware.

Wedge B8 — the single, deterministic, traceable ingress site where
HTTP headers converge into a typed
:class:`app.identity.AuthorityContext`. After this middleware runs,
the authority for the request lives in exactly TWO mirrored places:

1. ``request.state.authority``       — for handlers / dependencies
   that prefer explicit access.
2. The :func:`app.identity.get_request_authority` ContextVar — for
   observability attribution where threading the authority through
   every layer would be impractical.

No other code path in the codebase is permitted to read identity
HTTP headers (``X-Tenant-ID`` / ``X-Principal-ID`` /
``X-Organization-ID`` / ``X-Environment-ID``). A static doctrine
scan in ``tests/test_authority_context_middleware.py`` enforces
this — the moment a second site starts parsing identity headers,
the "ingress authority is singular" invariant is broken and the
audit-tagged ``AuthoritySource`` attribution flowing into
``resolve_authority`` becomes unreliable.

Constitutional positioning
──────────────────────────
This middleware is the STRUCTURAL convergence point for HTTP
authority. It is intentionally NOT:

* an authentication site — header signatures / JWT verification
  belongs to the future auth-provider ecosystem wedge. This
  middleware trusts that whatever produced the header (gateway,
  auth provider, frontend) authorised it upstream.
* an authorisation site — RBAC / capability evaluation belongs in
  governance via ``SubjectKind.CAPABILITY`` (out of scope).
* a tenant policing site — that doctrine lives in
  ``TenantScopePolicy`` (governance) and ``TenantIsolationEvaluator``
  (coordination policy), both unified by Wedge B5.

Malformed-input doctrine
────────────────────────
A header that is PRESENT but whitespace-only / empty is a
structural malformation: it cannot satisfy ``coerce_*_id``'s
validity contract, and silently coercing it to ``None`` would
violate the ``IdentityError`` invariant established in Wedge A.
The middleware refuses such requests with ``400 Bad Request`` and
a stable JSON body identifying the offending header. Missing
headers entirely are legitimate (anonymous requests) and produce
an ``AuthorityContext`` with the corresponding field set to
``None``.

Ordering note
─────────────
This middleware is registered AFTER
:class:`app.middleware.request_context.RequestContextMiddleware` in
``app.main.create_app`` so that, given Starlette's prepend-based
``add_middleware`` semantics, it ends up INNER to the request-id
middleware in the request flow. Request flow is therefore
``RequestContext → AuthorityContext → Router``: the request id is
bound BEFORE this middleware logs or returns a 400, so every
authority-extraction error carries a correlation id.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Final, Mapping

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.identity.authority import AuthorityContext
from app.identity.primitives import IdentityError
from app.identity.runtime import (
    reset_request_authority,
    set_request_authority,
)

logger = logging.getLogger(__name__)


# ─── Canonical header names ────────────────────────────────────────
# These are the SINGLE source of truth for HTTP authority header
# names. Other code paths that need to refer to them must import
# these constants — string literals duplicated elsewhere break the
# singularity invariant and are caught by the doctrine test.

TENANT_HEADER: Final[str] = "X-Tenant-ID"
PRINCIPAL_HEADER: Final[str] = "X-Principal-ID"
ORGANIZATION_HEADER: Final[str] = "X-Organization-ID"
ENVIRONMENT_HEADER: Final[str] = "X-Environment-ID"

#: Stable ordering — used by the middleware to walk headers and by
#: tests to enumerate the canonical surface.
AUTHORITY_HEADERS: Final[tuple[str, ...]] = (
    TENANT_HEADER,
    PRINCIPAL_HEADER,
    ORGANIZATION_HEADER,
    ENVIRONMENT_HEADER,
)

#: Maps each canonical header to its corresponding
#: ``AuthorityContext.from_raw`` keyword. Kept in module scope so
#: tests can pin the surface; consumers should not reach into this
#: mapping for parsing — call the middleware once at ingress.
HEADER_TO_FIELD: Final[Mapping[str, str]] = {
    TENANT_HEADER: "tenant_id",
    PRINCIPAL_HEADER: "principal_id",
    ORGANIZATION_HEADER: "organization_id",
    ENVIRONMENT_HEADER: "environment_id",
}


# ─── Middleware ────────────────────────────────────────────────────


class AuthorityContextMiddleware(BaseHTTPMiddleware):
    """Build and bind one :class:`AuthorityContext` per request.

    Algorithm (deterministic, pure):

    1. Read each canonical header. A missing header → field stays
       ``None``. A present-but-empty / whitespace-only header is a
       structural malformation handled in step 3.
    2. Hand the four raw values to
       :meth:`AuthorityContext.from_raw`, which runs each non-None
       value through the corresponding ``coerce_*_id`` helper.
    3. If ``coerce_*_id`` raises :class:`IdentityError`, the
       request is rejected with ``400 Bad Request`` and a stable
       JSON body identifying the offending header. The body is
       designed to be machine-parseable so client-side test
       fixtures (and the future auth provider) can pin against it.
    4. On success, stash the result on ``request.state.authority``
       and bind the ContextVar (with paired reset in ``finally``).
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            authority = self._extract(request)
        except _AuthorityHeaderError as err:
            logger.warning(
                "authority_header_malformed",
                extra={
                    "header": err.header,
                    "reason": err.reason,
                },
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

        request.state.authority = authority
        token = set_request_authority(authority)
        try:
            response: Response = await call_next(request)
        finally:
            reset_request_authority(token)
        return response

    @staticmethod
    def _extract(request: Request) -> AuthorityContext:
        """Pure extraction: headers → ``AuthorityContext``.

        Raises :class:`_AuthorityHeaderError` (caught by ``dispatch``
        and translated to a 400 response) when any present header is
        whitespace-only / empty. Missing headers are tolerated and
        produce ``None`` axes.
        """
        raw: dict[str, str | None] = {}
        for header in AUTHORITY_HEADERS:
            value = request.headers.get(header)
            field = HEADER_TO_FIELD[header]
            if value is None:
                raw[field] = None
                continue
            try:
                # We rely on ``coerce_*_id`` (invoked by
                # ``AuthorityContext.from_raw``) to perform the
                # canonical strip-and-validate. We pass the value
                # through so the SAME validation runs in the
                # middleware as in any other ``from_raw`` caller —
                # there is no parallel validation path. We still
                # short-circuit obvious whitespace here so the
                # error attribution names the exact offending
                # HEADER (not just the field), which audit needs.
                if not value.strip():
                    raise _AuthorityHeaderError(
                        header=header,
                        reason="value is empty or whitespace-only",
                    )
            except _AuthorityHeaderError:
                raise
            raw[field] = value

        try:
            return AuthorityContext.from_raw(**raw)
        except IdentityError as err:
            # Defensive: ``coerce_*_id`` could in principle raise
            # for a malformation we did not pre-screen. Map back
            # to the offending header by re-walking the inputs.
            offending_header = _identify_offending_header(raw, err)
            raise _AuthorityHeaderError(
                header=offending_header,
                reason=str(err),
            ) from err


# ─── Internals ─────────────────────────────────────────────────────


class _AuthorityHeaderError(Exception):
    """Internal carrier for one malformed HTTP authority header.

    Not exported; the middleware catches it and renders a 400 JSON
    response. The shape matches the response body so tests can pin
    both the wire format and the internal contract.
    """

    def __init__(self, *, header: str, reason: str) -> None:
        super().__init__(f"{header}: {reason}")
        self.header = header
        self.reason = reason


def _identify_offending_header(
    raw: Mapping[str, str | None],
    err: IdentityError,
) -> str:
    """Best-effort attribution of an ``IdentityError`` to a header.

    The ``coerce_*_id`` helpers all raise messages prefixed with the
    field name (``tenant_id``, ``principal_id``, ...). We invert the
    ``HEADER_TO_FIELD`` map to recover the header. If the message
    doesn't match any field (would only happen if the helper API
    changes), we fall back to the first non-None raw entry so the
    response always names some header. The static field-name shape
    is pinned by ``test_identity_primitives.py``.
    """
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
    "AuthorityContextMiddleware",
    "ENVIRONMENT_HEADER",
    "HEADER_TO_FIELD",
    "ORGANIZATION_HEADER",
    "PRINCIPAL_HEADER",
    "TENANT_HEADER",
]
