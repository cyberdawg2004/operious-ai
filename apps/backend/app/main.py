"""FastAPI application entrypoint.

Thin composition root: builds settings, initialises logging, registers
middleware, constructs the aggregated API router, and wires them onto a
`FastAPI` instance. No business logic lives here — this file is
intentionally boring.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import build_api_router
from app.auth import AuthProvider
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis
from app.db.session import dispose_engine
from app.middleware.authority_context import (
    AUTHORITY_HEADERS,
    AuthorityContextMiddleware,
)
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.trusted_ingress import (
    IPNetwork,
    TrustedIngressMiddleware,
)
from app.observability.context import get_request_id
from app.survivability import (
    PROBLEM_DETAILS_MEDIA_TYPE,
    ProblemDetails,
    problem_details_response,
)

_unhandled_logger = logging.getLogger("app.main.unhandled")


def _problem_for_status(
    *,
    status: int,
    title: str,
    detail: str,
    request: Request,
) -> ProblemDetails:
    """Build a ProblemDetails carrying the request_id as ``instance``.

    Exception handlers funnel every error through this helper so the
    wire shape is uniform and the request_id is always discoverable
    in the body, not just the headers.
    """
    request_id = get_request_id() or request.headers.get("X-Request-ID")
    return ProblemDetails(
        type="about:blank",
        title=title,
        status=status,
        detail=detail,
        instance=f"urn:operious:request:{request_id}" if request_id else None,
    )


def _build_cors_origins(raw: str) -> list[str]:
    """Parse the comma-separated CORS allowlist.

    Doctrine: wildcard ``"*"`` is rejected at composition time. An
    empty string disables CORS entirely (no middleware mounted).
    """
    items = [v.strip() for v in raw.split(",") if v.strip()]
    if any(v == "*" for v in items):
        raise ValueError(
            "CORS_ALLOW_ORIGINS must be a concrete allowlist; "
            "wildcard '*' is forbidden by transport doctrine."
        )
    return items


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings: Settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)
    logger.info(
        "application_startup",
        extra={
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    )
    try:
        yield
    finally:
        # The pre-Phase-2.1 orchestration / AI-provider lifespan hooks were
        # removed when those substrates were quarantined into
        # `app/_deprecated/`. The constitutional substrates are pure
        # value-object layers and have no I/O resources to dispose of. The
        # only live infra we still own is the SQLAlchemy engine and the
        # Redis connection (both lazy / no-op when not configured).
        await dispose_engine()
        await close_redis()
        logger.info("application_shutdown", extra={"app": settings.APP_NAME})


def _register_exception_handlers(app: FastAPI) -> None:
    """Register the ProblemDetails-shaped exception handlers (2.5-I).

    Every error path returns a uniform RFC 9457 envelope carrying the
    request_id as ``instance``. This keeps the wire format consistent
    across HTTPException, validation errors, and unhandled exceptions
    so frontend / SDK consumers can render and log uniformly.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ):
        problem = _problem_for_status(
            status=exc.status_code,
            title=exc.detail if isinstance(exc.detail, str) else "http_error",
            detail=str(exc.detail) if exc.detail else "",
            request=request,
        )
        return problem_details_response(problem)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ):
        problem = _problem_for_status(
            status=422,
            title="validation_error",
            detail="One or more fields failed validation.",
            request=request,
        )
        # Attach the structured errors as an extension member.
        payload = problem.model_dump(exclude_none=True)
        payload["errors"] = exc.errors()
        from fastapi.responses import JSONResponse

        return JSONResponse(
            content=payload,
            status_code=422,
            media_type=PROBLEM_DETAILS_MEDIA_TYPE,
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        # Log with traceback; do not leak internal details to the wire.
        _unhandled_logger.exception(
            "unhandled_exception",
            extra={"path": str(request.url.path)},
        )
        problem = _problem_for_status(
            status=500,
            title="internal_error",
            detail="The server encountered an unexpected condition.",
            request=request,
        )
        return problem_details_response(problem)


def create_app(
    *,
    auth_provider: AuthProvider | None = None,
    trusted_proxies: tuple[IPNetwork, ...] | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    ``auth_provider`` is plumbed into
    :class:`AuthorityContextMiddleware`. When ``None`` (default),
    Authorization-bearing requests are rejected with
    ``401 verification_unavailable`` (fail-closed per B5) while
    the legacy ``X-*-ID`` ingress path and anonymous requests
    continue to work. Concrete provider implementations are
    delivered by Wedge C3.

    ``trusted_proxies`` activates the C4 trusted-ingress chain.
    When ``None`` and ``ENVIRONMENT == "production"``, the
    composition root REJECTS the boot — production deployments
    MUST pin an explicit (possibly empty) trusted-proxy allowlist
    (2.5-I). For non-production deployments, ``None`` preserves
    the legacy behaviour (no enforcement) so test harnesses
    continue to work.

    2.5-I additionally registers:
      * uniform RFC 9457 ``application/problem+json`` exception
        handlers (HTTPException, validation, unhandled),
      * a fail-closed ``CORSMiddleware`` configured from the
        ``CORS_ALLOW_ORIGINS`` allowlist (no wildcard).
    """

    settings = get_settings()
    configure_logging(settings)

    # 2.5-I production posture — trusted_proxies must be explicit.
    if (
        settings.is_production
        and trusted_proxies is None
    ):
        raise RuntimeError(
            "Production deployments MUST pin an explicit "
            "`trusted_proxies` tuple (possibly empty for the strict "
            "fail-closed setting). Refusing to boot with "
            "`trusted_proxies=None`."
        )

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    _register_exception_handlers(app)

    # Middleware registration order matters: Starlette's
    # ``add_middleware`` prepends to ``user_middleware`` and the
    # build wraps in REVERSED order, so the LAST registered class
    # ends up OUTERMOST in the request flow. We want:
    #
    #     CORS (outermost) → RequestContext → TrustedIngress
    #         → AuthorityContext (innermost) → Router
    #
    # so the request id is bound BEFORE the authority middleware
    # logs / returns a 400 — every authority-extraction error then
    # carries the correlation id. Wedge B8 establishes
    # ``AuthorityContextMiddleware`` as the SINGLE canonical
    # HTTP-level identity extraction site; see
    # ``app/middleware/authority_context.py`` for the doctrine.
    # Inner → outer (Starlette prepends; last added is outermost).
    app.add_middleware(
        AuthorityContextMiddleware,
        auth_provider=auth_provider,
    )
    if trusted_proxies is not None:
        app.add_middleware(
            TrustedIngressMiddleware,
            trusted_proxies=trusted_proxies,
        )
    app.add_middleware(RequestContextMiddleware)

    cors_origins = _build_cors_origins(settings.CORS_ALLOW_ORIGINS)
    if cors_origins:
        # Authority headers are sourced from the single canonical
        # owner (``AUTHORITY_HEADERS`` in
        # ``app.middleware.authority_context``) so config / main never
        # repeat their literals. See
        # ``test_no_other_source_reads_authority_headers``.
        cors_headers = [
            h.strip()
            for h in settings.CORS_ALLOW_HEADERS.split(",")
            if h.strip()
        ] + list(AUTHORITY_HEADERS)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
            allow_methods=[
                m.strip()
                for m in settings.CORS_ALLOW_METHODS.split(",")
                if m.strip()
            ],
            allow_headers=cors_headers,
        )

    app.include_router(build_api_router(settings))

    return app


app: FastAPI = create_app()
