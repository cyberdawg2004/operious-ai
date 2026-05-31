"""Canonical authority / tenant-scope FastAPI dependencies.

Constitutional positioning
──────────────────────────
This module is the **single** way public HTTP read endpoints
extract the tenant scope to forward to persistence reads. It
materialises the contract established by Wedge 2.75-ε
(``expected_tenant_id`` row-level isolation) at the composition
root so that no read handler can accidentally bypass scope.

Doctrine
────────
1. The :class:`AuthorityContext` is bound onto
   ``request.state.authority`` by
   :class:`app.middleware.authority_context.AuthorityContextMiddleware`
   (Wedge B8 / C2). Read handlers consume it via these
   dependencies — never by manually digging into ``request.state``.
2. ``require_tenant_scope`` is the **default** for any read
   endpoint that returns tenant-scoped resources (sessions,
   coordination envelopes, supervisor inspections, agent
   executions, governance decisions, …). It REJECTS anonymous
   requests and requests whose authority has no tenant axis.
   The constitutional reason: a tenant-less authority cannot
   safely enumerate tenant-scoped records — the only safe
   behaviour is denial.
3. ``request_tenant_scope_opt`` is reserved for admin /
   substrate-internal handlers that intentionally span tenants
   (replay-from-cold-storage tools, ops-visibility surfaces).
   When ``None`` is returned, persistence reads see ``None``
   and behave exactly as they did pre-2.75-ε (no scope clamp).
   Using this on a tenant-scoped resource is a constitutional
   violation; reviewers MUST justify any new caller.
4. RBAC remains parked behind ``SubjectKind.CAPABILITY`` — this
   module does NOT make capability decisions. Capability legality
   is a separate gate evaluated by the substrate runtimes (Wedge
   2.75-α); these dependencies only handle the *tenant* axis.

Why dependencies and not middleware
───────────────────────────────────
A middleware would couple every endpoint to the same tenant-scope
policy, which contradicts admin / substrate-internal handlers.
A dependency makes the constraint **explicit at the handler
signature** — the policy is visible in the route definition, so
reviewers can verify scope intent per-endpoint without reading
middleware ordering.

Future
──────
When Phase 2.4 ships substrate DI providers (session runtime,
coordination runtime, supervisor repository, …), they will
declare ``expected_tenant_id`` as a dependency parameter sourced
from :func:`require_tenant_scope`. Endpoint authors then write::

    @router.get("/sessions/{sid}")
    async def get_session(
        sid: SessionId,
        runtime: SessionRuntime = Depends(get_session_runtime),
        expected_tenant_id: str = Depends(require_tenant_scope),
    ) -> SessionResponse:
        envelope = await runtime.get_session(
            sid, expected_tenant_id=expected_tenant_id
        )
        ...

and the substrate's read enforces row-level isolation by
construction. There is no path for a handler to read
tenant-scoped persistence WITHOUT consulting one of these
dependencies — that property is asserted by an architectural
invariant test (``test_tenant_scope_dependency_invariants``).
"""

from __future__ import annotations

from typing import Callable, Final

from fastapi import Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.identity.authority import AuthorityContext

#: Stable error code for "anonymous request hit tenant-scoped read".
#: Frontends should map this to a sign-in redirect; SDKs should
#: surface it as :class:`AuthenticationRequiredError`. The code is
#: deliberately distinct from a 401 "credentials invalid" because
#: anonymous IS the credentials state; only its scope is the
#: problem.
ERROR_CODE_AUTHORITY_REQUIRED: Final[str] = "authority_required"

#: Stable error code for "authority present but no tenant axis".
#: This is a constitutional configuration error in the upstream
#: identity provider (the authority should always carry a tenant
#: when the requester is not anonymous). Returning a distinct code
#: from ``authority_required`` lets ops triage misconfigured
#: providers separately from un-authed requests.
ERROR_CODE_TENANT_AXIS_MISSING: Final[str] = "tenant_axis_missing"
ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED: Final[str] = "operator_authority_required"
OPERATOR_CAPABILITY: Final[str] = "operator"

#: Stable error code for "authority present but lacks the capability
#: a mutation route requires" (S-02). Distinct from
#: ``tenant_axis_missing`` (which is a tenant-axis problem) and from
#: ``authority_required`` (which is the anonymous state) so the
#: frontend / SDK can surface a precise "insufficient privilege"
#: message rather than a sign-in redirect.
ERROR_CODE_CAPABILITY_REQUIRED: Final[str] = "capability_required"

