"""Centralized application configuration.

Single source of truth for runtime settings. All settings are typed,
loaded from environment variables (with optional `.env` fallback), and
accessed through a cached `get_settings()` dependency so the rest of the
codebase never reads `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "development", "staging", "production", "test"]

# Repository-root anchored environment resolution.
#
# Prevents:
# - cwd-dependent .env loading
# - Alembic/runtime divergence
# - pytest configuration drift
# - CI path inconsistencies
# - deployment environment ambiguity
#
def _resolve_root_dir() -> Path:
    """Resolve the runtime root without assuming filesystem depth.

    Local checkouts anchor configuration at the repository root so the
    root `.env` is loaded exactly as before. The Railway Docker image
    copies `apps/backend` to `/app`, so the same module lives at
    `/app/app/core/config.py`; in that layout the backend root is the
    stable runtime anchor.
    """

    config_path = Path(__file__).resolve()
    for parent in config_path.parents:
        if (
            (parent / "package.json").is_file()
            and (parent / "apps" / "backend").is_dir()
        ):
            return parent
    for parent in config_path.parents:
        if (
            (parent / "alembic.ini").is_file()
            and (parent / "app" / "main.py").is_file()
        ):
            return parent
    for parent in config_path.parents:
        if (parent / ".env").is_file():
            return parent
    parents = list(config_path.parents)
    if len(parents) >= 3:
        return parents[2]
    return parents[-1]


ROOT_DIR = _resolve_root_dir()
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Add new settings here as the platform grows (DB URLs, AI provider
    keys, feature flags, etc.). Everything must be typed and documented.
    """

    AUTH_ENABLED: bool = False
    AUTH_PROVIDER: str | None = None

    AUTH0_DOMAIN: str | None = None
    AUTH0_ISSUER: str | None = None
    AUTH0_AUDIENCE: str | None = None
    AUTH0_JWKS_URL: str | None = None

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── App metadata ────────────────────────────────────────────────
    APP_NAME: str = "Operious AI"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = "local"

    # ─── API ─────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"

    # ─── Logging ─────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool | None = None

    # ─── Sentry ──────────────────────────────────────────────────────
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.0
    SENTRY_SEND_DEFAULT_PII: bool = False

    # ─── PostgreSQL ──────────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "operious"
    POSTGRES_USER: str = "operious"
    POSTGRES_PASSWORD: str = "operious"
    # Optional explicit override. When unset we synthesise an asyncpg URL
    # from the POSTGRES_* fields above (12-factor friendly).
    DATABASE_URL: str | None = None

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False
    DB_CONNECT_TIMEOUT_SECONDS: float = 30.0

    # ─── Redis ───────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_URL: str | None = None

    # ─── AI providers (gateway-level) ────────────────────────────────
    AI_DEFAULT_PROVIDER: str = "openai"
    AI_TIMEOUT_SECONDS: float = 30.0
    AI_MAX_ATTEMPTS: int = 3
    AI_RETRY_BACKOFF_BASE: float = 0.5
    AI_RETRY_BACKOFF_MAX: float = 8.0

    # ─── OpenAI provider ─────────────────────────────────────────────
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_DEFAULT_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    # Optional; lets us reduce dimensions for `text-embedding-3-*` models.
    # When None the provider returns the model's native dimensionality.
    OPENAI_EMBEDDING_DIMENSIONS: int | None = None

    # ─── Anthropic provider ──────────────────────────────────────────
    # Used by Phase 5-C diagnostic cognition. The key is platform-owned
    # deployment secret material: it is read only at runtime composition
    # and is never persisted, logged, or returned through APIs.
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_VERSION: str = "2023-06-01"
    ANTHROPIC_DEFAULT_MODEL: str = "claude-sonnet-4-20250514"
    ANTHROPIC_MAX_OUTPUT_TOKENS: int = 512
    ANTHROPIC_TEMPERATURE: float = 0.0

    # ─── Embedding gateway ───────────────────────────────────────────
    EMBEDDING_DEFAULT_PROVIDER: str = "openai"
    EMBEDDING_TIMEOUT_SECONDS: float = 30.0
    EMBEDDING_MAX_ATTEMPTS: int = 3
    EMBEDDING_RETRY_BACKOFF_BASE: float = 0.5
    EMBEDDING_RETRY_BACKOFF_MAX: float = 8.0

    # ─── Vector store ────────────────────────────────────────────────
    VECTOR_DEFAULT_PROVIDER: str = "in_memory"
    VECTOR_DEFAULT_INDEX: str = "operious_default"

    # ─── Chunking ────────────────────────────────────────────────────
    CHUNK_TARGET_SIZE: int = 1000
    CHUNK_OVERLAP: int = 100
    CHUNK_MIN_SIZE: int = 50

    # ─── RAG runtime ─────────────────────────────────────────────────
    # Defaults applied when callers do not pass their own policy / budget.
    # Every knob here is an OPERATIONAL default, not a hard ceiling — the
    # retrieval and assembly services accept overrides per call.
    RAG_DEFAULT_RETRIEVAL_STRATEGY: str = "single_query"
    RAG_DEFAULT_RERANKER: str = "identity"
    RAG_DEFAULT_GROUNDING_STRATEGY: str = "default"
    RAG_DEFAULT_TOP_K: int = 8
    RAG_DEFAULT_MIN_SCORE: float = 0.0
    RAG_DEFAULT_MAX_CHUNKS_PER_DOCUMENT: int | None = None
    RAG_DEFAULT_CONTEXT_TOKEN_BUDGET: int = 4000
    RAG_DEFAULT_TOKEN_ESTIMATOR_RATIO: int = 4  # chars-per-token heuristic.

    # ─── Cognition LLM runtime (Phase 5-C) ───────────────────────────
    COGNITION_LLM_CONTEXT_TOP_K: int = 6
    COGNITION_LLM_CONTEXT_TOKEN_BUDGET: int = 2500
    COGNITION_LLM_REQUIRE_CITATIONS: bool = False
    COGNITION_LLM_INPUT_TOKEN_MICRO_USD: int = 3
    COGNITION_LLM_OUTPUT_TOKEN_MICRO_USD: int = 15

    # ─── Governance runtime ──────────────────────────────────────────
    # Operational defaults for the governance substrate. Empty
    # allowlist / denylist values mean "permissive default" — production
    # deployments override these at boot via environment variables.
    # List values use comma-separated strings; the governance DI layer
    # splits them at composition time.
    GOVERNANCE_ENABLED: bool = True
    GOVERNANCE_TENANT_ALLOWLIST: str = ""  # comma-separated tenant ids
    GOVERNANCE_CONTENT_DENYLIST: str = ""  # comma-separated substrings
    GOVERNANCE_MAX_QUERY_LENGTH: int = 4000

    # ─── Tenant-owned credentials (Phase 2.5-A) ─────────────────────
    # Platform master key used only to derive per-tenant AES-256-GCM
    # credential keys via HKDF. Empty by default so deployments must
    # explicitly provide key material before channel credential write
    # endpoints can be used.
    TENANT_CREDENTIAL_MASTER_KEY: str = ""

    # ─── Execution recovery (Phase 1-F) ──────────────────────────────
    # Stale execution claim recovery remains owned by
    # ``ExecutionRuntime``. Worker/scheduler transports may invoke the
    # recovery task, but these knobs only bound the runtime sweep.
    EXECUTION_CLAIM_LEASE_SECONDS: int = 900
    EXECUTION_RECOVERY_BATCH_SIZE: int = 100

    # ─── Survivability (P2-E) ────────────────────────────────────────
    # Production-survivability knobs. These are operational
    # defaults consumed by the ``app.survivability`` primitives; no
    # orchestration wiring uses them yet (adoption deferred to a
    # later wedge under explicit direction).
    SURVIVABILITY_IDEMPOTENCY_TTL_SECONDS: int = 86_400  # 24h
    SURVIVABILITY_IDEMPOTENCY_MAX_RECORDS: int | None = None
    SURVIVABILITY_REQUEST_BODY_MAX_BYTES: int = 1_000_000  # 1 MiB
    SURVIVABILITY_READINESS_PROBE_TIMEOUT_SECONDS: float = 2.0

    # ─── HTTP transport (2.5-I) ──────────────────────────────────────
    # Comma-separated CORS allowlist. Empty string disables CORS at
    # the FastAPI level (production posture defaults to "no CORS";
    # callers must opt in with a real list of origins). This is
    # intentionally fail-closed — wildcard ``*`` is rejected at
    # composition time so we never bless cross-origin from an
    # unconfigured deployment.
    #
    # ``CORS_ALLOW_HEADERS`` lists ONLY the non-authority headers
    # callers may send. The canonical authority-bearing headers
    # (defined exclusively in ``app.middleware.authority_context``
    # as ``AUTHORITY_HEADERS``) are appended at composition time in
    # ``app.main.create_app`` so this file never references them
    # by literal — preserving the single-source-of-truth invariant
    # pinned by ``test_no_other_source_reads_authority_headers``.
    CORS_ALLOW_ORIGINS: str = ""
    CORS_ALLOW_CREDENTIALS: bool = False
    CORS_ALLOW_METHODS: str = "GET,POST,PATCH,DELETE,OPTIONS"
    CORS_ALLOW_HEADERS: str = (
        "Authorization,Content-Type,X-Request-ID,"
        "x-operious-client-request-id,x-operious-correlation-id"
    )

    # ─── Derived properties ──────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_local(self) -> bool:
        return self.ENVIRONMENT in ("local", "development", "test")

    @property
    def use_json_logs(self) -> bool:
        if self.LOG_JSON is not None:
            return self.LOG_JSON
        return not self.is_local

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """SQLAlchemy async DSN (driver: asyncpg)."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_sync(self) -> str:
        """Sync DSN (driver: psycopg2). Used only by Alembic offline mode."""
        return self.database_url.replace("+asyncpg", "+psycopg2")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        if self.REDIS_URL:
            return _normalize_redis_url(self.REDIS_URL)
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached `Settings` instance.

    Cached so repeated `Depends(get_settings)` calls are free and so the
    application observes a single, consistent configuration snapshot.
    """

    return Settings()


def _normalize_redis_url(url: str) -> str:
    """Return a Redis URL accepted by Redis clients and Celery transports."""

    parsed = urlsplit(url)
    if parsed.scheme != "rediss":
        return url
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "ssl_cert_reqs" in query:
        return url
    query["ssl_cert_reqs"] = "CERT_REQUIRED"
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )
