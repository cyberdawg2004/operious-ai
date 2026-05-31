# Spec 1b — Edge Hardening

- Date: 2026-06-01
- Status: Approved (design); pending implementation plan
- Phase: 1 (code-level hardening), spec 1b
- Audit findings closed: #16, #23, #24, #25, #39, #40
- Credentials required: none (fully unblocked)

## Purpose

Harden the externally reachable backend boundary so a single misconfigured or
hostile client cannot enumerate routes, spoof webhook signatures, read recon
detail from auth failures, flood the service, or hold voice sockets open
indefinitely. This is the perimeter slice of Phase 1.

## Current State

- Middleware pipeline (outer → inner):
  `RequestBodyLimit → CORS → RequestContext → TrustedIngress → AuthorityContext → Router`
  ([apps/backend/app/main.py:620-676](../../../apps/backend/app/main.py)).
- No inbound HTTP rate limiting exists. Every `rate_limit`/`429` reference in the
  backend is about *outbound* provider 429s, not inbound abuse control.
- Twilio signature verification trusts a **client-supplied** canonical URL header
  `x-operious-webhook-url` (`TWILIO_CANONICAL_URL_HEADER`) at
  [apps/backend/app/core/twilio_signature.py:78](../../../apps/backend/app/core/twilio_signature.py).
  Consumers: [voice.py:216](../../../apps/backend/app/api/v1/routers/voice.py) and
  [channel_webhooks.py:782](../../../apps/backend/app/boundary/adapters/channel_webhooks.py).
  The attacker controls the URL fed into the HMAC, weakening the check (#23).
- Auth failures return specific reasons (e.g. `header_authority_disabled`) to the
  client ([authority_context.py](../../../apps/backend/app/middleware/authority_context.py)) (#25).
- Webhook rejection paths can differ by cause, enabling route/tenant enumeration (#24).
- Voice WebSocket has byte/count frame caps but no wall-clock duration, idle, or
  frame-rate cap (#40).
- CORS is already fail-closed on wildcard ([main.py:113-118](../../../apps/backend/app/main.py));
  needs an explicit posture assertion (#16).
- `trusted_ingress.py:130` already extracts client IP against a trusted-proxy
  allowlist — reuse it for the IP rate-limit layer.
- No `PUBLIC_BASE_URL` setting exists yet.

## Goals

1. Inbound rate limiting: per-IP (pre-auth) and per-tenant/principal (post-auth),
   Redis-backed, with an explicit Redis-failure policy (never silent fail-open).
2. Webhook canonical URL derived server-side, not from a client header.
3. Uniform webhook rejection that does not leak route/tenant existence.
4. Auth errors coarsened externally; full reason logged server-side only.
5. Voice WebSocket wall-clock duration, idle, and frame-rate caps.
6. An explicit CORS production-posture test.

## Non-Goals

- Frontend CSP / CSRF / browser token storage (#46–49) — separate command-center spec.
- Outbound/provider rate limiting (already handled by circuit breaker / retry policy).
- Per-tenant broker/queue QoS (#37) — belongs to spec 1d (Resilience).
- Real voice providers / token issuance — Phase 2.

## Design

### Component 1 — Inbound rate limiting (#39)

Two middlewares, both backed by an atomic Redis token-bucket Lua script
(`capacity` + `refill_per_second`, evaluated server-side for concurrency safety).

- `EdgeRateLimitMiddleware` (per-IP, pre-auth): placed just inside
  `RequestContextMiddleware` and **outside** `AuthorityContextMiddleware`, so it
  throttles before auth work is done. Client IP is resolved via the existing
  trusted-proxy logic (never raw `X-Forwarded-For` unless behind trusted ingress).
  Key: `rl:ip:{ip}`.
- `TenantRateLimitMiddleware` (per-tenant + per-principal, post-auth): placed just
  inside `AuthorityContextMiddleware` (innermost), so identity is resolved. Keys:
  `rl:tenant:{tenant_id}` and `rl:principal:{principal_id}`.

On breach: `429 Too Many Requests` with a `Retry-After` header and a coarse body.

**Redis-failure policy (ties to #38, no silent fail-open):** decided by HTTP method.
- Non-idempotent / state-changing (`POST`/`PUT`/`PATCH`/`DELETE`) and any auth route:
  **fail-closed** → `503 Service Unavailable` + alert event (503 distinguishes an
  infra failure from a genuine rate breach, which is always `429`).
- Idempotent reads (`GET`/`HEAD`/`OPTIONS`): **fail-degraded** → allow + emit alert.

New settings (`Settings`), with generous starting defaults (tunable):
- `RATE_LIMIT_ENABLED: bool = True`
- `RATE_LIMIT_IP_PER_MINUTE: int = 120`, `RATE_LIMIT_IP_BURST: int = 40`
- `RATE_LIMIT_TENANT_PER_MINUTE: int = 600`, `RATE_LIMIT_TENANT_BURST: int = 200`
- `RATE_LIMIT_PRINCIPAL_PER_MINUTE: int = 300` (0 = disabled layer)
- Fail policy is method-derived (above), not a free setting, to avoid misconfig.

Exemptions: liveness/readiness probes are exempt by path allowlist so health checks
are never throttled.

### Component 2 — Server-derived webhook canonical URL (#23)

- Add `PUBLIC_BASE_URL: str` setting (scheme + host, no trailing slash). Required in
  production (added to `production_readiness` checks when any webhook channel that
  uses signature verification is enabled).
- Canonical URL = `PUBLIC_BASE_URL` + the matched request path (from
  `request.scope["path"]` / `raw_path`), with Twilio's param scheme preserved
  (form params for POST, sorted query for GET), reconstructed server-side.
- New helper `derive_canonical_webhook_url(settings, request_path, query)` in
  `twilio_signature.py` (or a small `webhook_url.py`).
- `verify_twilio_signature_from_headers` is replaced at both call sites
  ([voice.py:216](../../../apps/backend/app/api/v1/routers/voice.py),
  [channel_webhooks.py:782](../../../apps/backend/app/boundary/adapters/channel_webhooks.py))
  by the server-derived URL.
- The `x-operious-webhook-url` header is honored **only** when
  `WEBHOOK_TRUST_URL_HEADER: bool = False` is explicitly enabled (non-prod testing).
  `production_readiness` rejects boot if it is true in production.

### Component 3 — Uniform webhook rejection (#24)

- Unknown route, unknown/disabled tenant, missing secret, and signature mismatch all
  return an **identical** response: same status (`403`), same constant body, same
  headers. The specific cause is logged server-side with the correlation id only.
- Avoid a timing oracle: when the route/secret is unknown, still perform a dummy
  constant-time HMAC comparison before returning, so "route exists" and "route does
  not exist" are indistinguishable by timing as well as by content.

### Component 4 — Auth error coarsening (#25)

- External auth failures return a generic `401` with body `{"detail": "unauthorized"}`
  and a generic `WWW-Authenticate: Bearer` header.
- The precise internal reason (`header_authority_disabled`, expired, bad claim, etc.)
  is logged server-side with the request correlation id; the correlation id is
  returned in a response header so support can trace without leaking the reason.
- A single mapping table (`internal_reason → log_code`) keeps the external surface
  uniform across `AuthorityContextMiddleware` and the auth dependencies.

### Component 5 — Voice WebSocket duration / rate caps (#40)

In the voice stream loop ([voice.py](../../../apps/backend/app/api/v1/routers/voice.py)):
- `VOICE_MAX_CALL_SECONDS: int` — wall-clock max; close with WS code `1000`
  (normal closure) + reason on breach.
- `VOICE_IDLE_TIMEOUT_SECONDS: int` — close (`1000` + reason) if no inbound frame
  within the window.
- `VOICE_MAX_FRAMES_PER_SECOND: int` — per-connection rolling-second frame-rate cap;
  close with policy-violation code `1008` on breach.
These layer on top of the existing byte/count caps; existing caps are unchanged.

### Component 6 — CORS posture assertion (#16)

- Add `test_cors_posture` asserting: no wildcard origin while `allow_credentials` is
  true; methods/headers come from the configured allowlist; production posture is
  fail-closed. Tighten `_build_cors_headers` only if the test reveals a gap.

## Middleware Pipeline (after change)

```
RequestBodyLimit → CORS → RequestContext → EdgeRateLimit(IP)
  → TrustedIngress → AuthorityContext → TenantRateLimit(tenant/principal) → Router
```

## Testing Strategy (TDD — failing test first for each)

- `test_edge_rate_limit.py`: IP bucket exhaustion → 429 + Retry-After; tenant bucket
  exhaustion → 429; principal layer; health paths exempt; Redis-down on POST →
  fail-closed (503) + alert; Redis-down on GET → fail-degraded (allow) + alert.
- `test_webhook_canonical_url.py`: forged `x-operious-webhook-url` ignored;
  server-derived URL used; valid signature over server URL accepted; tampered URL
  rejected; `WEBHOOK_TRUST_URL_HEADER=true` (non-prod) honors header.
- `test_webhook_uniform_rejection.py`: unknown route, bad secret, unknown tenant,
  signature mismatch all produce identical status + body + headers.
- `test_auth_error_coarsening.py`: external body is generic; server log contains the
  precise reason + correlation id; correlation id header present.
- `test_voice_ws_caps.py`: over-duration close; idle-timeout close; frame-rate-cap
  close; under-limit traffic unaffected.
- `test_cors_posture.py`: production CORS posture assertions.
- `production_readiness` tests: `WEBHOOK_TRUST_URL_HEADER=true` in prod fails boot;
  webhook-signature channel enabled without `PUBLIC_BASE_URL` fails boot.

Run from repo root (per project convention) to avoid spurious collection failures.

## Rollout / Flags

- `RATE_LIMIT_ENABLED` defaults true; can be disabled for emergency rollback.
- `WEBHOOK_TRUST_URL_HEADER` defaults false; prod boot rejects true.
- `PUBLIC_BASE_URL` required in prod when signature-verified webhook channels are on.
- No data migration required.

## Risks

- Rate-limit thresholds too tight could throttle legitimate bursts → start with
  generous defaults, make them settings, document tuning.
- Client-IP trust depends on correct `TRUSTED_PROXIES`; reuse the existing
  trusted-ingress extraction so IP spoofing via `X-Forwarded-For` is not possible
  outside trusted proxies.
- Coarsening auth errors must not break the command-center's ability to distinguish
  "not logged in" from "forbidden" — verify the frontend only needs the status code,
  not the body reason.
