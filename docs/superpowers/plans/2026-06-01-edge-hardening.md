# Edge Hardening (Spec 1b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the externally reachable backend boundary with inbound rate limiting, server-derived webhook signature URLs, uniform webhook rejection, coarsened auth errors, and voice WebSocket duration/rate caps.

**Architecture:** Two new ASGI middlewares (per-IP pre-auth, per-tenant/principal post-auth) backed by an atomic Redis token-bucket Lua script with a method-derived Redis-failure policy. A server-side canonical-URL helper replaces the client-supplied `x-operious-webhook-url` header at both verification sites. A setting-gated coarsening helper genericizes external auth errors while preserving server-side detail. Voice handler gains wall-clock, idle, and frame-rate caps.

**Tech Stack:** Python 3.12, FastAPI/Starlette ASGI, `redis.asyncio`, pydantic-settings, pytest.

**Execution amendment (2026-06-01, during inline execution):** The rate-limit
primitive was changed from a Lua token-bucket to an atomic `INCR`+`EXPIRE`
**fixed-window** counter. Reason: the dependency manifest is constitutionalized
(`tests/test_forbidden_dependencies.py` forbids extras beyond `celery[redis]`, so
`fakeredis[lua]` is disallowed) and the suite's convention is a hand-rolled
per-test `_FakeRedis` (`incr`/`expire`/`fail`), not the `fakeredis` library.
Fixed-window fully satisfies the spec intent (per-tenant, fail-closed, provable in
CI) with no new dependency. Consequences: limiter API is `consume(key, limit,
window_seconds)` (not `capacity`/`refill`); the `*_BURST` settings are dropped in
favour of `RATE_LIMIT_WINDOW_SECONDS`. Task code blocks below that reference
`capacity`/`refill`/Lua are superseded by this amendment; the tests/behaviour are
otherwise unchanged.

**Conventions (read before starting):**
- Run pytest from the **repo root** (`/home/imad-baraja/Projects/operious-ai`), never from `apps/backend` — running from the subdir causes ~29 spurious failures. Use `python -m pytest apps/backend/tests/...`.
- Spec: [docs/superpowers/specs/2026-06-01-edge-hardening-design.md](../specs/2026-06-01-edge-hardening-design.md).
- Middleware pattern: pure-ASGI like [request_body_limit.py](../../../apps/backend/app/middleware/request_body_limit.py). Problem-details media type is `app.survivability.PROBLEM_DETAILS_MEDIA_TYPE`.
- Settings live in `app.core.config.Settings` (class starts [config.py:78](../../../apps/backend/app/core/config.py)). `settings.is_production` and `settings.production_readiness_enforced` already exist.
- Commit message trailer for every commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

**Create:**
- `apps/backend/app/core/rate_limit.py` — Redis token-bucket primitive + fail-policy result type.
- `apps/backend/app/middleware/edge_rate_limit.py` — per-IP pre-auth middleware.
- `apps/backend/app/middleware/tenant_rate_limit.py` — per-tenant/principal post-auth middleware.
- `apps/backend/app/core/webhook_url.py` — `derive_canonical_webhook_url`.
- `apps/backend/app/middleware/auth_error.py` — coarsening helper + reason→code map.
- Test files (one per task, paths in each task).

**Modify:**
- `apps/backend/app/core/config.py` — new settings.
- `apps/backend/app/main.py` — register middlewares; respect CORS credentials setting.
- `apps/backend/app/core/twilio_signature.py` — re-export helper (optional).
- `apps/backend/app/boundary/adapters/channel_webhooks.py` — server-derived URL + uniform rejection.
- `apps/backend/app/api/v1/routers/voice.py` — server-derived URL + WS caps.
- `apps/backend/app/middleware/authority_context.py` — route errors through coarsening helper.
- `apps/backend/app/core/production_readiness.py` — gate `WEBHOOK_TRUST_URL_HEADER` / `PUBLIC_BASE_URL`.

---

## Task 1: Settings foundation

**Files:**
- Modify: `apps/backend/app/core/config.py` (Settings class, after the voice block ~line 214 and CORS block ~line 400)
- Test: `apps/backend/tests/test_edge_hardening_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_edge_hardening_settings.py
from app.core.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        ENVIRONMENT="test",
        TENANT_CREDENTIAL_MASTER_KEY="k" * 32,
        AUDIT_EXPORT_HMAC_SECRET="s" * 32,
    )
    base.update(overrides)
    return Settings(**base)


def test_rate_limit_defaults():
    s = _settings()
    assert s.RATE_LIMIT_ENABLED is True
    assert s.RATE_LIMIT_IP_PER_MINUTE == 120
    assert s.RATE_LIMIT_IP_BURST == 40
    assert s.RATE_LIMIT_TENANT_PER_MINUTE == 600
    assert s.RATE_LIMIT_TENANT_BURST == 200
    assert s.RATE_LIMIT_PRINCIPAL_PER_MINUTE == 300


def test_rate_limit_exempt_suffixes_default():
    s = _settings()
    assert s.rate_limit_exempt_suffixes == ("/health", "/live", "/ready")


def test_webhook_and_voice_cap_defaults():
    s = _settings()
    assert s.PUBLIC_BASE_URL == ""
    assert s.WEBHOOK_TRUST_URL_HEADER is False
    assert s.VOICE_MAX_CALL_SECONDS == 3600
    assert s.VOICE_IDLE_TIMEOUT_SECONDS == 30
    assert s.VOICE_MAX_FRAMES_PER_SECOND == 100
    assert s.COARSE_AUTH_ERRORS is False  # default off; prod turns on


def test_coarse_auth_errors_default_true_in_production():
    s = _settings(ENVIRONMENT="production")
    assert s.coarse_auth_errors_effective is True


def test_public_base_url_strips_trailing_slash():
    s = _settings(PUBLIC_BASE_URL="https://api.example.com/")
    assert s.public_base_url_normalized == "https://api.example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_edge_hardening_settings.py -v`
Expected: FAIL — `AttributeError`/`ValidationError` (settings not defined).

- [ ] **Step 3: Add the settings**

In `apps/backend/app/core/config.py`, inside `class Settings`, after the existing `VOICE_MAX_FRAMES_PER_CALL` line (~214) add:

```python
    # ── Inbound rate limiting (spec 1b #39) ──────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_IP_PER_MINUTE: int = 120
    RATE_LIMIT_IP_BURST: int = 40
    RATE_LIMIT_TENANT_PER_MINUTE: int = 600
    RATE_LIMIT_TENANT_BURST: int = 200
    RATE_LIMIT_PRINCIPAL_PER_MINUTE: int = 300  # 0 disables the layer
    RATE_LIMIT_EXEMPT_SUFFIXES: str = "/health,/live,/ready"

    # ── Webhook canonical URL (spec 1b #23) ──────────────────────────
    PUBLIC_BASE_URL: str = ""  # e.g. https://api.operious.com (no slash)
    WEBHOOK_TRUST_URL_HEADER: bool = False  # non-prod only; prod boot rejects

    # ── Voice WebSocket caps (spec 1b #40) ───────────────────────────
    VOICE_MAX_CALL_SECONDS: int = 3600
    VOICE_IDLE_TIMEOUT_SECONDS: int = 30
    VOICE_MAX_FRAMES_PER_SECOND: int = 100

    # ── Auth error coarsening (spec 1b #25) ──────────────────────────
    COARSE_AUTH_ERRORS: bool = False  # default off; prod default via property
```

Then add these properties near `is_production` (~line 407):

