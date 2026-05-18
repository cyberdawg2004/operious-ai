"""FastAPI application entrypoint.

Thin composition root: builds settings, initialises logging, registers
middleware, constructs the aggregated API router, and wires them onto a
`FastAPI` instance. No business logic lives here — this file is
intentionally boring.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import build_api_router
from app.auth import AuthProvider
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis
from app.db.session import dispose_engine
from app.middleware.authority_context import AuthorityContextMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.trusted_ingress import (
    IPNetwork,
    TrustedIngressMiddleware,
)


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
    When ``None`` (default), no trust enforcement runs and the
    B8/C2 ingress is byte-for-byte preserved (legacy / test
    deployments). When passed (including the empty tuple),
    :class:`TrustedIngressMiddleware` is registered and rejects
    authority-bearing headers from peers outside the allowlist
    with ``400 untrusted_ingress``. An empty tuple is the strict
    fail-closed setting — every peer is untrusted.
    """

    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    # Middleware registration order matters: Starlette's
    # ``add_middleware`` prepends to ``user_middleware`` and the
    # build wraps in REVERSED order, so the LAST registered class
    # ends up OUTERMOST in the request flow. We want:
    #
    #     RequestContext (outer) → AuthorityContext (inner) → Router
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

    app.include_router(build_api_router(settings))

    return app


app: FastAPI = create_app()