#: Capability required to MUTATE tenant configuration — channels,
#: knowledge, governance policy, execution governance, and topology.
#: Granted by the ``TenantAdmin`` Auth0 role (see
#: ``app.auth.providers.jwt.ROLE_CAPABILITY_MAP``). Tenant scope alone
#: is NOT sufficient; without this capability a tenant-scoped caller
#: can only READ configuration.
TENANT_ADMIN_CAPABILITY: Final[str] = "tenant_admin"

#: Stable error code for "config change may be PROPOSED but not APPLIED
#: by this caller" (S-03). Separation of duties: applying a knowledge /
#: policy / execution-governance change requires an independent approval
#: capability distinct from the write capability.
ERROR_CODE_INDEPENDENT_APPROVAL_REQUIRED: Final[str] = "independent_approval_required"

#: Capability required to APPROVE / APPLY a tenant governance, knowledge,
#: or execution-governance change (S-03). Deliberately DISTINCT from
#: ``tenant_admin`` so an organisation can separate the write duty from
#: the approve duty. Granted by the ``TenantApprover`` Auth0 role.
TENANT_CONFIG_APPROVE_CAPABILITY: Final[str] = "tenant.config.approve"


def request_authority_opt(request: Request) -> AuthorityContext | None:
    """Return the request's :class:`AuthorityContext` or ``None``.

    Use this only in handlers that explicitly support anonymous
    access (health, readiness, public marketing pages). For
    tenant-scoped resources, depend on
    :func:`require_tenant_scope` instead.

    The value is bound onto ``request.state.authority`` by the
    authority-context middleware (Wedge B8 / C2). Reading
    ``request.state`` directly bypasses this contract and is
    forbidden by architectural invariant.
    """
    return getattr(request.state, "authority", None)


def require_authority(request: Request) -> AuthorityContext:
    """FastAPI dependency: return the request :class:`AuthorityContext`.

    Raises :exc:`fastapi.HTTPException` (401
    ``authority_required``) when the request carries no usable
    authority. This is the wedge every authenticated handler
    transitively depends on.

    "No usable authority" covers two operationally distinct
    states the dependency treats identically:

    * ``request.state.authority`` is unbound — the
      :class:`AuthorityContextMiddleware` did not run. This is
      a test-only state in practice; production always runs the
      middleware.
    * ``request.state.authority`` is bound to a fully-empty
      :class:`AuthorityContext` (every axis ``None``,
      :attr:`is_fully_anonymous` ``True``). This is the
      middleware's normal output for an anonymous ingress (no
      ``Authorization``, no ``X-*-ID`` headers).

    Both states represent "no principal has been attested for
    this request" — the only safe answer to a protected
    endpoint is refusal. Returning the empty
    :class:`AuthorityContext` here would let handlers see "an
    authority" and then mishandle the all-``None`` axes as
    legitimate identity material — exactly the failure mode the
    fail-closed doctrine forbids.
    """
    authority = request_authority_opt(request)
    if authority is None or authority.is_fully_anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": ERROR_CODE_AUTHORITY_REQUIRED},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authority


def require_tenant_scope(request: Request) -> str:
    """FastAPI dependency: return the **canonical tenant scope** for
    forwarding to persistence ``expected_tenant_id`` arguments.

    Constitutional contract:

    * The authority MUST be bound (otherwise → 401
      ``authority_required``).
    * The authority MUST carry a ``tenant_id`` axis (otherwise →
      400 ``tenant_axis_missing``). The platform refuses to
      enumerate tenant-scoped records under a tenant-less
      authority because no safe answer exists: returning ALL
      tenants' records is a multi-tenant boundary violation, and
      returning NONE silently masks the misconfiguration.

    Return value is always a non-empty ``str`` ready to forward
    directly into ``runtime.get_session(..., expected_tenant_id=…)``,
    ``persistence.query_envelopes(..., expected_tenant_id=…)``,
    etc. Handlers MUST forward this value verbatim — they MUST
    NOT widen, narrow, or substitute it.
    """
    authority = require_authority(request)
    if authority.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": ERROR_CODE_TENANT_AXIS_MISSING},
        )
    return str(authority.tenant_id)