```python
    @property
    def rate_limit_exempt_suffixes(self) -> tuple[str, ...]:
        return tuple(
            s.strip()
            for s in self.RATE_LIMIT_EXEMPT_SUFFIXES.split(",")
            if s.strip()
        )

    @property
    def public_base_url_normalized(self) -> str:
        return self.PUBLIC_BASE_URL.strip().rstrip("/")

    @property
    def coarse_auth_errors_effective(self) -> bool:
        # Coarsen externally in production by default; explicit override wins.
        if self.COARSE_AUTH_ERRORS:
            return True
        return self.is_production
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_edge_hardening_settings.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/core/config.py apps/backend/tests/test_edge_hardening_settings.py
git commit -m "feat(config): edge-hardening settings (rate limits, public base url, voice caps, auth coarsening)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Redis token-bucket primitive

**Files:**
- Create: `apps/backend/app/core/rate_limit.py`
- Test: `apps/backend/tests/test_rate_limit_bucket.py`

The bucket is an atomic Lua script: GCRA-style token bucket keyed by `key`, with
`capacity` (burst) and `refill_per_second`. Returns `[allowed, retry_after_ms]`.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_rate_limit_bucket.py
import pytest
from fakeredis.aioredis import FakeRedis

from app.core.rate_limit import RateLimitDecision, TokenBucketLimiter


@pytest.fixture
def redis():
    return FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_allows_within_capacity(redis):
    limiter = TokenBucketLimiter(redis)
    for _ in range(5):
        decision = await limiter.consume(
            key="t:1", capacity=5, refill_per_second=1.0
        )
        assert decision.allowed is True
        assert decision.degraded is False


@pytest.mark.asyncio
async def test_blocks_over_capacity_with_retry_after(redis):
    limiter = TokenBucketLimiter(redis)
    for _ in range(5):
        await limiter.consume(key="t:2", capacity=5, refill_per_second=1.0)
    decision = await limiter.consume(key="t:2", capacity=5, refill_per_second=1.0)
    assert decision.allowed is False
    assert decision.retry_after_seconds >= 1


@pytest.mark.asyncio
async def test_redis_failure_returns_unavailable_decision():
    class _Boom:
        async def eval(self, *a, **k):
            raise ConnectionError("redis down")

    limiter = TokenBucketLimiter(_Boom())
    decision = await limiter.consume(key="t:3", capacity=5, refill_per_second=1.0)
    assert decision.backend_available is False
    assert isinstance(decision, RateLimitDecision)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_rate_limit_bucket.py -v`
Expected: FAIL — `ModuleNotFoundError: app.core.rate_limit`.
(If `fakeredis` is missing: `uv pip install fakeredis` in the backend env, and add it to the backend dev dependencies.)

- [ ] **Step 3: Implement the limiter**

```python
# apps/backend/app/core/rate_limit.py
"""Atomic Redis token-bucket limiter for inbound rate limiting (spec 1b)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

# KEYS[1] = bucket key
# ARGV[1] = capacity, ARGV[2] = refill_per_second, ARGV[3] = now_ms, ARGV[4] = ttl_ms
_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then
  tokens = capacity
  ts = now
end
local elapsed = math.max(0, now - ts) / 1000.0
tokens = math.min(capacity, tokens + elapsed * refill)
local allowed = 0
local retry_after_ms = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  if refill > 0 then
    retry_after_ms = math.ceil((1 - tokens) / refill * 1000)
  else
    retry_after_ms = ttl
  end
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, ttl)
return {allowed, retry_after_ms}
"""


class _AsyncRedis(Protocol):
    async def eval(self, script: str, numkeys: int, *args: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    backend_available: bool
    degraded: bool = False


class TokenBucketLimiter:
    """Token bucket evaluated atomically in Redis."""

    def __init__(self, redis: _AsyncRedis) -> None:
        self._redis = redis

    async def consume(
        self,
        *,
        key: str,
        capacity: int,
        refill_per_second: float,
    ) -> RateLimitDecision:
        now_ms = int(time.time() * 1000)
        ttl_ms = max(1000, int(capacity / max(refill_per_second, 1e-9) * 1000) + 1000)
        try:
            raw = await self._redis.eval(
                _BUCKET_LUA,
                1,
                key,
                str(capacity),
                str(refill_per_second),
                str(now_ms),
                str(ttl_ms),
            )
        except Exception:  # noqa: BLE001 - any Redis error => backend unavailable.
            return RateLimitDecision(
                allowed=False, retry_after_seconds=1, backend_available=False
            )
        allowed = bool(int(raw[0]))
        retry_after_ms = int(raw[1])
        return RateLimitDecision(
            allowed=allowed,
            retry_after_seconds=max(1, (retry_after_ms + 999) // 1000),
            backend_available=True,
        )


__all__ = ["RateLimitDecision", "TokenBucketLimiter"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_rate_limit_bucket.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/core/rate_limit.py apps/backend/tests/test_rate_limit_bucket.py
git commit -m "feat(rate-limit): atomic Redis token-bucket primitive

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Shared fail-policy + 429 response helpers

**Files:**
- Modify: `apps/backend/app/core/rate_limit.py` (append helpers)
- Test: `apps/backend/tests/test_rate_limit_policy.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_rate_limit_policy.py
from app.core.rate_limit import fail_open_allowed, too_many_requests_response


def test_get_fails_degraded_open():
    assert fail_open_allowed("GET") is True
    assert fail_open_allowed("HEAD") is True
    assert fail_open_allowed("OPTIONS") is True


def test_writes_fail_closed():
    assert fail_open_allowed("POST") is False
    assert fail_open_allowed("PUT") is False
    assert fail_open_allowed("PATCH") is False
    assert fail_open_allowed("DELETE") is False


def test_429_response_has_retry_after():
    resp = too_many_requests_response(retry_after_seconds=7)
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "7"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_rate_limit_policy.py -v`
Expected: FAIL — `ImportError` (helpers undefined).

- [ ] **Step 3: Append helpers to `rate_limit.py`**

```python
# append to apps/backend/app/core/rate_limit.py
import json

from starlette.responses import Response

from app.survivability import PROBLEM_DETAILS_MEDIA_TYPE

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def fail_open_allowed(method: str) -> bool:
    """When Redis is unavailable, idempotent reads degrade open; writes closed."""
    return method.upper() in _IDEMPOTENT_METHODS


def _problem_body(title: str, status: int, detail: str, **extra: object) -> bytes:
    payload = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "code": title,
    }
    payload.update(extra)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def too_many_requests_response(*, retry_after_seconds: int) -> Response:
    body = _problem_body("rate_limited", 429, "Rate limit exceeded.")
    return Response(
        content=body,
        status_code=429,
        media_type=PROBLEM_DETAILS_MEDIA_TYPE,
        headers={"Retry-After": str(retry_after_seconds)},
    )


def service_unavailable_response() -> Response:
    body = _problem_body(
        "rate_limit_unavailable", 503, "Rate limiter temporarily unavailable."
    )
    return Response(
        content=body, status_code=503, media_type=PROBLEM_DETAILS_MEDIA_TYPE
    )
