# Operious AI Full Repository Audit

Date: 2026-05-31
Current-state update: 2026-06-05, after Phase 1/2 governed-connector, onboarding, work-order, commerce-action-stub, and real-embedding review
Auditor: Codex static architecture/security review
Audited HEAD: `eb74b55` (`security(2.x): commerce action tools fail closed in production (no fake-success stubs)`)
Embedding update note: the follow-on real-embeddings B work wires `build_embedding_provider()` into live knowledge composition, fixes native pgvector search at one 1536-dimensional HNSW column, adds a dry-run-first re-embed job for the Anker knowledge set, and proves the path with mocked OpenAI HTTP plus DB-backed retrieval tests. Production still needs the careful snapshot -> migrate -> re-embed -> retrieval-confirm rollout.

## Executive Verdict

Operious today is a serious governed-operations platform prototype, not a production-ready enterprise operating system. The repository contains real architecture: FastAPI APIs, Postgres with RLS discipline, Celery workers, Redis-backed queues, deterministic execution identities, governance decision persistence, supervisor/QA surfaces, tenant configuration, webhook ingress, outbound dispatch, Auth0 integration, RAG/cognition, voice media paths, and a Next.js command center.

The current state is materially stronger than the original May 31 audit. Claude/Codex follow-on work after the baseline did not only touch the voice socket. It closed or materially remediated the core code-level security findings S-01 through S-09, and the Phase 1/2 governed-operations work also closed/downgraded several follow-on risks:

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
- Most recon-sensitive authority-state errors are coarsened in production, and voice max-duration / idle / frame-rate caps are enforced in the WebSocket route.
- Observability and audit-export endpoints now have domain read/export capability gates, and principal-bound conversation sessions now enforce owner access.
- Object RBAC was broadened across sensitive tenant-scoped router modules, with structural and functional tests.
- Tenant config apply now persists `applied_by`, and approved-but-not-applied change requests can be revoked through service/API paths.
- Data protection now exists as production code: envelope encryption for sensitive customer content, DSAR dual-control crypto-shred, legal holds, retention policy API, purge behavior, and DB constraints.
- Redis-dependent quota and queue-admission paths now fail closed for pre-call/publish admission, durable webhook ingress capture happens before processing admission, execution governance versions are bound to execution records, worker completion-event failures are dead-lettered, and per-tenant queue QoS exists.
- The deleted `_deprecated` package is now absent and guarded by invariant tests. Container/supply-chain posture improved through digest-pinned images, non-root backend runtime, SBOM artifact generation, and `pip-audit`.
- Customer-facing resolution drafts now pass through grounding-aware generation and central communication governance; ungrounded factual claims are denied/escalated rather than sent as confident free text.
- Connector side effects now have a real substrate: connector invocation idempotency ledger, governed generic REST connector base, tenant connector configs, provider idempotency headers, SSRF pinning, credential redaction, and a refund/repair dispatch path.
- Tenant action governance is now per-tenant and policy-backed through the same change-request ledger; connector configuration and action policy onboarding are dual-control and reconstruction-bound.
- Platform tenant creation is split from tenant configuration: `platform.tenant.admin` creates inert tenant anchors, while Command Center onboarding configures channels/connectors/action policy through tenant-scoped Phase B change requests.
- Work-order dispatch now has a tenant-scoped ledger, explicit state machine, reconstruction fields, idempotent repair dispatch, and receipt-only fulfillment callbacks that advance only after tenant-reported status is consumed.
- Unconfigured commerce actions now have a fail-closed tool path for the worker runtime: production derives `ALLOW_STUB_ACTIONS=false` by default, and the diagnostic worker passes that setting into the tenant action registry. However, the manager action-approval service factory still omits the setting and therefore can still build fake-success stubs through the registry default. This is a real residual, not a documentation nit.
- S-10 is still open, but live-verification tooling now exists for spoof rejection, RLS probes, worker/DLQ proof, smoke traces, and legacy Anker knowledge rewrap.

The blocking issue has shifted again. It is no longer "there are no controls" or "there are no side-effect ledgers." The blocker is live proof, operational completeness, provider maturity, and one remaining commerce-action DI gap. `S-10` remains open because Phase E deployment verification is not archived: no live proof yet that production rejects direct spoofed authority headers, enforces RLS under production roles, runs workers/DLQ correctly, and has real secrets/providers configured. Remaining review caveats: auth-error coarsening is not yet wired to every malformed authority parse path, the per-IP limiter may key the immediate Fly proxy peer unless real client IP handling is proven live, data-protection controls need KMS/retention/legal-operation proof before compliance claims, the action-approval service must pass `settings.allow_stub_actions_effective` into `build_tenant_action_tool_registry`, and the new connector side-effect path is code/test-proven but not live-provider-proven.

Final status: safer for controlled internal demo and a tightly scoped non-regulated pilot with irreversible actions constrained. Still not safe to call enterprise-production-ready for Anker/Samsung/Microsoft/Amazon operations until S-10 live evidence, the manager-approval stub DI gap, real provider drills, and compliance evidence are closed.

## Scope And Evidence

Repository traversal now finds 2,500 discoverable files via `rg --files`.

Top-level inventory:

| Area | Count | Notes |
| --- | ---: | --- |
| `apps` | 2,302 | Backend, command center, platform console, marketing, duplicated legacy app trees |
| `packages` | 77 | TS shared/types/contracts/sdk/ui/auth/tracing/topology/observability |
| `docs` | 61 | Architecture, runbooks, readiness, prior audits |
| `frontend` | 28 | Older standalone marketing frontend |
| `tests-frontend` | 21 | Static frontend architecture tests |

Backend implementation inventory:

| Backend area | Files | Notes |
| --- | ---: | --- |
| `boundary` | 148 | Ingress/egress, adapters, voice, language, media, fulfillment callback normalization |
| `coordination` | 98 | Topology, routing, policies |
| `_deprecated` | 0 active | Deleted by `7731f5a`; invariant tests prevent recreation/imports |
| `api` | 63 | FastAPI v1 routers |
| `organizational_intelligence` | 56 | Intelligence/learning subsystems |
| `hardening` | 55 | Metrics, alerts, operational hardening |
| `governance` | 52 | Policy chains, enforcement, decisions, capability runtime |
| `session` | 50 | Timeline/session lifecycle |
| `agents` | 51 | Runtime, tools, action governance, connector invocation ledger |
| `arbitration` | 41 | Evaluators and records |
| `supervisor` | 37 | Supervisor inspections and projections |
| `services` | 35 | Tenant config, lifecycle, ingress, outbound, enrichment, fulfillment receipt |
| `runtime` | 26 | Resolution governance, grounding, conversation generation |
| `workers` | 18 | Celery tasks, recovery, S-10 probe tasks |
| `execution` | 17 | Durable execution authority |
| `knowledge` | 17 | Knowledge ingestion/retrieval/vector runtime |
| `tenant` | 17 | Tenant config runtime/persistence/credentials/lifecycle |
| `work_orders` | 12 | Work-order dispatch ledger, state machine, fulfillment consumer |

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
| `5d2168a` | Production readiness requires `PUBLIC_BASE_URL` and rejects `WEBHOOK_TRUST_URL_HEADER=true`. |
| `92f01b2` | Uniform webhook rejection for unknown route, tenant mismatch, missing signature, and bad signature. |
| `3f87cea` | Auth-error coarsening helper. |
| `e048f30` | Recon-sensitive authority-state errors coarsened in production. |
| `bc5e88b` | Voice WebSocket max-duration, idle-timeout, and frame-rate caps. |
| `692003f` | CORS credentials and methods follow configured posture. |
| `4aeea67` | Rate-limit production default and pinned middleware/settings tests updated. |
| `01600a7` | Adds `tenant.observability.read` and `tenant.audit.export` domain capabilities and Auth0 mappings. |
| `3ed75b9` | Gates all observability routes on `tenant.observability.read`. |
| `12fff9d` | Gates audit export on `tenant.audit.export` and adds a 256 KiB verify body cap. |
| `f8268f1` | Enforces principal ownership for principal-bound conversation sessions. |
| `8549492` | Adds migration 0066 for tenant-config `applied_by`, `REVOKED`, `revoked_by`, and `revoked_at`. |
| `e1eed47` | Adds tenant-config ledger record/ORM fields for `applied_by`, `REVOKED`, `revoked_by`, and `revoked_at`. |
| `df78ac7` | Tenant-config ledger `apply()` records `applied_by`; `revoke()` service path added. |
| `d917d0e` | Tenant-config ledger schema/API exposes applied/revoked fields and `/revoke`. |
| `7aa2507` | HTTP-level tests prove conversation router ownership wiring. |
| `9d842d3` | Object RBAC sweep across sensitive read/write surfaces and action approval SoD. |
| `a9d9d4c` | Break-control tests prove functional RBAC gates fail when removed. |
| `dd3e7be` | Data-protection FK semantics repaired: legal hold/erasure restrict tenant deletion; data keys/retention cascade. |
| `2335756` | Resilience tranche: fail-closed Redis policy for quota/admission, durable ingress capture, policy version binding, completion-event DLQ, per-tenant queue QoS. |
| `9db40f0` | Data-protection admin API: DSAR dual-control erasure, legal hold, retention management. |
| `7731f5a` | Deletes `_deprecated`, removes rewrite scripts, pins runtime images, adds SBOM/pip-audit CI artifacts, fixes type-map errors, and adds deterministic DNS-rebinding tests. |
| `229c2f4` | Phase 2.0: knowledge span provenance with char offsets through retrieval/citation/audit paths. |
| `8a78721` | Security dependency bump: PyJWT 2.13.0 for PYSEC-2026-175/177/178/179. |
| `19ac6f0` | Phase 2.1: governed conversational layer with grounded EN/AR replies, grounding-as-governance, and escalation handoff. |
| `04457ae` | Phase 2.1: translation provider config dependency fixed. |
| `dc285bd` | Phase 2.2: connector invocation idempotency ledger with exactly-once replay semantics and FORCE RLS. |
| `61cc62b` | Phase 2.3: per-tenant refund connector framework, SSRF-guarded generic REST connector base, queryable credential-free config. |
| `19fb37b` | S-10 prep: legacy ciphertext rewrap job and live verification probes. |
| `22adb81` | Redis health/pubsub retry quota burn reduced. |
| `2208f6a` | Fly pilot worker process groups right-sized. |
| `0315122` | Phase 2.4: per-tenant action governance from tenant action policy records. |
| `cfa7110` | Phase 2.5a: connector-config and action-policy onboarding via dual-control change-request ledger, write-only credentials, reconstruction binding. |
| `4d87f11` | Phase 2.5b: credential-free connector-config read APIs, capability-gated and tenant-isolated. |
| `27326aa` | Phase 2.5a fix: change-request tenant IDs use canonical string identity; FORCE RLS reasserted. |
| `6b4f67f` | Security dependency bump: aiohttp 3.14.0 for CVE-2026-34993/47265. |
| `d4cc1a9` | Phase 2.5a fix: change-request list/detail gated on `tenant.config.read`; read does not grant write/approve. |
| `898598d` | Phase 2.5c: platform-gated tenant creation, inert-on-create, audited lifecycle event, platform/tenant capability split. |
| `a5beaea` | Phase 2.5d: Platform Console scaffold. |
| `35d8c7d` / `5505257` | Platform Console owns tenant creation; Command Center onboarding is tenant-config only. |
| `221e848` | Phase 2.3.x-a: work-order dispatch ledger, explicit state machine, reconstruction-bound, FORCE RLS. |
| `ed25dbc` | Phase 2.3.x-b: `repair.dispatch` outbound action, governed fail-closed, connector-config-backed, idempotent reserve-before-dispatch. |
| `46347f4` / `106f28a` | Phase 2.3.x-c: inbound work-order fulfillment callbacks record ingress only; tenant-scoped consumer advances awaiting fulfillment to terminal states idempotently. |
| `eb74b55` | Commerce action stubs now fail closed when `allow_stub_actions=False`; production settings derive that default and the diagnostic worker passes it. Residual: action-approval service DI still omits the flag and can use the registry default. |

