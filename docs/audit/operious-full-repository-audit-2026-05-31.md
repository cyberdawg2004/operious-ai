# Operious AI Full Repository Audit

Date: 2026-05-31
Current-state update: 2026-06-01, after edge-hardening tranche
Auditor: Codex static architecture/security review
Audited HEAD: `692003f` (`fix(cors): respect CORS_ALLOW_CREDENTIALS and CORS_ALLOW_METHODS config (#16)`)
Local uncommitted audit-relevant drift: backend tests align stale webhook assertions to uniform `webhook_rejected` and add handler-level voice frame-rate cap proof; `packages/types/src/session.ts` still carries the local session enum mirror.

## Executive Verdict

Operious today is a serious governed-operations platform prototype, not a production-ready enterprise operating system. The repository contains real architecture: FastAPI APIs, Postgres with RLS discipline, Celery workers, Redis-backed queues, deterministic execution identities, governance decision persistence, supervisor/QA surfaces, tenant configuration, webhook ingress, outbound dispatch, Auth0 integration, RAG/cognition, voice media paths, and a Next.js command center.

The current state is materially stronger than the original May 31 audit. Claude/Codex work after the baseline did not only touch the voice socket. It closed or materially remediated the core code-level security findings S-01 through S-09, and the latest edge-hardening commits also closed/downgraded several follow-on risks:

- Production header authority now fails closed by default.
- Auth0 custom claims are mapped with the expected namespace.
- Tenant config writes are capability-gated and split into domain capabilities.
- Tenant config self-approval is replaced by a durable propose/approve/reject/apply ledger.
- Voice WebSockets require signed session tokens and provider handshake signatures before accept.
- Pre-approved action decisions use durable actor-bound one-time grants with binding hashes and provider idempotency keys.
- Outbound webhook SSRF protection now validates, rejects private/internal addresses, disables redirects, and pins the connection to the validated IP.
- Tenant knowledge ingestion now has quarantine/review status, injection scanning, approved-only retrieval, and untrusted-context delimiters.
- Diagnostic LLM token-per-minute quota is enforced.
- Production boot/readiness and RLS coverage gates exist in code and CI.
- Server-derived canonical webhook/voice signature URLs replace trusting client-supplied URL headers.
- Per-IP pre-auth and per-tenant/principal post-auth fixed-window rate limiting is wired into the FastAPI pipeline.
- Voice load/capacity test harnesses were repaired for the new provider-signature contract.
- Recon-sensitive auth errors are coarsened in production, and voice max-duration / idle / frame-rate caps are enforced in the WebSocket route.

The blocking issue has shifted. It is no longer "there are no controls." The blocker is live proof and operational completeness. `S-10` remains open because Phase E deployment verification is not archived: no live proof yet that production rejects direct spoofed authority headers, enforces RLS under production roles, runs workers/DLQ correctly, and has real secrets/providers configured. New review caveats: the per-IP limiter may key the immediate Fly proxy peer unless real client IP handling is proven live, and Redis quota/admission outage policy remains scoped to spec 1d.

Final status: safer for controlled internal demo and tightly scoped non-regulated pilot. Still not safe for Anker/Samsung/Microsoft/Amazon production operations.

## Scope And Evidence

Repository traversal in the original audit found 2,437 discoverable files via `rg --files`.

Top-level inventory:

| Area | Count | Notes |
| --- | ---: | --- |
| `apps` | 2,249 | Backend, command center, marketing, duplicated legacy app trees |
| `packages` | 77 | TS shared/types/contracts/sdk/ui/auth/tracing/topology/observability |
| `docs` | 55 | Architecture, runbooks, readiness, prior audits |
| `frontend` | 28 | Older standalone marketing frontend |
| `tests-frontend` | 17 | Static frontend architecture tests |

Backend implementation inventory:

| Backend area | Files | Notes |
| --- | ---: | --- |
| `boundary` | 145 | Ingress/egress, adapters, voice, language, media |
| `coordination` | 98 | Topology, routing, policies |
| `_deprecated` | 82 | Retained old code; deployment ambiguity risk |
| `api` | 61 | FastAPI v1 routers |
| `organizational_intelligence` | 56 | Intelligence/learning subsystems |
| `hardening` | 55 | Metrics, alerts, operational hardening |
| `governance` | 52 | Policy chains, enforcement, decisions, capability runtime |
| `session` | 50 | Timeline/session lifecycle |
| `agents` | 43 | Runtime, tools, action governance |
| `arbitration` | 41 | Evaluators and records |
| `supervisor` | 37 | Supervisor inspections and projections |
| `services` | 30 | Tenant config, ingress, outbound, enrichment |
| `workers` | 17 | Celery tasks and recovery |
| `execution` | 17 | Durable execution authority |
| `knowledge` | 16 | Knowledge ingestion/retrieval/vector runtime |
| `tenant` | 15 | Tenant config runtime/persistence/credentials |

Evidence note: this audit reads the critical paths end to end: backend composition, auth/authority, RLS/session wiring, tenant config, governance, agent tool invocation, execution/worker flow, ingress/webhooks, voice, knowledge/RAG/cognition, frontend auth/API client, command center demo paths, deployment config, TODO/mock/stub markers, and readiness docs. It does not claim live Fly/Vercel production proof.

## Verification Update - Current State

Recent security-relevant commits reviewed:

| Commit | Current meaning |
| --- | --- |
| `c9a2712` | S-01/S-08: fail-closed edge trust boundary, verified bearer frontend default, namespaced Auth0 claims. |
| `8a7a7b1` | S-02: require tenant config write capability. |
| `b247167` | Early S-03 separation-of-duties gate. |
| `6454bb7` | S-04: signed voice session token, voice disabled by default, token/capacity tests. |
| `49ebd72` | Early S-05: payload binding for pre-approved decisions. |
| `cd8c6bc` | S-06: initial SSRF guard for tenant outbound dispatch. |
| `4cdf202` | S-09: token-per-minute quota enforcement. |
| `0a7f8af` | S-10/S-09 posture: fail-closed production readiness gate for stubs/secrets. |
| `ac24b5d` | CI, readiness CLI, RLS coverage invariant. |
| `7602507` | S-03: durable tenant config propose/approve/apply ledger with RLS. |
| `942b131` | S-05: durable action grants, actor binding, idempotency keys. |
| `4e6451c` | S-05: explicit test-only break-control proof for grant invariants. |
| `20a890a` | S-06: DNS-rebinding pin-to-IP outbound transport. |
| `42a9c5c` | S-07: RAG poisoning controls, quarantine, injection scan, delimiters. |
| `fe985fb` | S-02: split broad tenant admin into domain capabilities. |
| `4694d63` | S-04: voice provider handshake signature verification. |
| `78447d7` | Edge-hardening settings: inbound rate limits, public base URL, voice cap knobs, auth coarsening flag. |
| `69f740e` | Fixed-window Redis-backed rate limiter with 429/503 response helpers. |
| `96fb003` | Per-IP pre-auth edge rate-limit middleware. |
| `6ba3a99` | Per-tenant/principal post-auth rate-limit middleware. |
| `2878f4b` | Wires edge and tenant rate-limit middlewares into app composition. |
| `741b63c` | Server-side canonical webhook URL derivation helper. |
| `3de6a85` | Production-only fail-closed rate-limit behavior for non-idempotent methods when Redis is unavailable. |
| `a2960f5` | Twilio/channel webhook signatures verified against server-derived URL. |
| `175dd52` | Voice provider signatures verified against server-derived URL; stale load/capacity harnesses repaired. |
| `92f01b2` | Uniform webhook rejection for unknown route, tenant mismatch, missing signature, and bad signature. |
| `3f87cea` | Auth-error coarsening helper. |
| `e048f30` | Recon-sensitive authority errors coarsened in production. |
| `bc5e88b` | Voice WebSocket max-duration, idle-timeout, and frame-rate caps. |
| `692003f` | CORS credentials and methods follow configured posture. |

