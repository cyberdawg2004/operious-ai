"""Request-scoped ``AuthorityContext`` runtime accessors.

Wedge B8 — canonical HTTP authority extraction. This module exposes
the single ``ContextVar`` that holds the per-request
``AuthorityContext`` constructed by
``app.middleware.authority_context.AuthorityContextMiddleware``.

The runtime context mirrors the pattern in
``app.observability.context`` (request id ContextVar): the
middleware OWNS the binding via ``set_request_authority`` and MUST
call ``reset_request_authority`` on the way out. Application code is
read-only via ``get_request_authority``.

The constitutional purpose is observability without explicit
threading: any code path that needs to attribute logs, audit events,
or background tasks to the inbound authority can do so via this
ContextVar without every handler having to pass the
``AuthorityContext`` explicitly. This preserves the "ingress
authority is singular" doctrine — there is exactly ONE
``AuthorityContext`` per request, set by the middleware once and
read everywhere.

Important: business logic (governance evaluation, orchestration,
persistence) MUST NOT consume this ContextVar. The
``AuthorityContext`` belongs on the request itself
(``request.state.authority``) and flows through typed contracts.
The ContextVar exists strictly for *observability* attribution
where threading the value through every layer would be impractical
(structured logging, audit hooks, profiling). Anyone using this for
control-flow violates the "Authority Singularity" core law because
the singular source of truth at evaluation time is the typed
``AuthorityContext`` argument, not an ambient ContextVar.

See ``app/middleware/authority_context.py`` for the binding site
and ``docs/identity/tenant-propagation-audit.md`` for the upstream
doctrine.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from app.identity.authority import AuthorityContext

_REQUEST_AUTHORITY: ContextVar[AuthorityContext | None] = ContextVar(
    "operious_request_authority",
    default=None,
)

#: Branch D — observability attribution. Carries the request's
#: ``authority_source`` literal (``"verified"`` / ``"header"`` /
#: ``"anonymous"``) alongside the :class:`AuthorityContext` itself
#: so structured logs and audit hooks can attribute each record to
#: the ingress trust posture without re-reading ``request.state``.
_REQUEST_AUTHORITY_SOURCE: ContextVar[str | None] = ContextVar(
    "operious_request_authority_source",
    default=None,
)


def get_request_authority() -> AuthorityContext | None:
    """Return the current request's :class:`AuthorityContext`.

    Returns ``None`` outside a request (background tasks not
    spawned from a request, startup code, REPL).
    """
    return _REQUEST_AUTHORITY.get()


def set_request_authority(
    authority: AuthorityContext,
) -> Token[AuthorityContext | None]:
    """Bind ``authority`` to the current task context.

    Returns the reset token; callers (the ingress middleware) MUST
    call :func:`reset_request_authority` with this token in their
    ``finally`` block to keep the context strictly per-request and
    prevent cross-request leakage on ASGI worker reuse.
    """
    return _REQUEST_AUTHORITY.set(authority)


def reset_request_authority(
    token: Token[AuthorityContext | None],
) -> None:
    """Restore the previous request's authority (or ``None``)."""
    _REQUEST_AUTHORITY.reset(token)


def get_request_authority_source() -> str | None:
    """Return the current request's authority source literal.

    Mirrors :func:`get_request_authority`. Returns ``None`` when
    no authority is bound (background tasks, REPL).
    """
    return _REQUEST_AUTHORITY_SOURCE.get()


def set_request_authority_source(
    source: str,
) -> Token[str | None]:
    return _REQUEST_AUTHORITY_SOURCE.set(source)


def reset_request_authority_source(
    token: Token[str | None],
) -> None:
    _REQUEST_AUTHORITY_SOURCE.reset(token)


__all__ = [
    "get_request_authority",
    "get_request_authority_source",
    "reset_request_authority",
    "reset_request_authority_source",
    "set_request_authority",
    "set_request_authority_source",
]