Focused verification evidence:

| Scope | Result |
| --- | --- |
| Header authority, Auth0 claim config, tenant RBAC, domain capabilities, direct-apply authorization | `28 passed in 5.40s` |
| Header authority subset | `15 passed in 2.70s` |
| SSRF guard, quota runtime, production readiness CLI/gate | `44 passed in 1.46s` |
| DB-backed tenant config ledger, action grants, RLS coverage invariant | Earlier `17 passed in 1.66s`; newer DB-backed proof below covers the repaired apply/revoke/data-protection paths |
| Voice signed-token and provider-signature auth tests | `13 passed in 2.13s` |
| Edge hardening settings, fixed-window limiter, fail policy, edge/tenant rate-limit middleware, app pipeline | `27 passed in 3.28s` |
| Webhook canonical URL, channel signature URL, voice signature URL, voice provider signature, voice load/capacity | `27 passed in 4.30s` |
| Production readiness plus webhook canonical URL readiness gates | `16 passed in 0.69s` |
| Spec 1b regression bundle after break-control restoration | `120 passed in 7.61s` |
| Auth coarsening helper, authority-state coarsening, voice WS caps, domain authz, conversation ownership | `32 passed in 4.66s` |
| CORS posture plus production readiness/readiness-webhook checks | `20 passed in 3.99s` |
| Ledger unit/revocation, queue admission, quota runtime, production readiness, legacy deletion, dependency manifest | `45 passed in 4.08s` |
| Object RBAC sweep | User rerun: `13 passed in 25.90s` |
| Auth/domain/coarsening/conversation bundle | User rerun: `57 passed in 7.82s`; split proof: auth coarsening `7 passed in 0.19s`, domain capabilities `39 passed in 3.63s`, conversation ownership `11 passed in 7.02s` |
| DB-backed tenant config ledger, data-protection controls/admin API, completion-event DLQ, execution-governance hardening | User rerun: `42 passed in 6.32s` |
| Phase 2 governance/domain/Auth0/resolution/config-router bundle | User normal-shell rerun: `112 passed, 10 skipped in 8.85s` |
| Work-order dispatch substrate | User normal-shell rerun: `6 passed in 0.69s` |
| Commerce action fail-closed tool and setting derivation | Codex rerun: `4 passed in 0.63s` |
| Real OpenAI embedding provider/runtime proof | Codex rerun: `25 passed in 2.35s`; user normal-shell DB proof: combined retrieval/re-embed/FORCE-RLS bundle `8 passed in 1.06s`, retrieval file `6 passed in 0.87s`, FORCE-RLS invariant `1 passed in 0.13s` |
| Frontend architecture/onboarding/platform-console invariants | `npm run test:frontend`: `105 passed in 0.74s` after sandbox IPC restriction was bypassed with approval |
| Per-tenant action governance | Codex rerun: `4 passed in 0.69s` |
| Resolution grounding/conversation proposal unit bundle | Codex rerun: `36 passed, 2 skipped in 1.06s` |
| Connector framework non-DB/socket-gated bundle | Codex rerun: `3 passed, 3 skipped`; skips were DB gating and sandbox loopback bind limits |

Non-clean verification:

| Scope | Result | Interpretation |
| --- | --- | --- |
| Full combined audit suite | Timed out at 300s | Not counted as a pass. Smaller bundles above are used as proof. |
| Prior voice auth plus load/capacity bundle | Previously `5 failed, 16 passed` | This is now repaired by `175dd52`; the current focused voice/canonical/load bundle passed. |
| Codex sandbox rerun of object-RBAC/app HTTP tests | Timed out entering `TestClient` lifespan | Not reproduced by user's normal-shell run (`13 passed`, `57 passed`). Likely local Redis/lifespan startup behavior; not counted as a code failure. |
| Codex sandbox rerun of DB bundle | Timed out after an early error marker | Superseded by user's exact normal-shell rerun (`42 passed`). Not counted as a code failure. |
| SSRF DNS-rebinding bundle in this sandbox | `3 failed, 2 passed` | Failures were sandbox loopback binding (`could not bind on 127.0.0.1:0`). The test file is now deterministic, but loopback-server cases still need normal-shell/CI proof before being claimed as locally green here. |
| Frontend invariant tests in sandbox | Failed before tests: `tsx` could not create `/tmp/tsx-1000/*.pipe` | Reran outside sandbox with approval; real result was `105 passed`. |
| Codex sandbox DB runs for connector/work-order files | Timed out after early pytest error marker, no traceback flushed before `timeout` | Not counted as a code failure; normal-shell proof is used where provided. Connector invocation ledger, repair dispatch, fulfillment callback, tenant lifecycle, S-10 prep, and tenant config DB bundle still need normal-shell proof unless supplied separately. |
| Commerce action fail-closed DI coverage | Focused tests pass for the tool/registry/setting, but static review found one production DI call omitting the setting | `apps/backend/app/dependencies/services.py:839-844` calls `build_tenant_action_tool_registry()` without `allow_stub_actions=settings.allow_stub_actions_effective`, while `ActionApprovalService.approve()` re-invokes approved actions through that factory. This keeps #14/#72 partial. |
| Codex sandbox DB run for embedding proof bundle | Timed out after an early marker, no traceback flushed before `timeout` | Superseded by the user's exact normal-shell rerun: combined retrieval/re-embed/FORCE-RLS bundle `8 passed in 1.06s`. |

Residual gaps update: S-01 through S-09 are no longer open original vulnerabilities. They are closed or closed-with-residuals as described below. The previous tenant-config `applied_by` regression is fixed and proven by current DB-backed tests. Phase 2 adds real side-effect and onboarding controls, but S-10 remains open until live deployment evidence is archived. The latest commerce-action hardening is directionally correct but not fully closed until the action-approval service factory is wired to the same fail-closed setting as the diagnostic worker.

## Spec 1b Edge-Hardening Remediation (2026-06-01)

Phase 1, spec 1b (`docs/superpowers/specs/2026-06-01-edge-hardening-design.md`,
plan `docs/superpowers/plans/2026-06-01-edge-hardening.md`) closed or
downgraded the following Top-100 findings **in code, with tests** (live
production proof remains part of Phase 3 / S-10):