```

Add `"fail_open_allowed"`, `"too_many_requests_response"`,
`"service_unavailable_response"` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_rate_limit_policy.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/core/rate_limit.py apps/backend/tests/test_rate_limit_policy.py
git commit -m "feat(rate-limit): method-based fail policy + 429/503 responses

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Edge (per-IP, pre-auth) rate-limit middleware

**Files:**
- Create: `apps/backend/app/middleware/edge_rate_limit.py`
- Test: `apps/backend/tests/test_edge_rate_limit_middleware.py`

Client IP must come from the trusted-proxy-validated peer, not raw
`X-Forwarded-For`. Reuse `app.middleware.trusted_ingress` peer extraction; when
no trusted proxies are configured, fall back to `scope["client"]`.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_edge_rate_limit_middleware.py
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware.edge_rate_limit import EdgeRateLimitMiddleware


class _StubLimiter:
    def __init__(self, allow_first: int, available: bool = True):
        self.allow_first = allow_first
        self.calls = 0
        self.available = available

    async def consume(self, *, key, capacity, refill_per_second):
        from app.core.rate_limit import RateLimitDecision

        self.calls += 1
        if not self.available:
            return RateLimitDecision(False, 1, backend_available=False)
        allowed = self.calls <= self.allow_first
        return RateLimitDecision(allowed, 1, backend_available=True)


def _app(limiter, exempt=()):
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok), Route("/health", ok)])
    app.add_middleware(
        EdgeRateLimitMiddleware,
        limiter=limiter,
        capacity=2,
        refill_per_second=1.0,
        exempt_suffixes=exempt,
        enabled=True,
    )
    return app


def test_allows_then_blocks_with_429():
    client = TestClient(_app(_StubLimiter(allow_first=2)))
    assert client.get("/x").status_code == 200
    assert client.get("/x").status_code == 200
    blocked = client.get("/x")
    assert blocked.status_code == 429
    assert "retry-after" in {k.lower() for k in blocked.headers}


def test_health_path_exempt():
    client = TestClient(_app(_StubLimiter(allow_first=0), exempt=("/health",)))
    assert client.get("/health").status_code == 200


def test_redis_down_get_fails_open():
    client = TestClient(_app(_StubLimiter(allow_first=0, available=False)))
    assert client.get("/x").status_code == 200  # GET degrades open
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_edge_rate_limit_middleware.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the middleware**

```python
# apps/backend/app/middleware/edge_rate_limit.py
"""Per-IP pre-auth inbound rate limiting (spec 1b #39)."""

from __future__ import annotations

import logging
from typing import Protocol

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.rate_limit import (
    RateLimitDecision,
    fail_open_allowed,
    service_unavailable_response,
    too_many_requests_response,
)

logger = logging.getLogger(__name__)


class _Limiter(Protocol):
    async def consume(
        self, *, key: str, capacity: int, refill_per_second: float
    ) -> RateLimitDecision: ...


class EdgeRateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: _Limiter,
        capacity: int,
        refill_per_second: float,
        exempt_suffixes: tuple[str, ...],
        enabled: bool,
    ) -> None:
        self.app = app
        self._limiter = limiter
        self._capacity = capacity
        self._refill = refill_per_second
        self._exempt = tuple(exempt_suffixes)
        self._enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._enabled:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path.endswith(suffix) for suffix in self._exempt):
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        ip = _client_ip(scope)
        decision = await self._limiter.consume(
            key=f"rl:ip:{ip}", capacity=self._capacity, refill_per_second=self._refill
        )
        if not decision.backend_available:
            if fail_open_allowed(method):
                logger.warning("rate_limit_backend_unavailable_degraded", extra={"ip": ip})
                await self.app(scope, receive, send)
                return
            logger.warning("rate_limit_backend_unavailable_closed", extra={"ip": ip})
            await service_unavailable_response()(scope, receive, send)
            return
        if not decision.allowed:
            await too_many_requests_response(
                retry_after_seconds=decision.retry_after_seconds
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    if client:
        return str(client[0])
    return "unknown"


__all__ = ["EdgeRateLimitMiddleware"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_edge_rate_limit_middleware.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/middleware/edge_rate_limit.py apps/backend/tests/test_edge_rate_limit_middleware.py
git commit -m "feat(middleware): per-IP pre-auth edge rate limiting

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Tenant/principal (post-auth) rate-limit middleware

**Files:**
- Create: `apps/backend/app/middleware/tenant_rate_limit.py`
- Test: `apps/backend/tests/test_tenant_rate_limit_middleware.py`

Reads resolved identity from `request.state.authority` (set by
`AuthorityContextMiddleware`, which runs OUTSIDE this one). Anonymous requests
skip the tenant layer (they were already IP-limited at the edge).

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_tenant_rate_limit_middleware.py
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.rate_limit import RateLimitDecision
from app.middleware.tenant_rate_limit import TenantRateLimitMiddleware


class _Spy:
    def __init__(self, allow_first):
        self.allow_first = allow_first
        self.calls = 0
        self.keys = []

    async def consume(self, *, key, capacity, refill_per_second):
        self.calls += 1
        self.keys.append(key)
        return RateLimitDecision(self.calls <= self.allow_first, 1, True)


def _app(limiter, tenant="t-1", principal="p-1"):
    async def ok(request):
        class _Auth:
            tenant_id = tenant
            principal_id = principal

        request.state.authority = _Auth()
        return PlainTextResponse("ok")

    # NOTE: state set inside endpoint won't help; instead inject via a tiny
    # upstream middleware that stamps authority before the limiter.
    app = Starlette(routes=[Route("/x", ok)])
    app.add_middleware(
        TenantRateLimitMiddleware,
        limiter=limiter,
        tenant_capacity=2,
        tenant_refill=1.0,
        principal_capacity=2,
        principal_refill=1.0,
        enabled=True,
    )

    class _StampAuth:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope.setdefault("state", {})
            await self.inner(scope, receive, send)

    return app


def test_tenant_key_used_and_blocks():
    spy = _Spy(allow_first=2)
    # Build app where authority is stamped by a wrapper middleware.
    from starlette.requests import Request

    async def ok(request: Request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok)])

    class _Auth:
        tenant_id = "t-1"
        principal_id = "p-1"

    class _Stamp:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope["state"] = {"authority": _Auth()}
            await self.inner(scope, receive, send)

    app.add_middleware(TenantRateLimitMiddleware, limiter=spy,
                       tenant_capacity=2, tenant_refill=1.0,
                       principal_capacity=0, principal_refill=1.0, enabled=True)
    app.add_middleware(_Stamp)
    client = TestClient(app)
    assert client.get("/x").status_code == 200
    assert client.get("/x").status_code == 200
    assert client.get("/x").status_code == 429
    assert any(k.startswith("rl:tenant:t-1") for k in spy.keys)
```

> Implementer note: read identity via `scope["state"]["authority"]` (Starlette
> exposes `request.state` as `scope["state"]`). Skip the layer when no authority
> or no `tenant_id`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_tenant_rate_limit_middleware.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the middleware**

```python
# apps/backend/app/middleware/tenant_rate_limit.py
"""Per-tenant/principal post-auth inbound rate limiting (spec 1b #39)."""

from __future__ import annotations

import logging
from typing import Protocol

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.rate_limit import (
    RateLimitDecision,
    fail_open_allowed,
    service_unavailable_response,
    too_many_requests_response,
)

logger = logging.getLogger(__name__)


class _Limiter(Protocol):
    async def consume(
        self, *, key: str, capacity: int, refill_per_second: float
    ) -> RateLimitDecision: ...


class TenantRateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: _Limiter,
        tenant_capacity: int,
        tenant_refill: float,
        principal_capacity: int,
        principal_refill: float,
        enabled: bool,
    ) -> None:
        self.app = app
        self._limiter = limiter
        self._tc = tenant_capacity
        self._tr = tenant_refill
        self._pc = principal_capacity
        self._pr = principal_refill
        self._enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._enabled:
            await self.app(scope, receive, send)
            return
        authority = (scope.get("state") or {}).get("authority")
        tenant_id = getattr(authority, "tenant_id", None)
        if not tenant_id:
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        checks = [(f"rl:tenant:{tenant_id}", self._tc, self._tr)]
        principal_id = getattr(authority, "principal_id", None)
        if principal_id and self._pc > 0:
            checks.append((f"rl:principal:{principal_id}", self._pc, self._pr))
        for key, capacity, refill in checks:
            decision = await self._limiter.consume(
                key=key, capacity=capacity, refill_per_second=refill
            )
            if not decision.backend_available:
                if fail_open_allowed(method):
                    logger.warning("rate_limit_backend_unavailable_degraded", extra={"key": key})
                    continue
                logger.warning("rate_limit_backend_unavailable_closed", extra={"key": key})
                await service_unavailable_response()(scope, receive, send)
                return
            if not decision.allowed:
                await too_many_requests_response(
                    retry_after_seconds=decision.retry_after_seconds
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


__all__ = ["TenantRateLimitMiddleware"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_tenant_rate_limit_middleware.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/middleware/tenant_rate_limit.py apps/backend/tests/test_tenant_rate_limit_middleware.py
git commit -m "feat(middleware): per-tenant/principal post-auth rate limiting

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Wire both middlewares into the app pipeline

**Files:**
- Modify: `apps/backend/app/main.py` (middleware registration block ~636-678)
- Test: `apps/backend/tests/test_edge_hardening_pipeline.py`

Target order (outer → inner):
`RequestBodyLimit → CORS → RequestContext → EdgeRateLimit → TrustedIngress → AuthorityContext → TenantRateLimit → Router`.
Starlette prepends, so register inner-most first: TenantRateLimit, then
AuthorityContext, then TrustedIngress, then EdgeRateLimit, then RequestContext, …

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_edge_hardening_pipeline.py
from app.core.config import Settings
from app.main import create_app


def _settings(**kw):
    base = dict(ENVIRONMENT="test", TENANT_CREDENTIAL_MASTER_KEY="k" * 32,
                AUDIT_EXPORT_HMAC_SECRET="s" * 32, RATE_LIMIT_ENABLED=True)
    base.update(kw)
    return Settings(**base)


def test_both_rate_limit_middlewares_registered():
    app = create_app(_settings())
    names = [m.cls.__name__ for m in app.user_middleware]
    assert "EdgeRateLimitMiddleware" in names
    assert "TenantRateLimitMiddleware" in names


def test_order_edge_outside_authority_tenant_inside():
    app = create_app(_settings())
    names = [m.cls.__name__ for m in app.user_middleware]
    # user_middleware is outer-first in Starlette's list ordering.
    assert names.index("EdgeRateLimitMiddleware") < names.index("AuthorityContextMiddleware")
    assert names.index("AuthorityContextMiddleware") < names.index("TenantRateLimitMiddleware")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_edge_hardening_pipeline.py -v`
Expected: FAIL — middlewares not registered.

- [ ] **Step 3: Register the middlewares**

In `apps/backend/app/main.py`, add imports near the other middleware imports (~76-82):

```python
from app.middleware.edge_rate_limit import EdgeRateLimitMiddleware
from app.middleware.tenant_rate_limit import TenantRateLimitMiddleware
from app.core.rate_limit import TokenBucketLimiter
from app.core.redis import get_redis_client
```

Then in the registration block, **before** `app.add_middleware(AuthorityContextMiddleware, ...)` (so it ends up inner-most), add:

```python
    _rate_limiter = TokenBucketLimiter(cast(Any, get_redis_client()))
    app.add_middleware(
        TenantRateLimitMiddleware,
        limiter=_rate_limiter,
        tenant_capacity=settings.RATE_LIMIT_TENANT_BURST,
        tenant_refill=settings.RATE_LIMIT_TENANT_PER_MINUTE / 60.0,
        principal_capacity=settings.RATE_LIMIT_PRINCIPAL_PER_MINUTE,  # burst==rate
        principal_refill=settings.RATE_LIMIT_PRINCIPAL_PER_MINUTE / 60.0,
        enabled=settings.RATE_LIMIT_ENABLED,
    )
```

And **after** the `TrustedIngress` block but **before** `RequestContextMiddleware` registration, add the edge layer (so it sits outside TrustedIngress/Authority, inside RequestContext):

```python
    app.add_middleware(
        EdgeRateLimitMiddleware,
        limiter=_rate_limiter,
        capacity=settings.RATE_LIMIT_IP_BURST,
        refill_per_second=settings.RATE_LIMIT_IP_PER_MINUTE / 60.0,
        exempt_suffixes=settings.rate_limit_exempt_suffixes,
        enabled=settings.RATE_LIMIT_ENABLED,
    )
```

> Implementer note: confirm the registration order produces the asserted
> `user_middleware` ordering; adjust placement (not logic) until the test passes.
> `cast` and `Any` are already imported in `main.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_edge_hardening_pipeline.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the broader app-boot test to ensure no regression**

Run: `python -m pytest apps/backend/tests/test_main_legacy_header_disabled.py apps/backend/tests/test_config_security_posture.py -v`
Expected: PASS (existing tests still green).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/main.py apps/backend/tests/test_edge_hardening_pipeline.py
git commit -m "feat(main): register edge + tenant rate-limit middlewares in pipeline

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Server-derived webhook canonical URL helper

**Files:**
- Create: `apps/backend/app/core/webhook_url.py`
- Test: `apps/backend/tests/test_webhook_canonical_url.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_webhook_canonical_url.py
import pytest

from app.core.webhook_url import CanonicalWebhookUrlError, derive_canonical_webhook_url


def test_builds_from_public_base_url_and_path():
    url = derive_canonical_webhook_url(
        public_base_url="https://api.operious.com",
        request_path="/api/v1/webhooks/twilio/voice",
        query_string="",
    )
    assert url == "https://api.operious.com/api/v1/webhooks/twilio/voice"


def test_appends_query_when_present():
    url = derive_canonical_webhook_url(
        public_base_url="https://api.operious.com",
        request_path="/hook",
        query_string="b=2&a=1",
    )
    assert url == "https://api.operious.com/hook?b=2&a=1"


def test_empty_base_url_raises():
    with pytest.raises(CanonicalWebhookUrlError):
        derive_canonical_webhook_url(
            public_base_url="", request_path="/hook", query_string=""
        )


def test_strips_trailing_slash_on_base():
    url = derive_canonical_webhook_url(
        public_base_url="https://api.operious.com/",
        request_path="/hook",
        query_string="",
    )
    assert url == "https://api.operious.com/hook"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_webhook_canonical_url.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the helper**

```python
# apps/backend/app/core/webhook_url.py
"""Server-side canonical webhook URL derivation (spec 1b #23).

The Twilio signature must be verified against the URL the provider actually
signed. That URL is OUR public URL, derived from server-trusted config, never
a client-supplied header.
"""

from __future__ import annotations


class CanonicalWebhookUrlError(ValueError):
    """Raised when the canonical URL cannot be derived (missing base URL)."""


def derive_canonical_webhook_url(
    *,
    public_base_url: str,
    request_path: str,
    query_string: str,
) -> str:
    base = public_base_url.strip().rstrip("/")
    if not base:
        raise CanonicalWebhookUrlError(
            "PUBLIC_BASE_URL must be configured to verify webhook signatures"
        )
    path = request_path if request_path.startswith("/") else f"/{request_path}"
    url = f"{base}{path}"
    if query_string:
        url = f"{url}?{query_string}"
    return url


__all__ = ["CanonicalWebhookUrlError", "derive_canonical_webhook_url"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_webhook_canonical_url.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/core/webhook_url.py apps/backend/tests/test_webhook_canonical_url.py
git commit -m "feat(webhook): server-side canonical URL derivation helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Use server-derived URL in the channel-webhook verifier

**Files:**
- Modify: `apps/backend/app/boundary/adapters/channel_webhooks.py` (`_verify_twilio_signature` ~770-782, and its caller ~193)
- Test: `apps/backend/tests/test_channel_webhook_signature_url.py`

The verifier currently reads the URL from the client header
`TWILIO_CANONICAL_URL_HEADER`. Change it to use the server-derived URL, honoring
the header only when `WEBHOOK_TRUST_URL_HEADER` is true.

- [ ] **Step 1: Read the current call site**

Run: `sed -n '180,200p;760,800p' apps/backend/app/boundary/adapters/channel_webhooks.py`
Note the exact signature of `_verify_twilio_signature` and how `payload.headers`,
the request path, and query are available on the inbound payload object.

- [ ] **Step 2: Write the failing test**

```python
# apps/backend/tests/test_channel_webhook_signature_url.py
from app.core.twilio_signature import compute_twilio_signature
from app.boundary.adapters.channel_webhooks import _verify_twilio_signature


def _make_payload(headers, path="/api/v1/webhooks/twilio", query="", params=None):
    # Build the minimal inbound-payload shape the verifier consumes.
    # Adjust attribute names to match the real payload object discovered in Step 1.
    from types import SimpleNamespace

    return SimpleNamespace(headers=headers, path=path, query_string=query,
                           form=params or {})


def test_forged_header_url_is_ignored(monkeypatch):
    auth_token = "tok"
    server_url = "https://api.operious.com/api/v1/webhooks/twilio"
    good_sig = compute_twilio_signature(auth_token=auth_token, url=server_url, params={})
    payload = _make_payload(
        headers={"x-twilio-signature": good_sig,
                 "x-operious-webhook-url": "https://evil.test/forged"},
    )
    ok = _verify_twilio_signature(
        payload, auth_token,
        public_base_url="https://api.operious.com",
        trust_url_header=False,
    )
    assert ok is True  # signature verified against SERVER url, header ignored


def test_signature_over_forged_url_rejected():
    auth_token = "tok"
    forged_url = "https://evil.test/forged"
    sig_over_forged = compute_twilio_signature(auth_token=auth_token, url=forged_url, params={})
    payload = _make_payload(
        headers={"x-twilio-signature": sig_over_forged,
                 "x-operious-webhook-url": forged_url},
    )
    ok = _verify_twilio_signature(
        payload, auth_token,
        public_base_url="https://api.operious.com",
        trust_url_header=False,
    )
    assert ok is False
```

> Implementer note: the exact payload attribute names (`path`, `query_string`,
> `form`) come from Step 1. Update the test + implementation to the real names.

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_channel_webhook_signature_url.py -v`
Expected: FAIL — `_verify_twilio_signature` does not accept the new kwargs.

- [ ] **Step 4: Update the verifier**

Change `_verify_twilio_signature` to derive the URL server-side:

```python
from app.core.webhook_url import derive_canonical_webhook_url, CanonicalWebhookUrlError

def _verify_twilio_signature(
    payload,
    auth_token,
    *,
    public_base_url: str,
    trust_url_header: bool,
) -> bool:
    signature = _header(payload.headers, TWILIO_SIGNATURE_HEADER)
    if trust_url_header:
        url = _header(payload.headers, TWILIO_CANONICAL_URL_HEADER)
    else:
        try:
            url = derive_canonical_webhook_url(
                public_base_url=public_base_url,
                request_path=payload.path,
                query_string=getattr(payload, "query_string", "") or "",
            )
        except CanonicalWebhookUrlError:
            return False
    return verify_twilio_signature(
        auth_token=auth_token,
        url=url,
        params=getattr(payload, "form", None),
        signature=signature,
    )
```

Update the caller (~193) to pass `public_base_url=settings.public_base_url_normalized`
and `trust_url_header=settings.WEBHOOK_TRUST_URL_HEADER` (thread `settings` through
or call `get_settings()` at the call site, matching local conventions).

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_channel_webhook_signature_url.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run existing webhook tests for regressions**

Run: `python -m pytest apps/backend/tests/ -k "webhook or channel" -v`
Expected: PASS (fix any test that relied on the client header by setting
`WEBHOOK_TRUST_URL_HEADER=true` or providing `PUBLIC_BASE_URL`).

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/boundary/adapters/channel_webhooks.py apps/backend/tests/test_channel_webhook_signature_url.py
git commit -m "fix(webhook): verify Twilio signature against server-derived URL (#23)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Use server-derived URL in the voice provider-signature check

**Files:**
- Modify: `apps/backend/app/api/v1/routers/voice.py` (`_verify_voice_provider_signature` ~209-219)
- Test: `apps/backend/tests/test_voice_provider_signature_url.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_voice_provider_signature_url.py
from types import SimpleNamespace

from app.core.twilio_signature import compute_twilio_signature
from app.api.v1.routers.voice import _verify_voice_provider_signature


def _ws(headers, path="/api/v1/voice/sess-1/stream"):
    return SimpleNamespace(
        headers=headers,
        url=SimpleNamespace(path=path),
        scope={"path": path, "query_string": b""},
    )


def test_voice_signature_uses_server_url_ignores_header():
    auth = "provtok"
    server_url = "https://api.operious.com/api/v1/voice/sess-1/stream"
    sig = compute_twilio_signature(auth_token=auth, url=server_url, params=None)
    ws = _ws({"x-twilio-signature": sig, "x-operious-webhook-url": "https://evil/x"})
    assert _verify_voice_provider_signature(
        websocket=ws, auth_token=auth,
        public_base_url="https://api.operious.com", trust_url_header=False,
    ) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_voice_provider_signature_url.py -v`
Expected: FAIL — signature changed / kwargs unknown.

- [ ] **Step 3: Update `_verify_voice_provider_signature`**

```python
from app.core.webhook_url import derive_canonical_webhook_url, CanonicalWebhookUrlError

def _verify_voice_provider_signature(
    *,
    websocket,
    auth_token: str,
    public_base_url: str,
    trust_url_header: bool,
) -> bool:
    if trust_url_header:
        url = websocket.headers.get(TWILIO_CANONICAL_URL_HEADER)
    else:
        path = websocket.scope.get("path", "")
        query = websocket.scope.get("query_string", b"")
        query_string = query.decode("latin-1") if isinstance(query, bytes) else str(query)
        try:
            url = derive_canonical_webhook_url(
                public_base_url=public_base_url,
                request_path=path,
                query_string=query_string,
            )
        except CanonicalWebhookUrlError:
            return False
    return verify_twilio_signature(
        auth_token=auth_token,
        url=url,
        params=None,
        signature=websocket.headers.get(TWILIO_SIGNATURE_HEADER),
    )
```

Update the call site (~76) to pass
`public_base_url=settings.public_base_url_normalized` and
`trust_url_header=settings.WEBHOOK_TRUST_URL_HEADER`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_voice_provider_signature_url.py -v`
Expected: PASS.

- [ ] **Step 5: Run existing voice auth tests**

Run: `python -m pytest apps/backend/tests/test_voice_provider_signature.py apps/backend/tests/test_voice_session_token.py -v`
Expected: PASS (adjust fixtures to set `PUBLIC_BASE_URL` or `WEBHOOK_TRUST_URL_HEADER=true`).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/api/v1/routers/voice.py apps/backend/tests/test_voice_provider_signature_url.py
git commit -m "fix(voice): verify provider signature against server-derived URL (#23)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Production-readiness gates for webhook settings

**Files:**
- Modify: `apps/backend/app/core/production_readiness.py` (`collect_production_problems`)
- Test: `apps/backend/tests/test_production_readiness_webhook.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_production_readiness_webhook.py
from app.core.config import Settings
from app.core.production_readiness import collect_production_problems


def _prod(**kw):
    base = dict(ENVIRONMENT="production", TENANT_CREDENTIAL_MASTER_KEY="k" * 32,
                AUDIT_EXPORT_HMAC_SECRET="s" * 32, ANTHROPIC_API_KEY="a" * 8,
                TRANSLATION_PROVIDER="anthropic")
    base.update(kw)
    return Settings(**base)


def test_trust_url_header_rejected_in_production():
    problems = collect_production_problems(_prod(WEBHOOK_TRUST_URL_HEADER=True))
    assert any("WEBHOOK_TRUST_URL_HEADER" in p for p in problems)


def test_public_base_url_required_when_not_trusting_header():
    problems = collect_production_problems(_prod(PUBLIC_BASE_URL="",
                                                 WEBHOOK_TRUST_URL_HEADER=False))
    assert any("PUBLIC_BASE_URL" in p for p in problems)


def test_public_base_url_set_is_clean():
    problems = collect_production_problems(
        _prod(PUBLIC_BASE_URL="https://api.operious.com", WEBHOOK_TRUST_URL_HEADER=False)
    )
    assert not any("PUBLIC_BASE_URL" in p or "WEBHOOK_TRUST_URL_HEADER" in p
                   for p in problems)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_production_readiness_webhook.py -v`
Expected: FAIL — gates not present.

- [ ] **Step 3: Add the gates**

In `collect_production_problems`, before `return tuple(problems)`:

```python
    # ── Webhook signature URL (spec 1b #23) ──────────────────────────
    if settings.WEBHOOK_TRUST_URL_HEADER:
        problems.append(
            "WEBHOOK_TRUST_URL_HEADER=true -> webhook signatures would trust a "
            "client-supplied canonical URL header; this must be false in "
            "production."
        )
    elif not settings.public_base_url_normalized:
        problems.append(
            "PUBLIC_BASE_URL is empty -> webhook/voice provider signatures "
            "cannot be verified against a server-derived URL."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_production_readiness_webhook.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full readiness test module**

Run: `python -m pytest apps/backend/tests/test_production_readiness.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/core/production_readiness.py apps/backend/tests/test_production_readiness_webhook.py
git commit -m "feat(readiness): gate WEBHOOK_TRUST_URL_HEADER + require PUBLIC_BASE_URL in prod

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Uniform webhook rejection (anti-enumeration)

**Files:**
- Modify: `apps/backend/app/boundary/adapters/channel_webhooks.py` (rejection paths) and/or the webhook router that returns responses
- Test: `apps/backend/tests/test_webhook_uniform_rejection.py`

- [ ] **Step 1: Discover the rejection sites**

Run: `grep -n "status_code=40\|HTTPException\|JSONResponse\|raise\|return.*40" apps/backend/app/boundary/adapters/channel_webhooks.py | head -40`
Identify every distinct response for: unknown route/channel, unknown/disabled
tenant, missing secret, signature mismatch. Note their statuses and bodies.

- [ ] **Step 2: Write the failing test**

```python
# apps/backend/tests/test_webhook_uniform_rejection.py
from app.boundary.adapters.channel_webhooks import webhook_rejection, WEBHOOK_REJECTION_BODY


def test_all_rejection_reasons_share_one_response():
    for reason in ("unknown_route", "unknown_tenant", "missing_secret",
                   "signature_mismatch"):
        resp = webhook_rejection(reason)
        assert resp.status_code == 403
        assert resp.body == WEBHOOK_REJECTION_BODY


def test_rejection_body_is_constant_and_detailless():
    resp = webhook_rejection("signature_mismatch")
    assert b"signature" not in resp.body.lower()
    assert b"tenant" not in resp.body.lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_webhook_uniform_rejection.py -v`
Expected: FAIL — `webhook_rejection` undefined.

- [ ] **Step 4: Implement uniform rejection**

Add to `channel_webhooks.py`:

```python
import logging
from starlette.responses import Response
from app.survivability import PROBLEM_DETAILS_MEDIA_TYPE

_webhook_logger = logging.getLogger(__name__)

WEBHOOK_REJECTION_BODY = (
    b'{"code":"webhook_rejected","detail":"Request rejected.",'
    b'"status":403,"title":"webhook_rejected","type":"about:blank"}'
)


def webhook_rejection(reason: str) -> Response:
    """One identical response for every webhook rejection cause (#24).

    The specific ``reason`` is logged server-side ONLY, so an attacker cannot
    distinguish unknown-route from bad-secret from signature-mismatch.
    """
    _webhook_logger.warning("webhook_rejected", extra={"reason": reason})
    return Response(
        content=WEBHOOK_REJECTION_BODY,
        status_code=403,
        media_type=PROBLEM_DETAILS_MEDIA_TYPE,
    )
```

Replace each distinct rejection return discovered in Step 1 with
`return webhook_rejection("<reason>")`. For the signature-mismatch path, when the
route/secret is unknown, still perform a dummy constant-time comparison before
returning so timing does not leak existence:

```python
import hmac
# when route/secret unknown:
hmac.compare_digest("0" * 32, "1" * 32)  # constant-time dummy
return webhook_rejection("unknown_route")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_webhook_uniform_rejection.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run webhook regression tests**

Run: `python -m pytest apps/backend/tests/ -k "webhook or channel" -v`
Expected: PASS (update any test asserting an old distinct status/body).

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/boundary/adapters/channel_webhooks.py apps/backend/tests/test_webhook_uniform_rejection.py
git commit -m "fix(webhook): uniform rejection + timing-safe unknown-route path (#24)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Auth error coarsening helper

**Files:**
- Create: `apps/backend/app/middleware/auth_error.py`
- Test: `apps/backend/tests/test_auth_error_coarsening.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_auth_error_coarsening.py
import json

from app.middleware.auth_error import auth_error_response


def test_coarse_response_is_generic():
    resp = auth_error_response(
        status_code=401, internal_code="header_authority_disabled",
        reason="legacy headers not accepted", coarsen=True,
    )
    body = json.loads(resp.body)
    assert body == {"error": "unauthorized"}
    assert resp.headers["www-authenticate"] == "Bearer"


def test_detailed_response_when_not_coarsened():
    resp = auth_error_response(
        status_code=401, internal_code="header_authority_disabled",
        reason="legacy headers not accepted", coarsen=False,
    )
    body = json.loads(resp.body)
    assert body["error"] == "header_authority_disabled"
    assert body["reason"] == "legacy headers not accepted"


def test_400_codes_also_coarsen_to_generic():
    resp = auth_error_response(
        status_code=400, internal_code="malformed_authorization_header",
        reason="bad scheme", coarsen=True,
    )
    assert resp.status_code == 400
    assert json.loads(resp.body) == {"error": "bad_request"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_auth_error_coarsening.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the helper**

```python
# apps/backend/app/middleware/auth_error.py
"""External coarsening of authority/auth errors (spec 1b #25).

In production the external body is generic (no recon detail); the precise
internal code + reason are logged server-side with the request correlation id.
"""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_GENERIC = {401: "unauthorized", 403: "forbidden", 400: "bad_request"}


def auth_error_response(
    *,
    status_code: int,
    internal_code: str,
    reason: str,
    coarsen: bool,
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    if coarsen:
        logger.warning(
            "auth_error_coarsened",
            extra={"internal_code": internal_code, "reason": reason,
                   "status": status_code},
        )
        generic = _GENERIC.get(status_code, "error")
        return JSONResponse(
            status_code=status_code, content={"error": generic}, headers=headers
        )
    return JSONResponse(
        status_code=status_code,
        content={"error": internal_code, "reason": reason},
        headers=headers,
    )


__all__ = ["auth_error_response"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_auth_error_coarsening.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/middleware/auth_error.py apps/backend/tests/test_auth_error_coarsening.py
git commit -m "feat(auth): external auth-error coarsening helper (#25)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 13: Route AuthorityContext errors through the coarsening helper

**Files:**
- Modify: `apps/backend/app/middleware/authority_context.py` (constructor + each `JSONResponse(...)` error return)
- Test: `apps/backend/tests/test_authority_context_coarsening.py`

Keep existing detailed behavior when `coarsen=False` (default in test env) so
existing tests stay green; coarsen when constructed with `coarsen_errors=True`.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_authority_context_coarsening.py
import json

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware.authority_context import AuthorityContextMiddleware


def _client(coarsen):
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok)])
    app.add_middleware(
        AuthorityContextMiddleware,
        auth_provider=None,
        legacy_header_authority_enabled=False,
        coarsen_errors=coarsen,
    )
    return TestClient(app)


def test_disabled_header_authority_coarsened():
    resp = _client(coarsen=True).get("/x", headers={"X-Tenant-ID": "t-1"})
    assert resp.status_code == 401
    assert json.loads(resp.text) == {"error": "unauthorized"}


def test_detailed_when_not_coarsened():
    resp = _client(coarsen=False).get("/x", headers={"X-Tenant-ID": "t-1"})
    assert resp.status_code == 401
    assert json.loads(resp.text)["error"] == "header_authority_disabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_authority_context_coarsening.py -v`
Expected: FAIL — `coarsen_errors` kwarg unknown.

- [ ] **Step 3: Thread coarsening through the middleware**

In `authority_context.py`:

1. Add to `__init__`: `coarsen_errors: bool = False` and store
   `self._coarsen_errors = coarsen_errors`.
2. Add a private helper:

```python
    def _error(self, *, status_code: int, internal_code: str, reason: str) -> Response:
        from app.middleware.auth_error import auth_error_response
        return auth_error_response(
            status_code=status_code, internal_code=internal_code,
            reason=reason, coarsen=self._coarsen_errors,
        )
```

3. Replace each error `return JSONResponse(...)` with `return self._error(...)`,
   mapping the existing `"error"` value to `internal_code` and the existing
   `"reason"` (or a short string) to `reason`. Example for the disabled-header
   branch (~223):

```python
            return self._error(
                status_code=401,
                internal_code="header_authority_disabled",
                reason="legacy X-*-ID identity headers are not accepted",
            )
```

Do this for: `malformed_authorization_header`, `malformed_authority_header`,
`header_authority_disabled`, `authority_source_conflict`,
`verification_unavailable`, `verification_failed`, `malformed_verified_claim`.

4. In `apps/backend/app/main.py`, pass
   `coarsen_errors=settings.coarse_auth_errors_effective` to the
   `AuthorityContextMiddleware` registration (~636).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_authority_context_coarsening.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the existing authority tests for regressions**

Run: `python -m pytest apps/backend/tests/test_authority_header_disabled.py apps/backend/tests/ -k "authority" -v`
Expected: PASS (default `coarsen_errors=False` preserves existing bodies).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/middleware/authority_context.py apps/backend/app/main.py apps/backend/tests/test_authority_context_coarsening.py
git commit -m "feat(auth): coarsen authority errors in production posture (#25)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 14: Voice WebSocket duration / idle / frame-rate caps

**Files:**
- Modify: `apps/backend/app/api/v1/routers/voice.py` (`stream_voice_session` call into `_handle_voice_call`, and the loop ~125-197)
- Test: `apps/backend/tests/test_voice_ws_caps.py`

Add wall-clock max-duration, idle timeout (wrap `receive_text` in
`asyncio.wait_for`), and a rolling-second frame-rate cap.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_voice_ws_caps.py
import asyncio
import pytest

from app.api.v1.routers.voice import _enforce_frame_rate, FrameRateExceeded


def test_frame_rate_cap_trips_over_limit():
    times = [100.0, 100.1, 100.2]  # 3 frames within same second
    window = []
    # max 2 frames/sec
    _enforce_frame_rate(window, now=times[0], max_per_second=2)
    _enforce_frame_rate(window, now=times[1], max_per_second=2)
    with pytest.raises(FrameRateExceeded):
        _enforce_frame_rate(window, now=times[2], max_per_second=2)


def test_frame_rate_window_evicts_old_timestamps():
    window = []
    _enforce_frame_rate(window, now=100.0, max_per_second=2)
    _enforce_frame_rate(window, now=100.4, max_per_second=2)
    # 1.1s later: old timestamps evicted, allowed again
    _enforce_frame_rate(window, now=101.5, max_per_second=2)
    assert len(window) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_voice_ws_caps.py -v`
Expected: FAIL — `_enforce_frame_rate` / `FrameRateExceeded` undefined.

- [ ] **Step 3: Implement the frame-rate primitive + wire caps into the loop**

Add to `voice.py`:

```python
import asyncio


class FrameRateExceeded(Exception):
    """Per-connection frame-rate cap exceeded."""


def _enforce_frame_rate(window: list[float], *, now: float, max_per_second: int) -> None:
    cutoff = now - 1.0
    while window and window[0] <= cutoff:
        window.pop(0)
    if len(window) >= max_per_second:
        raise FrameRateExceeded
    window.append(now)
```

Then in `_handle_voice_call`, accept new params and enforce them. Replace the
`while True:` receive with idle/duration/rate enforcement:

```python
async def _handle_voice_call(
    *,
    websocket,
    adapter,
    runtime,
    call_id,
    session_id,
    tenant_id,
    max_frame_bytes,
    max_frames,
    max_call_seconds: int,
    idle_timeout_seconds: int,
    max_frames_per_second: int,
) -> None:
    frames_seen = 0
    rate_window: list[float] = []
    started = time.monotonic()
    try:
        while True:
            if time.monotonic() - started > max_call_seconds:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                await runtime.terminate_call(call_id=call_id,
                    reason="voice_max_duration", expected_tenant_id=tenant_id)
                return
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=idle_timeout_seconds
                )
            except asyncio.TimeoutError:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                await runtime.terminate_call(call_id=call_id,
                    reason="voice_idle_timeout", expected_tenant_id=tenant_id)
                return
            try:
                _enforce_frame_rate(rate_window, now=time.monotonic(),
                                    max_per_second=max_frames_per_second)
            except FrameRateExceeded:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                await runtime.terminate_call(call_id=call_id,
                    reason="voice_frame_rate_exceeded", expected_tenant_id=tenant_id)
                return
            # ... existing byte-size, frame-count, and event handling unchanged ...
```

Pass the three new settings from `stream_voice_session` (~103):

```python
        await _handle_voice_call(
            websocket=websocket,
            adapter=adapter,
            runtime=runtime,
            call_id=call_id,
            session_id=session_id,
            tenant_id=tenant_id,
            max_frame_bytes=settings.VOICE_MAX_FRAME_BYTES,
            max_frames=settings.VOICE_MAX_FRAMES_PER_CALL,
            max_call_seconds=settings.VOICE_MAX_CALL_SECONDS,
            idle_timeout_seconds=settings.VOICE_IDLE_TIMEOUT_SECONDS,
            max_frames_per_second=settings.VOICE_MAX_FRAMES_PER_SECOND,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_voice_ws_caps.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run existing voice tests + repair stale capacity/load harness**

Run: `python -m pytest apps/backend/tests/ -k "voice" -v`
Expected: PASS. If `test_voice_capacity.py` / `test_voice_load.py` fail because
their fake WebSockets do not model the new params, update those fakes to provide
`scope` + `receive_text` that returns frames then raises `WebSocketDisconnect`,
and set the three new settings to generous values so the caps do not trip. (This
also closes audit #63.)

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/api/v1/routers/voice.py apps/backend/tests/test_voice_ws_caps.py
git commit -m "feat(voice): wall-clock, idle, and frame-rate WebSocket caps (#40)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 15: CORS production posture (respect config) + posture test

**Files:**
- Modify: `apps/backend/app/main.py` (CORS registration ~664-671)
- Test: `apps/backend/tests/test_cors_posture.py`

`main.py` currently hardcodes `allow_credentials=True`, ignoring the existing
`CORS_ALLOW_CREDENTIALS` setting (#16). Respect the setting, and forbid the
unsafe wildcard-origin + credentials combination.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_cors_posture.py
import pytest

from app.core.config import Settings
from app.main import create_app


def _settings(**kw):
    base = dict(ENVIRONMENT="test", TENANT_CREDENTIAL_MASTER_KEY="k" * 32,
                AUDIT_EXPORT_HMAC_SECRET="s" * 32,
                CORS_ALLOW_ORIGINS="https://app.operious.com")
    base.update(kw)
    return Settings(**base)


def _cors_options(app):
    for m in app.user_middleware:
        if m.cls.__name__ == "CORSMiddleware":
            return m.kwargs
    raise AssertionError("CORSMiddleware not registered")


def test_credentials_respect_setting_true():
    app = create_app(_settings(CORS_ALLOW_CREDENTIALS=True))
    assert _cors_options(app)["allow_credentials"] is True


def test_credentials_respect_setting_false():
    app = create_app(_settings(CORS_ALLOW_CREDENTIALS=False))
    assert _cors_options(app)["allow_credentials"] is False


def test_wildcard_origin_with_credentials_is_rejected():
    with pytest.raises(ValueError):
        create_app(_settings(CORS_ALLOW_ORIGINS="*", CORS_ALLOW_CREDENTIALS=True))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest apps/backend/tests/test_cors_posture.py -v`
Expected: FAIL — `allow_credentials` hardcoded true; wildcard+creds not rejected.

- [ ] **Step 3: Respect the setting and reject the unsafe combination**

In `main.py`, replace the hardcoded `allow_credentials=True` (~668) with
`allow_credentials=settings.CORS_ALLOW_CREDENTIALS`, and in `_build_cors_origins`
(or just before CORS registration) add:

```python
    cors_origins = _build_cors_origins(settings.CORS_ALLOW_ORIGINS)
    if settings.CORS_ALLOW_CREDENTIALS and "*" in cors_origins:
        raise ValueError(
            "CORS_ALLOW_CREDENTIALS=true is incompatible with a wildcard origin"
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=[m.strip() for m in settings.CORS_ALLOW_METHODS.split(",") if m.strip()],
        allow_headers=_build_cors_headers(settings.CORS_ALLOW_HEADERS),
    )
```

Also update the `middleware_cors_register_begin` log `allow_credentials` value to
`settings.CORS_ALLOW_CREDENTIALS`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest apps/backend/tests/test_cors_posture.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run config-posture regression**

Run: `python -m pytest apps/backend/tests/test_config_security_posture.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/main.py apps/backend/tests/test_cors_posture.py
git commit -m "fix(cors): respect CORS_ALLOW_CREDENTIALS, reject wildcard+credentials (#16)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 16: Spec-1b verification sweep

**Files:**
- Test: run all spec-1b tests together; no new code unless a gap is found.

- [ ] **Step 1: Run the full spec-1b test set**

Run:
```bash
python -m pytest \
  apps/backend/tests/test_edge_hardening_settings.py \
  apps/backend/tests/test_rate_limit_bucket.py \
  apps/backend/tests/test_rate_limit_policy.py \
  apps/backend/tests/test_edge_rate_limit_middleware.py \
  apps/backend/tests/test_tenant_rate_limit_middleware.py \
  apps/backend/tests/test_edge_hardening_pipeline.py \
  apps/backend/tests/test_webhook_canonical_url.py \
  apps/backend/tests/test_channel_webhook_signature_url.py \
  apps/backend/tests/test_voice_provider_signature_url.py \
  apps/backend/tests/test_production_readiness_webhook.py \
  apps/backend/tests/test_webhook_uniform_rejection.py \
  apps/backend/tests/test_auth_error_coarsening.py \
  apps/backend/tests/test_authority_context_coarsening.py \
  apps/backend/tests/test_voice_ws_caps.py \
  apps/backend/tests/test_cors_posture.py -v
```
Expected: all PASS.

- [ ] **Step 2: Run the security-posture + voice + webhook regression suites**

Run:
```bash
python -m pytest apps/backend/tests/ -k "authority or voice or webhook or channel or readiness or cors or posture" -v
```
Expected: all PASS (no regressions from coarsening or URL changes).

- [ ] **Step 3: Update the audit disposition note**

Edit `docs/audit/operious-full-repository-audit-2026-05-31.md` Top-100 table rows
#16, #23, #24, #25, #39, #40 to note "spec 1b implemented — code closed, pending
live proof (Phase 3)." Keep wording aligned with actual evidence (do not claim
live proof).

- [ ] **Step 4: Commit**

```bash
git add docs/audit/operious-full-repository-audit-2026-05-31.md
git commit -m "docs(audit): mark spec 1b edge-hardening findings code-closed

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** #39 → Tasks 1-6; #23 → Tasks 7-10; #24 → Task 11; #25 → Tasks 12-13; #40 → Task 14; #16 → Task 15. All six findings mapped.
- **Dependency injection:** every middleware takes its limiter/flags via constructor so tests use stubs without Redis; the real `TokenBucketLimiter` is wired only in `main.py`.
- **Backward compatibility:** auth coarsening and the webhook URL change are setting-gated (`coarsen_errors`/`COARSE_AUTH_ERRORS`, `WEBHOOK_TRUST_URL_HEADER`) so existing tests stay green; production posture turns them on.
- **Known follow-ups (NOT this spec):** real client-IP extraction behind trusted proxies beyond `scope["client"]` (depends on TRUSTED_PROXIES live config, Phase 3); frontend CSP/CSRF (#46-49, later spec); per-tenant broker QoS (#37, spec 1d).
- **Risk flagged in spec:** confirm the command-center frontend distinguishes auth states by status code, not body reason, before enabling `COARSE_AUTH_ERRORS` in prod — verify during Task 13 review.