Focused verification evidence:

| Scope | Result |
| --- | --- |
| Header authority, Auth0 claim config, tenant RBAC, domain capabilities, direct-apply authorization | `28 passed in 5.40s` |
| Header authority subset | `15 passed in 2.70s` |
| SSRF guard, quota runtime, production readiness CLI/gate | `44 passed in 1.46s` |
| DB-backed tenant config ledger, action grants, RLS coverage invariant | `17 passed in 1.66s` |
| Voice signed-token and provider-signature auth tests | `13 passed in 2.13s` |
| Edge hardening settings, fixed-window limiter, fail policy, edge/tenant rate-limit middleware, app pipeline | `27 passed in 3.28s` |
| Webhook canonical URL, channel signature URL, voice signature URL, voice provider signature, voice load/capacity | `27 passed in 4.30s` |
| Production readiness plus webhook canonical URL readiness gates | `16 passed in 0.69s` |
| Spec 1b regression bundle after break-control restoration | `120 passed in 7.61s` |

Non-clean verification:

| Scope | Result | Interpretation |
| --- | --- | --- |
| Full combined audit suite | Timed out at 300s | Not counted as a pass. Smaller bundles above are used as proof. |
| Prior voice auth plus load/capacity bundle | Previously `5 failed, 16 passed` | This is now repaired by `175dd52`; the current focused voice/canonical/load bundle passed. |
| SSRF DNS-rebinding bundle in this sandbox | `4 failed, 52 passed, 1 skipped` | Failures were environmental: live DNS for `httpbin.org` and loopback binding. The DNS pinning tests are committed but should be made deterministic. |

Residual gaps update: S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08, and S-09 are no longer open original vulnerabilities. They are closed or closed-with-residuals as described below. S-10 remains open.

## Spec 1b Edge-Hardening Remediation (2026-06-01)

Phase 1, spec 1b (`docs/superpowers/specs/2026-06-01-edge-hardening-design.md`,
plan `docs/superpowers/plans/2026-06-01-edge-hardening.md`) closed the following
Top-100 findings **in code, with tests** (live production proof remains part of
Phase 3 / S-10):