def require_operator_authority(request: Request) -> AuthorityContext:
    """FastAPI dependency: require an operator-level authority claim."""

    authority = require_authority(request)
    if OPERATOR_CAPABILITY not in authority.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED},
        )
    return authority


def require_capability(
    capability: str,
) -> Callable[[Request], AuthorityContext]:
    """Build a dependency that requires ``capability`` on the authority.

    The returned dependency:

    * rejects anonymous requests with 401 ``authority_required``
      (delegated to :func:`require_authority`), and
    * rejects an authenticated request that does not hold
      ``capability`` with 403 ``capability_required``.

    Capabilities are sourced exclusively from the verified bearer
    identity (JWT ``capabilities`` / ``roles`` / ``permissions`` claims
    mapped at :mod:`app.auth.providers.jwt`). A spoofable ``X-*-ID``
    header carries NO capabilities, so a header-mode caller can never
    satisfy a capability gate — which is the intended posture for
    privileged mutations.
    """

    def _dependency(request: Request) -> AuthorityContext:
        authority = require_authority(request)
        if capability not in authority.capabilities:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": ERROR_CODE_CAPABILITY_REQUIRED,
                    "capability": capability,
                },
            )
        return authority

    return _dependency


def require_tenant_admin(request: Request) -> AuthorityContext:
    """FastAPI dependency: require the tenant-admin capability (S-02).

    Default gate for every tenant-configuration MUTATION route.
    Reusing a module-level function (rather than a closure) keeps the
    dependency identity stable so tests can override it via
    ``app.dependency_overrides[require_tenant_admin]``.
    """

    authority = require_authority(request)
    if TENANT_ADMIN_CAPABILITY not in authority.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": ERROR_CODE_CAPABILITY_REQUIRED,
                "capability": TENANT_ADMIN_CAPABILITY,
            },
        )
    return authority


def require_config_apply_authorization(
    authority: AuthorityContext = Depends(require_tenant_admin),
) -> AuthorityContext:
    """Authorize the legacy direct tenant-config mutation path (S-03).

    The durable ledger is the production path. Direct mutation remains
    available only when explicitly enabled in non-production, so old
    endpoints cannot silently self-approve in production even if the
    caller also holds the approve capability.
    """

    if get_settings().tenant_config_self_approval_allowed:
        return authority
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": ERROR_CODE_INDEPENDENT_APPROVAL_REQUIRED,
            "capability": TENANT_CONFIG_APPROVE_CAPABILITY,
        },
    )


def request_tenant_scope_opt(request: Request) -> str | None:
    """FastAPI dependency: return the request's tenant scope or
    ``None`` (unconstrained).

    **Restricted use.** Reserved for admin / substrate-internal
    handlers that intentionally span tenants (cold-storage replay
    tools, ops dashboards, cross-tenant audit endpoints). Reviewers
    must justify every new caller — using this for a normal
    customer-facing endpoint is a constitutional violation that
    re-opens the tenant-isolation gap Wedge 2.75-ε closed.

    When the request has no bound authority (anonymous), or when
    the authority has no tenant axis, this returns ``None``. The
    consuming persistence read then sees ``None`` and behaves
    identically to pre-2.75-ε (no scope clamp). The CALLER is
    therefore responsible for ensuring this is the desired
    semantics for the endpoint — the platform does not
    second-guess admin intent.
    """
    authority = request_authority_opt(request)
    if authority is None or authority.tenant_id is None:
        return None
    return str(authority.tenant_id)


__all__ = [
    "ERROR_CODE_AUTHORITY_REQUIRED",
    "ERROR_CODE_CAPABILITY_REQUIRED",
    "ERROR_CODE_INDEPENDENT_APPROVAL_REQUIRED",
    "ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED",
    "ERROR_CODE_TENANT_AXIS_MISSING",
    "OPERATOR_CAPABILITY",
    "TENANT_ADMIN_CAPABILITY",
    "TENANT_CONFIG_APPROVE_CAPABILITY",
    "request_authority_opt",
    "request_tenant_scope_opt",
    "require_authority",
    "require_capability",
    "require_config_apply_authorization",
    "require_operator_authority",
    "require_tenant_admin",
    "require_tenant_scope",
]