| # | Finding | Disposition after spec 1b |
| ---: | --- | --- |
| 16 | CORS credential posture | Code-closed. CORS respects `CORS_ALLOW_CREDENTIALS` / `CORS_ALLOW_METHODS` instead of hardcoding `allow_credentials=True`; wildcard origins already rejected. |
| 23 | Twilio canonicalization should be server-derived | Code-closed. Webhook + voice provider signatures verify against a server-derived URL (`PUBLIC_BASE_URL` + path); client `x-operious-webhook-url` honoured only under non-prod `WEBHOOK_TRUST_URL_HEADER`, which prod boot rejects. |
| 24 | Route enumeration risk | Code-closed. Unknown route / tenant mismatch / missing or invalid signature all return an identical `401 webhook_rejected`. Residual: content oracle closed, timing oracle mitigated by rate limiting, full constant-time rejection deemed impractical given variable DB-lookup timing. |
| 25 | Auth error detail can aid recon | Partial. Authority-state errors such as disabled header authority and verification unavailable are coarsened in production, but malformed `Authorization` and malformed legacy authority headers still return detailed `reason` / `header` / `field` bodies. |
| 39 | Edge rate limits incomplete | Code-closed. Per-IP (pre-auth) and per-tenant/principal (post-auth) fixed-window limiters; `429`+`Retry-After`; fail-closed for writes in production, degrade-open elsewhere (#38 partial). |
| 40 | WebSocket wall-clock/rate proof missing | Code-closed. Voice WebSocket enforces max-duration, idle timeout, and per-second frame-rate caps atop the existing byte/count caps. |

Also cleared during spec 1b: finding 63 (stale voice load/capacity harnesses now
model the full provider-signature handshake). Finding 38 (Redis fail policy) is
now code-closed for the audited rate-limit, quota, and queue-admission paths after 1d.

Break-control proof for spec 1b was run with temporary production-code breaks,
restored immediately after each run. Post-proof production diff check:
`git diff -- apps/backend/app` was empty.

| Invariant | Temporary break | Proof command/result | Restored state |
| --- | --- | --- | --- |
| 1b-1 Rate limit enforced | Edge middleware ignored over-limit decisions. | `test_edge_rate_limit_middleware.py::test_allows_then_blocks_with_429` failed: over-limit request returned `200` instead of `429`. | Restored; included in final `120 passed`. |
| 1b-2 Uniform webhook rejection | `_uniform_webhook_rejection` returned internal reasons. | `test_webhook_uniform_rejection.py::test_all_rejection_reasons_share_one_response` failed: codes split into route/mismatch/signature causes. | Restored; included in final `120 passed`. |
| 1b-3 Server-derived canonical URL | Channel webhook verifier trusted `x-operious-webhook-url` again. | `test_channel_webhook_signature_url.py::test_signature_over_forged_url_rejected` failed: forged URL signature was accepted. | Restored; included in final `120 passed`. |
| 1b-4 Voice WS caps | Frame-rate guard returned without enforcing the cap. | `test_voice_ws_caps.py::test_over_rate_stream_is_closed_and_call_terminated` failed: stream closed normally with `1000` instead of policy `1008`. | Restored; included in final `120 passed`. |

Edge-hardening review update: #16, #23, #24, #39, #40, and #63 are now materially closed in code/tests. #25 is materially improved but not fully closed because malformed parse errors still leak detail. #38 is now code-closed for the audited rate-limit/quota/admission paths, with live outage proof still required.

## Phase 1a-ext/1c/1d/1e Review (2026-06-02)

The latest committed tranche is materially correct at the production-code level. I did not find a new production-code blocker in the modified areas reviewed.

- Observability endpoints are gated on `tenant.observability.read`, audit export is gated on `tenant.audit.export`, and the broader object-RBAC sweep now covers sensitive tenant-scoped router modules with no allowlist. Functional RBAC proof passed in the user's normal shell.
- Public audit export verification has a 256 KiB endpoint cap. This bounds HMAC/verification work after request parsing; it is not a complete pre-parse body-budget control.
- Principal-bound conversation sessions now deny non-owner callers and allow operator bypass. Ownerless sessions still pass through under tenant authority, so ownerless/operator policy remains a residual rather than a closed enterprise object-policy story.
- Tenant config ledger apply attribution is fixed: `TenantConfigChangeRequestService.apply()` now requires and persists `applied_by`, `apply_config_change_request()` threads the approving principal into the service, response schemas expose the field, and DB-backed tenant-config tests pass. Approved-but-not-applied requests can also be revoked through `revoke()` and `/revoke`.
- Data-protection admin APIs are real: privacy-admin/approver gates, DSAR dual-control erasure, legal holds, retention policy management, envelope encryption, and FK/check constraints are implemented and DB-tested.
- Resilience controls are real: quota and queue admission fail closed when Redis-backed admission state is unavailable, webhook capture happens before processing admission, execution records bind governance config id/version/sha, completion-event emission failure records a DLQ task, and per-tenant queue QoS exists.
- Cleanup/hardening is real: the `_deprecated` package is deleted and guarded by invariant tests; backend Docker now pins the Python image digest and runs as non-root; CI emits SBOM and `pip-audit` artifacts.

Remaining fixes are not the old ledger regression. The real residuals are: complete #25 malformed-parse coarsening, archive Phase E live production proof for S-10, prove real-client-IP behavior for rate limiting, run DNS-rebinding loopback tests in normal CI, and avoid presenting data-protection controls as full compliance until KMS, retention/legal operations, and live erasure evidence are complete.

## Phase 2 Governed Operations Review (2026-06-05)

The Phase 2 changes are materially correct in the reviewed production-code paths, with one clear exception in the commerce-action approval DI path.

- Grounded resolution/conversation: Phase 2.0/2.1 adds citation span provenance, evidence-bound generation, central grounding governance, and escalation on ungrounded factual replies. The user's normal-shell governance/domain/Auth0/resolution/config-router bundle passed `112 passed, 10 skipped`.
- Connector side effects: Phase 2.2/2.3 adds a tenant-scoped connector invocation ledger, provider idempotency keys, generic REST refund connector, connector config records, credential redaction, SSRF validation/pin-to-IP transport, and terminal replay semantics.
- Tenant action/onboarding governance: Phase 2.4/2.5a-b moves action policy and connector configuration into the dual-control tenant-config change-request ledger with reconstruction hashes and write-only credentials. Read APIs are credential-free and capability-gated.
- Platform/tenant boundary: Phase 2.5c-d splits platform tenant creation from tenant configuration. `platform.tenant.admin` creates inert tenants in the Platform Console; Command Center onboarding is tenant-scoped config work only.
- Work-order dispatch: Phase 2.3.x-a/b/c adds a work-order ledger, explicit `created -> dispatched -> awaiting_fulfillment -> fulfilled/failed` transitions, connector-backed `repair.dispatch`, receipt-only callback ingress, and tenant-scoped fulfillment consumption. The user's normal-shell work-order dispatch substrate test passed `6 passed`.
- Commerce action stubs: `eb74b55` adds `ALLOW_STUB_ACTIONS`, `Settings.allow_stub_actions_effective`, and `FailClosedActionTool`. The diagnostic worker passes the derived production setting into the tenant action registry, and focused tests passed `4 passed`. This materially reduces fake-success risk for automatic action execution.
- S-10 prep: live verification probes, DLQ probe task, smoke trace probe, RLS table probe, spoof-rejection probe, and legacy Anker knowledge rewrap tooling exist. This is preparation, not closure.
- Embeddings: real OpenAI embedding support is now production-wired through `build_embedding_provider()` in API and worker composition, constrained to one 1536-dimensional native pgvector column plus HNSW index, and covered by provider, wiring, DB retrieval, tenant-isolation, and re-embed tests.

Residuals from this review:

- The action-approval service factory still calls `build_tenant_action_tool_registry()` without `allow_stub_actions=settings.allow_stub_actions_effective` (`apps/backend/app/dependencies/services.py:839-844`). Because `ActionApprovalService.approve()` re-invokes approved actions through that factory, a manager-approved unconfigured action can still hit the registry default `allow_stub_actions=True`. Fix: pass the setting in that factory and add an API/service test proving manager-approved unconfigured actions return `action_connector_not_configured` in production.
- Fulfillment callback ingress is tenant-authenticated and receipt-only, which is safer than direct mutation, but provider-origin signature verification/replay TTL for public provider callbacks is not yet proven.
- Connector invocation ledger, repair dispatch, callback, tenant lifecycle, and S-10-prep DB suites need normal-shell/CI proof if they are to be used as release evidence; Codex sandbox DB runs were inconclusive.
- OpenAI embeddings are code/test-closed for runtime wiring and dimension-aware pgvector retrieval. Remaining work is production rollout evidence: snapshot, migration, real-provider re-embed of the Anker documents, and retrieval confirmation.
- Live provider idempotency, live outbound private-IP blocking, real client IP rate limiting, and Phase E production verification remain outside local code proof.

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
- Tenant config ledger schema/ORM now includes `applied_by`, `REVOKED`, `revoked_by`, and `revoked_at`; service/API paths populate applying and revoking principals.
- Direct tenant config mutation disabled in production and disabled by default outside production unless explicitly opted in.
- Signed voice session tokens, voice feature flag, provider handshake signature verification, and frame byte/count/duration/idle/rate caps.
- Voice and channel webhook provider signatures are now checked against a server-derived canonical URL (`PUBLIC_BASE_URL` + request path/query), not a client-controlled URL header.
- Durable pre-approved action grants bound to exact actor/tenant/tool/action/target/payload hash, with `consumed_at`, `consumed_by`, and idempotency key.
- Outbound webhook SSRF validation, redirect blocking, and pin-to-IP transport.
- Fixed-window inbound rate limiting: per-IP pre-auth and per-tenant/principal post-auth, with 429 responses and production 503 fail-closed behavior for non-idempotent requests when Redis is unavailable.
- Production coarsening for most recon-sensitive authority-state failures.
- Domain read/export capability gates for observability and audit export.
- Object-RBAC sweep across sensitive tenant-scoped operational, supervisor, governance, cognition, observability, action, training, and privacy surfaces.
- Principal-bound conversation session ownership checks.
- Data-protection runtime and admin API: envelope encryption, DSAR dual-control erasure, legal hold, retention policy, master-key rotation support, and purge behavior.
- Fail-closed Redis-backed quota and queue-admission policy for pre-call/publish decisions.
- Durable webhook capture before processing-admission evaluation.
- Execution-governance config id/version/content hash binding and worker-side reconstruction checks.
- Completion-event DLQ recording when worker operational-event emission fails.
- Per-tenant queue QoS reservations.
- Connector invocation reservation/replay and work-order transition history reduce duplicate side effects in the new refund/repair paths.
- Unconfigured automatic commerce actions fail closed in production through the worker path.
- Token-per-minute quota accounting/enforcement for diagnostic LLM usage.
- RAG quarantine/review status, injection scanner, approved-only retrieval, and untrusted knowledge delimiters.
- Knowledge span provenance and grounding-aware customer-reply generation with central communication governance.
- Connector invocation idempotency ledger, generic REST connector base, queryable credential-free connector config, and SSRF-pinned connector HTTP transport.
- Per-tenant action governance loaded from tenant action-policy records.
- Governed connector-config and action-policy onboarding through the tenant config change-request ledger.
- Platform-gated inert tenant creation and separate Platform Console/Command Center onboarding responsibilities.
- Work-order dispatch ledger, explicit state machine, connector-backed `repair.dispatch`, and receipt-only fulfillment callback ingestion/consumer.
- Production-default fail-closed commerce action tool registration for the diagnostic worker path when no connector exists.
- Production boot-readiness validation for provider stubs and security-critical secrets.
- CI workflow, production readiness CLI gate, and RLS coverage invariant.
- `_deprecated` package deletion invariants, pinned backend/container images, non-root backend runtime, SBOM artifact generation, and `pip-audit` CI artifact generation.
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
- Auth-error coarsening is partial: authority-state failures coarsen, but malformed authorization/header parse errors still return detailed bodies.
- Voice auth/cap controls are closed, but production token issuance UX/API and real STT/TTS provider proof remain incomplete.
- Action grants and the connector invocation ledger are much stronger. Real external connector side effects now have an initial refund/repair/work-order path, but live provider idempotency drills, provider-origin callback signatures, and one manager-approval DI gap remain.
- Quotas include diagnostic token-per-minute enforcement, fail-closed pre-call Redis policy, queue admission, and inbound request rate limiting; idempotent rate-limit reads still degrade open by design, per-IP limiting may key the Fly proxy peer, and quota is not a universal enterprise budget system.
- RAG poisoning controls exist, but human review UX, adversarial evals, and source-trust workflows remain immature.
- Real OpenAI embeddings are wired into API/worker runtime composition with a 1536-dimensional native pgvector/HNSW path and re-embed tooling. Production rollout evidence remains pending.
- Data-protection controls exist, but enterprise compliance remains partial until KMS/key custody, legal operations, retention jobs, live DSAR evidence, and access-control workflows are proven.
- Broader object RBAC now covers selected sensitive tenant-scoped surfaces, but live Auth0 mapping, uncovered/future route coverage, and production alert/health/readiness checks are not live-proven.
- Marketing/command-center/platform-console proof improved materially, but public external validation, compliance proof, status/SLA pages, and some demo residue remain.

What is mocked/stubbed:

- Voice STT/TTS paths still rely on stub-like providers unless production providers are configured.
- Commerce actions are mixed: generic REST `refund.request` and `repair.dispatch` connector paths exist; unconfigured automatic actions fail closed in production through the worker path; warranty/replacement/warehouse still lack real connectors; the manager approval path can still register stubs until the DI gap is fixed.
- Shopify enrichment can fall back to deterministic stub behavior.
- Translation defaults/fallbacks can behave as identity outside configured production posture.
- Knowledge embeddings use the real OpenAI provider in production composition when `EMBEDDING_DEFAULT_PROVIDER=openai` and `OPENAI_API_KEY` are configured; deterministic embeddings remain only as explicit fallback/test behavior.
- Command center still contains proof/demo-oriented data.

What is planned/missing:

- Phase E live production verification for S-10.
- Real production STT/TTS and call initiation/token issuance flow.
- Real provider integration drills and idempotency contracts for refund/repair connectors.
- Production execution of the real-embedding rollout: snapshot, migrate, re-embed the Anker docs with OpenAI, and archive retrieval/eval evidence.
- Provider-origin signature/replay protection for public fulfillment callbacks.
- Action-approval service DI fix so manager-approved unconfigured actions also fail closed in production.
- Command-center workflow maturity for the tenant config change-request ledger and action approvals.
- Data-protection operator workflow, KMS-backed key custody, live erasure/legal-hold/retention evidence, and compliance runbooks.
- Real-client-IP proof or proxy-aware configuration for per-IP rate limiting on Fly.
- Live proof of outbound connector allowlists/private-IP blocking in production.
- Redis outage chaos proof for quota/admission/rate-limit paths.
- Production readiness verification for Fly health, workers, DLQ, RLS, secrets, Auth0 operator capability.
- SOC 2/compliance artifacts, retention/deletion workflows, public SLA/status proof.

## Service Map

| Service | Role | Runtime dependencies | Current status |
| --- | --- | --- | --- |
| Backend API | Authority, orchestration, tenant APIs, governance, sessions, data protection, action approvals | Postgres, Redis, Auth0 JWKS, Sentry, Anthropic/OpenAI optional | Stronger controls; manager action-approval stub DI gap and production proof pending |
| Celery workers | Diagnostic execution, supervisor, QA, SOP intelligence, maintenance, outbound, work-order/S-10 probes | Redis, Postgres, Anthropic optional | Real topology; completion-event DLQ and action fail-closed worker path improved; live worker/DLQ proof pending |
| Command Center | Tenant operator UI | Auth0, backend API | Real UI with typed channel settings and tenant-config onboarding; approval workflow/demo residue remains |
| Platform Console | Platform tenant lifecycle UI | Auth0, backend API | New app for platform-gated inert tenant creation; live platform Auth0 proof pending |
| Marketing app | Public website | Vercel/Next | Improved proof surface; claims must stay aligned with live proof |
| Postgres | Tenant data, RLS, audit, execution, knowledge | App role and owner role discipline | Strong design; prod RLS proof missing |
| Redis | Broker, queue depth, quotas, nonce/cache, inbound rate limits, per-tenant QoS | Celery, runtime services | Real; quota/queue admission fail closed for pre-call/publish decisions; rate-limit idempotent paths still degrade open |
| Auth0 | Browser/user identity | Next middleware, backend JWKS | Namespaced mapping present; live token proof missing |
| External channels/connectors | Webhooks, generic REST refund/repair dispatch, fulfillment callback ingress | Tenant credentials, SSRF guard, connector/work-order ledgers | Guarded generic outbound exists; live provider/signature/idempotency proof pending |
| Translation | Boundary localization | Identity or Anthropic provider | Real Anthropic path when configured |
| Voice | WebSocket media path | Voice runtime, signed session token, provider signature | Auth control closed; provider/issuance/load test maturity pending |

## Execution Map

HTTP request:

`client -> RequestBodyLimit -> CORS -> RequestContext -> EdgeRateLimit -> optional TrustedIngress -> AuthorityContext -> TenantRateLimit -> router -> service -> runtime -> repository -> Postgres/RLS`

Current answer: the original production header-spoofing path is closed by default in code, and inbound rate limiting now runs both before and after authority resolution. Remaining risk is operational: live trusted proxy ranges, Auth0 settings, override flags, Redis availability, and whether the per-IP key reflects the real client or only the Fly proxy peer.

Webhook:

`channel webhook -> route secret resolver -> signature check -> tenant context -> boundary normalization -> session/dispatch/execution`

Current answer: Twilio-style provider signatures now derive the canonical URL server-side from `PUBLIC_BASE_URL` and request path, instead of trusting a client-supplied URL header. Generic outbound dispatch is SSRF-guarded and redirect-blocked. Webhook ingress now captures durable boundary records before processing-admission decisions so Redis/admission pressure does not silently drop already-authenticated inbound events.

Diagnostic execution:

`dispatch -> governance admission token -> execution record/outbox -> Celery queue -> worker claim -> cognition snapshot -> approved-only RAG retrieval -> LLM/deterministic fallback -> quota usage record -> governance persistence -> timeline/resolution proposal`

Current answer: RAG poisoning and token quota are materially improved. Execution records now bind the execution-governance configuration id/version/content hash used at admission, and workers verify that bound version before running. Live provider/readiness proof remains required.

Action tool:

`agent request -> ToolInvoker -> capability/constraint checks -> governance evaluation or pre-approved decision -> durable grant -> exact actor/payload/binding consumption -> tool invoke -> envelope`

Current answer: old cross-payload replay is closed. Tool invocation now reserves connector idempotency before provider calls, terminal connector results replay, and the diagnostic worker registers fail-closed tools for unconfigured commerce actions in production. Residual: manager-approved re-invocation still needs the fail-closed setting wired; real irreversible provider side effects still require live provider idempotency and production tests.

Work order:

`repair.dispatch -> connector invocation reservation -> work-order create -> provider dispatch -> awaiting_fulfillment -> receipt-only callback ingress -> tenant-scoped fulfillment consumer -> fulfilled/failed`

Current answer: the repair dispatch lifecycle is materially modeled, tenant-scoped, and idempotent in code. Residual: provider-origin callback signatures/replay controls and live provider proof are still missing.

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
- Connector invocation rows, connector configuration records, work-order records, and fulfillment receipt/correlation metadata.
- Grounding traces, evidence span references, and customer-reply draft governance decisions.
- Operational trace/audit records.
- Data-protection key rows, erasure request ledger rows, legal hold rows, and retention policy rows.

## Scope Alignment Scorecard

| Subsystem | Prior score | Current score | Status | Rationale |
| --- | ---: | ---: | --- | --- |
| Governance layer | 72 | 89 | Partial | Durable config ledger, apply attribution, revoke flow, action grants, domain capabilities, object-RBAC sweep, per-tenant action policy, connector/onboarding change requests, policy binding, and grounding governance improve governance; live proof/workflow maturity still missing. |
| Agent layer | 50 | 76 | Partial | Replay is durably actor/payload-bound, connector invocation ledger exists, automatic unconfigured commerce actions fail closed in production, and quota/backpressure are stronger; manager-approved action DI and live provider proof remain. |
| Supervisor layer | 60 | 64 | Partial | Supervisor/QA records exist and read gates improved; still more observability than hard production control. |
| Execution layer | 62 | 76 | Partial | Durable execution/claims/outbox/recovery plus governance version binding, completion DLQ, per-tenant QoS, connector invocation reservation, and work-order transitions improve replay/reliability. |
| Knowledge layer | 50 | 74 | Partial | Quarantine/review, injection scan, approved-only retrieval, delimiters, citation span provenance, grounded generation, and data-protection encryption close more of the original path; review UX/evals remain. |
| Audit layer | 68 | 78 | Partial | Better grant/ledger/DLQ/data-protection/connector/work-order evidence and boot checks; live secret/rotation proof still missing. |
| Compliance layer | 35 | 52 | Partial | DSAR erasure, legal holds, retention policy, envelope encryption, and better reconstruction metadata now exist; SOC 2, KMS/key custody, live evidence, and legal operations remain incomplete. |
| Human escalation layer | 58 | 78 | Partial | Tenant config dual-control ledger, connector/action onboarding, apply attribution, revocation, and action approvals exist; UI workflow, expiry, and the approval-stub DI gap remain. |
| Intelligence layer | 52 | 72 | Partial | Anthropic paths, TPM quota, RAG controls, grounded response governance, and encrypted sensitive audit/prompt fields improved; provider/quality proof remains. |
| Auth/RBAC | 57 | 82 | Partial | Header authority, Auth0 namespaced mapping, domain capabilities, platform/tenant capability split, object-RBAC sweep, data-protection caps, and conversation ownership improved; live proof and partial auth-error coarsening remain. |
| Tenancy | 76 | 85 | Partial | RLS discipline plus header/voice/data-protection/object-RBAC/platform-lifecycle/work-order fixes improve isolation; production proof remains. |
| Observability | 58 | 64 | Partial | Logs/metrics/alerts exist and completion-event DLQ, work-order states, and connector invocation records are stronger; live operator and compliance proof incomplete. |
| Reliability | 55 | 74 | Partial | Boot gates, CI, durable grants, repaired voice load harnesses, rate-limit fail policy, quota/queue fail-closed behavior, durable ingress capture, completion DLQ, connector idempotency, and work-order state help; live worker/DLQ/full-suite proof keep this capped. |
| Scalability | 49 | 61 | Partial | Queue topology, token quota, inbound rate limiting, per-tenant QoS, admission controls, and connector/work-order ledgers help; no meaningful live load/scale proof and per-IP proxy semantics remain unproven. |
| Enterprise readiness | 43 | 63 | Not ready | Security/governance primitives improved sharply, but S-10, the action-approval stub DI gap, formal compliance, live provider integrations, DR/SLO evidence, and production proof cap readiness. |

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

Residual: live Auth0 role assignment proof and broader object-scope policy for uncovered or future tenant-scoped surfaces are still needed for enterprise readiness.

### S-03: Production Self-Approval - CLOSED, Workflow Residuals

Original finding: `TenantConfigurationService` could internally create approved records with `reviewed_by=proposed_by`.

Current evidence:

- `apps/backend/app/core/config.py:434-442` disables direct self-approval in production.
- `apps/backend/app/api/v1/routers/tenant.py:126-240` exposes propose/list/approve/reject/apply endpoints.
- `apps/backend/app/services/tenant_config_change_request_service.py:117-124` rejects same proposer/approver.
- `apps/backend/app/services/tenant_config_change_request_service.py:166-208` requires and persists `applied_by` when applying an approved request.
- `apps/backend/app/api/v1/routers/tenant.py:228-248` passes the applying principal into `service.apply()`.
- `apps/backend/app/services/tenant_config_change_request_service.py:210-251` implements pre-apply revocation of approved requests.
- `apps/backend/app/api/v1/routers/tenant.py:251-277` exposes `/config/change-requests/{id}/revoke`.
- Migration `0063_tenant_config_change_requests` enforces `approved_by != proposed_by` and FORCE RLS.
- Tests: `test_tenant_config_apply_authorization.py`, `test_tenant_config_change_requests.py`, `test_ledger_revocation.py`.

Status: original self-approval vulnerability closed by `7602507`; apply attribution and revocation completed by `df78ac7`/`d917d0e` and proven by current user reruns.

Residual: add expiry/time-bound approval behavior, command-center workflow adoption, and live Auth0 writer/approver proof.

### S-04: Voice WebSocket Authentication - CLOSED For Auth/Caps, Provider Residual

Original finding: voice stream accepted tenant identity from `?tenant=...`.

Current evidence:

- `apps/backend/app/api/v1/routers/voice.py:51-69` requires `VOICE_ENABLED` and signed session token before accept.
- `apps/backend/app/api/v1/routers/voice.py:71-80` requires tenant voice provider auth token and provider signature.
- `apps/backend/app/api/v1/routers/voice.py:215-260` derives the signature URL server-side from `PUBLIC_BASE_URL`, request path, and query string unless `WEBHOOK_TRUST_URL_HEADER` is explicitly enabled.
- `apps/backend/app/core/twilio_signature.py:38-55` verifies Twilio-style signatures with constant-time comparison.
- `apps/backend/app/services/voice_provider_auth.py:19-48` loads provider auth token from tenant channel credentials.
- Tests: `test_voice_session_token.py`, `test_voice_provider_signature.py`, `test_voice_provider_signature_url.py`, repaired `test_voice_capacity.py`, and `test_voice_load.py`.

Status: original unauthenticated/spoofable voice path is closed by `6454bb7`, `4694d63`, and strengthened by `175dd52`. The prior stale load/capacity harness issue is closed.

Residual: production token issuance and real STT/TTS provider proof are still needed. Wall-clock, idle-timeout, and frame-rate controls are now enforced in the voice route and covered by handler-level tests.

### S-05: Replayable Decisions - CLOSED

Original finding: `ToolInvoker` pre-approved path validated UUID, same tenant, and persisted ALLOW only; another request could replay that allow decision.

Current evidence:

- `apps/backend/app/agents/tools/grants.py:36-49` persists grant actor, payload hash, binding hash, idempotency key, consumption fields.
- `apps/backend/app/agents/tools/grants.py:97-103` atomically consumes a grant only when `consumed_at IS NULL`.
- `apps/backend/app/agents/tools/grants.py:262-291` enforces actor mismatch and already-consumed failure.
- `apps/backend/app/agents/tools/invoker.py:263-356` requires binding hash, durable repo, actor match, unconsumed grant, and provider idempotency key.
- Migration `0064_agent_action_grants` adds RLS and uniqueness.
- Tests: `test_action_grant_durability.py`, `test_tool_governance_mandatory.py`.

Status: closed by `942b131`; explicit break-control proof in `4e6451c`. Phase 2 further reduces replay risk with connector invocation reservation, provider idempotency keys, terminal-result replay, and work-order state binding.

Residual: real provider connectors still need live idempotency and side-effect tests before high-value actions. Manager-approved unconfigured actions must also inherit the production fail-closed stub setting.

### S-06: Outbound Webhook SSRF - CLOSED For Generic Outbound Dispatch

Original finding: tenant-configured outbound URLs were posted directly without scheme/domain/private-IP guardrails.

Current evidence:

- `apps/backend/app/core/ssrf.py:173-233` validates HTTPS, host allowlist, DNS results, blocked IP classes, and selected pinned IP.
- `apps/backend/app/core/ssrf.py:49-120` implements pinned-IP transport that dials the validated IP while preserving host/SNI.
- `apps/backend/app/boundary/outbound/adapter.py:81-107` validates before dispatch, uses pinned transport, and disables redirects.
- Tests: `test_ssrf_guard.py`, `test_ssrf_dns_rebinding.py`.

Status: closed by `cd8c6bc` and `20a890a`.

Residual: DNS-rebinding tests are now deterministic in code, but loopback-server proof still needs a normal-shell/CI pass here; live egress proof remains part of S-10/Phase E.

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

- `apps/backend/app/agents/runtime/quota_runtime.py:148-163` fails closed when Redis-backed token budget state is unavailable before a call.
- `apps/backend/app/agents/runtime/quota_runtime.py:179-221` fails closed when request-minute/hour Redis windows cannot be incremented.
- `apps/backend/app/agents/runtime/quota_runtime.py:284-315` records post-call token usage and intentionally fails open only after the provider call has already happened.
- `apps/backend/app/cognition/diagnostic_runtime.py:261-309` checks quota before LLM calls and records real completion usage.
- Tests: `test_quota_runtime.py`, `test_diagnostic_agent_quota_integration.py`.

Status: closed by `4cdf202` for diagnostic LLM usage and strengthened by `2335756` for Redis-backend fail-closed pre-call behavior.

Residual: enterprise-wide provider budgets, reservations, observability, and live Redis-outage chaos proof remain needed.

### S-10: Production Readiness - OPEN

Current evidence:

- `apps/backend/app/core/production_readiness.py:39-119` collects and raises on production readiness problems, including provider stubs, tenant credential/data-protection key material, audit export HMAC, voice session secret, and public-base webhook URL posture.
- `apps/backend/app/main.py:468-473` invokes readiness validation when enforced.
- `apps/backend/scripts/check_production_readiness.py` exposes release-gate CLI.
- `.github/workflows/ci.yml` runs backend/frontend and DB-backed checks.
- `test_rls_coverage_invariant.py` requires tenant tables with RLS to force RLS.
- Tests: `test_production_readiness.py`, `test_check_production_readiness_script.py`, `test_rls_coverage_invariant.py`.
- Production-readiness rejection for `WEBHOOK_TRUST_URL_HEADER=true` and missing `PUBLIC_BASE_URL` is covered by `test_production_readiness_webhook.py`; the readiness bundle passed `16` tests.
- `apps/backend/scripts/s10_prep/live_verification_probes.py` adds deploy-time probes for direct spoof rejection, Auth0/bearer smoke, production-role RLS isolation, worker/DLQ proof, and smoke trace evidence.
- `apps/backend/app/workers/s10_probe_tasks.py` adds a DLQ probe task.
- `apps/backend/scripts/s10_prep/rewrap_legacy_anker_knowledge.py` adds a dry-run-first rewrap path for legacy Anker knowledge ciphertext.

Status: open. The boot gate is committed, but live production verification is not done.

Required to close:

- Live direct spoofed authority-header rejection.
- Live bearer/Auth0 success path with namespaced claims.
- Live production-role RLS tenant isolation.
- Live workers and DLQ smoke/replay proof.
- Live secrets/provider/readiness CLI output.
- Rollback evidence.

## Data Protection, Resilience, And Cleanup Review

The Phase 1c/1d/1e tranche materially changes the current state:

- Data protection: `apps/backend/app/api/v1/routers/data_protection.py:41-247` exposes privacy-admin and privacy-approver gated erasure/legal-hold/retention APIs. `apps/backend/app/data_protection/crypto.py:425-493` implements dual-control DSAR erasure by deleting the subject data key only after an independent approver passes lifecycle/legal-hold checks. `apps/backend/app/data_protection/db/models.py:30-185` stores data keys, retention policies, legal holds, and erasure-request ledgers with check/FK constraints.
- Data-protection proof: `test_data_protection_controls.py` proves envelope encryption, crypto-shred unreadability after erasure, legal-hold blocking, tenant-delete FK semantics, same-principal DB/app rejection, master-key rewrap, and tenant-owned knowledge encryption. `test_data_protection_admin_api.py` proves API gates, unconfigured-key `503`, propose/approve erasure, legal-hold release, same-principal rejection, and retention purge behavior.
- Resilience: `apps/backend/app/core/queue_admission.py:101-152` fails closed when queue depth cannot be read; `apps/backend/app/core/queue_admission.py:214-278` adds per-tenant queue reservations. `apps/backend/app/agents/runtime/quota_runtime.py:148-221` fails closed for pre-call quota state loss.
- Durable ingress: `apps/backend/app/services/ticket_ingress_service.py:543-608` commits the captured boundary ingress before recording processing-admission pressure, so authenticated inbound events are not lost when admission defers.
- Governance binding: `apps/backend/app/execution/runtime.py:390-430` persists execution-governance config id/version/sha into the execution record, and `apps/backend/app/runtime/execution_governance.py:306-343` rejects missing/mismatched bound configs during reconstruction.
- Completion DLQ: `apps/backend/app/workers/execution_completion_events.py:45-82` records a dead-letter task if worker completion-event emission fails.
- Cleanup: `apps/backend/tests/test_legacy_module_quarantine.py:78-114` proves `_deprecated` is absent and not imported; `apps/backend/Dockerfile:1-22` pins the base image digest and runs as non-root; `.github/workflows/ci.yml:61-76` generates SBOM and `pip-audit` artifacts.

Residuals: data protection is now real code, not a stub, but it is not yet a complete compliance program. KMS/key custody, live erasure evidence, retention/legal operations, audit access controls, and customer-facing compliance artifacts still sit outside this code closure. Resilience controls are stronger, but live Redis outage, worker, DLQ, and queue-pressure drills remain S-10/ops proof work.

## Edge-Hardening Review

Claude's latest committed tranche materially improves the edge posture:

- #23 webhook/voice canonical URL spoofing: closed in production code and tests. `derive_canonical_webhook_url` builds URLs from `PUBLIC_BASE_URL` plus trusted path/query, channel webhook signatures pass `request_path`, and voice provider signatures now ignore forged canonical URL headers unless `WEBHOOK_TRUST_URL_HEADER` is explicitly enabled for non-production testing.
- #39 inbound rate limiting: closed at code/test level. `EdgeRateLimitMiddleware` runs pre-auth by IP, `TenantRateLimitMiddleware` runs post-auth by tenant/principal, and `main.py` registers both in the request pipeline.
- #38 Redis backend-loss policy: code-closed for the audited quota/admission paths. Rate-limiter production writes fail closed in 1b; quota and queue admission now fail closed for pre-call/publish decisions in 1d. Residual: live outage drills and idempotent rate-limit degrade-open semantics must be documented.
- #63 stale voice load/capacity harnesses: closed. The fake WebSocket harnesses now include signed session token, provider auth loader, server-derived signature URL, and provider signature headers.
- #25 auth-error coarsening: partial. Authority-state errors are coarsened in production, but malformed `Authorization` and malformed legacy authority-header parse paths still return detailed bodies.
- #40 voice wall-clock, idle, and frame-rate caps: closed at code/test level in the voice WebSocket route.

Remaining edge-hardening gaps:

- Per-IP rate limiting may be per Fly proxy, not per real internet client, because the middleware keys `scope["client"]` and the Fly deployment comments say the app observes the proxy as an `fdaa::/16` peer. This still provides a coarse abuse brake, but live proxy/client-IP semantics must be proven before claiming true per-client edge rate limiting.
- Malformed auth/header parse errors should be routed through the same coarsening helper used by verification/source-state failures before #25 is called closed. Evidence: `AuthorityContextMiddleware` returns direct detailed `JSONResponse` bodies for malformed authorization and legacy authority headers at `apps/backend/app/middleware/authority_context.py:207-214`, `224-232`, and `322-330`.
- Redis quota/admission outage policy is no longer deferred: spec 1d implemented fail-closed pre-call/publish behavior. Remaining work is live chaos proof and operator runbook evidence.

## Multi-Tenancy Audit

Could tenant A ever see tenant B data?

Current answer: materially less likely than before, but still not proven impossible in production. The original direct-header spoof path is closed by default, Auth0 namespaced tenant claims are mapped, RLS discipline exists, voice no longer trusts raw `?tenant=...`, object-RBAC coverage is broader, and sensitive data is increasingly protected by tenant/subject-scoped envelope keys. Remaining risk sits in live deployment posture: trusted proxy range, Auth0 claim drift, production RLS proof, owner-session misuse, and any future route bypassing tenant dependencies.

Could tenant A affect tenant B execution?

Current answer: not through normal execution runtime when authority and RLS are correct. Per-tenant queue QoS reduces shared-queue noisy-neighbor risk, but broker isolation is still not per tenant. Residual risk comes from production authority/RLS misconfiguration, privileged maintenance paths, or shared infrastructure failure.

Could tenant A affect tenant B governance?

Current answer: not through the original tenant-scope-only mutation path. Tenant policy/config mutation now requires domain write capability and independent approve/apply flow. Residual risk is Auth0 role drift, over-broad tenant roles, or UI/workflow bypasses.

Tenant isolation strengths:

- RLS migrations and FORCE RLS intent.
- ContextVar tenant setting per DB transaction.
- `expected_tenant_id` checks are widespread.
- Production header authority fails closed by default.
- Voice tenant binding uses signed session tokens and provider signatures.
- Tenant config mutation is capability-gated and ledgered.
- Object-RBAC sweep covers sensitive tenant-scoped operational/governance/cognition/privacy surfaces.
- Subject-scoped data-protection keys make DSAR crypto-shred possible without deleting all tenant data.

Tenant isolation weaknesses:

- S-10 live production proof is still missing.
- Owner sessions bypass RLS and are used by maintenance tasks.
- Command center still has local/non-production header mode support.
- Some tenant-wide read surfaces lack object-level RBAC.
- No per-tenant broker isolation.

## Governance Audit

Can governance be skipped?

Current answer: much less than before for tenant config, action replay, and automatic commerce actions. Tenant config now has durable proposal, approval, rejection, apply, and revoke states with principal separation and applier/revoker attribution. Action grants are actor/payload-bound and consumed durably. Per-tenant action policies and connector configuration flow through governed change requests. Remaining gaps are UI workflow adoption, expiry/time-bound approvals, live Auth0 proof, manager-approved action fail-closed DI, and provider-side idempotency for real irreversible actions.

Can execution happen without authorization?

Diagnostic execution still expects governance admission. Voice call execution now requires signed token plus provider signature. Pre-approved action execution now requires a matching durable one-time grant. Automatic unconfigured commerce actions fail closed in the worker production path. Remaining risk is deployment misconfiguration, the action-approval service DI gap, and future connector paths.

Can stale policies be used?

Much less than before. Execution records now bind the execution-governance config id/version/content hash admitted at request time, and workers reconstruct that bound config before executing. In-flight work intentionally uses the historical admitted version; the residual is live proof, replay tooling maturity, and cache invalidation discipline.

Can evidence be tampered with?

Evidence is stronger than before. Config change requests, apply/revoke attribution, action grants, connector invocation rows, work-order records, fulfillment receipts, data-protection erasure/legal-hold ledgers, and completion-event DLQ records create more durable replayable evidence. Residual gaps include no expiry lifecycle for config approvals, incomplete command-center/action-approval workflows, and missing live secret/rotation proof.

Can replay become inaccurate?

Yes, but less than before. Action grant replay is now precise, connector invocation/work-order records improve side-effect reconstruction, and execution-governance config binding reduces stale-policy ambiguity. RAG replay is improved by citation spans but still needs stronger exact-content/hash binding and production review workflow.

## Agent Safety Audit

Can an agent exceed its authority?

Less easily than before. The prior cross-payload replay weakness is closed, per-tenant action policy exists, and automatic unconfigured commerce actions now fail closed in the worker production path. Remaining risk is over-broad tenant capabilities, poisoned or poorly reviewed knowledge, stale policies, the action-approval DI gap, or connecting real external side effects before provider idempotency and connector tests exist.

Can an agent trigger unintended actions?

Less easily than before, but still yes in the wrong deployment posture. Refund and repair dispatch now have connector/work-order ledgers, and unconfigured automatic commerce actions fail closed in production. Warranty/replacement/warehouse connectors are not real yet, manager-approved unconfigured actions can still hit the registry default until DI is fixed, and live providers need idempotency/signature proof.

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
- Data-protection keys, legal holds, erasure requests, and retention policies are first-class tables with constraints and FK semantics.
- Sensitive session/cognition/knowledge values can be envelope-encrypted and crypto-shredded by subject key.

Risks:

- Production FORCE RLS proof is not archived.
- Owner-session misuse would bypass RLS.
- Some model/schema nullability drift can still exist.
- Retention/legal hold/erasure now exist in code, but live operations and compliance evidence are incomplete.
- Knowledge/vector query-plan proof at production scale is missing.

## Performance Audit

10x scale:

- Backend likely survives if Postgres/Redis are healthy and workers are scaled manually.
- Diagnostic workers and provider quotas remain bottlenecks.
- Token quota helps cost blast radius.
- Inbound fixed-window rate limiting now adds a basic abuse brake.
- Per-tenant queue QoS reduces one-tenant queue saturation but is not full broker isolation.

100x scale:

- Queue backlog, worker concurrency, DB pool limits, Redis availability, and provider rate limits dominate.
- Voice load/capacity harnesses now pass under the provider-signature contract, but real provider/media load remains unproven.
- Tenant-wide dashboards need pagination/index proof under production volume.
- If Fly exposes only the proxy peer to the app, the per-IP limiter may throttle proxy-wide traffic rather than individual abusive clients.

1000x scale:

- Current architecture needs sharding strategy, autoscaling, stronger broker isolation or strict QoS, vector index strategy, cost budget enforcement, and operational SLO proof.

Failure points:

1. S-10 deployment misconfiguration.
2. Provider quota/cost during diagnostic load.
3. Queue backlog and worker saturation.
4. Redis unavailable causing admission/quota writes to fail closed while idempotent rate-limit paths can still degrade open by design.
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
- Quota and queue admission now fail closed when Redis-backed admission state is unavailable.
- Durable webhook capture happens before processing-admission decisions.
- Worker completion-event emission failures are dead-lettered.
- Per-tenant queue QoS exists for diagnostic publication.

Risks:

- Production worker process verification is not archived.
- Voice load/capacity test suite has been repaired after the auth gate.
- Some periodic tasks intentionally do not DLQ.
- Live Redis outage drills are not archived; rate-limit idempotent paths still degrade open by design.
- No disaster recovery/backup restore evidence was found in active gates.
- Real external action side effects are only partially integrated, so reliability claims remain unproven outside the initial refund/repair/work-order paths.
- Manager-approved unconfigured commerce actions can still use the registry default until the action-approval service DI is fixed.
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

- Duplicate app trees still create deployment ambiguity, but the `_deprecated` backend package has been deleted and guarded by invariant tests.
- Multiple runtime compositions use in-memory/deterministic defaults outside production gates.
- Tenant config workflow still needs UI adoption and expiry/time-bound approvals.
- Voice load/capacity test harnesses now model the provider-signature contract; real provider load proof remains.
- Command center demo/proof constants remain in active product code.
- The action registry default remains stub-friendly for backwards compatibility; every production DI caller must explicitly pass the derived fail-closed setting.
- Some abstractions are ahead of real integrations, increasing false confidence.

## Testing Audit

Known current proof:

- Header authority and Auth0 claim posture passed.
- Tenant config RBAC and direct-apply denial passed.
- Domain capabilities passed.
- Tenant config change-request lifecycle and RLS passed.
- Tenant config apply attribution and revoke behavior passed.
- Durable action grant consumption and RLS passed.
- SSRF guard, quota runtime, production readiness passed.
- Voice signed token and provider signature passed.
- Voice signature URL spoofing and repaired voice load/capacity harnesses passed.
- Edge/tenant rate-limit middleware and app pipeline tests passed.
- Channel webhook canonical URL signature tests passed.
- RAG poisoning controls exist and are covered by targeted tests.
- Data-protection controls/admin API, legal hold, retention, crypto-shred, master-key rotation, and FK semantics passed in DB-backed tests.
- Object RBAC sweep and functional domain gates passed in the user's normal shell.
- Deleted `_deprecated` and forbidden-dependency invariants passed.
- Grounded response/resolution governance and Phase 2 domain/Auth0/config-router bundle passed in the user's normal shell.
- Work-order dispatch substrate passed in the user's normal shell.
- Commerce action fail-closed tool/registry/settings tests passed.
- Real OpenAI embedding provider/runtime tests passed, including provider HTTP shape, production composition wiring, native pgvector retrieval, tenant isolation, and re-embed behavior.

Untested or insufficiently proven:

- Live production Auth0 token claim mapping and role assignment.
- Production trusted ingress behavior and direct spoof rejection.
- Production FORCE RLS query proof.
- Production worker/DLQ/health checks.
- Live production SSRF/egress proof.
- Auth-error coarsening for malformed authorization/header parse errors; authority-state errors are covered, parse errors still return detailed bodies.
- Real provider STT/TTS/action integration behavior.
- Live production embedding rollout evidence: the code path is wired and DB-tested, but the live Anker document re-embed and retrieval confirmation still need to be archived.
- Manager-approved unconfigured commerce actions are not yet proven fail-closed in production; static review found the service DI still omits the setting.
- Live quota/admission/rate-limit behavior under production Redis outage policy.
- DNS-rebinding loopback-server tests need normal-shell/CI proof because Codex sandbox could not bind `127.0.0.1:0`.

## Website And Command Center Update

Claude's committed frontend work materially improved the public proof surface:

- New public proof routes for security, integrations, implementation, alternatives, role pages, and insights.
- Homepage includes execution trace, improved pilot proof, ROI methodology, stronger CTA language, and broader navigation.
- Command center labels improved from explicit proof-set language toward pilot language.
- Channel settings gained typed credential forms.
- Platform Console now owns platform-gated inert tenant creation; Command Center onboarding is tenant-config work only.
- Frontend invariant tests pass for the current platform/command-center architecture.

Residual website/product trust gaps:

- No named customer references, public status page, public SLA, subprocessor page, downloadable verified security packet, completed SOC 2, or public pen-test proof.
- Some claims remain too absolute for S-10-open status.
- Demo/proof residue remains in command-center/product code.

## Enterprise Readiness

| Customer class | Readiness | Prior score | Current score | Verdict |
| --- | --- | ---: | ---: | --- |
| Internal demo | Ready with caveats | n/a | 88 | Good if demo/stub boundaries are disclosed and S-10 gaps are not represented as complete. |
| Scoped non-regulated pilot | Conditional | n/a | 77 | Reasonable after code hardening if Phase E checks pass, manager-approved stub DI is fixed, risky integrations stay constrained, and pilot scope is explicit. |
| $100k customer | Conditional pilot | 58 | 71 | More plausible after Phase 2/1c/1d/1e, but still depends on live proof, the approval DI fix, and constrained integrations. |
| $500k customer | Not ready | 43 | 59 | Better security/governance primitives, but procurement/security/compliance gaps remain large. |
| $1M customer | Not ready | 34 | 47 | Needs live production proof, compliance, real integrations, DR/SLO proof, and operator runbooks. |
| Fortune 500 | Not ready | 25 | 34 | Below expected security/compliance/change-control/supply-chain bar. |
| Regulated enterprise | Not ready | 20 | 33 | Data-protection controls exist, but formal compliance, KMS/key custody, retention/legal operations, and evidence are incomplete. |

## Red Team Review

Most likely breach paths now:

1. Production ingress/Auth0 misconfiguration or override reopens header authority.
2. S-10 gaps: RLS/worker/DLQ/secrets not actually correct in deployed environment.
3. Manager-approved unconfigured commerce action returns fake stub success because action-approval DI does not pass the production fail-closed setting.
4. Real refund/repair/replacement/warehouse connector connected before provider idempotency, callback signatures, and action side-effect tests.
5. Voice enabled before production token issuance and real STT/TTS provider proof are complete.
6. Rate-limit per-IP assumptions wrong in production, causing proxy-wide throttling rather than true abusive-client throttling.
7. RAG poisoning through approved-but-poorly-reviewed knowledge despite baseline quarantine controls.
8. XSS in command center leading to token/localStorage authority theft.
9. Compromised integration webhook route flooding queues/nonces; rate limits now reduce but do not eliminate this risk.

Most catastrophic failures:

- Cross-tenant data exposure through trusted-ingress/Auth0/RLS production misconfiguration.
- Privileged policy/config change causing automated wrong decisions if ledger roles drift.
- Real external action connected before side-effect idempotency, callback signatures, and approval fail-closed proof.
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
| 4 | Closed/Medium residual | RBAC | S-02 closed; domain capabilities and object-RBAC sweep added | Verify live Auth0 roles and extend object-scope policy for uncovered/future routes |
| 5 | Closed/Medium residual | Governance | `applied_by` persisted: service.apply() records applier, router threads principal, schema exposes it (spec 1a) | UI workflow + expiry remain |
| 6 | Closed/High residual | Voice | S-04 auth closed; load harness repaired; frame byte/count/duration/idle/rate caps enforced; provider/issuance maturity remains | Prove issuance/STT/TTS and keep cap/load tests in CI |
| 7 | Closed/Medium residual | Agent | S-05 replay closed by durable grants; connector invocation ledger and work-order states improve side-effect replay | Add live provider idempotency tests and manager-approval fail-closed proof |
| 8 | Closed/Medium residual | SSRF | S-06 closed for generic outbound; deterministic DNS-rebinding tests exist | Archive normal-shell/CI loopback proof and live egress proof |
| 9 | Closed/High residual | RAG | S-07 original path closed | Add reviewer UX, evals, source trust policy |
| 10 | Closed/Medium residual | Auth0 | S-08 code closed | Add live token contract fixture |
| 11 | Closed/Medium residual | Quota | S-09 diagnostic TPM closed; Redis pre-call quota loss fails closed | Add enterprise budgets, provider-wide quotas, and live outage drills |
| 12 | Open/High | Readiness | S-10 open | Complete Phase E live verification |
| 13 | High | Voice | Real STT/TTS provider proof missing | Integrate/prove providers or keep voice disabled |
| 14 | Partial/High | Actions | Refund and repair now have connector/work-order paths; automatic unconfigured commerce actions fail closed in production; warranty/replacement/warehouse remain unintegrated and manager-approved actions still have a DI gap | Wire approval DI, add provider drills, then implement remaining connectors |
| 15 | High | Governance | Tenant-specific policy residue risk remains | Move hardcoded proof policies to tenant data |
| 16 | Closed/Low residual | CORS/Auth | CORS credential posture respects config and is tested | Keep posture test in CI |
| 17 | Medium | Secrets | Boot gate checks audit secret; live proof missing | Set, rotate, verify secret in Phase E |
| 18 | High | RLS | Production FORCE RLS proof missing | Run and archive prod proof query |
| 19 | High | Workers | Worker health proof missing | Verify all process groups and alerts |
| 20 | Medium | Channel | Credentials and connector config are gated/read-redacted; live provider proof incomplete | Channel-specific admin/approval/live proof |
| 21 | Medium | Topology | Ledger-gated; live workflow proof missing | Verify topology flow in CI/live |
| 22 | Closed/Medium residual | Policy | Ledger revocation implemented: REVOKED status, revoke() service, /revoke endpoint, TENANT_CONFIG_CHANGE_REVOKE act (spec 1a) | Expiry (time-based) and UI workflow remain |
| 23 | Closed/Medium residual | Webhook | Twilio/voice canonical URLs are server-derived in code/tests | Commit/readiness-gate `PUBLIC_BASE_URL`; archive live provider proof |
| 24 | Closed/Medium residual | Webhook | Uniform `401 webhook_rejected` closes content oracle; timing oracle mitigated by rate limiting | Do not pursue constant-time DB lookups; keep rate limits live |
| 25 | Partial | Auth | Authority-state errors coarsen in production, but malformed auth/header parse errors still expose detail | Route malformed parse paths through coarsening helper and add tests |
| 26 | Closed/Medium residual | Tenant | Domain gates plus object-RBAC sweep cover selected sensitive tenant-scoped surfaces | Live Auth0 proof and route-coverage invariant expansion |
| 27 | High | Audit | LLM prompts/completions are sensitive | Encrypt/redact/retain by policy |
| 28 | Closed/Medium residual | Prompt/RAG | Baseline injection controls added | Add adversarial evals and policy tuning |
| 29 | Partial/Medium | Cognition | Customer replies now pass grounded generation/governance, but universal production citation policy and evals are not complete | Keep grounding mandatory and add prod tenant eval gates |
| 30 | Closed/Medium residual | RAG | Real OpenAI embedding provider is wired into production composition, native pgvector/HNSW is dimension-coherent at 1536, and DB-backed retrieval/re-embed tests pass | Execute and archive production snapshot -> migrate -> re-embed -> retrieval/eval proof |
| 31 | Medium | Provider | Boot gate and real translation-provider path help; provider health proof missing | Provider health checks and override governance |
| 32 | Partial/Medium | Deployment | Backend runtime image is digest-pinned and non-root; SBOM/pip-audit artifacts exist, but scanning/signing/attestation are incomplete | Add image scanning, signing, provenance, and minimal multi-stage runtime |
| 33 | Partial/Medium | Supply chain | SBOM and `pip-audit` artifacts added; dependency-review and license gates incomplete | Add dependency review, license audit, and artifact attestations |
| 34 | High | Local secrets | Local `.env` hygiene risk | Keep gitignore and secret scanners |
| 35 | High | Owner DB | Owner sessions bypass RLS | Separate creds, lint owner usage |
| 36 | Closed/Medium residual | Migrations | RLS coverage invariant added | Keep invariant in CI and prove prod RLS |
| 37 | Partial/Medium | Queue | Per-tenant queue QoS reservations added for diagnostic publication; broker still not isolated per tenant | Prove QoS live, extend priority/rate limits, and consider broker isolation |
| 38 | Closed/Medium residual | Admission | Rate-limit, quota, and queue-admission audited paths fail closed for Redis-backed write/admission failures; idempotent rate-limit behavior still degrades open | Archive live Redis outage drills and runbooks |
| 39 | Closed/Medium residual | Rate limit | Per-IP and tenant/principal rate limits are wired and tested | Prove real-client-IP behavior behind Fly/proxy |
| 40 | Closed/Low residual | WebSocket | Voice frame byte/count plus wall-clock/idle/rate caps are enforced and tested | Keep handler-level cap proof in CI |
| 41 | Medium | UX/Product | Demo proof sessions remain | Remove/isolate proof sessions |
| 42 | Medium | Business | Claims can outrun live proof | Align claims to S-10 status |
| 43 | Medium | Docs | S-10 probe tooling exists, but archived live evidence is still missing | Make Phase E checklist blocking and attach probe output |
| 44 | Closed/Low residual | Codebase | `_deprecated` backend package deleted and invariant-tested | Keep quarantine test and avoid recreation |
| 45 | Medium | Codebase | Duplicate app histories remain | Declare active apps and archive old ones |
| 46 | Medium | Frontend | Browser token exposure/XSS blast radius | Harden CSP/BFF option |
| 47 | Medium | Frontend | Local storage authority labels risk confusion | Store display state only |
| 48 | Medium | CSRF | Cookie-auth token route deserves review | POST + CSRF or BFF proxy |
| 49 | Medium | CSP | CSP review incomplete | Add CSP/reporting |
| 50 | Medium | Webhook | Tenant context reset discipline should be audited | Use scoped context managers |
| 51 | Medium | Webhook | Semantic circuit advisory/fail-open risk | Make response mode configurable |
| 52 | Medium | Nonce | Nonce cleanup maintenance dependency | TTL/index/alert on growth |
| 53 | Closed/Low residual | Outbound | Redirects disabled in generic adapter | Keep invariant tests |
| 54 | Medium | Credentials | Tenant connector credentials are encrypted/write-only, but master key/KMS proof is pending | Verify injection, rotation, and KMS custody |
| 55 | Partial/Medium | Encryption | Envelope encryption and crypto-shred implemented for sensitive customer content; KMS/key custody proof missing | Move master keys to KMS and prove rotation/custody |
| 56 | Partial/Medium | Retention | Retention policy API and purge behavior exist for covered data; universal archival/legal operations incomplete | Expand coverage, schedule jobs, and archive live purge/hold evidence |
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
| 69 | Closed/Medium residual | Execution | Execution records bind governance config id/version/sha and workers verify the bound config | Add replay tooling, cache-invalidation proof, and live drills |
| 70 | Closed/Medium residual | Execution | Completion-event emission failures are dead-lettered | Add replay/drill proof and alerting |
| 71 | Partial/Medium | Execution | Connector invocation and work-order ledgers model initial refund/repair side effects; broader provider outbox/callback proof incomplete | Provider-specific outbox/drills and callback signatures |
| 72 | Partial/Medium | Action | Automatic unconfigured commerce actions fail closed in production, but manager-approved path can still register stubs and remaining tools lack real connectors | Wire approval DI and keep explicit stub labels/flags |
| 73 | Medium | Shopify | Enrichment fallback risk remains | Fail explicit in prod |
| 74 | Low | Translation | Anthropic provider exists and config dependency was fixed; fallback policy remains | Provider health and failure policy |
| 75 | Partial/Medium | Governance | Per-tenant action policies and connector config persist through the change-request ledger; other in-memory capability paths may remain | Persist all prod decisions |
| 76 | Medium | Governance | Work-order awaiting-fulfillment helps action handoff; broader durable escalation/approval queue maturity remains | Durable escalation/approval queue |
| 77 | Medium | Governance | Execution/action policy binding improved; cache invalidation remains partial | Central policy version/cache invalidation |
| 78 | Medium | Governance | Content safety policy defaults need review | Require explicit prod policy |
| 79 | Medium | Governance | Tenant allowlist/default ambiguity | Make defaults explicit/tested |
| 80 | Closed/Medium residual | API | Object-RBAC sweep covers selected sensitive tenant-scoped modules; conversation ownership is covered separately | Verify live Auth0 mappings and extend object policies where needed |
| 81 | Partial | API | Audit verify now has a 256 KiB handler cap, but no dedicated rate limit/pre-parse cap | Add route-specific rate limit and pre-parse cap if public traffic grows |
| 82 | Medium | API | Batch ingest capability/quotas incomplete | Add ingest capability and quotas |
| 83 | Partial | API | Principal-bound conversation sessions enforce owner access; ownerless tenant sessions remain tenant-wide | Add role/object policy for ownerless sessions |
| 84 | Partial/Medium | UI | Platform Console and Command Center onboarding improved, but dashboard proof metrics and approval workflows remain immature | Replace with SLA/risk/action metrics and complete workflows |
| 85 | Medium | UI | API base URL misconfig risk | Fail build without prod API URL |
| 86 | Medium | UI | No generated API client contract | Generate from OpenAPI |
| 87 | Medium | Packages | Shared auth package placeholder risk | Mature or remove |
| 88 | Partial/Medium | License | SBOM artifact exists; license review is still missing | Add license audit/gate |
| 89 | Partial/Medium | Dependency | Digest-pinned non-root runtime and `pip-audit` artifact added; multi-stage/minimal/scanning posture incomplete | Add multi-stage/minimal runtime, scanner, and signing |
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
| Architecture | 62 | 78 |
| Security | 57 | 84 |
| Scalability | 49 | 61 |
| Reliability | 55 | 74 |
| Governance | 72 | 89 |
| Code quality | 68 | 78 |
| Enterprise readiness | 43 | 63 |

## Customer Survival Verdict

Could Operious survive 10 customers?

Yes, as a controlled pilot platform with verified bearer auth, production readiness gate enabled, manager-approved commerce-stub DI fixed or disabled, risky features constrained, live tenant isolation checks archived, and manual monitoring.

Could Operious survive 100 customers?

Not safely as a general production platform today. A narrow non-regulated pilot cohort is plausible after the approval DI fix and Phase E proof, but queue, provider, support, compliance, and production verification gaps would surface quickly outside a constrained scope.

Could Operious survive 1,000 customers?

No. The architecture has promising primitives but lacks hard operational, compliance, scaling, and isolation guarantees.

Would I allow Anker production operations?

No, not production. I would allow a scoped pilot after the approval DI fix and Phase E environment checks, with irreversible refund/replacement side effects constrained behind proven connectors.

Would I allow Samsung production operations?

No. Enterprise change control, compliance evidence, and integration hardening remain below bar.

Would I allow Microsoft production operations?

No. Auth/RBAC code improved, but live proof, supply chain, audit, and compliance posture remain below bar.

Would I allow Amazon production operations?

No. Scale, abuse resistance, isolation proof, and operational rigor are not close enough yet.
