"""Auth endpoints — v1 transport layer (Phase 3.2 / PR-D1).

Single endpoint:

* ``GET /me`` — return the verified principal bound to the
  request by :class:`AuthorityContextMiddleware`. Used by the
  command-center login flow to confirm the Auth0 token is
  accepted and to hydrate the in-browser principal context
  (replaces the ``principal-demo`` mock from PR-A2).

Why /me lands first
───────────────────
``/me`` is the smallest possible round-trip that exercises the
entire Phase 3 auth wiring end-to-end:

* the Auth0 token reaches :class:`AuthorityContextMiddleware`;
* the configured :class:`AuthProvider` (typically
  :class:`JWKSAuthProvider` from PR-C1) verifies it;
* the :func:`verified_identity_to_authority` bridge produces a
  typed :class:`AuthorityContext`;
* :func:`require_authority` materialises the context as a route
  dependency;
* the handler projects it through the schema and returns JSON.

Every failure mode (anonymous, malformed Authorization,
verification failure, malformed claim) returns a stable error
shape so the SDK can map status codes to client-side actions
(redirect to sign-in, surface error toast, etc.).

Tenant-scope dependency choice
──────────────────────────────
``/me`` depends on :func:`require_authority` rather than
:func:`require_tenant_scope`. A verified principal whose
authority lacks a tenant axis is constitutionally rare (the
upstream IdP should always emit the tenant claim) but it is not
an error per se — the response simply carries ``tenant_id =
None`` and the frontend handles the no-tenant case (e.g. by
rendering a tenant-selector UI). Tenant-scope enforcement
belongs on tenant-SCOPED reads (sessions, governance decisions,
…), not on the self-identity endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.v1.schemas.auth import MePrincipalResponse
from app.dependencies.authority import require_authority
from app.identity.authority import AuthorityContext
from app.middleware.authority_context import AUTHORITY_SOURCE_ANONYMOUS

router = APIRouter(tags=["auth"])


@router.get(
    "/me",
    response_model=MePrincipalResponse,
    summary="Current principal",
    description=(
        "Return the verified principal bound to this request. "
        "Returns 401 ``authority_required`` when no authority is "
        "bound (anonymous request)."
    ),
)
async def me(
    request: Request,
    authority: AuthorityContext = Depends(require_authority),
) -> MePrincipalResponse:
    # ``request.state.authority_source`` is set by
    # :class:`AuthorityContextMiddleware` on every successful
    # ingress. The fallback to ``AUTHORITY_SOURCE_ANONYMOUS``
    # cannot fire in practice (``require_authority`` would have
    # raised 401 first), but keeps the handler total under an
    # unexpected middleware ordering change.
    source = getattr(
        request.state, "authority_source", AUTHORITY_SOURCE_ANONYMOUS
    )
    return MePrincipalResponse.from_authority(
        authority, source=source
    )


__all__ = ["router"]
