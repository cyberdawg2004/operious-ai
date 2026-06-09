"""Centralized application configuration.

Single source of truth for runtime settings. All settings are typed,
loaded from environment variables (with optional `.env` fallback), and
accessed through a cached `get_settings()` dependency so the rest of the
codebase never reads `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.queues import (
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_ESCALATION,
    QUEUE_INGRESS_EMAIL,
    QUEUE_INGRESS_SHOPIFY,
    QUEUE_INGRESS_VOICE,
    QUEUE_INGRESS_WHATSAPP,
    QUEUE_QA,
    QUEUE_SOP_INTELLIGENCE,
    QUEUE_SUPERVISOR,
)

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
        if (parent / "package.json").is_file() and (
            parent / "apps" / "backend"
        ).is_dir():
            return parent
    for parent in config_path.parents:
        if (parent / "alembic.ini").is_file() and (
            parent / "app" / "main.py"
        ).is_file():
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

    # ─── Ingress trust posture (S-01) ────────────────────────────────
    # ``TRUSTED_PROXIES`` is a comma-separated list of CIDR blocks (or
    # bare IPs) for the upstream proxies allowed to stamp authority
    # headers. Empty in production means the STRICT fail-closed empty
    # allowlist (every direct peer is untrusted). See
    # ``app.middleware.trusted_ingress``.
    TRUSTED_PROXIES: str = ""
    # When ``None`` (default), legacy upstream-attested ``X-*-ID``
    # identity headers are honoured everywhere EXCEPT production, where
    # they are fail-closed. Set explicitly to force either posture.
    LEGACY_HEADER_AUTHORITY_ENABLED: bool | None = None

    # ─── Production readiness (S-09 stubs, #31/#30/#74/#17/#54) ──────
    # When ``None`` (default), production refuses to boot with stubbed
    # providers / missing security secrets; non-production never
    # enforces. Set explicitly to force either posture (e.g. ``false``
    # for a test harness that boots a production-env app).
    PRODUCTION_READINESS_ENFORCED: bool | None = None
    # Non-production escape hatches for local/test stub providers. Production
    # readiness ignores these flags and still fails closed when a real provider
    # or durable substrate is missing.
    ALLOW_STUB_LLM: bool = False
    ALLOW_STUB_TRANSLATION: bool = False
    ALLOW_STUB_VECTOR: bool = False
    ALLOW_STUB_EMBEDDINGS: bool = False
    ALLOW_STUB_VOICE: bool = False
    # Commerce action tools (refund/warranty/replacement/warehouse) with no
    # configured connector. Production always fails closed. Non-production
    # derives to stub-enabled by default, with an explicit false available for
    # fail-closed tests/staging.
    ALLOW_STUB_ACTIONS: bool | None = None
    # Deterministic Shopify enrichment fixtures (#73): fail-closed in prod.
    ALLOW_STUB_SHOPIFY_ENRICHMENT: bool | None = None

    # Legacy direct tenant configuration application (S-03).
    # The durable tenant-config ledger is the production path. This flag
    # exists only as an explicit non-production escape hatch for older
    # direct mutation endpoints during tests and local development.
    TENANT_CONFIG_ALLOW_SELF_APPROVAL: bool | None = None

    AUTH0_DOMAIN: str | None = None
    AUTH0_ISSUER: str | None = None
    AUTH0_AUDIENCE: str | None = None
    AUTH0_JWKS_URL: str | None = None
    # Auth0 Management API M2M settings for platform admin provisioning.
    # Secrets are consumed only by the backend integration client and are
    # never returned through API responses or operational event metadata.
    AUTH0_MGMT_CLIENT_ID: str | None = None
    AUTH0_MGMT_CLIENT_SECRET: str | None = None
    AUTH0_MGMT_AUDIENCE: str | None = None
    AUTH0_MGMT_CONNECTION: str | None = None
    AUTH0_TENANT_CONFIG_ADMIN_ROLE_ID: str | None = None
    AUTH0_NAMESPACE: str = Field(
        default="https://operious.com",
        description=(
            "Namespace prefix for Auth0 custom claims. "
            "Used to build namespaced claim keys like "
            "https://operious.com/roles"
        ),
    )

    AUDIT_EXPORT_HMAC_SECRET: str | None = Field(
        default=None,
        description="HMAC-SHA256 key for audit export signing.",
    )

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
    DB_USE_NULLPOOL: bool = False

    # ─── Redis ───────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_RESULT_DB: int = 1
    REDIS_PASSWORD: str | None = None
    REDIS_URL: str | None = None
    QUOTA_REDIS_URL: str | None = None
    CELERY_RESULT_BACKEND_URL: str | None = None
    CELERY_RESULT_EXPIRES_SECONDS: int = 3600
    CELERY_TASK_SOFT_TIME_LIMIT_SECONDS: int = 300
    CELERY_TASK_TIME_LIMIT_SECONDS: int = 600
    CELERY_VISIBILITY_TIMEOUT_SECONDS: int = 3600
    INGRESS_EMAIL_QUEUE_NAME: str = QUEUE_INGRESS_EMAIL
    INGRESS_WHATSAPP_QUEUE_NAME: str = QUEUE_INGRESS_WHATSAPP
    INGRESS_SHOPIFY_QUEUE_NAME: str = QUEUE_INGRESS_SHOPIFY
    INGRESS_VOICE_QUEUE_NAME: str = QUEUE_INGRESS_VOICE
    VOICE_CAPACITY_LIMIT: int = Field(
        default=100,
        description="Maximum concurrent active voice calls.",
    )
    # ─── Voice media gateway security (S-04) ─────────────────────────
    # Voice is DISABLED by default. The media WebSocket only accepts a
    # connection when voice is explicitly enabled AND the handshake
    # presents a valid short-lived signed session token whose payload
    # binds the tenant + session. The tenant is taken from the verified
    # token, never from a client-supplied query parameter.
    VOICE_ENABLED: bool = False
    VOICE_SESSION_TOKEN_SECRET: str = ""
    VOICE_SESSION_TOKEN_TTL_SECONDS: int = 300
    # Per-frame byte ceiling and per-call frame cap — bound the memory /
    # CPU a single media stream can consume (WebSocket DoS).
    VOICE_MAX_FRAME_BYTES: int = 65_536
    VOICE_MAX_FRAMES_PER_CALL: int = 100_000
    # ── Voice WebSocket wall-clock / idle / rate caps (spec 1b #40) ──
    # Bound how long a single media stream can hold a connection and how
    # fast it may push frames, on top of the per-frame byte / per-call
    # count caps above.
    VOICE_MAX_CALL_SECONDS: int = 3600
    VOICE_IDLE_TIMEOUT_SECONDS: int = 30
    VOICE_MAX_FRAMES_PER_SECOND: int = 100

    # ── Inbound rate limiting (spec 1b #39) ──────────────────────────
    # Fixed-window (INCR+EXPIRE) request budgets. The per-IP layer runs
    # pre-auth; the per-tenant / per-principal layers run post-auth.
    # None = derive from environment (enabled in production, off elsewhere).
    # Explicit true/false overrides the environment default.
    RATE_LIMIT_ENABLED: bool | None = None
    RATE_LIMIT_IP_PER_MINUTE: int = 120
    RATE_LIMIT_TENANT_PER_MINUTE: int = 600
    RATE_LIMIT_PRINCIPAL_PER_MINUTE: int = 300  # 0 disables the layer
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    # Path suffixes never rate limited (health / liveness / readiness
    # probes); suffix match so it is independent of the mount prefix.
    RATE_LIMIT_EXEMPT_SUFFIXES: str = "/health,/live,/ready"

    # ── Webhook canonical URL (spec 1b #23) ──────────────────────────
    # The public origin (scheme + host, no trailing slash) the substrate
    # is reachable at, used to derive the canonical URL provider
    # signatures are verified against — never a client-supplied header.
    PUBLIC_BASE_URL: str = ""
    # Honour the client-supplied ``x-operious-webhook-url`` header only
    # when explicitly enabled (non-prod testing). Production boot rejects
    # this being true (see ``production_readiness``).
    WEBHOOK_TRUST_URL_HEADER: bool = False

    # ── Auth error coarsening (spec 1b #25) ──────────────────────────
    # When true (default in production via property below), external auth
    # failures return a generic body; the precise reason is logged only.
    COARSE_AUTH_ERRORS: bool = False

    EXECUTION_QUEUE_NAME: str = QUEUE_DIAGNOSTIC_NORMAL
    EXECUTION_QUEUE_MAX_DEPTH: int = 10_000
    EXECUTION_QUEUE_TENANT_MAX_DEPTH: int = 100
    ESCALATION_QUEUE_NAME: str = QUEUE_ESCALATION
    ESCALATION_QUEUE_MAX_DEPTH: int = 10_000
    SUPERVISOR_QUEUE_NAME: str = QUEUE_SUPERVISOR
    SUPERVISOR_QUEUE_MAX_DEPTH: int = 10_000
    QA_QUEUE_NAME: str = QUEUE_QA
    QA_QUEUE_MAX_DEPTH: int = 10_000
    TRAINER_RECOMMENDATION_THRESHOLD: float = 0.75
    TRAINER_RECOMMENDATION_DIMENSION_THRESHOLD: float = 0.7
    SOP_INTELLIGENCE_QUEUE_NAME: str = QUEUE_SOP_INTELLIGENCE
    SOP_INTELLIGENCE_QUEUE_MAX_DEPTH: int = 10_000
    SOP_REPEATED_FAILURE_THRESHOLD: int = 3
    SOP_REPEATED_FAILURE_LOOKBACK_DAYS: int = 7
    SOP_REPEATED_FAILURE_SCAN_SECONDS: int = 86_400
    SOP_FAILURE_PATTERN_DLQ_WINDOW_HOURS: int = Field(default=24)
    SOP_FAILURE_PATTERN_DLQ_THRESHOLD: int = Field(default=3)
    SOP_FAILURE_PATTERN_ADMISSION_THRESHOLD: int = Field(default=10)
    REDIS_REQUIRED_MAXMEMORY_POLICY: str = "allkeys-lru"
    ADMISSION_QUEUE_DEPTH_WARN: int = 500
    ADMISSION_QUEUE_DEPTH_REJECT: int = 2000
    ADMISSION_QUEUE_AGE_WARN_SECONDS: int = 120
    ADMISSION_QUEUE_AGE_REJECT_SECONDS: int = 600
    ADMISSION_REDIS_MEMORY_PCT_WARN: float = 70.0
    ADMISSION_REDIS_MEMORY_PCT_REJECT: float = 90.0
    ADMISSION_DB_POOL_WAIT_WARN_MS: float = 250.0
    ADMISSION_DB_POOL_WAIT_REJECT_MS: float = 1000.0
    SEMANTIC_CIRCUIT_WINDOW_SECONDS: int = Field(default=300)
    SEMANTIC_CIRCUIT_CLUSTER_THRESHOLD: int = Field(default=5)
    SEMANTIC_CIRCUIT_SIMILARITY_THRESHOLD: float = Field(default=0.7)
    DEFECT_CLUSTER_WINDOW_HOURS: int = Field(default=24)
    DEFECT_CLUSTER_THRESHOLD: int = Field(default=5)
    ALERT_QUEUE_AGE_CRITICAL_SECONDS: int = 600
    ALERT_DLQ_SPIKE_THRESHOLD: int = 5
    ALERT_REDIS_MEMORY_PCT: float = 85.0
    ALERT_DB_POOL_UTILIZATION: float = 0.9
    QUOTA_REQUESTS_PER_MINUTE_DEFAULT: int = 60
    QUOTA_TOKENS_PER_MINUTE_DEFAULT: int = 100_000
    QUOTA_REQUESTS_PER_HOUR_DEFAULT: int = 1_000

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
    # Native pgvector storage is currently migrated to one coherent dimension.
    OPENAI_EMBEDDING_DIMENSIONS: int | None = 1536

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

    # ─── Translation provider ────────────────────────────────────────
    TRANSLATION_PROVIDER: str = Field(
        default="identity",
        description=(
            "Translation provider: 'identity' (verbatim) or "
            "'anthropic' (real translation via Claude)."
        ),
    )
    TRANSLATION_MODEL: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Anthropic model for translation calls.",
    )

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
    # Lifetime of a pre-approved agent action grant (S-05). A persisted
    # ALLOW decision may be redeemed as a ``pre_approved_decision_id``
    # only within this window (and only once, when Redis is configured).
    AGENT_PRE_APPROVED_DECISION_TTL_SECONDS: int = 3600

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

    # ─── Data protection envelope encryption (Spec 1c) ──────────────
    # Comma-separated versioned key ring entries, e.g.
    # ``v1:<base64-or-hex-or-raw>,v2:<material>``. When unset, the
    # envelope runtime falls back to TENANT_CREDENTIAL_MASTER_KEY for
    # backwards-compatible single-key deployments.
    DATA_PROTECTION_MASTER_KEYS: str = ""
    DATA_PROTECTION_ACTIVE_MASTER_KEY_VERSION: str = "v1"
    DATA_PROTECTION_DEFAULT_RETENTION_DAYS: int = 90

    # ─── Outbound dispatch SSRF allowlist (S-06) ─────────────────────
    # Optional comma-separated host allowlist for tenant-configured
    # outbound webhook / connector URLs. Empty means "any PUBLIC host"
    # (private / loopback / link-local / reserved addresses are always
    # blocked regardless). Set to known SaaS hosts (e.g. Jira / Linear)
    # to require verified connector destinations.
    OUTBOUND_WEBHOOK_ALLOWED_HOSTS: str = ""

    # ─── Channel send egress allowlists (S-06 extension) ─────────────
    # Customer-facing channel senders POST to tenant-configurable provider
    # endpoints with credentials attached. Every destination is SSRF-validated
    # (HTTPS, public address only) and pinned to its resolved IP, AND the host
    # must be in the provider allowlist below. Defaults are the official
    # provider hosts; operators may add comma-separated hosts (never tenants).
    WHATSAPP_GRAPH_ALLOWED_HOSTS: str = "graph.facebook.com"
    # SES sends are additionally always allowed against the regional AWS host
    # ``email.<region>.amazonaws.com`` derived from the request; this is for
    # extra operator-approved hosts only.
    SES_ADDITIONAL_ALLOWED_HOSTS: str = ""

    # ─── Execution recovery (Phase 1-F) ──────────────────────────────
    # Stale execution claim recovery remains owned by
    # ``ExecutionRuntime``. Worker/scheduler transports may invoke the
    # recovery task, but these knobs only bound the runtime sweep.
    EXECUTION_CLAIM_LEASE_SECONDS: int = 900
    EXECUTION_RECOVERY_BATCH_SIZE: int = 100
    EXECUTION_OUTBOX_FAILED_RETRY_COOLDOWN_SECONDS: int = 30
    EXECUTION_OUTBOX_FAILED_RETRY_MAX_ATTEMPTS: int = 3
    ESCALATION_OUTBOX_CLAIM_LEASE_SECONDS: int = 300

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
    def allow_stub_actions_effective(self) -> bool:
        """Whether fake-success commerce action stubs may be registered.

        Always fail-closed in production: an unconfigured action returns a
        governed error, never fake success. Non-production allows stubs by
        default so dev/CI can exercise the tools, unless explicitly disabled.
        """
        if self.is_production:
            return False
        if self.ALLOW_STUB_ACTIONS is not None:
            return self.ALLOW_STUB_ACTIONS
        return True

    @property
    def allow_stub_shopify_enrichment_effective(self) -> bool:
        """Whether deterministic fixture Shopify enrichment may be used.

        Fail-closed in production: without a live Shopify channel the cluster
        is left un-enriched (no fabricated product/inventory data), never
        seeded with stub fixtures. Non-production allows stubs by default so
        dev/CI can exercise enrichment, unless explicitly disabled (#73).
        """
        if self.is_production:
            return False
        if self.ALLOW_STUB_SHOPIFY_ENRICHMENT is not None:
            return self.ALLOW_STUB_SHOPIFY_ENRICHMENT
        return True

    @property
    def is_local(self) -> bool:
        return self.ENVIRONMENT in ("local", "development", "test")

    @property
    def rate_limit_enabled_effective(self) -> bool:
        """Rate limiting is enforced in production by default.

        Follows the same environment-derived pattern as
        ``legacy_header_authority_enabled`` and ``coarse_auth_errors_effective``:
        an explicit ``RATE_LIMIT_ENABLED`` setting overrides the derived value so
        operators can force rate limiting on in staging or off in an emergency.
        This prevents tests and local dev from hitting Redis when no override is
        set.
        """
        if self.RATE_LIMIT_ENABLED is not None:
            return self.RATE_LIMIT_ENABLED
        return self.is_production

    @property
    def rate_limit_exempt_suffixes(self) -> tuple[str, ...]:
        """Parsed path suffixes never subject to inbound rate limiting."""
        return tuple(
            part.strip()
            for part in self.RATE_LIMIT_EXEMPT_SUFFIXES.split(",")
            if part.strip()
        )

    @property
    def public_base_url_normalized(self) -> str:
        """The public origin with surrounding whitespace and trailing slash removed."""
        return self.PUBLIC_BASE_URL.strip().rstrip("/")

    @property
    def coarse_auth_errors_effective(self) -> bool:
        """Whether external auth errors are coarsened.

        Coarsen in production by default so failure detail cannot aid
        reconnaissance; an explicit ``COARSE_AUTH_ERRORS=true`` forces it
        on anywhere (e.g. to exercise the production posture in tests).
        """
        if self.COARSE_AUTH_ERRORS:
            return True
        return self.is_production

    @property
    def legacy_header_authority_enabled(self) -> bool:
        """Whether upstream-attested ``X-*-ID`` headers are honoured.

        Fail-closed in production unless explicitly overridden — a
        direct caller must never be able to spoof tenant identity by
        stamping the canonical identity headers itself (S-01).
        """
        if self.LEGACY_HEADER_AUTHORITY_ENABLED is not None:
            return self.LEGACY_HEADER_AUTHORITY_ENABLED
        return not self.is_production

    @property
    def production_readiness_enforced(self) -> bool:
        """Whether the fail-closed production config gate runs at boot."""
        if self.PRODUCTION_READINESS_ENFORCED is not None:
            return self.PRODUCTION_READINESS_ENFORCED
        return self.is_production

    @property
    def tenant_config_self_approval_allowed(self) -> bool:
        """Whether legacy direct tenant config mutation is enabled.

        Fail-closed in production regardless of the flag. Non-production
        callers must opt in explicitly with
        ``TENANT_CONFIG_ALLOW_SELF_APPROVAL=true``; otherwise all config
        mutations should flow through the durable ledger.
        """
        return not self.is_production and self.TENANT_CONFIG_ALLOW_SELF_APPROVAL is True

    @property
    def outbound_webhook_allowed_hosts(self) -> tuple[str, ...]:
        """Parsed SaaS host allowlist for outbound dispatch (S-06)."""
        return tuple(
            host.strip().lower()
            for host in self.OUTBOUND_WEBHOOK_ALLOWED_HOSTS.split(",")
            if host.strip()
        )

    @property
    def whatsapp_graph_allowed_hosts(self) -> tuple[str, ...]:
        """Provider host allowlist for WhatsApp Graph API sends (S-06 ext)."""
        return tuple(
            host.strip().lower()
            for host in self.WHATSAPP_GRAPH_ALLOWED_HOSTS.split(",")
            if host.strip()
        )

    @property
    def ses_additional_allowed_hosts(self) -> tuple[str, ...]:
        """Extra operator-approved SES hosts beyond the regional AWS host."""
        return tuple(
            host.strip().lower()
            for host in self.SES_ADDITIONAL_ALLOWED_HOSTS.split(",")
            if host.strip()
        )

    @property
    def trusted_proxy_networks(
        self,
    ) -> tuple[IPv4Network | IPv6Network, ...]:
        """Parse ``TRUSTED_PROXIES`` into IP networks (pure parser)."""
        networks: list[IPv4Network | IPv6Network] = []
        for entry in self.TRUSTED_PROXIES.split(","):
            candidate = entry.strip()
            if not candidate:
                continue
            networks.append(ip_network(candidate, strict=False))
        return tuple(networks)

    @property
    def resolved_trusted_proxies(
        self,
    ) -> tuple[IPv4Network | IPv6Network, ...] | None:
        """Trusted-ingress allowlist to pass to ``create_app``.

        Production always yields a concrete (possibly empty) tuple so
        the trusted-ingress middleware is registered and the strict
        boot guard is satisfied. Non-production deployments that pinned
        nothing yield ``None`` to preserve the legacy no-enforcement
        behaviour relied on by test harnesses.
        """
        networks = self.trusted_proxy_networks
        if networks:
            return networks
        if self.is_production:
            return ()
        return None

    @property
    def use_json_logs(self) -> bool:
        if self.LOG_JSON is not None:
            return self.LOG_JSON
        return not self.is_local

    @property
    def audit_export_signing_key(self) -> str | None:
        return self.AUDIT_EXPORT_HMAC_SECRET

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def quota_redis_url(self) -> str:
        if self.QUOTA_REDIS_URL:
            return _normalize_redis_url(self.QUOTA_REDIS_URL)
        return self.redis_url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def celery_result_backend_url(self) -> str:
        if self.CELERY_RESULT_BACKEND_URL:
            return _normalize_redis_url(self.CELERY_RESULT_BACKEND_URL)
        if self.REDIS_URL:
            if urlsplit(self.redis_url).scheme == "rediss":
                return self.redis_url
            return _redis_url_with_database(self.redis_url, self.REDIS_RESULT_DB)
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return (
            f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/"
            f"{self.REDIS_RESULT_DB}"
        )


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
    query["ssl_cert_reqs"] = "required"
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def _redis_url_with_database(url: str, database: int) -> str:
    """Return ``url`` with its logical Redis database path replaced."""

    normalized = _normalize_redis_url(url)
    parsed = urlsplit(normalized)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"/{database}",
            parsed.query,
            parsed.fragment,
        )
    )
