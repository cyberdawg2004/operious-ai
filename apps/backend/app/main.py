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
from typing import Any, Mapping, cast

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agents.runtime.quota_runtime import (
    TenantQuotaRuntime,
    initialize_quota_runtime,
)
from app.api.router import build_api_router
from app.auth import AuthProvider
from app.auth.providers import ClaimMapping, JWKSAuthProvider
from app.boundary.translation import (
    IdentityTranslationProvider,
    InMemoryTranslationPersistence,
    TranslationEgressRuntime,
    TranslationIngressRuntime,
    TranslationRuntime,
)
from app.boundary.voice import (
    DeterministicStubSpeechToTextProvider,
    DeterministicStubTextToSpeechProvider,
    InMemoryVoicePersistence,
    VoiceEgressRuntime,
    VoiceIngressRuntime,
    VoiceRuntime,
)
from app.boundary.voice.call import (
    VoiceCallSessionRuntime,
    VoiceCapacityCounter,
    VoiceCapacityRedisClient,
)
from app.core.config import Settings, get_settings
from app.core.http import close_shared_http_client, init_shared_http_client
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis_client
from app.core.redis_policy import RedisConfigClient, verify_redis_memory_policy
from app.db.session import dispose_engine, get_session_factory
from app.governance.capability.runtime import (
    build_capability_governance_runtime,
)
from app.hardening.observability import (
    OperationalMetricsCollector,
    initialize_alert_evaluator,
    initialize_metrics_collector,
)
from app.middleware.authority_context import (
    AUTHORITY_HEADERS,
    AuthorityContextMiddleware,
)
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.request_body_limit import RequestBodyLimitMiddleware
from app.middleware.trusted_ingress import (
    IPNetwork,
    TrustedIngressMiddleware,
)
from app.observability.context import get_request_id
from app.runtime.tenant_production_hardening import (
    AUDIT_EXPORT_UNCONFIGURED_SIGNING_KEY,
    TenantProductionHardeningRuntime,
)
from app.runtime.timeline_runtime import TimelineRuntime
from app.session.persistence import PostgresSessionPersistence
from app.services.alert_evaluator_factory import create_alert_evaluator
from app.survivability import (
    PROBLEM_DETAILS_MEDIA_TYPE,
    ProblemDetails,
    problem_details_response,
)

_unhandled_logger = logging.getLogger("app.main.unhandled")

ALLOWED_ORIGINS = [
    "https://app.operious.com",
    "https://www.operious.com",
    "https://operious.com",
    "http://localhost:3000",
    "https://operious-ai-command-center.vercel.app",
]


def _build_cors_origins(raw: str) -> list[str]:
    """Parse CORS origins and reject wildcard transport posture."""

    items = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if any(origin == "*" for origin in items):
        raise ValueError(
            "CORS_ALLOW_ORIGINS must be a concrete allowlist; "
            "wildcard '*' is forbidden by transport doctrine."
        )
    return items or list(ALLOWED_ORIGINS)


def _build_cors_headers(raw: str) -> list[str]:
    headers = [header.strip() for header in raw.split(",") if header.strip()]
    return list(dict.fromkeys([*headers, *AUTHORITY_HEADERS]))


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


def _init_sentry(settings: Settings) -> None:
    """Initialize Sentry once, from the composition root.

    The observability hook is deliberately attached to ``create_app`` so
    imports, tests, and deploy boot all pass through the same lifecycle
    boundary. Empty DSN means Sentry is disabled for that process.
    """

    logger = logging.getLogger(__name__)
    logger.info(
        "sentry_init_begin",
        extra={
            "environment": settings.ENVIRONMENT,
            "dsn_configured": bool(settings.SENTRY_DSN),
            "already_initialized": sentry_sdk.is_initialized(),
        },
    )
    if not settings.SENTRY_DSN:
        logger.info("sentry_init_skipped", extra={"reason": "missing_dsn"})
        return
    if sentry_sdk.is_initialized():
        logger.info("sentry_init_skipped", extra={"reason": "already_initialized"})
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        integrations=[FastApiIntegration()],
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        send_default_pii=settings.SENTRY_SEND_DEFAULT_PII,
        environment=settings.ENVIRONMENT,
        release=settings.APP_VERSION,
    )
    logger.info("sentry_init_complete")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings: Settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)
    logger.info(
        "lifespan_startup_begin",
        extra={
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    )
    init_shared_http_client()
    await verify_redis_memory_policy(
        redis_client=cast(RedisConfigClient, get_redis_client()),
        expected_policy=settings.REDIS_REQUIRED_MAXMEMORY_POLICY,
        check_logger=logger,
    )
    logger.info("lifespan_yield_begin")
    try:
        yield
    finally:
        logger.info("lifespan_shutdown_begin")
        # The pre-Phase-2.1 orchestration / AI-provider lifespan hooks were
        # removed when those substrates were quarantined into
        # `app/_deprecated/`. The constitutional substrates are pure
        # value-object layers and have no I/O resources to dispose of. The
        # only live infra we still own is the SQLAlchemy engine, Redis
        # connection, and shared outbound HTTP client (all lazy / no-op
        # when not configured).
        quota_runtime = getattr(app.state, "quota_runtime", None)
        if isinstance(quota_runtime, TenantQuotaRuntime):
            await quota_runtime.close()
        await close_shared_http_client()
        await dispose_engine()
        await close_redis()
        logger.info("lifespan_shutdown_complete", extra={"app": settings.APP_NAME})


def _register_exception_handlers(app: FastAPI) -> None:
    """Register the ProblemDetails-shaped exception handlers (2.5-I).

    Every error path returns a uniform RFC 9457 envelope carrying the
    request_id as ``instance``. This keeps the wire format consistent
    across HTTPException, validation errors, and unhandled exceptions
    so frontend / SDK consumers can render and log uniformly.
    """

    # The exception handlers below are registered with FastAPI via the
    # ``@app.exception_handler`` decorator. The local binding name is
    # therefore unused at the Python level (the decorator stores the
    # callable on the app); the ``pyright: ignore`` silences the
    # ``reportUnusedFunction`` diagnostic without weakening intent.

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: StarletteHTTPException
    ):
        # Starlette types ``exc.detail`` as ``Any``; defensively coerce
        # to ``str`` to keep the wire envelope stable when middleware
        # raises with structured payloads.
        detail_value: Any = exc.detail
        title = detail_value if isinstance(detail_value, str) else "http_error"
        problem = _problem_for_status(
            status=exc.status_code,
            title=title,
            detail=str(detail_value) if detail_value else "",
            request=request,
        )
        return problem_details_response(
            problem,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(  # pyright: ignore[reportUnusedFunction]
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
        payload["errors"] = jsonable_encoder(exc.errors())
        from fastapi.responses import JSONResponse

        return JSONResponse(
            content=payload,
            status_code=422,
            media_type=PROBLEM_DETAILS_MEDIA_TYPE,
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: Exception
    ):
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
      * a fail-closed ``CORSMiddleware`` configured from the production
        domain allowlist (no wildcard).
    """

    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)
    logger.info(
        "create_app_begin",
        extra={
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    )
    _init_sentry(settings)

    # 2.5-I production posture — trusted_proxies must be explicit.
    if settings.is_production and trusted_proxies is None:
        raise RuntimeError(
            "Production deployments MUST pin an explicit "
            "`trusted_proxies` tuple (possibly empty for the strict "
            "fail-closed setting). Refusing to boot with "
            "`trusted_proxies=None`."
        )

    logger.info("fastapi_instance_create_begin")
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )
    logger.info("fastapi_instance_create_complete")

    logger.info("quota_runtime_register_begin")
    quota_runtime = TenantQuotaRuntime(
        redis_url=settings.quota_redis_url,
        session_factory=get_session_factory(),
        request_per_minute_limit=settings.QUOTA_REQUESTS_PER_MINUTE_DEFAULT,
        tokens_per_minute_limit=settings.QUOTA_TOKENS_PER_MINUTE_DEFAULT,
        requests_per_hour_limit=settings.QUOTA_REQUESTS_PER_HOUR_DEFAULT,
    )
    app.state.quota_runtime = quota_runtime
    initialize_quota_runtime(quota_runtime)
    logger.info("quota_runtime_register_complete")

    logger.info(
        "tenant_hardening_runtime_register_begin",
        extra={
            "audit_export_signing_configured": bool(
                settings.audit_export_signing_key
            )
        },
    )
    app.state.tenant_production_hardening_runtime = (
        TenantProductionHardeningRuntime(
            audit_export_signing_key=(
                settings.audit_export_signing_key
                or AUDIT_EXPORT_UNCONFIGURED_SIGNING_KEY
            ),
        )
    )
    logger.info("tenant_hardening_runtime_register_complete")

    logger.info("metrics_collector_register_begin")
    metrics_collector = OperationalMetricsCollector()
    initialize_metrics_collector(metrics_collector)
    app.state.metrics_collector = metrics_collector
    logger.info("metrics_collector_register_complete")

    logger.info("alert_evaluator_register_begin")
    alert_evaluator = create_alert_evaluator()
    initialize_alert_evaluator(alert_evaluator)
    app.state.alert_evaluator = alert_evaluator
    logger.info("alert_evaluator_register_complete")

    logger.info("boundary_media_runtime_register_begin")
    capability_governance_runtime = build_capability_governance_runtime()
    app.state.capability_governance_runtime = capability_governance_runtime

    voice_persistence = InMemoryVoicePersistence()
    app.state.voice_runtime = VoiceRuntime(
        ingress=VoiceIngressRuntime(
            provider=DeterministicStubSpeechToTextProvider(),
            persistence=voice_persistence,
        ),
        egress=VoiceEgressRuntime(
            provider=DeterministicStubTextToSpeechProvider(),
            persistence=voice_persistence,
            capability_governance=capability_governance_runtime,
        ),
    )
    app.state.voice_capacity_counter = VoiceCapacityCounter(
        redis_client=cast(VoiceCapacityRedisClient, get_redis_client()),
        limit=settings.VOICE_CAPACITY_LIMIT,
    )

    async def _append_voice_call_timeline(
        session_id: str,
        dispatch_id: str,
        tenant_id: str,
        event_type: str,
        payload: Mapping[str, object],
    ) -> None:
        session_factory = get_session_factory()
        async with session_factory() as db_session:
            try:
                await TimelineRuntime(
                    persistence=PostgresSessionPersistence(db_session),
                ).append_event(
                    session_id=session_id,
                    dispatch_id=dispatch_id,
                    tenant_id=tenant_id,
                    event_type=event_type,
                    payload=payload,
                    idempotency_key=(
                        f"voice:{event_type}:{dispatch_id}"
                    ),
                )
                await db_session.commit()
            except Exception:
                await db_session.rollback()
                logger.info(
                    "voice_timeline_append_skipped",
                    extra={
                        "event_type": event_type,
                        "session_id": session_id,
                    },
                )

    app.state.voice_call_runtime = VoiceCallSessionRuntime(
        voice_runtime=app.state.voice_runtime,
        capability_governance=capability_governance_runtime,
        timeline_appender=_append_voice_call_timeline,
    )

    translation_persistence = InMemoryTranslationPersistence()
    translation_provider = IdentityTranslationProvider()
    app.state.translation_runtime = TranslationRuntime(
        ingress=TranslationIngressRuntime(
            provider=translation_provider,
            persistence=translation_persistence,
            capability_governance=capability_governance_runtime,
        ),
        egress=TranslationEgressRuntime(
            provider=translation_provider,
            persistence=translation_persistence,
            capability_governance=capability_governance_runtime,
        ),
    )
    logger.info("boundary_media_runtime_register_complete")

    logger.info("exception_handlers_register_begin")
    _register_exception_handlers(app)
    logger.info("exception_handlers_register_complete")

    # Middleware registration order matters: Starlette's
    # ``add_middleware`` prepends to ``user_middleware`` and the
    # build wraps in REVERSED order, so the LAST registered class
    # ends up OUTERMOST in the request flow. We want:
    #
    #     RequestBodyLimit (outermost) → CORS → RequestContext
    #         → TrustedIngress → AuthorityContext (innermost) → Router
    #
    # so the request id is bound BEFORE the authority middleware
    # logs / returns a 400 — every authority-extraction error then
    # carries the correlation id. Wedge B8 establishes
    # ``AuthorityContextMiddleware`` as the SINGLE canonical
    # HTTP-level identity extraction site; see
    # ``app/middleware/authority_context.py`` for the doctrine.
    # Inner → outer (Starlette prepends; last added is outermost).
    logger.info("middleware_authority_register_begin")
    app.add_middleware(
        AuthorityContextMiddleware,
        auth_provider=auth_provider,
    )
    logger.info("middleware_authority_register_complete")
    if trusted_proxies is not None:
        logger.info("middleware_trusted_ingress_register_begin")
        app.add_middleware(
            TrustedIngressMiddleware,
            trusted_proxies=trusted_proxies,
        )
        logger.info("middleware_trusted_ingress_register_complete")
    else:
        logger.info("middleware_trusted_ingress_register_skipped")
    logger.info("middleware_request_context_register_begin")
    app.add_middleware(RequestContextMiddleware)
    logger.info("middleware_request_context_register_complete")

    logger.info(
        "middleware_cors_register_begin",
        extra={
            "origin_count": len(_build_cors_origins(settings.CORS_ALLOW_ORIGINS)),
            "allow_credentials": True,
        },
    )
    cors_origins = _build_cors_origins(settings.CORS_ALLOW_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=_build_cors_headers(settings.CORS_ALLOW_HEADERS),
    )
    logger.info("middleware_cors_register_complete")
    logger.info("middleware_request_body_limit_register_begin")
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=settings.SURVIVABILITY_REQUEST_BODY_MAX_BYTES,
    )
    logger.info("middleware_request_body_limit_register_complete")

    logger.info("router_registration_begin")
    app.include_router(build_api_router(settings))
    logger.info("router_registration_complete")
    logger.info("create_app_complete")

    return app


def select_auth_provider(settings: Settings) -> AuthProvider | None:
    """Compose the application-level :class:`AuthProvider` from settings.

    Fail-closed selector — production deployments MUST set
    ``AUTH_ENABLED=true`` AND a recognised ``AUTH_PROVIDER``;
    otherwise the substrate boots with ``None`` and the
    :class:`AuthorityContextMiddleware` rejects every
    Authorization-bearing request with ``401 verification_unavailable``
    (B5 doctrine). Returning ``None`` here is therefore safe — it
    cannot accidentally elevate an unverified caller.

    Recognised providers:

    * ``"auth0"`` — :class:`JWKSAuthProvider` configured from
      ``AUTH0_JWKS_URL`` / ``AUTH0_AUDIENCE`` / ``AUTH0_ISSUER``.
      All three settings must be non-empty or the composition
      root refuses to boot — missing settings would silently
      degrade to ``None`` and mask a misconfiguration.

    Unrecognised provider names are rejected. New providers
    (Cognito, Keycloak, custom JWT) are added by extending this
    function — never by passing custom adapters through
    environment variables.
    """
    if not settings.AUTH_ENABLED:
        return None
    provider_name = (settings.AUTH_PROVIDER or "").lower()
    if provider_name == "" or provider_name == "none":
        return None
    if provider_name == "auth0":
        missing: list[str] = []
        if not settings.AUTH0_JWKS_URL:
            missing.append("AUTH0_JWKS_URL")
        if not settings.AUTH0_AUDIENCE:
            missing.append("AUTH0_AUDIENCE")
        if not settings.AUTH0_ISSUER:
            missing.append("AUTH0_ISSUER")
        if missing:
            raise RuntimeError(
                "AUTH_PROVIDER='auth0' requires "
                f"{', '.join(missing)} to be set. Refusing to boot."
            )
        assert settings.AUTH0_JWKS_URL is not None
        assert settings.AUTH0_AUDIENCE is not None
        assert settings.AUTH0_ISSUER is not None
        return JWKSAuthProvider(
            jwks_uri=settings.AUTH0_JWKS_URL,
            audience=settings.AUTH0_AUDIENCE,
            issuer=settings.AUTH0_ISSUER,
            algorithms=("RS256",),
            name="auth0",
            claim_mapping=ClaimMapping(
                roles_claim=f"{settings.AUTH0_NAMESPACE}/roles",
            ),
        )
    raise RuntimeError(
        f"unsupported AUTH_PROVIDER={settings.AUTH_PROVIDER!r}. "
        "Recognised values: 'auth0', 'none', or unset. Extend "
        "app.main.select_auth_provider to add new providers."
    )


app: FastAPI = create_app(
    auth_provider=select_auth_provider(get_settings()),
)