| # | Finding | Disposition after spec 1b |
| ---: | --- | --- |
| 16 | CORS credential posture | Code-closed. CORS respects `CORS_ALLOW_CREDENTIALS` / `CORS_ALLOW_METHODS` instead of hardcoding `allow_credentials=True`; wildcard origins already rejected. |
| 23 | Twilio canonicalization should be server-derived | Code-closed. Webhook + voice provider signatures verify against a server-derived URL (`PUBLIC_BASE_URL` + path); client `x-operious-webhook-url` honoured only under non-prod `WEBHOOK_TRUST_URL_HEADER`, which prod boot rejects. |
| 24 | Route enumeration risk | Code-closed. Unknown route / tenant mismatch / missing or invalid signature all return an identical `401 webhook_rejected`. Residual: content oracle closed, timing oracle mitigated by rate limiting, full constant-time rejection deemed impractical given variable DB-lookup timing. |
| 25 | Auth error detail can aid recon | Code-closed. Recon-sensitive authority errors are coarsened in production; precise codes logged server-side only. |
| 39 | Edge rate limits incomplete | Code-closed. Per-IP (pre-auth) and per-tenant/principal (post-auth) fixed-window limiters; `429`+`Retry-After`; fail-closed for writes in production, degrade-open elsewhere (#38 partial). |
| 40 | WebSocket wall-clock/rate proof missing | Code-closed. Voice WebSocket enforces max-duration, idle timeout, and per-second frame-rate caps atop the existing byte/count caps. |

Also cleared during spec 1b: finding 63 (stale voice load/capacity harnesses now
model the full provider-signature handshake). Finding 38 (Redis fail policy) is
split by owner: rate-limiter portion closed in 1b; quota/admission portion owned by 1d.

Break-control proof for spec 1b was run with temporary production-code breaks,
restored immediately after each run. Post-proof production diff check:
`git diff -- apps/backend/app` was empty.

| Invariant | Temporary break | Proof command/result | Restored state |
| --- | --- | --- | --- |
| 1b-1 Rate limit enforced | Edge middleware ignored over-limit decisions. | `test_edge_rate_limit_middleware.py::test_allows_then_blocks_with_429` failed: over-limit request returned `200` instead of `429`. | Restored; included in final `120 passed`. |
| 1b-2 Uniform webhook rejection | `_uniform_webhook_rejection` returned internal reasons. | `test_webhook_uniform_rejection.py::test_all_rejection_reasons_share_one_response` failed: codes split into route/mismatch/signature causes. | Restored; included in final `120 passed`. |
| 1b-3 Server-derived canonical URL | Channel webhook verifier trusted `x-operious-webhook-url` again. | `test_channel_webhook_signature_url.py::test_signature_over_forged_url_rejected` failed: forged URL signature was accepted. | Restored; included in final `120 passed`. |
| 1b-4 Voice WS caps | Frame-rate guard returned without enforcing the cap. | `test_voice_ws_caps.py::test_over_rate_stream_is_closed_and_call_terminated` failed: stream closed normally with `1000` instead of policy `1008`. | Restored; included in final `120 passed`. |

Edge-hardening review update: #16, #23, #24, #25, #39, #40, and #63 are now materially closed in code/tests. #38 remains split as above rather than reopened or dropped.

## What Operious Is Today

Operious is currently a governed customer-operations substrate with:

- Backend API: FastAPI application at `apps/backend/app/main.py`.
- Persistence: Postgres/SQLAlchemy migrations with tenant RLS and owner-session maintenance paths.
- Async execution: Celery workers, Redis broker/result backend, queue admission, DLQ/recovery tasks.
- Governance: policy chain/evaluation/enforcement/persistence with fail-closed central decisions.
- Agent runtime: deterministic diagnostic agent, governed tool invoker, durable action grants.
- RAG/cognition: tenant knowledge documents, review status, vector records, Anthropic diagnostic completion when configured.
- Command center: Next.js/Auth0 frontend for sessions, queues, operations, traces, approvals, channel settings.
- Marketing site: Next.js marketing app with enterprise positioning.
- Docs/runbooks: architecture plans, deployment/rollback/secret rotation, SLO, pilot readiness.

What is implemented:

- RLS migrations and session tenant context.
- Auth0 JWKS verifier and namespaced role/capability mapping.
- Production header authority fail-closed default and command-center verified-bearer default.
- Tenant config mutation capability gates and domain capability split.
- Durable tenant config change-request ledger with propose/list/approve/reject/apply APIs, DB-level proposer/approver separation, operational events, and FORCE RLS.
- Direct tenant config mutation disabled in production and disabled by default outside production unless explicitly opted in.
- Signed voice session tokens, voice feature flag, provider handshake signature verification, and frame byte/count/duration/idle/rate caps.
- Voice and channel webhook provider signatures are now checked against a server-derived canonical URL (`PUBLIC_BASE_URL` + request path/query), not a client-controlled URL header.
- Durable pre-approved action grants bound to exact actor/tenant/tool/action/target/payload hash, with `consumed_at`, `consumed_by`, and idempotency key.
- Outbound webhook SSRF validation, redirect blocking, and pin-to-IP transport.
- Fixed-window inbound rate limiting: per-IP pre-auth and per-tenant/principal post-auth, with 429 responses and production 503 fail-closed behavior for non-idempotent requests when Redis is unavailable.
- Production coarsening for recon-sensitive authority failures.
- Token-per-minute quota accounting/enforcement for diagnostic LLM usage.
- RAG quarantine/review status, injection scanner, approved-only retrieval, and untrusted knowledge delimiters.
- Production boot-readiness validation for provider stubs and security-critical secrets.
- CI workflow, production readiness CLI gate, and RLS coverage invariant.
- Tenant-scoped API dependencies.
- Celery process groups, routes, retries, late acks, visibility timeout.
- Execution state machine, claims, attempts, outbox, recovery.
- Webhook signature routing for configured channel routes.
- Audit export HMAC verification path.
- Supervisor, arbitration, QA, operational event records.
- Anthropic translation provider when configured.
- Marketing proof pages and command-center channel settings UI with typed credential forms for nine channel types.

What is partial:

- Production proof remains missing: trusted proxy/Auth0/RLS/worker/DLQ/secrets checks are not archived.
- Voice auth/cap controls are closed, but production token issuance UX/API and real STT/TTS provider proof remain incomplete.
- Action grants are much stronger, but real external connector side effects still need provider idempotency and connector tests.
- Quotas include diagnostic token-per-minute enforcement and inbound request rate limiting; idempotent reads still degrade open when Redis is unavailable, per-IP limiting may key the Fly proxy peer, and quota is not a universal enterprise budget system.
- RAG poisoning controls exist, but human review UX, adversarial evals, and source-trust workflows remain immature.
- Observability exists, but production alert/health/readiness checks are not live-proven.
- Marketing/command-center proof improved materially, but public external validation, compliance proof, status/SLA pages, and some demo residue remain.

What is mocked/stubbed:

- Voice STT/TTS paths still rely on stub-like providers unless production providers are configured.
- Action tools for refunds/replacements/warranty/warehouse remain stub or prepared-result integrations.
- Shopify enrichment can fall back to deterministic stub behavior.
- Translation defaults/fallbacks can behave as identity outside configured production posture.
- Knowledge embeddings can use deterministic/test providers outside production provider config.
- Command center still contains proof/demo-oriented data.

What is planned/missing:

- Phase E live production verification for S-10.
- Real production STT/TTS and call initiation/token issuance flow.
- Real external action integrations and idempotency contracts with providers.
- Command-center workflow for the tenant config change-request ledger.
- Real-client-IP proof or proxy-aware configuration for per-IP rate limiting on Fly.
- Live proof of outbound connector allowlists/private-IP blocking in production.
- Quota observability and fail-closed/degraded policy for Redis outages.
- Production readiness verification for Fly health, workers, DLQ, RLS, secrets, Auth0 operator capability.
- SOC 2/compliance artifacts, retention/deletion workflows, public SLA/status proof.

## Service Map

| Service | Role | Runtime dependencies | Current status |
| --- | --- | --- | --- |
| Backend API | Authority, orchestration, tenant APIs, governance, sessions | Postgres, Redis, Auth0 JWKS, Sentry, Anthropic/OpenAI optional | Stronger security controls; production proof pending |
| Celery workers | Diagnostic execution, supervisor, QA, SOP intelligence, maintenance, outbound | Redis, Postgres, Anthropic optional | Real topology; live worker/DLQ proof pending |
| Command Center | Operator UI | Auth0, backend API | Real UI with typed channel settings; ledger workflow/demo residue remains |
| Marketing app | Public website | Vercel/Next | Improved proof surface; claims must stay aligned with live proof |
| Postgres | Tenant data, RLS, audit, execution, knowledge | App role and owner role discipline | Strong design; prod RLS proof missing |
| Redis | Broker, queue depth, quotas, nonce/cache, inbound rate limits | Celery, runtime services | Real; writes fail closed on production rate-limit backend loss, reads still degrade open |
| Auth0 | Browser/user identity | Next middleware, backend JWKS | Namespaced mapping present; live token proof missing |
| External channels | Webhooks, Jira/Linear dispatch | Tenant credentials, SSRF guard | Guarded generic outbound; real connector proof pending |
| Translation | Boundary localization | Identity or Anthropic provider | Real Anthropic path when configured |
| Voice | WebSocket media path | Voice runtime, signed session token, provider signature | Auth control closed; provider/issuance/load test maturity pending |

## Execution Map

HTTP request:

`client -> RequestBodyLimit -> CORS -> RequestContext -> EdgeRateLimit -> optional TrustedIngress -> AuthorityContext -> TenantRateLimit -> router -> service -> runtime -> repository -> Postgres/RLS`

Current answer: the original production header-spoofing path is closed by default in code, and inbound rate limiting now runs both before and after authority resolution. Remaining risk is operational: live trusted proxy ranges, Auth0 settings, override flags, Redis availability, and whether the per-IP key reflects the real client or only the Fly proxy peer.

Webhook:

`channel webhook -> route secret resolver -> signature check -> tenant context -> boundary normalization -> session/dispatch/execution`

Current answer: Twilio-style provider signatures now derive the canonical URL server-side from `PUBLIC_BASE_URL` and request path, instead of trusting a client-supplied URL header. Generic outbound dispatch is SSRF-guarded and redirect-blocked.

Diagnostic execution:

`dispatch -> governance admission token -> execution record/outbox -> Celery queue -> worker claim -> cognition snapshot -> approved-only RAG retrieval -> LLM/deterministic fallback -> quota usage record -> governance persistence -> timeline/resolution proposal`

Current answer: RAG poisoning and token quota are materially improved, but live provider/readiness proof remains required.

Action tool:

`agent request -> ToolInvoker -> capability/constraint checks -> governance evaluation or pre-approved decision -> durable grant -> exact actor/payload/binding consumption -> tool invoke -> envelope`

Current answer: old cross-payload replay is closed. Real irreversible provider side effects still require connector idempotency and production tests.

Voice:

`WebSocket /voice/{session_id}/stream?token=... -> signed token verification -> provider auth token lookup -> provider signature verification -> capacity counter -> runtime.start_call`

Current answer: old `?tenant=` spoof path is closed, provider signature URL spoofing is closed in code/tests, and load/capacity harnesses now model the valid handshake. Remaining work is production token issuance, real provider paths, and runtime enforcement of the newly added wall-clock/idle/frame-rate cap settings.

## Data Flow Map

Customer event data enters through batch ingest, channel webhook, conversation, or voice. It is normalized at the boundary, written to session/timeline/coordination records under tenant context, admitted into execution, processed by diagnostic cognition and governance, then projected to resolution/supervisor/arbitration/QA and surfaced in the command center. Knowledge documents now pass through review status and approved-only retrieval before RAG context reaches diagnostic prompts.

Sensitive data classes remain:

- Customer ticket content and conversation history.
- Knowledge documents/SOPs.
- LLM prompts/completions and retrieved citations.
- Tenant channel credentials and webhook secrets.
- Governance policy parameters, action grants, and execution decisions.
- Operational trace/audit records.

## Scope Alignment Scorecard

| Subsystem | Prior score | Current score | Status | Rationale |
| --- | ---: | ---: | --- | --- |
| Governance layer | 72 | 80 | Partial | Durable config ledger, action grants, domain capabilities, and RAG review status improve governance; live proof/workflow maturity still missing. |
| Agent layer | 50 | 63 | Partial | Pre-approved action replay is now durably actor/payload-bound; real side-effect connectors remain incomplete. |
| Supervisor layer | 60 | 60 | Partial | Supervisor/QA records exist; still more observability than hard production control. |
| Execution layer | 62 | 65 | Partial | Durable execution/claims/outbox/recovery are real; action-grant persistence improves replay. |
| Knowledge layer | 50 | 64 | Partial | Quarantine/review, injection scan, approved-only retrieval, and delimiters close the original poisoning path; review UX/evals remain. |
| Audit layer | 68 | 70 | Partial | Better grant/ledger evidence and boot checks; live secret/rotation proof still missing. |
| Compliance layer | 35 | 35 | Missing/partial | SOC 2, retention, DSAR, legal hold, and key management proof remain incomplete. |
| Human escalation layer | 58 | 66 | Partial | Tenant config dual-control ledger exists; command-center workflow and expiry/revocation remain. |
| Intelligence layer | 52 | 62 | Partial | Anthropic paths, TPM quota, and RAG controls improved; provider/quality proof remains. |
| Auth/RBAC | 57 | 70 | Partial | Header authority, Auth0 namespaced mapping, and domain config capabilities are improved; live proof, auth-error coarsening, and object RBAC remain. |
| Tenancy | 76 | 80 | Partial | RLS discipline plus header/voice fixes improve isolation; production proof remains. |
| Observability | 58 | 58 | Partial | Logs/metrics/alerts exist; live operator and compliance proof incomplete. |
| Reliability | 55 | 61 | Partial | Boot gates, CI, durable grants/ledger, repaired voice load harnesses, and rate-limit fail policy help; live worker/DLQ/full-suite proof remains incomplete. |
| Scalability | 49 | 53 | Partial | Queue topology, token quota, and inbound rate limiting help; no meaningful live load/scale proof and per-IP proxy semantics remain unproven. |
| Enterprise readiness | 43 | 50 | Not ready | Security improved sharply and edge hardening helps, but S-10, compliance, integrations, and live proof cap readiness. |

## Security Audit Summary

### S-01: Production Header Authority Spoofing - CLOSED, Live Proof Pending

Original finding: production could accept spoofable legacy `X-Tenant-ID` / `X-Principal-ID` authority headers if deployed without trusted ingress.

Current evidence:

- `apps/backend/app/core/config.py:415-424` disables legacy header authority by default in production.
- `apps/backend/app/middleware/authority_context.py:221-226` rejects legacy identity headers with `401 header_authority_disabled`.
- `apps/backend/app/main.py:762-768` wires trusted proxies from settings into app composition.
- `apps/backend/fly.toml` sets production posture and trusted proxy assumptions.
- `apps/command-center2/frontend/lib/api-client.ts` defaults to `verified-bearer`.
- Tests: `test_authority_header_disabled.py`, `test_main_legacy_header_disabled.py`, `test_config_security_posture.py`.

Status: closed in code and tests by `c9a2712`. Live production ingress proof is still part of S-10.

Prior attack path is no longer valid by default:

1. Attacker sends direct backend request.
2. Stamps `X-Tenant-ID: victim-tenant`.
3. Avoids bearer auth.
4. Calls tenant-scoped route.

Current residual: only operational override/misconfiguration can reopen it.

### S-02: Tenant Config Write RBAC - CLOSED

Original finding: tenant config mutation routes only required tenant scope plus a principal.

Current evidence:

- `apps/backend/app/api/v1/routers/tenant.py:90-116` defines capability dependencies for config write/apply.
- `apps/backend/app/api/v1/routers/tenant.py:671-684` enforces domain capability for change requests.
- `apps/backend/app/auth/providers/jwt.py:78-112` maps Auth0 roles/permissions to domain capabilities.
- `apps/backend/app/dependencies/authority.py:112-150` defines domain write and approve capabilities.
- Tests: `test_tenant_rbac_dependency.py`, `test_domain_capabilities.py`.

Status: closed by `8a7a7b1` and strengthened by `fe985fb`.

Residual: live Auth0 role assignment proof and object-level RBAC are still needed for enterprise readiness.

### S-03: Production Self-Approval - CLOSED, Workflow Residuals

Original finding: `TenantConfigurationService` could internally create approved records with `reviewed_by=proposed_by`.

Current evidence:

- `apps/backend/app/core/config.py:434-442` disables direct self-approval in production.
- `apps/backend/app/api/v1/routers/tenant.py:126-240` exposes propose/list/approve/reject/apply endpoints.
- `apps/backend/app/services/tenant_config_change_request_service.py:117-124` rejects same proposer/approver.
- Migration `0063_tenant_config_change_requests` enforces `approved_by != proposed_by` and FORCE RLS.
- Tests: `test_tenant_config_apply_authorization.py`, `test_tenant_config_change_requests.py`.

Status: closed by `7602507`.

Residual: add separate `applied_by`, expiry/revocation, command-center workflow, and live Auth0 writer/approver proof.

### S-04: Voice WebSocket Authentication - CLOSED For Auth, Test Harness Residual

Original finding: voice stream accepted tenant identity from `?tenant=...`.

Current evidence:

- `apps/backend/app/api/v1/routers/voice.py:51-69` requires `VOICE_ENABLED` and signed session token before accept.
- `apps/backend/app/api/v1/routers/voice.py:71-80` requires tenant voice provider auth token and provider signature.
- `apps/backend/app/api/v1/routers/voice.py:215-260` derives the signature URL server-side from `PUBLIC_BASE_URL`, request path, and query string unless `WEBHOOK_TRUST_URL_HEADER` is explicitly enabled.
- `apps/backend/app/core/twilio_signature.py:38-55` verifies Twilio-style signatures with constant-time comparison.
- `apps/backend/app/services/voice_provider_auth.py:19-48` loads provider auth token from tenant channel credentials.
- Tests: `test_voice_session_token.py`, `test_voice_provider_signature.py`, `test_voice_provider_signature_url.py`, repaired `test_voice_capacity.py`, and `test_voice_load.py`.

Status: original unauthenticated/spoofable voice path is closed by `6454bb7`, `4694d63`, and strengthened by `175dd52`. The prior stale load/capacity harness issue is closed.

Residual: production token issuance and real STT/TTS provider proof are still needed. New settings for wall-clock, idle timeout, and frame rate are present but not yet enforced in the voice route.

### S-05: Replayable Decisions - CLOSED

Original finding: `ToolInvoker` pre-approved path validated UUID, same tenant, and persisted ALLOW only; another request could replay that allow decision.

Current evidence:

- `apps/backend/app/agents/tools/grants.py:36-49` persists grant actor, payload hash, binding hash, idempotency key, consumption fields.
- `apps/backend/app/agents/tools/grants.py:97-103` atomically consumes a grant only when `consumed_at IS NULL`.
- `apps/backend/app/agents/tools/grants.py:262-291` enforces actor mismatch and already-consumed failure.
- `apps/backend/app/agents/tools/invoker.py:263-356` requires binding hash, durable repo, actor match, unconsumed grant, and provider idempotency key.
- Migration `0064_agent_action_grants` adds RLS and uniqueness.
- Tests: `test_action_grant_durability.py`, `test_tool_governance_mandatory.py`.

Status: closed by `942b131`; explicit break-control proof in `4e6451c`.

Residual: real provider connectors still need idempotency and side-effect tests before high-value actions.

### S-06: Outbound Webhook SSRF - CLOSED For Generic Outbound Dispatch

Original finding: tenant-configured outbound URLs were posted directly without scheme/domain/private-IP guardrails.

Current evidence:

- `apps/backend/app/core/ssrf.py:173-233` validates HTTPS, host allowlist, DNS results, blocked IP classes, and selected pinned IP.
- `apps/backend/app/core/ssrf.py:49-120` implements pinned-IP transport that dials the validated IP while preserving host/SNI.
- `apps/backend/app/boundary/outbound/adapter.py:81-107` validates before dispatch, uses pinned transport, and disables redirects.
- Tests: `test_ssrf_guard.py`, `test_ssrf_dns_rebinding.py`.

Status: closed by `cd8c6bc` and `20a890a`.

Residual: DNS-rebinding tests should be made deterministic in CI; live egress proof remains part of S-10/Phase E.

### S-07: RAG Poisoning Through Tenant Knowledge Writes - CLOSED For Original Path

Original finding: approved knowledge could flow into active retrieval without quarantine/reviewer workflow or injection controls.

Current evidence:

- Migration `0065_knowledge_review_status` adds review status defaulting new documents to `quarantined`.
- `apps/backend/app/knowledge/runtime.py:94-115` scans and records knowledge review metadata on indexing.
- `apps/backend/app/knowledge/runtime.py:386-425` fails closed to quarantine on scanner error or flagged content.
- `apps/backend/app/knowledge/persistence/postgres.py:133-141` retrieves only active approved documents.
- `apps/backend/app/cognition/diagnostic_runtime.py:95-99` treats retrieved SOPs as untrusted reference data.
- `apps/backend/app/cognition/diagnostic_runtime.py:1007-1030` delimits chunks and carries citation metadata.
- Tests: `test_knowledge_poisoning_controls.py`.

Status: closed by `42a9c5c` for the audited tenant-knowledge write-to-retrieval path.

Residual: prompt injection is not "solved" universally; reviewer UX, evals, and source trust policy remain needed.

### S-08: Auth0 Tenant Claim Mapping - CLOSED, Live Token Proof Pending

Original finding: Auth0 provider customized only roles and risked missing namespaced tenant/org/environment claims.

Current evidence:

- `apps/backend/app/core/config.py:124-130` configures Auth0 namespace.
- `apps/backend/app/main.py:733-753` maps namespaced tenant, org, env, capabilities, and roles.
- Frontend defaults to verified-bearer authority.
- Tests: `test_config_security_posture.py`.

Status: closed in code by `c9a2712`.

Residual: live Auth0 tenant token fixture/contract proof still needed.

### S-09: Token Quota Enforcement - CLOSED For Diagnostic LLM

Original finding: token quota settings existed but were not enforced.

Current evidence:

- `apps/backend/app/agents/runtime/quota_runtime.py:139-156` blocks calls after token-minute budget is exhausted.
- `apps/backend/app/agents/runtime/quota_runtime.py:253-282` records post-call token usage.
- `apps/backend/app/cognition/diagnostic_runtime.py:261-309` checks quota before LLM calls and records real completion usage.
- Tests: `test_quota_runtime.py`, `test_diagnostic_agent_quota_integration.py`.

Status: closed by `4cdf202` for diagnostic LLM usage.

Residual: Redis outage still fails open by design; enterprise-wide provider budgets remain needed.

### S-10: Production Readiness - OPEN

Current evidence:

- `apps/backend/app/core/production_readiness.py:39-105` collects and raises on production readiness problems.
- `apps/backend/app/main.py:468-473` invokes readiness validation when enforced.
- `apps/backend/scripts/check_production_readiness.py` exposes release-gate CLI.
- `.github/workflows/ci.yml` runs backend/frontend and DB-backed checks.
- `test_rls_coverage_invariant.py` requires tenant tables with RLS to force RLS.
- Tests: `test_production_readiness.py`, `test_check_production_readiness_script.py`, `test_rls_coverage_invariant.py`.
- Production-readiness rejection for `WEBHOOK_TRUST_URL_HEADER=true` and missing `PUBLIC_BASE_URL` is covered by `test_production_readiness_webhook.py`; the readiness bundle passed `16` tests.

Status: open. The boot gate is committed, but live production verification is not done.

Required to close:

- Live direct spoofed authority-header rejection.
- Live bearer/Auth0 success path with namespaced claims.
- Live production-role RLS tenant isolation.
- Live workers and DLQ smoke/replay proof.
- Live secrets/provider/readiness CLI output.
- Rollback evidence.

## Edge-Hardening Review

Claude's latest committed tranche materially improves the edge posture:

- #23 webhook/voice canonical URL spoofing: closed in production code and tests. `derive_canonical_webhook_url` builds URLs from `PUBLIC_BASE_URL` plus trusted path/query, channel webhook signatures pass `request_path`, and voice provider signatures now ignore forged canonical URL headers unless `WEBHOOK_TRUST_URL_HEADER` is explicitly enabled for non-production testing.
- #39 inbound rate limiting: closed at code/test level. `EdgeRateLimitMiddleware` runs pre-auth by IP, `TenantRateLimitMiddleware` runs post-auth by tenant/principal, and `main.py` registers both in the request pipeline.
- #38 Redis backend-loss policy: split by owner. Rate-limiter production writes fail closed in 1b; quota/admission fail-closed/degraded Redis policy is explicitly owned by 1d.
- #63 stale voice load/capacity harnesses: closed. The fake WebSocket harnesses now include signed session token, provider auth loader, server-derived signature URL, and provider signature headers.
- #25 auth-error coarsening: closed at code/test level for recon-sensitive authority failures in production.
- #40 voice wall-clock, idle, and frame-rate caps: closed at code/test level in the voice WebSocket route.

Remaining edge-hardening gaps:

- Per-IP rate limiting may be per Fly proxy, not per real internet client, because the middleware keys `scope["client"]` and the Fly deployment comments say the app observes the proxy as an `fdaa::/16` peer. This still provides a coarse abuse brake, but live proxy/client-IP semantics must be proven before claiming true per-client edge rate limiting.
- Quota/admission Redis outage policy is not dropped; it is deferred to spec 1d (Resilience), which owns the broader #38 quota/admission policy.

## Multi-Tenancy Audit

Could tenant A ever see tenant B data?

Current answer: materially less likely than before, but still not proven impossible in production. The original direct-header spoof path is closed by default, Auth0 namespaced tenant claims are mapped, RLS discipline exists, and voice no longer trusts raw `?tenant=...`. Remaining risk sits in live deployment posture: trusted proxy range, Auth0 claim drift, production RLS proof, owner-session misuse, and any future route bypassing tenant dependencies.

Could tenant A affect tenant B execution?

Current answer: not through normal execution runtime when authority and RLS are correct. Residual risk comes from production authority/RLS misconfiguration, privileged maintenance paths, or shared queue/noisy-neighbor behavior. Broker isolation is not per tenant.

Could tenant A affect tenant B governance?

Current answer: not through the original tenant-scope-only mutation path. Tenant policy/config mutation now requires domain write capability and independent approve/apply flow. Residual risk is Auth0 role drift, over-broad tenant roles, or UI/workflow bypasses.

Tenant isolation strengths:

- RLS migrations and FORCE RLS intent.
- ContextVar tenant setting per DB transaction.
- `expected_tenant_id` checks are widespread.
- Production header authority fails closed by default.
- Voice tenant binding uses signed session tokens and provider signatures.
- Tenant config mutation is capability-gated and ledgered.

Tenant isolation weaknesses:

- S-10 live production proof is still missing.
- Owner sessions bypass RLS and are used by maintenance tasks.
- Command center still has local/non-production header mode support.
- Some tenant-wide read surfaces lack object-level RBAC.
- No per-tenant broker isolation.

## Governance Audit

Can governance be skipped?

Current answer: much less than before for tenant config and action replay. Tenant config now has durable proposal, approval, rejection, and apply states with principal separation. Action grants are actor/payload-bound and consumed durably. Remaining gaps are UI workflow adoption, separate `applied_by`, expiry/revocation, live Auth0 proof, and provider-side idempotency for real irreversible actions.

Can execution happen without authorization?

Diagnostic execution still expects governance admission. Voice call execution now requires signed token plus provider signature. Pre-approved action execution now requires a matching durable one-time grant. Remaining risk is deployment misconfiguration and future connector paths.

Can stale policies be used?

Yes, bounded but real. Worker comments accept policy staleness during in-flight diagnostic tasks. Policy version binding and cache invalidation remain important for high-value production operations.

Can evidence be tampered with?

Evidence is stronger than before. Config change requests and action grants create durable replayable evidence. Residual gaps include no separate applier identity, no expiry/revocation, and missing live secret/rotation proof.

Can replay become inaccurate?

Yes, but less than before. Action grant replay is now precise. RAG replay can still drift unless exact chunk hashes/content snapshots are bound to decisions. Knowledge activation now has review status but needs stronger production review workflow.

## Agent Safety Audit

Can an agent exceed its authority?

Less easily than before. The prior cross-payload replay weakness is closed. Remaining risk is over-broad tenant capabilities, poisoned or poorly reviewed knowledge, stale policies, or connecting real external side effects before provider idempotency and connector tests exist.

Can an agent trigger unintended actions?

Today most action tools are stub/prepared-result paths. Once connected to real systems, yes, unless grants remain bound to exact actor/payload/resource, provider idempotency is enforced, and external actions are ledgered.

Can an agent leak information?

Potentially through tenant-wide read surfaces, prompt/audit storage, or RAG retrieval if tenant RBAC is too broad. Cross-tenant leakage primarily depends on authority/RLS failure.

Can agents manipulate each other?

No direct multi-agent peer manipulation path was identified. Topology/governance configuration can change routing and evaluation behavior, now gated by ledger/capabilities.

Can supervisors fail open?

Supervisor/QA remain mostly evaluative. The risk is that supervisor findings do not block all downstream effects unless every caller treats them as hard gates.

## Database Audit

Strengths:

- Postgres is treated as source of truth.
- Many tenant tables have RLS policy migrations.
- Tenant context is installed on transaction begin.
- Owner sessions are explicitly privileged.
- Execution transitions, config requests, action grants, cognition usage, and audit records are durable.
- RLS coverage invariant now exists.

Risks:

- Production FORCE RLS proof is not archived.
- Owner-session misuse would bypass RLS.
- Some model/schema nullability drift can still exist.
- Retention/archival/legal hold strategy is incomplete.
- Knowledge/vector query-plan proof at production scale is missing.

## Performance Audit

10x scale:

- Backend likely survives if Postgres/Redis are healthy and workers are scaled manually.
- Diagnostic workers and provider quotas remain bottlenecks.
- Token quota helps cost blast radius.
- Inbound fixed-window rate limiting now adds a basic abuse brake.

100x scale:

- Queue backlog, worker concurrency, DB pool limits, Redis availability, and provider rate limits dominate.
- Voice load/capacity harnesses now pass under the provider-signature contract, but real provider/media load remains unproven.
- Tenant-wide dashboards need pagination/index proof under production volume.
- If Fly exposes only the proxy peer to the app, the per-IP limiter may throttle proxy-wide traffic rather than individual abusive clients.

1000x scale:

- Current architecture needs per-tenant QoS/sharding strategy, autoscaling, broker isolation or strict QoS, vector index strategy, cost budget enforcement, and operational SLO proof.

Failure points:

1. S-10 deployment misconfiguration.
2. Provider quota/cost during diagnostic load.
3. Queue backlog and worker saturation.
4. Redis unavailable causing idempotent/read traffic to degrade open and write traffic to fail closed under rate-limit policy.
5. Postgres connection/pool pressure.
6. Operator trust damage from demo/stub residue.

## Reliability Audit

Strengths:

- Celery uses JSON serializers, late acks, visibility timeout, prefetch multiplier 1.
- Distinct queues exist for diagnostic, supervisor, QA, SOP, maintenance, voice.
- Execution claim recovery and outbox reconciliation exist.
- DLQ records and replay paths exist.
- Provider circuit breaker exists.
- Boot/readiness gate and CI reduce accidental demo/stub deployments.
- Config ledger and action grants improve durable recovery/replay.

Risks:

- Production worker process verification is not archived.
- Voice load/capacity test suite has been repaired after the auth gate.
- Some periodic tasks intentionally do not DLQ.
- Queue admission/quota can fail open on Redis read failure; inbound write rate limits now fail closed in production when their Redis backend is unavailable.
- No disaster recovery/backup restore evidence was found in active gates.
- Real external action side effects are not integrated, so reliability claims are unproven.
- Rate limiting itself is now a Redis dependency; idempotent traffic degrades open on rate-limit backend loss.

## Observability Audit

Strengths:

- Structured logging, request context, metrics collector, alert evaluator, operational events, traces, queue snapshots, DLQ views.
- Cognition usage/audit persistence records prompt/completion/cost metadata.
- Audit export signing exists.
- Action grants and config ledger add better forensic material.

Gaps:

- Production alerting and health gates are not live-proven.
- Executive health visibility is not yet a verified status/SLO artifact.
- Audit export secret injection/rotation proof is still part of S-10.
- Sensitive prompt/completion retention and access controls need formal policy.

## Code Quality Audit

Strengths:

- Strong domain modeling and protocols.
- Clear separation of runtime/persistence/router in many areas.
- Good use of deterministic IDs and expected tenant checks.
- Tests are extensive around the new controls.
- Security-critical paths now have stronger local invariants.

Debt:

- `_deprecated` code and duplicate app trees create deployment ambiguity.
- Multiple runtime compositions use in-memory/deterministic defaults outside production gates.
- Tenant config workflow still needs UI adoption, expiry/revocation, and separate `applied_by`.
- Voice load/capacity test harnesses lag the new auth contract.
- Command center demo/proof constants remain in active product code.
- Some abstractions are ahead of real integrations, increasing false confidence.

## Testing Audit

Known current proof:

- Header authority and Auth0 claim posture passed.
- Tenant config RBAC and direct-apply denial passed.
- Domain capabilities passed.
- Tenant config change-request lifecycle and RLS passed.
- Durable action grant consumption and RLS passed.
- SSRF guard, quota runtime, production readiness passed.
- Voice signed token and provider signature passed.
- Voice signature URL spoofing and repaired voice load/capacity harnesses passed.
- Edge/tenant rate-limit middleware and app pipeline tests passed.
- Channel webhook canonical URL signature tests passed.
- RAG poisoning controls exist and are covered by targeted tests.

Untested or insufficiently proven:

- Live production Auth0 token claim mapping and role assignment.
- Production trusted ingress behavior and direct spoof rejection.
- Production FORCE RLS query proof.
- Production worker/DLQ/health checks.
- Live production SSRF/egress proof.
- Voice wall-clock, idle-timeout, and frames-per-second cap enforcement.
- Auth-error coarsening behavior; settings exist but middleware responses remain detailed.
- Real provider STT/TTS/action integration behavior.
- Quota behavior under production Redis outage policy.

## Website And Command Center Update

Claude's committed frontend work materially improved the public proof surface:

- New public proof routes for security, integrations, implementation, alternatives, role pages, and insights.
- Homepage includes execution trace, improved pilot proof, ROI methodology, stronger CTA language, and broader navigation.
- Command center labels improved from explicit proof-set language toward pilot language.
- Channel settings gained typed credential forms.

Residual website/product trust gaps:

- No named customer references, public status page, public SLA, subprocessor page, downloadable verified security packet, completed SOC 2, or public pen-test proof.
- Some claims remain too absolute for S-10-open status.
- Demo/proof residue remains in command-center/product code.

## Enterprise Readiness

| Customer class | Readiness | Prior score | Current score | Verdict |
| --- | --- | ---: | ---: | --- |
| Internal demo | Ready with caveats | n/a | 80 | Good if demo/stub boundaries are disclosed. |
| Scoped non-regulated pilot | Conditional | n/a | 66 | Stronger after edge hardening, but still requires pilot-environment spoof/RLS/worker/secrets checks and risky integrations disabled. |
| $100k customer | Conditional pilot | 58 | 62 | More plausible after Phase B plus edge hardening, but still needs live proof. |
| $500k customer | Not ready | 43 | 47 | Procurement/security gaps remain large. |
| $1M customer | Not ready | 34 | 36 | Needs live production proof, compliance, real integrations, DR/SLO proof. |
| Fortune 500 | Not ready | 25 | 27 | Below expected security/compliance/change-control bar. |
| Regulated enterprise | Not ready | 20 | 20 | Missing formal controls, retention, legal hold, and audit/legal evidence. |

## Red Team Review

Most likely breach paths now:

1. Production ingress/Auth0 misconfiguration or override reopens header authority.
2. S-10 gaps: RLS/worker/DLQ/secrets not actually correct in deployed environment.
3. Real refund/replacement/warehouse connector connected before provider idempotency and action side-effect tests.
4. Voice enabled before production token issuance, real STT/TTS provider proof, and runtime wall-clock/idle/rate caps are enforced.
5. Rate-limit per-IP assumptions wrong in production, causing proxy-wide throttling rather than true abusive-client throttling.
6. RAG poisoning through approved-but-poorly-reviewed knowledge despite baseline quarantine controls.
7. XSS in command center leading to token/localStorage authority theft.
8. Compromised integration webhook route flooding queues/nonces; rate limits now reduce but do not eliminate this risk.

Most catastrophic failures:

- Cross-tenant data exposure through trusted-ingress/Auth0/RLS production misconfiguration.
- Privileged policy/config change causing automated wrong decisions if ledger roles drift.
- Real external action connected before side-effect idempotency and approval proof.
- Audit replay cannot prove production state because S-10 evidence was not archived.

Highest business risks:

- Enterprise procurement discovers S-10 live proof is missing.
- Pilot customer sees demo/stub/proof residue.
- Governance brand promise outruns current workflow/compliance evidence.
- A single auth/RLS misconfiguration becomes a cross-tenant incident.

## Top 100 Findings - Current Disposition

| # | Severity | Category | Current disposition | Recommended next action |
| ---: | --- | --- | --- | --- |
| 1 | Closed/High residual | Auth | S-01 closed in code; live proof pending under S-10 | Archive direct spoof rejection and bearer success proof |
| 2 | Medium | Deployment | Fly/prod posture improved; proxy/secrets proof pending | Verify `TRUSTED_PROXIES`, secrets, health, RLS, workers |
| 3 | Closed/Medium residual | Frontend | Command center defaults to verified bearer | Fail production if tenant-header mode is configured |
| 4 | Closed/Medium residual | RBAC | S-02 closed; domain capabilities added | Verify live Auth0 roles and add object RBAC |
| 5 | Partial | Governance | S-03 core closed; apply actor/expiry/UI residuals | Add `applied_by`, expiry/revocation, UI workflow |
| 6 | Closed/High residual | Voice | S-04 auth closed; load harness repaired; provider/issuance/cap-runtime maturity remains | Prove issuance/STT/TTS and enforce wall-clock/idle/rate caps |
| 7 | Closed/Medium residual | Agent | S-05 replay closed by durable grants | Add real provider idempotency tests |
| 8 | Closed/Medium residual | SSRF | S-06 closed for generic outbound | Make DNS tests deterministic and archive egress proof |
| 9 | Closed/High residual | RAG | S-07 original path closed | Add reviewer UX, evals, source trust policy |
| 10 | Closed/Medium residual | Auth0 | S-08 code closed | Add live token contract fixture |
| 11 | Closed/Medium residual | Quota | S-09 diagnostic TPM closed | Add reservations/outage policy/provider-wide budgets |
| 12 | Open/High | Readiness | S-10 open | Complete Phase E live verification |
| 13 | High | Voice | Real STT/TTS provider proof missing | Integrate/prove providers or keep voice disabled |
| 14 | High | Actions | Refund/replacement/warranty tools stub-like | Implement connectors with idempotency/governance |
| 15 | High | Governance | Tenant-specific policy residue risk remains | Move hardcoded proof policies to tenant data |
| 16 | Closed/Low residual | CORS/Auth | CORS credential posture respects config and is tested | Keep posture test in CI |
| 17 | Medium | Secrets | Boot gate checks audit secret; live proof missing | Set, rotate, verify secret in Phase E |
| 18 | High | RLS | Production FORCE RLS proof missing | Run and archive prod proof query |
| 19 | High | Workers | Worker health proof missing | Verify all process groups and alerts |
| 20 | Medium | Channel | Credentials are gated; connector proof incomplete | Channel-specific admin/approval/live proof |
| 21 | Medium | Topology | Ledger-gated; live workflow proof missing | Verify topology flow in CI/live |
| 22 | Medium | Policy | Ledger exists; expiry/revocation missing | Add expiry/revocation and policy roles |
| 23 | Closed/Medium residual | Webhook | Twilio/voice canonical URLs are server-derived in code/tests | Commit/readiness-gate `PUBLIC_BASE_URL`; archive live provider proof |
| 24 | Closed/Medium residual | Webhook | Uniform `401 webhook_rejected` closes content oracle; timing oracle mitigated by rate limiting | Do not pursue constant-time DB lookups; keep rate limits live |
| 25 | Closed/Low residual | Auth | Recon-sensitive authority errors are coarsened in production | Keep coarsening tests in CI |
| 26 | High | Tenant | Tenant-wide read surfaces lack object RBAC | Add roles/scopes by object/domain |
| 27 | High | Audit | LLM prompts/completions are sensitive | Encrypt/redact/retain by policy |
| 28 | Closed/Medium residual | Prompt/RAG | Baseline injection controls added | Add adversarial evals and policy tuning |
| 29 | High | Cognition | Citations not universally required | Require citations for prod tenants |
| 30 | High | RAG | Deterministic embeddings may still be used outside prod | Real embedding provider and evals |
| 31 | Medium | Provider | Boot gate helps; provider health proof missing | Provider health checks and override governance |
| 32 | High | Deployment | Container/SBOM hardening incomplete | Add image scanning, pinned digest, SBOM |
| 33 | Medium | Supply chain | CI exists; security scans incomplete | Add dependency review, SBOM, license audit |
| 34 | High | Local secrets | Local `.env` hygiene risk | Keep gitignore and secret scanners |
| 35 | High | Owner DB | Owner sessions bypass RLS | Separate creds, lint owner usage |
| 36 | Closed/Medium residual | Migrations | RLS coverage invariant added | Keep invariant in CI and prove prod RLS |
| 37 | High | Queue | Broker not isolated per tenant | Add per-tenant QoS/priority/rate limits |
| 38 | Partial/Deferred to 1d | Admission | Rate-limiter portion closed in 1b; quota/admission Redis policy owned by 1d | Implement fail-closed/degraded quota+admission policy in Resilience |
| 39 | Closed/Medium residual | Rate limit | Per-IP and tenant/principal rate limits are wired and tested | Prove real-client-IP behavior behind Fly/proxy |
| 40 | Closed/Low residual | WebSocket | Voice frame byte/count plus wall-clock/idle/rate caps are enforced and tested | Keep handler-level cap proof in CI |
| 41 | Medium | UX/Product | Demo proof sessions remain | Remove/isolate proof sessions |
| 42 | Medium | Business | Claims can outrun live proof | Align claims to S-10 status |
| 43 | Medium | Docs | Readiness source of truth must be canonical | Make Phase E checklist blocking |
| 44 | Medium | Codebase | `_deprecated` active tree retained | Remove or hard-isolate |
| 45 | Medium | Codebase | Duplicate app histories remain | Declare active apps and archive old ones |
| 46 | Medium | Frontend | Browser token exposure/XSS blast radius | Harden CSP/BFF option |
| 47 | Medium | Frontend | Local storage authority labels risk confusion | Store display state only |
| 48 | Medium | CSRF | Cookie-auth token route deserves review | POST + CSRF or BFF proxy |
| 49 | Medium | CSP | CSP review incomplete | Add CSP/reporting |
| 50 | Medium | Webhook | Tenant context reset discipline should be audited | Use scoped context managers |
| 51 | Medium | Webhook | Semantic circuit advisory/fail-open risk | Make response mode configurable |
| 52 | Medium | Nonce | Nonce cleanup maintenance dependency | TTL/index/alert on growth |
| 53 | Closed/Low residual | Outbound | Redirects disabled in generic adapter | Keep invariant tests |
| 54 | Medium | Credentials | Credential master key proof pending | Verify injection and rotation |
| 55 | Medium | Encryption | KMS/envelope proof missing | Use KMS/envelope encryption |
| 56 | Medium | Retention | Retention/archival incomplete | Add retention/purge jobs |
| 57 | Medium | DR | Backup/restore proof absent | Run restore drills |
| 58 | Medium | Observability | Alert tasks best-effort | Alert on evaluator failure |
| 59 | Medium | Metrics | Beat/queue observability gaps remain | Track beat health |
| 60 | Closed/Low residual | Testing | CI exists | Add artifact attestations/security gates |
| 61 | Medium | Testing | Live Auth0 contract missing | Archive real token fixture |
| 62 | Closed/Low residual | Testing | SSRF tests exist | Add live egress proof |
| 63 | Closed/Low residual | Testing | Voice auth and load/capacity harnesses now pass with provider-signature contract | Keep load/capacity tests in CI; add real provider load proof |
| 64 | Closed/Medium residual | Testing | Dual-control tests now exist | Keep in CI and add UI workflow tests |
| 65 | Medium | DB | ORM nullability drift risk remains | Align ORM with migrations |
| 66 | Medium | DB | Knowledge query plan unproven | Explain/analyze and indexes |
| 67 | Medium | DB | Large JSON metadata can become hot blobs | Promote indexed fields |
| 68 | Medium | DB | Tenant partitioning deferred | Partition when volume warrants |
| 69 | Medium | Execution | In-flight tasks can use stale policies | Policy version binding |
| 70 | Medium | Execution | Completion event sink can fail open | Dead-letter failed event emission |
| 71 | Medium | Execution | External side effects not fully modeled | Outbox per external provider |
| 72 | Medium | Action | Stubs can be mistaken for integrations | Feature flags and clear labels |
| 73 | Medium | Shopify | Enrichment fallback risk remains | Fail explicit in prod |
| 74 | Low | Translation | Anthropic provider exists; fallback policy remains | Provider health and failure policy |
| 75 | Medium | Governance | In-memory capability paths may remain | Persist all prod decisions |
| 76 | Medium | Governance | Deferred enforcement queue maturity | Durable escalation/approval queue |
| 77 | Medium | Governance | Policy invalidation partial | Central policy version/cache invalidation |
| 78 | Medium | Governance | Content safety policy defaults need review | Require explicit prod policy |
| 79 | Medium | Governance | Tenant allowlist/default ambiguity | Make defaults explicit/tested |
| 80 | Medium | API | Observability endpoints tenant-wide | Role-gate observability |
| 81 | Medium | API | Audit verify public CPU/body budget | Rate-limit verify |
| 82 | Medium | API | Batch ingest capability/quotas incomplete | Add ingest capability and quotas |
| 83 | Medium | API | Conversation append ownership checks | Session ownership/capability checks |
| 84 | Medium | UI | Dashboard proof metrics vs operator workflow | Replace with SLA/risk/action metrics |
| 85 | Medium | UI | API base URL misconfig risk | Fail build without prod API URL |
| 86 | Medium | UI | No generated API client contract | Generate from OpenAPI |
| 87 | Medium | Packages | Shared auth package placeholder risk | Mature or remove |
| 88 | Medium | License | License/SBOM review missing | License audit/SBOM |
| 89 | Medium | Dependency | Runtime image/package hardening incomplete | Multi-stage/minimal runtime |
| 90 | Medium | Dependency | Unused provider deps increase surface | Prune unused deps |
| 91 | Low | Docs | Architecture docs can be aspirational | Add status per feature |
| 92 | Low | Docs | Multiple audits can drift | Maintain single risk register |
| 93 | Low | Docs | Migration head expectations can drift | Update readiness docs |
| 94 | Low | Code | Pilot comments in active paths | Convert to tracked issues |
| 95 | Low | Code | Abstractions ahead of integrations | Collapse unused abstractions later |
| 96 | Low | Config | Prod boot gate exists; overrides remain | Restrict overrides and monitor |
| 97 | Low | Perf | Command center polling fixed | SSE/WebSocket/adaptive polling |
| 98 | Low | Perf | Knowledge ingest synchronous risk | Queue indexing job |
| 99 | Low | Perf | Body limits need endpoint tuning | Endpoint-specific limits |
| 100 | Low | Product | Public SLA/status/cert proof absent | Publish SLA/status/security packet |

## Final Scores

| Dimension | Prior score | Current score |
| --- | ---: | ---: |
| Architecture | 62 | 67 |
| Security | 57 | 76 |
| Scalability | 49 | 53 |
| Reliability | 55 | 61 |
| Governance | 72 | 81 |
| Code quality | 68 | 71 |
| Enterprise readiness | 43 | 50 |

## Customer Survival Verdict

Could Operious survive 10 customers?

Yes, only as a controlled pilot platform with verified bearer auth, production readiness gate enabled, risky features disabled, live tenant isolation checks archived, and manual monitoring.

Could Operious survive 100 customers?

Not safely today. Queue, provider, tenancy, support, compliance, and production verification gaps would surface quickly.

Could Operious survive 1,000 customers?

No. The architecture has promising primitives but lacks hard operational, compliance, scaling, and isolation guarantees.

Would I allow Anker production operations?

No, not production. I would allow a scoped pilot after Phase E-style environment checks and with no real irreversible refund/replacement side effects.

Would I allow Samsung production operations?

No. Enterprise change control, compliance evidence, and integration hardening remain below bar.

Would I allow Microsoft production operations?

No. Auth/RBAC code improved, but live proof, supply chain, audit, and compliance posture remain below bar.

Would I allow Amazon production operations?

No. Scale, abuse resistance, isolation proof, and operational rigor are not close enough yet.
