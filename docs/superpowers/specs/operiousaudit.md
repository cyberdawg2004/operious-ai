# Operious AI Full Repository Audit

Date: 2026-05-31
Current-state update: 2026-07-05, after post-Phase-2.2 security hardening, Stage 3b connector proof tooling, default-auth/stub/CORS/seeded-replay/action-approval fixes, MVP-1 extraction-schema agnosticism, MVP-2 generic action-registry agnosticism, MVP-3 through MVP-9 governed intelligence work, tenant-config payload validation, frontend schema/role editors, Phase 0 release-hygiene / no-stub production-fail-closed review, and partial S-10 live-production evidence capture.
Auditor: Codex static architecture/security review
Audited HEAD: `cccd538` (`fix(lint): remove unused import in test_rls_null_tenant_hardening`)
Working-tree note: this update reviews committed changes through `cccd538`, including the committed MVP/intelligence-layer work, CORS fail-closed fallback removal, malformed auth/authority parse coarsening, callback HMAC protection, raw-body callback wiring, S-10 v235 evidence files, zero-warning pyright cleanup, compliance/ops docs, and the RLS nullable-tenant hardening invariant. The current working tree still has audit/test/evidence edits: `apps/backend/tests/test_system_smoke.py`, `apps/backend/tests/test_authority_context_coarsening.py`, `docs/pilot-readiness-evidence/manifest.json`, untracked `docs/pilot-readiness-evidence/2026-07-05-smoke-trace.json`, and this audit file. Local ignored artifacts `audit-artifacts/`, `aws/`, `awscliv2.zip`, and `infra/` are still not production readiness evidence. Generated `__pycache__`/`.pyc` files must remain uncommitted. `docs/operiousaudit.md` was moved to `docs/superpowers/specs/operiousaudit.md`.
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
- The action-approval DI gap is now closed in current code: the case/manager approval service factory threads `settings.allow_stub_actions_effective` into `build_tenant_action_tool_registry()`, and `test_action_fail_closed.py` guards that wiring.
- Crisis/escalation handoffs are more durable: committed code adds a durable crisis action handoff path, regression coverage for the handoff wiring, escalation runtime/outbox/router tests, and cognition/escalation audit coverage.
- Data protection is materially stronger: sensitive write/read paths are wired through data protection, a dry-run-first backfill path exists, FK targets are registered for backfill flushing, and GCP KMS custody for the data-protection master key is now committed. Formal compliance still needs live evidence.
- Knowledge upload and ingestion now flow through governance, encryption-at-rest, quarantine/review, Command Center upload/review surfaces, and automatic approval only when the governance change-request apply path is used. The direct-write button has been removed.
- Resolution safety is stronger: tenant-defined taxonomy/autonomy policy fails closed for unclassified categories, auto-send refusals are terminal/logged, worker-level safety floors escalate P0/CRISIS regardless of model category, and governance denial observability now surfaces the real reason.
- Queue/outbox reliability improved: ingress outbox replay resets DLQ state, dead-letter writes are idempotent by task identity, outbound-send reconciliation resolves stale claims from outbox evidence, webhook nonce cleanup backlog growth is signaled, and worker concurrency/import issues were fixed.
- The connector/OMS/RLS patch is now committed: generic REST warranty/replacement connector safety, OMS credential update proposals with ciphertext-hash sentinels only, `tenant.connector.approve`, Auth0 role/permission mapping for connector approval, and `FORCE ROW LEVEL SECURITY` on `connector_configs` are in tracked code and DB-tested.
- Customer attachment ingestion is now a real substrate: tenant attachment records, DB/S3 blob abstraction, size/type/hash controls, tenant RLS, retention/purge/stream controls, email attachment capture, SES large-email fetch, and WhatsApp media two-hop fetch all exist in committed code.
- Diagnostic cognition is now multimodal for stored attachments: vision message construction, structured extraction, one-shot malformed-JSON self-correction, fail-closed ambiguity handling, and truncation escalation are committed and covered by targeted tests. Live Anthropic/S3 proof remains skipped without production credentials.
- Warranty/refund W0-W4 is now implemented in committed code: tenant message templates, eligibility verification, recommended remedy selection, generic `inventory.check`, availability-gated remedy selection, cannot-determine probe draft-for-review, manager grounding/evidence UI, approve/reject wiring, and governed case-approval auto-delivery.
- Case approval delivery was materially hardened after Phase 2.2: the reconciler now delivers eligible approved cases, preserves already governed replies, records a dedicated delivery-authorization decision, closes the decision-id collision/dual-surface gap, and returns clean API errors for denied bound actions.
- Deployment/runtime hardening moved forward: release-command migrations are wired before traffic shift, web memory is raised to 1024 MB, queue-depth snapshot failures are isolated per queue, queue-age sentinel add/remove races are fixed, shared `httpx` clients are recreated when event loops change, GCP master-key unwrap is threaded through all GCP backend call sites, and `pypdf` is bumped for GHSA-jm82-fx9c-mx94.
- Governance/action safety improved after the prior update: scope-less verified principals are rejected, human approval is enforced for money/goods commitments, the money/goods reply-text floor now fails closed on novel wording, and safety-relevant policy types are forced through dual control instead of being treated as generic/low-risk config.
- Customer-reply quality and safety improved: bundled asks are split into per-segment questions, template placeholder fail-open behavior is closed, WhatsApp citation leakage is fixed, customer-facing labels are friendlier, and local-override denials no longer end in an escalation dead end.
- Approval delivery reliability improved: the case-approval outbox now has a real email consumer, failed outbox rows are requeued so they retry, and stuck pending execution-outbox rows can be reclaimed after failed retry attempts.
- Stage 2/3 connector architecture is committed: action governance metadata is generalized, generic connector/operation definitions model read vs act, idempotency, request/response mappings, commitment kind, approval policy, and target-resource expressions, and the Stage 3 path proves real external calls through the generic connector model.
- The committed post-audit hardening cluster closes several high-risk defaults and edge cases: `AUTH_ENABLED` defaults on and is production-gated, seeded-replay governance has binding HMAC plus TTL, concurrent action approval is race-guarded, `allow_stub_actions` defaults fail-closed, money/goods actions fail closed without a connector ledger, `warranty_claim` is classified as `GOODS`, `max_tool_invocations` defaults to `50`, connector exceptions are sanitized, the cognition-audit null-key fallback is removed, ingress fields have size caps, rate-limit-off emits a warning, action-approval `status_filter` is an enum, CORS has production readiness gating for explicit origins, and the old hardcoded CORS fallback is now removed so an unset CORS allowlist fails closed.
- Auth/authority reconnaissance hardening is materially better: malformed `Authorization` headers, malformed legacy `X-*-ID` headers, verification-unavailable responses, and disabled legacy authority responses coarsen in production. The previously open #25 malformed-parse leak is code-closed with regression tests.
- Provider callback origin protection is stronger: work-order fulfillment callbacks can be bound to a tenant connector `callback_hmac_secret`, the router passes the raw body into the receipt service, and the service verifies `X-Operious-Signature` using HMAC-SHA256 before recording the receipt when a secret is configured.
- Edge rate-limit client-IP behavior is code-correct for Fly-style proxying: `resolve_client_ip()` uses `Fly-Client-IP` only when the immediate peer is in `TRUSTED_PROXIES` and ignores spoofed headers from untrusted peers. Live rate-limit bucket proof against the currently deployed commit is still not archived.
- RLS defense-in-depth improved: the new static invariant requires every direct FORCE-RLS tenant table in the model map to have `tenant_id nullable=False`, reducing the risk created by the policy helper's historic `row_tenant_id IS NULL OR ...` branch.
- Type hygiene improved materially: `pyright -p pyrightconfig.json` now reports `0 errors, 0 warnings, 0 informations` at current HEAD, not merely zero errors with warning debt.
- Phase 0 closes a real production-default gap found in review: the LLM factory no longer falls back to the deterministic diagnostic client in production when Anthropic credentials or Bedrock region are missing. It now raises a configuration error under production settings, with regression tests. Phase 0 also fixes the generic connector credential bridge so production tenant channel credentials can be used by `GenericConnectorTool` instead of failing through a mismatched credential-runtime interface.
- Current committed MVP work makes the product less commerce-hardcoded: tenant taxonomy can define extraction schemas, diagnostic extraction is schema-gated, warranty/refund policy can use semantic role mappings, custom tool names can be configured with required commitment kind, money/goods custom actions require human approval, and generic payload/target metadata is passed through instead of forcing e-commerce fields.
- The new governed LLM agent scaffold and fraud-detection agent are useful architecture pieces: governance runtime hooks, proposal/policy records, fail-closed policy denial, persistence hooks, and fraud-signal act types now exist. This is a scaffold/MVP, not yet proof of a complete production intelligence substrate.
- Tenant config change requests now fail earlier and more clearly for invalid enum, UUID, datetime, extraction-schema, and role-mapping payloads; frontend builders normalize status strings to lowercase wire enums; router errors return a clear `400 tenant_config_change_request_invalid` for validation failures.
- Connector configuration testing now has an explicit `probe_http=false` default with opt-in `probe_http=true` GET probing through the same SSRF-pinned transport. This is useful for live egress evidence but remains an operator-controlled live call.
- The forensic line-audit artifacts found no P0/P1 issue, but still identify valid defense-in-depth and hygiene findings: nullable tenant/RLS semantics need continued DB-level hardening even after the new static invariant, Vercel/Fly CORS release posture still needs archived live-origin proof, 522 tracked dead duplicate Python files under the Next.js app trees remain a repo hygiene issue, owner-session/RLS-off caveats remain, duplicate frontend API clients remain, and local AWS/Terraform artifacts are not release-clean evidence.
- S-10 is still open, but it is no longer "no live proof." A partial live-production bundle is archived for Fly release v235 / commit `c65fda5`: direct spoof rejection, production readiness READY, one-table production-role RLS isolation, workers/DLQ proof, and worker/smoke pipeline progress. It does not close S-10 for current HEAD `cccd538` because full current-head deployment evidence, current Auth0 `/auth/me` proof, full production FORCE-RLS catalog proof, CORS/rate-limit live proof, and a clean provider-completing smoke are still missing.

The blocking issue has shifted again. It is no longer "there are no controls," "there are no side-effect ledgers," "manager approvals can silently use fake-success stubs," "connector credential/RLS work is only local," "generic connectors are only a model," "the product can only express warranty/refund e-commerce fields," "CORS can silently fall back to hardcoded origins," or "#25 malformed auth parse leaks are still open." The blocker is current-head live proof, operational completeness, provider maturity, and repo/infra hygiene. `S-10` remains open because the archived live bundle was captured against deployed `c65fda5` / Fly v235, while the audited repo HEAD is `cccd538`, and because the bundle still lacks full current Auth0 `/auth/me` proof, full production FORCE-RLS catalog proof, archived CORS/rate-limit live proof, and a clean provider-completing smoke. Remaining review caveats: data-protection controls need KMS/retention/legal-operation proof before compliance claims, live S3/Anthropic/provider drills are not clean, the 2026-07-05 smoke trace reached the diagnostic worker but failed all retries on an Anthropic HTTP 400, nullable-tenant RLS policy semantics need continued DB-level hardening, the new frontend advanced raw-JSON override is display-only unless submit handling is wired, dead duplicate Python trees and local ignored AWS/Terraform artifacts remain, and the current smoke test suite still has a local DB/resource-lifespan timeout that is not counted as a pass.

Final status: safer for controlled internal demo and a tightly scoped non-regulated pilot with irreversible actions constrained behind governed connectors. Still not safe to call enterprise-production-ready for Anker/Samsung/Microsoft/Amazon operations until S-10 is recaptured against current HEAD, live provider drills pass, full FORCE-RLS/CORS/rate-limit live proof is archived, repository/infra cleanup is complete, DR/SLO proof is stronger, and compliance evidence is operational rather than mostly documentary.

## Scope And Evidence

Repository traversal now finds 2,793 discoverable files via `rg --files`. This reflects the tracked hardening/MVP/S-10/compliance commits plus current uncommitted audit/test/evidence edits, while local ignored `aws/`, `awscliv2.zip`, `infra/`, and `audit-artifacts/` still exist on disk.

Top-level inventory:

| Area | Count | Notes |
| --- | ---: | --- |
| `apps` | 2,580 | Backend, command center, platform console, marketing, connector, attachment, approval, warranty/refund, intelligence/governed-agent, and test changes |
| `packages` | 77 | TS shared/types/contracts/sdk/ui/auth/tracing/topology/observability |
| `docs` | 103 | Architecture, runbooks, compliance docs, readiness evidence, current audit under superpowers/specs, and intelligence-layer build plan |
| `tests-frontend` | 22 | Static frontend architecture tests |
| local ignored/artifact residue | n/a | `audit-artifacts/`, `aws/`, `awscliv2.zip`, `infra/`, generated `.next`/`node_modules` content, and generated Python bytecode are not product evidence; Phase 0 removes generated backend `__pycache__`/`.pyc` before handoff |

Backend implementation inventory:

| Backend area | Files | Notes |
| --- | ---: | --- |
| `boundary` | 161 | Ingress/egress, adapters, voice, language, media, fulfillment callback normalization |
| `attachments` | 11 | Tenant attachment metadata, blob storage abstraction, retention/purge/stream controls |
| `approvals` | 16 | Case approval delivery/reconciliation and customer-reply authorization |
| `coordination` | 98 | Topology, routing, policies |
| `_deprecated` | 0 active | Deleted by `7731f5a`; invariant tests prevent recreation/imports |
| `api` | 65 | FastAPI v1 routers |
| `cognition` | 19 | Diagnostic LLM, vision/multimodal message support, structured extraction |
| `organizational_intelligence` | 56 | Intelligence/learning subsystems |
| `hardening` | 55 | Metrics, alerts, operational hardening |
| `governance` | 51 | Policy chains, enforcement, decisions, capability runtime, intelligence capability acts |
| `session` | 50 | Timeline/session lifecycle |
| `agents` | 61 | Runtime, tools, action governance, connector invocation ledger, warranty/replacement connector work, generic connector operations, governed LLM/fraud scaffolds |
| `arbitration` | 41 | Evaluators and records |
| `supervisor` | 37 | Supervisor inspections and projections |
| `services` | 40 | Tenant config, lifecycle, ingress, outbound, enrichment, fulfillment receipt, credential-update/service hardening |
| `runtime` | 35 | Resolution governance, grounding, conversation generation, warranty/refund policy/runtime |
| `workers` | 24 | Celery tasks, recovery, S-10 probe tasks, queue hardening |
| `execution` | 17 | Durable execution authority |
| `knowledge` | 17 | Knowledge ingestion/retrieval/vector runtime |
| `tenant` | 20 | Tenant config runtime/persistence/credentials/lifecycle/connectors |
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
| `eb74b55` | Commerce action stubs fail closed when `allow_stub_actions=False`; production settings derive that default and the diagnostic worker passes it. |
| `fe5451d` / current services wiring | Action-approval/case-approved orchestration now also passes `settings.allow_stub_actions_effective` into the tenant action tool registry; regression guard checks the source wiring. |
| `b9f1c5f` / `bf0bced` | Durable crisis action handoff path and regression guard for durable crisis handoff wiring. |
| `6955048` | GCP KMS custody path for data-protection master key. |
| `d0a1d56` / `ff31704` / `39595c0` / `428f900` / `d20cd21` | Data protection wired into sensitive read/write sites and worker coordination, with backfill and readiness fallback/recurrence fixes. |
| `e60bf9d` / `f1a959a` / `9d7cdd3` / `f346f82` | Tenant-defined resolution taxonomy/autonomy, auto-send refusal terminal logging, P0/CRISIS worker safety floor, and real governance denial reason observability. |
| `466ed30` | Critical-path inbound -> governed-outbox E2E coverage. |
| `06dd1de` / `f0b78b2` / `67380c5` / `2c61879` | Nonce backlog signal, ingress DLQ replay reset, idempotent dead-letter writes by task identity, and outbound-send stale-claim reconciliation. |
| `561c0a9` / `9c6a54a` / `05361ff` / `2df23ea` | Worker import fix, voice-worker memory fit, CloudAMQP volume reduction, and Fly SME approval queue consumption. |
| `82df8cb` / `e51be3a` / `aa6cac5` | Dependency/license review gates, CI-gated manual deploy, patched vulnerabilities, and logout invariant restoration. |
| `9675e79` / `7ee7b52` / `dd84b76` / `5914f4b` | Knowledge upload/ingestion through governance and encryption-at-rest, Command Center upload/review surfaces, governance-apply auto-approval, and removal of the direct-write button. |
| `17d1565` / `04d130a` / `314869c` / `cf21fd7` / `1227b9d` | Tenant connectors, execution safety test endpoint, OMS credential dual-control storage/update route, connector self-service UI, connector approval mapping, and `connector_configs` FORCE RLS proof are committed. |
| `6d7b131` / `2c8fa65` / `19a2adb` / `e2ef554` | Customer attachment storage foundation, email attachment capture, SES large-email fetch, message-id attachment linkage, and Meta WhatsApp media capture with two-hop fail-soft fetch. |
| `a6fba4c` / `afa8cc6` / `b35dc8e` / `b5148ae` | Vision over stored attachments, structured extraction with fail-closed eligibility gating, malformed JSON retry, and live Anthropic default model update. |
| `630a44e` / `f1c8bd9` / `7ad4b27` / `aaf8116` / `37d4a08` / `523ec1f` / `d5c204b` / `f414c04` / `3ec84fa` / `f055224` / `06dad33` | Warranty/refund W0-W4: tenant message templates, eligibility verification, remedy recommendation, approval queue wiring, generic `inventory.check`, availability-gated selection, manager read-only grounding UI, approve/reject, cannot-determine probe draft, and evidence-source propagation. |
| `e05a13b` / `f9851ae` / `ae7e749` / `213793b` / `6963308` / `8552954` / `a7959d4` | Case approval path now delivers eligible governed replies, wires resolution governance into reconciliation, closes decision-id/dual-surface gaps, preserves already-governed replies, records dedicated delivery authorization, and auto-sends after case approval when eligible. |
| `5a35b2a` / `379375e` / `ae70576` / `910b9b5` | Verified principal and governance hardening: reject scope-less principals, enforce human approval for money/goods, fail closed on novel money/goods reply wording, and close dual-control bypass for safety-relevant policy types. |
| `c4311f2` / `3561294` | Repository hygiene: chronically dirty worktree cleanup and tracked tooling/stale-audit artifact removal. Local ignored AWS/Terraform/audit artifacts still exist on disk and remain non-evidence. |
| `dcac039` / `7aafb16` / `33d7247` / `b245589` / `1e9b4f9` | Pilot-readiness walk harness plus grounding/override false-positive fixes; useful pilot evidence but not a substitute for S-10 production verification. |
| `37490e3` / `ee06c91` / `4efa6b1` / `138475d` / `c8634dd` / `9718efe` / `ca2670a` | Reply and generation quality/safety: topical keyword grounding fixes, bundled-ask splitting, brand-specific fallback cleanup, template placeholder fail-closed behavior, WhatsApp citation leak closure, and customer-friendly labels. |
| `e5d22dd` / `4a33009` / `dfad4c9` / `1bd0992` / `a0a7002` / `d9954c5` | Approval/outbox reliability and UI clarity: local-override denial escalation path, real case-approval email consumer, rebuilt consumer, failed-row requeue, stuck execution-outbox reclaim, and clearer approval tabs/notifications. |
| `765941f` / `d05e4b2` | CodeQL workflow added and security alert backlog triaged. These improve process posture but do not replace live S-10 proof. |
| `dd5bb65` / `ffe1f7b` / `4f44686` / `4c30be0` / `e71e536` | Per-claim-type warranty windows, generalized action governance metadata, generic connector + operation model, Stage 3 real external calls through the generic connector model, and lint cleanup. |
| `baa0e31` / `09b9d02` / `db6eae9` / `690c372` / `57aa3d3` / `65c6e5d` / `05991a3` / `014111d` / `874147f` / `857c1f1` | Stage 3b proof path: connector probe/test endpoints, route fixes, real-tenant path scoping, pending-change detection, and legitimate dual-control flow for connector configuration. |
| `f15b5d7` / `5288eec` / `d3b7b6e` / `c34e839` / `9216447` / `026cd63` / `b715622` / `7b82cd6` / `6ba9143` / `af92c13` / `387edc5` / `f42a1f5` / `c036bba` / `fae4d8d` / `3ca6e99` / `50db697` / `98bfdc2` / `fc5824a` / `f416063` | Phase-1/2 security hardening and cleanup: sanitized connector exceptions, null-key encryption fallback removal, dual-control enforcement, enum validation, ingress size caps, rate-limit-disabled warning, auth-enabled default/prod gate, seeded-replay HMAC+TTL, approval race guard, stub-action fail-closed default, CORS production gate/localhost removal, tool invocation cap, warranty-claim `GOODS` reclassification, money/goods connector-ledger fail-closed behavior, and pyright cleanup. |
| `2113e01` / `2d42cd0` / `9b29e0a` / `c65fda5` / `c1f39f5` / `244e32e` / `57e5b88` / `cccd538` | Current committed Phase-1/2 extension: MVPs 1-9 committed, malformed auth/authority parse coarsening code-closed, fulfillment callback HMAC added, raw callback body/repository wiring fixed, hardcoded CORS fallback removed, S-10 v235 evidence captured, pyright warning count reduced to zero, ops/compliance docs added, and RLS nullable-tenant static invariant linted. |
| Current uncommitted audit/test/evidence work | Smoke-test env isolation, coarsening-test direct-ASGI harness, corrected S-10 evidence manifest, untracked 2026-07-05 partial smoke trace, and this audit update. These are not committed repository state until staged and committed. |
| `c23421c` / `77253d4` / `bdc2369` / `f133f7f` / `2a998c8` / `16978e0` / `803a3f4` / `d56db3d` | Queue/admission/deploy/runtime hardening: queue-age race fix, queue snapshot per-queue isolation, truncated completion escalation, event-loop-safe shared HTTP client, GCP unwrap call-site coverage, Fly release command, web memory increase, and deploy-stop bug evidence package. |
| `3f27604` / `8ac83ac` / `b8a93cf` | Security/test hygiene: `pypdf` bumped to 6.13.3 for GHSA-jm82-fx9c-mx94 and pre-existing pyright/vision-test format issues corrected. |
| `audit-artifacts/forensic-line-audit/12_final_report.md` | Untracked forensic audit artifact reviewed. It reports no P0/P1 findings. Current code removed the hardcoded CORS fallback and added nullable-tenant static coverage, but live CORS proof, continued nullable/RLS DB hardening, F-001 dead duplicate Python trees, F-011 owner-session caveat, and F-012 duplicate frontend clients remain open. |
| Local untracked `infra/`, `aws/`, `awscliv2.zip` | Not product evidence. Terraform contains placeholder DB passwords and open ingress/public-IP defaults; AWS CLI archive/vendor artifacts are repo hygiene/supply-chain blockers. |

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
| Frontend architecture/onboarding/platform-console invariants | `npm run test:frontend -- tests-frontend/src/command-center2-config-governance.test.ts`: `127 passed` after sandbox IPC restriction was bypassed with approval |
| Per-tenant action governance | Codex rerun: `4 passed in 0.69s` |
| Resolution grounding/conversation proposal unit bundle | Codex rerun: `36 passed, 2 skipped in 1.06s` |
| Connector framework non-DB/socket-gated bundle | Codex rerun: `3 passed, 3 skipped`; skips were DB gating and sandbox loopback bind limits |
| Action-approval fail-closed DI guard | Reported/user proof: `test_action_fail_closed.py` `5 passed`; `test_action_approvals.py` `7 passed`; ruff clean; pyright `0 errors` |
| Escalation/cognition/crisis handoff | User normal-shell proof: `test_escalation_router.py`, `test_cognition_audit.py`, `chaos/test_diagnostic_terminal_escalation.py` -> `11 passed in 3.82s`; broader escalation/Auth0/tenant lifecycle bundle -> `46 passed in 5.20s` |
| Connector dual-control and warranty/replacement connector code | Codex rerun: `test_connector_dual_control.py` -> `17 passed in 2.30s`; unsandboxed loopback/TLS rerun of `test_warranty_replacement_connector.py` -> `11 passed in 1.60s` after correcting stale assertions to the project `ToolInvocationResult(status=...)` contract |
| OMS credential storage | User normal-shell proof: `test_oms_credential_storage.py` -> `12 passed in 3.81s` |
| Connector RLS and RLS invariant | User normal-shell proof: `test_connector_rls.py`, `test_rls_coverage_invariant.py` -> `6 passed in 0.52s`; focused latest proof `test_connector_rls.py::test_connector_configs_force_rls_flags` -> `1 passed in 0.13s`; Codex alembic check reached current head `0092_resolution_verdict_template_purpose_rename` |
| Connector approval/Auth0 capability mapping | User normal-shell proof: `test_authz_domain_capabilities.py` -> `46 passed in 4.29s`; Codex pyright `0 errors`, ruff clean on touched auth/connector/service/test files |
| Full backend lint | Codex rerun: `venv/bin/ruff check apps/backend/app apps/backend/tests` -> `All checks passed!` |
| Backend type check | Current pyright at audited HEAD/worktree: `pyright -p pyrightconfig.json` -> `0 errors, 0 warnings, 0 informations` |
| S-10 partial live production evidence bundle | Committed evidence captured against Fly v235 / commit `c65fda5`: `2026-07-05-spoofing-pass.json`, `2026-07-05-readiness-ready.json`, `2026-07-05-rls-pass.json`, `2026-07-05-workers-dlq-pass.json`; manifest repaired in the working tree and validates as JSON |
| S-10 partial smoke trace | Untracked `2026-07-05-smoke-trace.json` validates as JSON and shows Auth0 bearer/tenant extraction, ingress, session creation, dispatch, diagnostic worker pickup, and retry behavior, but final diagnostic completion failed after Anthropic HTTP 400 |
| Auth coarsening, callback HMAC, Fly client-IP, production readiness, nullable-RLS invariant | Codex rerun after test-harness fix: `test_rls_null_tenant_hardening.py`, `test_authority_context_coarsening.py`, `test_fulfillment_callback_hmac.py`, `test_edge_client_ip.py`, `test_production_readiness.py` -> `78 passed in 2.92s` |
| Individual new hardening proof | `test_authority_context_coarsening.py` -> `8 passed in 0.12s`; `test_fulfillment_callback_hmac.py` -> `14 passed in 1.52s`; `test_edge_client_ip.py` -> `6 passed in 0.24s`; `test_production_readiness.py` -> `23 passed in 1.16s`; `test_rls_null_tenant_hardening.py` -> `27 passed in 1.60s` |
| Deterministic agent multimodal regression coverage | Codex rerun: `test_generated_sme_reviewer.py`, `test_cognition_audit.py` -> `6 passed, 3 skipped`; skips require `TEST_DATABASE_URL` |
| Committed connector/OMS/RLS DB bundle | Unsandboxed Codex rerun: `test_connector_rls.py`, `test_rls_coverage_invariant.py`, `test_oms_credential_storage.py`, `test_oms_credential_http_route.py` -> `21 passed in 41.72s` |
| Case/action approval auto-delivery bundle | Unsandboxed Codex rerun: `test_case_approval_auto_send.py`, `test_case_approval_recovery_tasks.py`, `test_case_approval_workflow.py`, `test_action_approval_case_completion.py`, `test_action_approvals_router.py`, `test_warranty_refund_approval_wiring.py`, `test_warranty_refund_approve_reject.py` -> `64 passed in 3.87s` |
| Attachment/email/WhatsApp media/vision/structured extraction DB bundle | Unsandboxed Codex rerun: `45 passed, 9 skipped in 63.06s`; skips require real S3 bucket/region/credentials or live `ANTHROPIC_API_KEY` |
| Warranty/refund workflow and connector bundle | Unsandboxed Codex rerun: `test_warranty_refund_eligibility.py`, `test_warranty_refund_eligibility_resolution_runtime.py`, `test_warranty_refund_policy.py`, `test_warranty_refund_probe_dispatch.py`, `test_warranty_refund_remedy_selection.py`, `test_inventory_check_connector.py`, `test_warranty_replacement_connector.py` -> `118 passed in 7.77s` |
| Diagnostic parsing/truncation/model-default bundle | Codex rerun: `test_diagnostic_json_parse_self_correction.py`, `test_diagnostic_parsing_failure_classification.py`, `test_diagnostic_truncation_escalation.py`, `test_resolution_verdict_override.py`, `test_anthropic_default_model_is_live.py`, `test_anthropic_client_circuit.py` -> `29 passed, 1 skipped`; skip requires live `ANTHROPIC_API_KEY` |
| Alembic migration state | Phase 0 unsandboxed Codex rerun: `alembic upgrade head`; `alembic current` -> `0097_mvp7_customer_identity_id (head)` |
| Stage 3 generic connector unit tests | Codex rerun: `test_generic_connector.py` -> `14 passed in 1.64s` |
| Stage 3 generic connector live external-call tests | Unsandboxed Codex rerun: `test_generic_connector_live.py` -> `12 passed in 7.37s` |
| Tenant-config validation regressions | Unsandboxed Codex rerun of new enum/datetime/router 400 tests -> `3 passed in 15.62s` |
| Frontend config governance/status normalization | Unsandboxed Codex rerun: `npm run test:frontend -- tests-frontend/src/command-center2-config-governance.test.ts` -> `127 passed` |
| Current MVP/intelligence/domain/action focused backend bundle | Phase 0 Codex rerun: `test_bedrock_llm_client.py`, production-readiness tests, action fail-closed, MVP-1 through MVP-9, governed LLM/fraud/SOP/QA/supervisor/repair tests, connector framework, and warranty/replacement connector tests -> `478 passed, 16 skipped in 8.51s`; skips are DB-required cases and sandbox loopback bind limits |
| Current production LLM/readiness bundle | Phase 0 Codex rerun: `test_bedrock_llm_client.py`, `test_production_readiness.py`, `test_check_production_readiness_script.py` -> `44 passed in 3.88s` |
| Current cross-policy integrity | Phase 0 Codex rerun with `TEST_DATABASE_URL=postgresql+asyncpg://operious:operious@localhost:5433/operious_test`: `14 passed in 1.63s` |
| Current DB migration head | Phase 0 unsandboxed Codex run: `alembic upgrade head` advanced the test DB through `0093` -> `0097`; `alembic current` reports `0097_mvp7_customer_identity_id (head)` |
| Current DB connector/tenant-config proof | Phase 0 unsandboxed Codex reruns: `test_connector_framework.py` -> `7 passed in 1.90s`; `test_warranty_replacement_connector.py` -> `22 passed in 7.78s`; `test_tenant_config_change_requests.py` -> `22 passed in 3.59s`; `test_tenant_configuration_router.py` -> `17 passed in 468.77s` |
| Current supervisor hardening proof | Phase 0 Codex rerun after sanitizer type fix: `test_mvp8_autonomous_supervisor.py` -> `45 passed in 1.77s` |
| Current frontend config governance/schema editor proof | Codex rerun outside sandbox IPC restriction with approval: `npm run test:frontend -- tests-frontend/src/command-center2-config-governance.test.ts` -> `127 passed` |
| Backend lint for current Python code | Phase 0 Codex rerun: `ruff check apps/backend/app apps/backend/tests apps/backend/scripts` -> `All checks passed!` |
| Backend type check after current cleanup | Codex rerun: `pyright -p pyrightconfig.json` -> `0 errors, 0 warnings, 0 informations` |

Non-clean verification:

| Scope | Result | Interpretation |
| --- | --- | --- |
| Full combined audit suite | Timed out at 300s | Not counted as a pass. Smaller bundles above are used as proof. |
| Prior voice auth plus load/capacity bundle | Previously `5 failed, 16 passed` | This is now repaired by `175dd52`; the current focused voice/canonical/load bundle passed. |
| Codex sandbox rerun of object-RBAC/app HTTP tests | Timed out entering `TestClient` lifespan | Not reproduced by user's normal-shell run (`13 passed`, `57 passed`). Likely local Redis/lifespan startup behavior; not counted as a code failure. |
| Codex sandbox rerun of DB bundle | Timed out after an early error marker | Superseded by user's exact normal-shell rerun (`42 passed`). Not counted as a code failure. |
| SSRF DNS-rebinding bundle in this sandbox | `3 failed, 2 passed` | Failures were sandbox loopback binding (`could not bind on 127.0.0.1:0`). The test file is now deterministic, but loopback-server cases still need normal-shell/CI proof before being claimed as locally green here. |
| Frontend invariant tests in sandbox | Failed before tests: `tsx` could not create `/tmp/tsx-1000/*.pipe` | Reran outside sandbox with approval; real result was `127 passed`. |
| Codex sandbox DB runs for connector/work-order files | Timed out after early pytest error marker, no traceback flushed before `timeout` | Not counted as a code failure; normal-shell/unsandboxed proof is used where provided. |
| Commerce action fail-closed DI coverage | Previously non-clean; now closed in current code | `apps/backend/app/dependencies/services.py:1014-1019` passes `allow_stub_actions=settings.allow_stub_actions_effective`; `apps/backend/tests/test_action_fail_closed.py:111-115` guards the wiring. |
| Codex sandbox DB run for embedding proof bundle | Timed out after an early marker, no traceback flushed before `timeout` | Superseded by the user's exact normal-shell rerun: combined retrieval/re-embed/FORCE-RLS bundle `8 passed in 1.06s`. |
| Live S3/Anthropic/provider proof | Skipped where credentials were absent | Attachment/vision code has local and DB proof, but live object-storage and live LLM evidence is not archived. |
| System smoke tests | `test_system_smoke.py::test_health_endpoint_live` emitted a passing dot but the pytest process timed out; `test_ticket_ingress_chain` timed out; direct DB probe to `localhost:5433/operious_test` also timed out | Not counted as a pass. This looks like local DB/resource-lifespan availability rather than a failed smoke assertion, but it must be made deterministic before using `test_system_smoke.py` as release evidence. |
| Live current-deploy provider smoke | `2026-07-05-smoke-trace.json` reached diagnostic worker/retry but ended `failed_all_retries` on Anthropic HTTP 400 | Not counted as a clean workflow pass. Fix live Anthropic model/key/request configuration and rerun smoke against current deployed commit. |
| Local infra/AWS artifacts | Still present on disk but not tracked evidence | Not counted as verification. `awscliv2.zip`, `aws/`, `infra/`, and `audit-artifacts/` exist locally/ignored; they are not release proof. |
| Current untracked helper residue | `apps/backend/scripts/test_http_probe.sh` remains untracked but was rewritten as an operator-configurable probe helper | Not product evidence unless intentionally reviewed/staged. It is excluded from Python lint/type proof because it is shell. |

Residual gaps update: S-01 through S-09 are no longer open original vulnerabilities. They are closed or closed-with-residuals as described below. The previous tenant-config `applied_by` regression is fixed and proven by DB-backed tests. The previous action-approval stub DI residual is fixed in current code and has a regression guard. The connector/OMS/RLS work is committed and DB-proven, Stage 3 generic connector calls now have unit plus live external-call proof, and the Phase 0 tenant-config DB/router proof is clean. The newer Phase-1/2 hardening commits are materially correct in the reviewed source. The hardcoded CORS fallback and #25 malformed-parse leak are now code-closed. S-10 remains open because the partial live evidence is not current-head-complete and does not include full Auth0 `/auth/me`, full production FORCE-RLS catalog, CORS/rate-limit live proof, or clean provider-completing smoke evidence. Remaining forensic/current residuals are nullable-tenant/RLS DB hardening, dead duplicate Python trees, owner-session/RLS-off assumptions, duplicate frontend clients, untracked/working-tree evidence edits, local ignored infra/AWS artifacts, and deterministic smoke/release evidence gaps.

## Spec 1b Edge-Hardening Remediation (2026-06-01)

Phase 1, spec 1b (`docs/superpowers/specs/2026-06-01-edge-hardening-design.md`,
plan `docs/superpowers/plans/2026-06-01-edge-hardening.md`) closed or
downgraded the following Top-100 findings **in code, with tests** (live
production proof remains part of Phase 3 / S-10):

| # | Finding | Disposition after spec 1b |
| ---: | --- | --- |
| 16 | CORS credential posture | Code-closed for fallback/config posture. CORS respects `CORS_ALLOW_CREDENTIALS` / `CORS_ALLOW_METHODS`, rejects wildcard origins, production readiness requires explicit `CORS_ALLOW_ORIGINS`, and `_build_cors_origins()` now returns an empty list rather than hardcoded origins when unset. Residual: archive live production origin/preflight proof against current deployed commit. |
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

Edge-hardening review update: #23, #24, #25, #39, #40, and #63 are now materially closed in code/tests. #16 is code-closed for fallback/config posture but still needs archived live production-origin proof. #38 is code-closed for the audited rate-limit/quota/admission paths, with live outage proof still required.

## Phase 1a-ext/1c/1d/1e Review (2026-06-02)

The latest committed tranche is materially correct at the production-code level. I did not find a new production-code blocker in the modified areas reviewed.

- Observability endpoints are gated on `tenant.observability.read`, audit export is gated on `tenant.audit.export`, and the broader object-RBAC sweep now covers sensitive tenant-scoped router modules with no allowlist. Functional RBAC proof passed in the user's normal shell.
- Public audit export verification has a 256 KiB endpoint cap. This bounds HMAC/verification work after request parsing; it is not a complete pre-parse body-budget control.
- Principal-bound conversation sessions now deny non-owner callers and allow operator bypass. Ownerless sessions still pass through under tenant authority, so ownerless/operator policy remains a residual rather than a closed enterprise object-policy story.
- Tenant config ledger apply attribution is fixed: `TenantConfigChangeRequestService.apply()` now requires and persists `applied_by`, `apply_config_change_request()` threads the approving principal into the service, response schemas expose the field, and DB-backed tenant-config tests pass. Approved-but-not-applied requests can also be revoked through `revoke()` and `/revoke`.
- Data-protection admin APIs are real: privacy-admin/approver gates, DSAR dual-control erasure, legal holds, retention policy management, envelope encryption, and FK/check constraints are implemented and DB-tested.
- Resilience controls are real: quota and queue admission fail closed when Redis-backed admission state is unavailable, webhook capture happens before processing admission, execution records bind governance config id/version/sha, completion-event emission failure records a DLQ task, and per-tenant queue QoS exists.
- Cleanup/hardening is real: the `_deprecated` package is deleted and guarded by invariant tests; backend Docker now pins the Python image digest and runs as non-root; CI emits SBOM and `pip-audit` artifacts.

Remaining fixes are not the old ledger regression. The real residuals are: recapture Phase E/S-10 live production proof against current HEAD, archive current-deploy real-client-IP rate-limit bucket behavior, run DNS-rebinding loopback tests in normal CI, clean the live Anthropic/provider smoke path, and avoid presenting data-protection controls as full compliance until KMS, retention/legal operations, and live erasure evidence are complete.

## Phase 2 Governed Operations Review (2026-06-17)

The Phase 2 changes are materially correct in the reviewed production-code paths. The previous commerce-action approval DI exception is now closed in current code; the remaining blockers are live provider proof, callback/provider-origin proof, S-10 production evidence, and repo/infra hygiene.

- Grounded resolution/conversation: Phase 2.0/2.1 adds citation span provenance, evidence-bound generation, central grounding governance, and escalation on ungrounded factual replies. The user's normal-shell governance/domain/Auth0/resolution/config-router bundle passed `112 passed, 10 skipped`.
- Connector side effects: Phase 2.2/2.3 adds a tenant-scoped connector invocation ledger, provider idempotency keys, generic REST refund connector, connector config records, credential redaction, SSRF validation/pin-to-IP transport, terminal replay semantics, committed warranty/replacement connector paths, committed OMS credential-update route, connector approval capability mapping, and `connector_configs` FORCE RLS proof.
- Tenant action/onboarding governance: Phase 2.4/2.5a-b moves action policy and connector configuration into the dual-control tenant-config change-request ledger with reconstruction hashes and write-only credentials. Read APIs are credential-free and capability-gated.
- Platform/tenant boundary: Phase 2.5c-d splits platform tenant creation from tenant configuration. `platform.tenant.admin` creates inert tenants in the Platform Console; Command Center onboarding is tenant-scoped config work only.
- Work-order dispatch: Phase 2.3.x-a/b/c adds a work-order ledger, explicit `created -> dispatched -> awaiting_fulfillment -> fulfilled/failed` transitions, connector-backed `repair.dispatch`, receipt-only callback ingress, and tenant-scoped fulfillment consumption. The user's normal-shell work-order dispatch substrate test passed `6 passed`.
- Commerce action stubs: `eb74b55` adds `ALLOW_STUB_ACTIONS`, `Settings.allow_stub_actions_effective`, and `FailClosedActionTool`. The diagnostic worker and action-approval/case-approved orchestration paths now pass the derived production setting into the tenant action registry. Reported focused tests passed `test_action_fail_closed.py` `5 passed` and `test_action_approvals.py` `7 passed`.
- S-10 prep: live verification probes, DLQ probe task, smoke trace probe, RLS table probe, spoof-rejection probe, and legacy Anker knowledge rewrap tooling exist. This is preparation, not closure.
- Embeddings: real OpenAI embedding support is now production-wired through `build_embedding_provider()` in API and worker composition, constrained to one 1536-dimensional native pgvector column plus HNSW index, and covered by provider, wiring, DB retrieval, tenant-isolation, and re-embed tests.

Residuals from this review:

- Fulfillment callback ingress is tenant-authenticated, receipt-only, and now supports connector-configured HMAC verification over the raw callback body. Residual: live provider callback signature proof and replay-window proof are still needed before broad provider-origin claims.
- Connector invocation ledger, connector RLS, OMS credential storage/route, repair dispatch, warranty/refund, and case-approval DB suites now have normal-shell/unsandboxed proof recorded above. S-10-prep now has partial live deployed proof, but not current-head-complete closure.
- OpenAI embeddings are code/test-closed for runtime wiring and dimension-aware pgvector retrieval. Remaining work is production rollout evidence: snapshot, migration, real-provider re-embed of the Anker documents, and retrieval confirmation.
- Live provider idempotency, live outbound private-IP blocking, current-deploy real-client-IP rate-limit bucket proof, and complete Phase E production verification remain outside local code proof.
- The warranty/replacement connector and OMS credential/RLS patch is no longer local-only; it is committed and locally/DB proven. It still needs CI and live-provider evidence before it can support production claims.
- The local AWS CLI archive/tree and Terraform scaffold should be cleaned before release work. Terraform placeholders/open ingress/public IP defaults are not acceptable production posture.

## Phase B/Current-State Review (2026-07-03)

The current work is materially stronger than the July 2 state. The committed hardening fixes close several ways a deployment could drift open by default, and the MVP/intelligence-layer work is now committed rather than just local scaffolding. The distinction has shifted: current committed code is stronger, but S-10 live deployment proof is only partial and was captured against `c65fda5`, not current HEAD `cccd538`.

- Post-audit hardening: auth now defaults on and is production-gated, stub actions default fail-closed, seeded-replay governance requires binding HMAC plus TTL, concurrent action approval is race-guarded, CORS has a production explicit-origin gate and no hardcoded fallback, default tool invocation count is capped, connector exception messages are sanitized, null-key cognition-audit encryption fallback is removed, ingress field sizes are capped, action-approval status filters are enum-validated, and malformed auth/authority parse errors coarsen in production.
- Callback and edge hardening: work-order fulfillment callbacks can require HMAC-SHA256 signatures, the router passes raw body bytes to verification, and Fly client-IP rate limiting is code/test-covered with trusted-proxy anti-spoofing. Live callback and rate-limit bucket proof remain required.
- Verification quality: current focused hardening bundle passes `78 passed`; ruff is clean on touched files; pyright is `0 errors, 0 warnings, 0 informations`; evidence JSON validates. `test_system_smoke.py` is non-clean locally because DB/resource-lifespan paths time out, and the 2026-07-05 live smoke reaches provider execution but fails all retries on Anthropic HTTP 400.
- Money/goods safety: `warranty_claim` is now classified as `GOODS`, money/goods commitments require human approval, and configured money/goods actions fail closed when no connector ledger exists. This closes a real class of "looks harmless but causes value movement" risks.
- MVP-1 extraction-schema agnosticism: tenant taxonomy can define extraction schemas, diagnostic extraction is schema-gated, out-of-schema fields are dropped, and legacy e-commerce defaults remain. This is the right direction for non-commerce tenants.
- MVP-1 warranty/refund role mapping: eligibility can use semantic roles such as `purchase_timestamp` and `authorized_seller` instead of hardcoded field names. That makes the workflow configurable, but it still needs production tenant examples and DB-backed tenant-config proof.
- MVP-2 action-registry agnosticism: custom tool names are accepted through tenant action policy, commitment kind is required, unknown/custom tools require approval, and metadata conflict checks catch misdeclared money/goods behavior. This is materially better than static e-commerce-only action names.
- MVP-3 governed-agent scaffold: `BaseGovernedLLMAgent`, proposal/policy records, governance runtime factory, and `FraudDetectionAgent` now exist and have focused tests. They are scaffolding for the intelligence layer, not a complete autonomous multi-agent production system.
- Command Center schema/role editors: the UI can edit extraction schema and warranty role mappings, and frontend invariants still pass. Caveat: the advanced raw JSON override in the warranty/refund editor is display-only unless submit handling reads `_parameters_raw_override`.
- Connector probing: the test endpoint defaults to TLS/SSRF validation only and performs a real pinned-IP HTTP GET only with `probe_http=true`. That remains an appropriate operator-controlled live evidence path.
- Verification quality: focused backend MVP/domain/action tests previously passed `478 passed, 16 skipped`; production LLM/readiness tests passed `44 passed`; supervisor hardening passed `45 passed`; DB-backed connector, warranty/replacement, tenant-config change-request, and tenant-configuration router tests passed; frontend config governance passed `127 passed`; current touched-file ruff is clean; current pyright is `0 errors, 0 warnings, 0 informations`; alembic test DB head evidence remains `0097_mvp7_customer_identity_id`.
- Phase 0 proof: the previous tenant-config DB file/subset uncertainty is closed in the unsandboxed Codex run (`17 passed in 468.77s`). The evidence is local test-DB proof, not production proof.
- Forensic/current residuals: nullable tenant columns plus `row_tenant_id IS NULL OR ...` RLS behavior remain defense-in-depth weaknesses even after the new static invariant; CORS code posture is better but still needs explicit live origin configuration proof; duplicate/dead tracked Python trees and local ignored AWS/Terraform artifacts remain release hygiene blockers; current untracked/modified evidence and test edits need review/commit.

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
- Generic connector/operation model with read/act modes, idempotency strategy, request/response mappings, operation governance metadata, commitment kind, approval policy, and target-resource expressions.
- Post-audit security hardening for auth/stub/action/CORS/replay defaults: `AUTH_ENABLED` production gate/default-on behavior, binding HMAC+TTL for seeded replay, concurrent approval race protection, `ALLOW_STUB_ACTIONS` default false, `max_tool_invocations=50`, and production CORS explicit-origin gate.
- Money/goods action safety backstops: `warranty_claim` is `GOODS`, custom money/goods tools require human approval, and money/goods actions fail closed when no connector ledger exists.
- Tenant-configurable extraction schemas and schema-gated diagnostic extraction with legacy e-commerce defaults.
- Warranty/refund semantic role mappings for tenant-specific extraction fields.
- Generic custom action registry support with explicit `commitment_kind`, approval defaults for unknown tools, metadata pass-through, and target-resource/payload construction not tied only to e-commerce fields.
- Governed LLM agent scaffold: base agent, governance runtime hooks, proposal/policy records, fail-closed governance denial behavior, persistence hooks, fraud-detection scaffold, and intelligence capability acts.
- Command Center extraction-schema and warranty-role-mapping editors with frontend invariant coverage.
- Per-tenant action governance loaded from tenant action-policy records.
- Governed connector-config and action-policy onboarding through the tenant config change-request ledger.
- OMS credential update route and connector credential update proposals store ciphertext-hash sentinels rather than secret plaintext in the change-request ledger.
- Connector approval capability `tenant.connector.approve` and Auth0 role/permission mapping are committed.
- `connector_configs` now has committed FORCE RLS migration/test coverage.
- Platform-gated inert tenant creation and separate Platform Console/Command Center onboarding responsibilities.
- Work-order dispatch ledger, explicit state machine, connector-backed `repair.dispatch`, and receipt-only fulfillment callback ingestion/consumer.
- Customer attachment storage, email attachment capture, SES large-email fetch, WhatsApp media fetch, stored-attachment vision, and structured extraction with fail-closed ambiguity behavior.
- Warranty/refund eligibility, remedy selection, generic `inventory.check`, grounded manager approval queue, approve/reject, and governed case-approval auto-delivery.
- Tenant config change-request proposal validation for enum, UUID, and datetime fields; frontend status normalization to lowercase wire enums.
- Opt-in connector HTTP probing through SSRF validation and pinned-IP transport.
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

- Production proof is partial: spoof rejection, one-table RLS, readiness, and worker/DLQ evidence are archived for Fly v235 / `c65fda5`, but current-head Auth0/RLS/FORCE-RLS/CORS/rate-limit/provider-smoke proof is not complete.
- Auth-error coarsening is code-closed for the audited authority-state and malformed-parse paths.
- Voice auth/cap controls are closed, but production token issuance UX/API and real STT/TTS provider proof remain incomplete.
- Action grants and the connector invocation ledger are much stronger. Real external connector side effects now have refund/repair/work-order plus committed warranty/replacement connector paths, but live provider idempotency drills and provider-origin callback signatures remain.
- Quotas include diagnostic token-per-minute enforcement, fail-closed pre-call Redis policy, queue admission, and inbound request rate limiting; idempotent rate-limit reads still degrade open by design, per-IP limiting may key the Fly proxy peer, and quota is not a universal enterprise budget system.
- RAG poisoning controls exist, but human review UX, adversarial evals, and source-trust workflows remain immature.
- Real OpenAI embeddings are wired into API/worker runtime composition with a 1536-dimensional native pgvector/HNSW path and re-embed tooling. Production rollout evidence remains pending.
- Data-protection controls exist, but enterprise compliance remains partial until KMS/key custody, legal operations, retention jobs, live DSAR evidence, and access-control workflows are proven.
- Broader object RBAC now covers selected sensitive tenant-scoped surfaces, but live Auth0 mapping, uncovered/future route coverage, and production alert/health/readiness checks are not live-proven.
- Marketing/command-center/platform-console proof improved materially, but public external validation, compliance proof, status/SLA pages, and some demo residue remain.
- MVP-1 through MVP-9 domain-agnostic and governed-agent work is focused-test proven, but still uncommitted in this working tree and not yet live-provider/prod-composition proven.
- The governed LLM/fraud/SOP/QA/supervisor/repair work is a scaffold with governance/persistence hooks; it is not yet a complete intelligence layer with live model evals, production routing, or operator workflow.
- Tenant-config DB validation proof for the latest schema/role-mapping/router paths is now clean in the Phase 0 unsandboxed Codex run. This is local test-DB evidence, not production evidence.
- The Command Center advanced raw JSON override for the warranty/refund editor appears display-only unless submit handling reads `_parameters_raw_override`; this is UX/quality debt, not a security closure.

What is mocked/stubbed:

- Voice STT/TTS paths still rely on stub-like providers unless production providers are configured.
- Commerce actions are mixed but materially stronger: generic REST `refund.request`, `repair.dispatch`, warranty/replacement, `inventory.check`, and the new generic connector/operation model exist; unconfigured automatic and manager-approved actions now inherit the production fail-closed stub policy; warehouse remains unintegrated; production provider drills remain missing.
- Diagnostic LLM deterministic fallback remains available for local/test behavior, but Phase 0 closes the production path: missing Anthropic credentials or Bedrock region now raise configuration errors under production settings.
- Shopify enrichment can fall back to deterministic stub behavior.
- Translation defaults/fallbacks can behave as identity outside configured production posture.
- Knowledge embeddings use the real OpenAI provider in production composition when `EMBEDDING_DEFAULT_PROVIDER=openai` and `OPENAI_API_KEY` are configured; deterministic embeddings remain only as explicit fallback/test behavior.
- Command center still contains proof/demo-oriented data.

What is planned/missing:

- Phase E live production verification for S-10.
- Real production STT/TTS and call initiation/token issuance flow.
- Production provider integration drills and idempotency contracts for generic/refund/repair/warranty/replacement connectors.
- Production execution of the real-embedding rollout: snapshot, migrate, re-embed the Anker docs with OpenAI, and archive retrieval/eval evidence.
- Provider-origin signature/replay protection for public fulfillment callbacks.
- CI-prove and live-provider-prove the committed warranty/replacement connector, OMS credential update, connector approval, connector RLS, and generic connector operation model.
- Harden nullable-tenant RLS semantics: backfill/repair nullable tenant rows, set tenant IDs NOT NULL on FORCE-RLS tenant tables where business semantics require tenancy, and remove or narrow the `row_tenant_id IS NULL OR ...` branch.
- Finish CORS production posture: localhost fallback residue is removed, production requires explicit `CORS_ALLOW_ORIGINS`, and the hardcoded fallback is removed; live production origin/preflight configuration must still be archived against the current release.
- Commit/review the MVP-1 through MVP-9 intelligence-layer work only after generated `__pycache__` bytecode stays removed and `apps/backend/scripts/test_http_probe.sh` is classified as a product helper, local operator helper, or intentionally untracked scratch file.
- Promote the Phase 0 DB proof into CI evidence for the latest tenant-config schema/role-mapping/router validation paths.
- Wire or remove the warranty/refund editor raw JSON override so UI behavior matches operator expectations.
- Promote the governed LLM/fraud scaffold into production composition only after live model evals, persistence/readback proof, operator workflow, and failure-mode tests.
- Delete or quarantine tracked duplicate/dead Python app trees, and keep generated/junk artifacts out of tracked release commits.
- Clean local AWS CLI archive/vendor files and harden or quarantine the Terraform scaffold before any infra commit.
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
| Backend API | Authority, orchestration, tenant APIs, governance, sessions, data protection, action approvals | Postgres, Redis, Auth0 JWKS, Sentry, Anthropic/OpenAI optional | Stronger controls; action-approval stub DI fixed; production proof pending |
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

`dispatch -> governance admission token -> execution record/outbox -> Celery queue -> worker claim -> cognition snapshot -> approved-only RAG retrieval -> configured LLM provider or non-production deterministic fallback -> quota usage record -> governance persistence -> timeline/resolution proposal`

Current answer: RAG poisoning and token quota are materially improved. Execution records now bind the execution-governance configuration id/version/content hash used at admission, and workers verify that bound version before running. Live provider/readiness proof remains required.

Action tool:

`agent request -> ToolInvoker -> capability/constraint checks -> governance evaluation or pre-approved decision -> durable grant -> exact actor/payload/binding consumption -> tool invoke -> envelope`

Current answer: old cross-payload replay is closed. Tool invocation now reserves connector idempotency before provider calls, terminal connector results replay, and worker plus manager-approved action paths inherit the production fail-closed stub policy. Residual: real irreversible provider side effects still require live provider idempotency, callback-origin proof, and production tests.

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
| Governance layer | 72 | 97 | Partial | Durable config ledger, apply attribution, revoke flow, action grants, domain capabilities, object-RBAC sweep, per-tenant action policy, connector/onboarding change requests, connector-specific approval, generalized operation metadata, money/goods human-approval floor, seeded-replay binding HMAC, approval race guard, custom-tool commitment-kind gates, policy binding, grounding governance, approval auto-delivery, and escalation handoff evidence are strong; live proof/workflow maturity still missing. |
| Agent layer | 50 | 93 | Partial | Replay is durably actor/payload-bound, connector invocation ledger exists, automatic and manager-approved unconfigured commerce actions now inherit fail-closed stub policy, quota/backpressure are stronger, warranty/replacement and `inventory.check` paths are committed, generic/custom connector operations are live/focused-tested, structured extraction is schema-gated, governed LLM/fraud/SOP/QA/supervisor/repair scaffolds exist, and Phase 0 closes production LLM stub fallback; production provider proof and full intelligence workflow remain. |
| Supervisor layer | 60 | 72 | Partial | Supervisor/QA records exist and read gates improved; cognition/escalation audit coverage improved; MVP-8 supervisor sanitizer and tests are cleaner after Phase 0. Still more observability than hard production control. |
| Execution layer | 62 | 90 | Partial | Durable execution/claims/outbox/recovery plus governance version binding, completion DLQ, per-tenant QoS, connector invocation reservation, generic operation metadata, work-order transitions, stale-claim reconciliation, queue-age race fix, approval race guard, tool invocation cap, idempotent DLQ writes, and Phase 0 connector credential bridging improve replay/reliability. |
| Knowledge layer | 50 | 86 | Partial | Quarantine/review, injection scan, approved-only retrieval, delimiters, citation span provenance, grounded generation, encrypted ingestion, governance upload/apply flow, direct-write removal, attachments, and vision evidence close more of the original path; evals/source-trust workflow remain. |
| Audit layer | 68 | 90 | Partial | Better grant/ledger/DLQ/data-protection/connector/work-order/knowledge/escalation/approval/generic-operation evidence, boot checks, Phase 0 DB proof, lint/type evidence, and hygiene tracking; live secret/rotation proof still missing. |
| Compliance layer | 35 | 72 | Partial | DSAR erasure, legal holds, retention policy, envelope encryption, GCP KMS custody path, attachment controls, and reconstruction metadata exist; SOC 2, live evidence, retention/legal operations, and customer artifacts remain incomplete. |
| Human escalation layer | 58 | 90 | Partial | Tenant config dual-control ledger, connector/action onboarding, apply attribution, revocation, action approvals, durable crisis handoff, escalation outbox/runtime coverage, and case-approval delivery exist; UI workflow, expiry, and live operator drills remain. |
| Intelligence layer | 52 | 91 | Partial | Anthropic/Bedrock paths, TPM quota, RAG controls, grounded response governance, taxonomy/autonomy fail-closed policy, safety floors, vision attachments, schema-gated structured extraction, malformed JSON retry, encrypted sensitive audit/prompt fields, governed LLM/fraud/SOP/QA scaffolds, and Phase 0 production LLM fail-closed behavior improved; provider/quality proof and full production composition remain. |
| Auth/RBAC | 57 | 92 | Partial | Header authority, Auth0 namespaced mapping, `AUTH_ENABLED` default/prod gate, scope-less principal rejection, domain capabilities, connector approval mapping, platform/tenant capability split, object-RBAC sweep, data-protection caps, conversation ownership, and production auth-error coarsening improved; current live Auth0 `/auth/me` proof remains. |
| Tenancy | 76 | 92 | Partial | RLS discipline plus header/voice/data-protection/object-RBAC/platform-lifecycle/work-order/connector RLS fixes, DB router proof, connector credential bridge fixes, partial production-role RLS proof, and nullable-tenant static invariant improve isolation; full current-head production FORCE-RLS/RLS proof remains. |
| Observability | 58 | 76 | Partial | Logs/metrics/alerts exist, completion-event DLQ, work-order states, connector invocation records, nonce backlog signal, case-approval delivery records, and real governance denial reasons are stronger; live operator and compliance proof incomplete. |
| Reliability | 55 | 92 | Partial | Boot gates, CI, durable grants, repaired voice load harnesses, rate-limit fail policy, quota/queue fail-closed behavior, durable ingress capture, completion DLQ, connector idempotency, generic connector live tests, work-order state, stale-claim reconciliation, queue/admission fixes, outbox retry fixes, approval race guard, tool cap, worker fixes, Phase 0 connector credential fix, partial live worker/DLQ proof, and clean tenant-config DB proof help; provider smoke and current-head full-suite production proof keep this capped. |
| Scalability | 49 | 74 | Partial | Queue topology, token quota, inbound rate limiting, Fly-aware client-IP resolution, per-tenant QoS, admission controls, worker right-sizing, CloudAMQP volume reduction, tool invocation caps, and connector/work-order/generic operation ledgers help; no meaningful live load/scale proof and current-deploy rate-limit bucket proof remain. |
| Enterprise readiness | 43 | 86 | Not ready | Security/governance primitives, domain agnosticism, production-fail-closed defaults, compliance docs, zero-warning type state, and partial S-10 evidence improved readiness, but current-head S-10, clean provider smoke, formal compliance operations, DR/SLO evidence, full live CORS/RLS/rate-limit proof, duplicate-tree/repo hygiene, and production provider integrations cap readiness. |

## Security Audit Summary

### S-01: Production Header Authority Spoofing - CLOSED, Current-Head Live Proof Pending

Original finding: production could accept spoofable legacy `X-Tenant-ID` / `X-Principal-ID` authority headers if deployed without trusted ingress.

Current evidence:

- `apps/backend/app/core/config.py:415-424` disables legacy header authority by default in production.
- `apps/backend/app/middleware/authority_context.py:221-226` rejects legacy identity headers with `401 header_authority_disabled`.
- `apps/backend/app/main.py:762-768` wires trusted proxies from settings into app composition.
- `apps/backend/fly.toml` sets production posture and trusted proxy assumptions.
- `apps/command-center2/frontend/lib/api-client.ts` defaults to `verified-bearer`.
- Tests: `test_authority_header_disabled.py`, `test_main_legacy_header_disabled.py`, `test_config_security_posture.py`.

Status: closed in code and tests by `c9a2712`. Live production ingress proof exists for Fly v235 / `c65fda5`; current-head proof remains part of S-10.

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
- Committed connector approval work adds `tenant.connector.approve`, maps Auth0 `TenantConnectorApprover` / `approve:tenant_connector`, and makes connector change-request approval require that connector-specific capability.
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

Residual: real provider connectors still need live idempotency, callback-origin, and side-effect tests before high-value actions.

### S-06: Outbound Webhook SSRF - CLOSED For Generic Outbound Dispatch And Connector HTTP

Original finding: tenant-configured outbound URLs were posted directly without scheme/domain/private-IP guardrails.

Current evidence:

- `apps/backend/app/core/ssrf.py:173-233` validates HTTPS, host allowlist, DNS results, blocked IP classes, and selected pinned IP.
- `apps/backend/app/core/ssrf.py:49-120` implements pinned-IP transport that dials the validated IP while preserving host/SNI.
- `apps/backend/app/boundary/outbound/adapter.py:81-107` validates before dispatch, uses pinned transport, and disables redirects.
- `apps/backend/app/agents/tools/connectors/base.py:139-158` applies the same validated/pinned HTTPS posture for tenant-configured connector calls.
- Committed tests include channel-send SSRF and warranty/replacement connector SSRF call-time coverage; loopback TLS cases are skipped in Codex sandbox when bind is unavailable.
- Tests: `test_ssrf_guard.py`, `test_ssrf_dns_rebinding.py`.

Status: closed by `cd8c6bc` and `20a890a`.

Residual: DNS-rebinding tests are now deterministic in code, but loopback-server proof still needs normal-shell/CI pass evidence when sandbox binding is unavailable; live egress proof remains part of S-10/Phase E.

### S-07: RAG Poisoning Through Tenant Knowledge Writes - CLOSED For Original Path

Original finding: approved knowledge could flow into active retrieval without quarantine/reviewer workflow or injection controls.

Current evidence:

- Migration `0065_knowledge_review_status` adds review status defaulting new documents to `quarantined`.
- `apps/backend/app/knowledge/runtime.py:94-115` scans and records knowledge review metadata on indexing.
- `apps/backend/app/knowledge/runtime.py:386-425` fails closed to quarantine on scanner error or flagged content.
- `apps/backend/app/knowledge/persistence/postgres.py:133-141` retrieves only active approved documents.
- `apps/backend/app/cognition/diagnostic_runtime.py:95-99` treats retrieved SOPs as untrusted reference data.
- `apps/backend/app/cognition/diagnostic_runtime.py:1007-1030` delimits chunks and carries citation metadata.
- Follow-on committed work adds governed encrypted knowledge upload/ingestion, Command Center upload/review surfaces, governance-apply auto-approval, and removes the direct-write button.
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
- Tests: `test_production_readiness.py`, `test_check_production_readiness_script.py`, `test_rls_coverage_invariant.py`, `test_rls_null_tenant_hardening.py`.
- Production-readiness rejection for `WEBHOOK_TRUST_URL_HEADER=true`, missing `PUBLIC_BASE_URL`, empty production `CORS_ALLOW_ORIGINS`, and related gates is covered by tests. Latest focused hardening bundle including production readiness passed `78` tests.
- `apps/backend/scripts/s10_prep/live_verification_probes.py` adds deploy-time probes for direct spoof rejection, Auth0/bearer smoke, production-role RLS isolation, worker/DLQ proof, and smoke trace evidence.
- `apps/backend/app/workers/s10_probe_tasks.py` adds a DLQ probe task.
- `apps/backend/scripts/s10_prep/rewrap_legacy_anker_knowledge.py` adds a dry-run-first rewrap path for legacy Anker knowledge ciphertext.
- Committed migration `0087_connector_configs_force_rls` extends the RLS posture for connector configs, and the static nullable-tenant invariant now guards direct FORCE-RLS tenant tables. These are not substitutes for full production-role live catalog proof.
- `docs/pilot-readiness-evidence/manifest.json` now points at a 2026-07-05 partial S-10 bundle captured against Fly v235 / commit `c65fda5`: direct spoof rejection (`2026-07-05-spoofing-pass.json`), in-container readiness READY (`2026-07-05-readiness-ready.json`), one-table production-role RLS isolation (`2026-07-05-rls-pass.json`), and worker/DLQ proof (`2026-07-05-workers-dlq-pass.json`).
- `docs/pilot-readiness-evidence/2026-07-05-smoke-trace.json` is a partial live smoke: Auth0 bearer/tenant extraction, ingress, session creation, dispatch, diagnostic worker pickup, and retry behavior reached production, but final diagnostic completion failed all retries due to Anthropic HTTP 400.
- The only archived `/api/v1/auth/me` Auth0 verified-claims proof remains `2026-06-06-bearer-auth0-verified-claims.json`, captured against an older deployment. The 2026-07-05 partial smoke supports live bearer use but is not a clean replacement for current `/auth/me` proof.

Status: open. The boot gate is committed and partial live production evidence exists, but S-10 is not closed for current HEAD `cccd538`.

Required to close:

- Deploy a clean current HEAD or exact release candidate and recapture evidence against that exact commit SHA.
- Current live direct spoofed authority-header rejection.
- Current live bearer/Auth0 `/api/v1/auth/me` success path with namespaced claims and expected capability mapping.
- Full production-role RLS tenant isolation across representative sensitive tables plus full production FORCE-RLS catalog proof.
- Current live workers and DLQ smoke/replay proof.
- Current live secrets/provider/readiness CLI output.
- Current live CORS preflight proof for allowed and disallowed origins.
- Current live rate-limit real-client-IP/proxy-aware proof.
- Clean live workflow smoke where diagnostic completion succeeds or safely escalates for product reasons, not provider misconfiguration.
- Rollback evidence tied to the current release candidate.

## Data Protection, Resilience, And Cleanup Review

The Phase 1c/1d/1e tranche materially changes the current state:

- Data protection: `apps/backend/app/api/v1/routers/data_protection.py:41-247` exposes privacy-admin and privacy-approver gated erasure/legal-hold/retention APIs. `apps/backend/app/data_protection/crypto.py:425-493` implements dual-control DSAR erasure by deleting the subject data key only after an independent approver passes lifecycle/legal-hold checks. `apps/backend/app/data_protection/db/models.py:30-185` stores data keys, retention policies, legal holds, and erasure-request ledgers with check/FK constraints.
- Data-protection proof: `test_data_protection_controls.py` proves envelope encryption, crypto-shred unreadability after erasure, legal-hold blocking, tenant-delete FK semantics, same-principal DB/app rejection, master-key rewrap, and tenant-owned knowledge encryption. `test_data_protection_admin_api.py` proves API gates, unconfigured-key `503`, propose/approve erasure, legal-hold release, same-principal rejection, and retention purge behavior.
- Resilience: `apps/backend/app/core/queue_admission.py:101-152` fails closed when queue depth cannot be read; `apps/backend/app/core/queue_admission.py:214-278` adds per-tenant queue reservations. `apps/backend/app/agents/runtime/quota_runtime.py:148-221` fails closed for pre-call quota state loss.
- Durable ingress: `apps/backend/app/services/ticket_ingress_service.py:543-608` commits the captured boundary ingress before recording processing-admission pressure, so authenticated inbound events are not lost when admission defers.
- Governance binding: `apps/backend/app/execution/runtime.py:390-430` persists execution-governance config id/version/sha into the execution record, and `apps/backend/app/runtime/execution_governance.py:306-343` rejects missing/mismatched bound configs during reconstruction.
- Completion DLQ: `apps/backend/app/workers/execution_completion_events.py:45-82` records a dead-letter task if worker completion-event emission fails.
- Cleanup: `apps/backend/tests/test_legacy_module_quarantine.py:78-114` proves `_deprecated` is absent and not imported; `apps/backend/Dockerfile:1-22` pins the base image digest and runs as non-root; `.github/workflows/ci.yml:61-76` generates SBOM and `pip-audit` artifacts.

Residuals: data protection is now real code, not a stub, and a GCP KMS custody path exists. It is still not a complete compliance program until live KMS custody/rotation evidence, live erasure evidence, retention/legal operations, audit access controls, and customer-facing compliance artifacts are archived. Resilience controls are stronger, but live Redis outage, worker, DLQ, and queue-pressure drills remain S-10/ops proof work.

## Edge-Hardening Review

Claude's latest committed tranche materially improves the edge posture:

- #23 webhook/voice canonical URL spoofing: closed in production code and tests. `derive_canonical_webhook_url` builds URLs from `PUBLIC_BASE_URL` plus trusted path/query, channel webhook signatures pass `request_path`, and voice provider signatures now ignore forged canonical URL headers unless `WEBHOOK_TRUST_URL_HEADER` is explicitly enabled for non-production testing.
- #39 inbound rate limiting: closed at code/test level. `EdgeRateLimitMiddleware` runs pre-auth by IP, `TenantRateLimitMiddleware` runs post-auth by tenant/principal, `main.py` registers both in the request pipeline, and `resolve_client_ip()` now keys on `Fly-Client-IP` only when the immediate peer is in `TRUSTED_PROXIES`.
- #38 Redis backend-loss policy: code-closed for the audited quota/admission paths. Rate-limiter production writes fail closed in 1b; quota and queue admission now fail closed for pre-call/publish decisions in 1d. Residual: live outage drills and idempotent rate-limit degrade-open semantics must be documented.
- #63 stale voice load/capacity harnesses: closed. The fake WebSocket harnesses now include signed session token, provider auth loader, server-derived signature URL, and provider signature headers.
- #25 auth-error coarsening: code-closed. Authority-state errors, malformed `Authorization`, malformed legacy authority-header parse paths, and verification-unavailable cases are routed through the same coarsening helper in production posture.
- #40 voice wall-clock, idle, and frame-rate caps: closed at code/test level in the voice WebSocket route.

Remaining edge-hardening gaps:

- Per-IP rate limiting is code/test-correct for Fly proxy semantics, but live proxy/client-IP bucket proof must be archived against current deployment before claiming true production per-client edge limiting.
- CORS posture is code-closed for fallback behavior: production readiness rejects empty `CORS_ALLOW_ORIGINS` and `_build_cors_origins()` has no hardcoded fallback. Remaining work is archived live preflight proof for allowed/disallowed production origins against current deployment.
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

- S-10 live production proof is partial and not current-head-complete.
- Owner sessions bypass RLS and are used by maintenance tasks.
- The base tenant RLS helper still allows `row_tenant_id IS NULL`, and forensic review found nullable tenant columns on some forced-RLS legacy/core tables. That is a defense-in-depth gap even where no active cross-tenant leak was proven.
- Command center still has local/non-production header mode support.
- Some tenant-wide read surfaces lack object-level RBAC.
- No per-tenant broker isolation.

## Governance Audit

Can governance be skipped?

Current answer: much less than before for tenant config, action replay, and automatic commerce actions. Tenant config now has durable proposal, approval, rejection, apply, and revoke states with principal separation and applier/revoker attribution. Action grants are actor/payload-bound and consumed durably. Per-tenant action policies and connector configuration flow through governed change requests. Connector approval and OMS credential update paths are committed. Remaining gaps are UI workflow adoption, expiry/time-bound approvals, live Auth0 proof, live provider-side idempotency, and live/CI proof for the committed connector/OMS/RLS paths.

Can execution happen without authorization?

Diagnostic execution still expects governance admission. Voice call execution now requires signed token plus provider signature. Pre-approved action execution now requires a matching durable one-time grant. Automatic and manager-approved unconfigured commerce actions now inherit the production fail-closed stub setting. Remaining risk is deployment misconfiguration, live provider/callback gaps, and future connector paths.

Can stale policies be used?

Much less than before. Execution records now bind the execution-governance config id/version/content hash admitted at request time, and workers reconstruct that bound config before executing. In-flight work intentionally uses the historical admitted version; the residual is live proof, replay tooling maturity, and cache invalidation discipline.

Can evidence be tampered with?

Evidence is stronger than before. Config change requests, apply/revoke attribution, action grants, connector invocation rows, work-order records, fulfillment receipts, data-protection erasure/legal-hold ledgers, and completion-event DLQ records create more durable replayable evidence. Residual gaps include no expiry lifecycle for config approvals, incomplete command-center/action-approval workflows, and missing live secret/rotation proof.

Can replay become inaccurate?

Yes, but less than before. Action grant replay is now precise, connector invocation/work-order records improve side-effect reconstruction, and execution-governance config binding reduces stale-policy ambiguity. RAG replay is improved by citation spans but still needs stronger exact-content/hash binding and production review workflow.

## Agent Safety Audit

Can an agent exceed its authority?

Less easily than before. The prior cross-payload replay weakness is closed, per-tenant action policy exists, and unconfigured commerce actions now inherit production fail-closed behavior in worker and approval paths. Remaining risk is over-broad tenant capabilities, poisoned or poorly reviewed knowledge, stale policies, or connecting real external side effects before provider idempotency and connector tests exist.

Can an agent trigger unintended actions?

Less easily than before, but still yes in the wrong deployment posture. Refund, repair, warranty/replacement, and inventory-check paths now have connector/work-order/governance coverage, and unconfigured automatic and manager-approved actions fail closed in production. Warehouse remains unintegrated, and live providers need idempotency/signature/callback-origin proof.

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
- Some model/schema nullability drift can still exist; forensic F-009 specifically keeps nullable-tenant RLS semantics open until `tenant_id NOT NULL` coverage and null-tenant cross-tenant tests are added where tenant semantics require isolation.
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

- Production worker/DLQ proof is archived for Fly v235 / `c65fda5`, but it must be recaptured against the current release candidate.
- Voice load/capacity test suite has been repaired after the auth gate.
- Some periodic tasks intentionally do not DLQ.
- Live Redis outage drills are not archived; rate-limit idempotent paths still degrade open by design.
- No disaster recovery/backup restore evidence was found in active gates.
- Real external action side effects are integrated in more paths, but reliability claims remain unproven until live provider idempotency/callback drills are archived.
- Warranty/replacement connector and OMS credential changes are committed and locally DB-proven, but production reliability claims still need CI/live provider evidence.
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
- Current repo scan counts 522 tracked dead duplicate Python files under `apps/marketing2/app/**/*.py` and `apps/command-center2/app/**/*.py`; this is still open repository hygiene and deployment ambiguity.
- Prior tracked junk files (`apps/backend/asyncio`, `apps/backend/asyncpg`, duplicate nested backend migration copy, and `h origin phase-2-2-stabilized`) are no longer present in the current dirty tree. Keep this invariant during commit review.
- Multiple runtime compositions use in-memory/deterministic defaults outside production gates.
- Tenant config workflow still needs UI adoption and expiry/time-bound approvals.
- Voice load/capacity test harnesses now model the provider-signature contract; real provider load proof remains.
- Command center demo/proof constants remain in active product code.
- The tenant action registry no longer registers fake-success stubs in the generic path; production DI callers reviewed pass the derived fail-closed setting, and this needs to stay under regression guard.
- Some abstractions are ahead of real integrations, increasing false confidence.
- Current smoke/evidence test hygiene still needs cleanup: `test_system_smoke.py` can pass an assertion and then hang on local DB/resource-lifespan paths when the configured local Postgres is unreachable, so it is not reliable release evidence yet.

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
- Fly client-IP extraction/anti-spoofing tests passed.
- Auth-error coarsening for malformed authorization/header parse paths passed after replacing the hanging minimal `TestClient` harness with direct ASGI invocation.
- Fulfillment callback HMAC unit/integration tests passed.
- Static nullable-tenant invariant for direct FORCE-RLS tenant tables passed.
- Channel webhook canonical URL signature tests passed.
- RAG poisoning controls exist and are covered by targeted tests.
- Data-protection controls/admin API, legal hold, retention, crypto-shred, master-key rotation, and FK semantics passed in DB-backed tests.
- Object RBAC sweep and functional domain gates passed in the user's normal shell.
- Deleted `_deprecated` and forbidden-dependency invariants passed.
- Grounded response/resolution governance and Phase 2 domain/Auth0/config-router bundle passed in the user's normal shell.
- Work-order dispatch substrate passed in the user's normal shell.
- Commerce action fail-closed tool/registry/settings tests passed, including the current action-approval/case-approved DI wiring guard.
- Real OpenAI embedding provider/runtime tests passed, including provider HTTP shape, production composition wiring, native pgvector retrieval, tenant isolation, and re-embed behavior.
- Current hardening bundle (`test_rls_null_tenant_hardening.py`, `test_authority_context_coarsening.py`, `test_fulfillment_callback_hmac.py`, `test_edge_client_ip.py`, `test_production_readiness.py`) passed `78 passed in 2.92s`.
- Pyright passed with `0 errors, 0 warnings, 0 informations`; ruff passed on touched files; S-10 manifest and smoke trace JSON validate.

Untested or insufficiently proven:

- Current-head live production Auth0 `/auth/me` token claim mapping and role assignment.
- Current-head production trusted ingress/direct spoof rejection. A 2026-07-05 proof exists for Fly v235 / `c65fda5`, not for current HEAD.
- Full production FORCE-RLS catalog proof. A 2026-07-05 one-table RLS proof exists, but it is not full catalog evidence.
- Current-head production worker/DLQ/health checks. A 2026-07-05 worker/DLQ proof exists for Fly v235 / `c65fda5`.
- Live production SSRF/egress proof.
- Current-head auth/coarsening live proof.
- Current-head CORS allowed/disallowed preflight proof.
- Current-head real-client-IP rate-limit bucket proof.
- Real provider STT/TTS/action integration behavior.
- Clean provider-completing diagnostic smoke. The 2026-07-05 partial smoke reaches diagnostic worker/retry but fails all retries on Anthropic HTTP 400.
- Live production embedding rollout evidence: the code path is wired and DB-tested, but the live Anker document re-embed and retrieval confirmation still need to be archived.
- Warranty/replacement connector and OMS credential/RLS changes are committed and locally DB-proven; they still need CI/live provider evidence.
- Local AWS CLI archive/vendor tree and Terraform scaffold are not release-clean.
- Live quota/admission/rate-limit behavior under production Redis outage policy.
- `test_system_smoke.py` is not reliable release evidence in the current local environment: health emits a passing dot but the process times out, ticket ingress times out, and direct local Postgres connection to `localhost:5433/operious_test` timed out.
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
| Internal demo | Ready with caveats | n/a | 94 | Good if demo/stub boundaries are disclosed and S-10 gaps are not represented as complete. |
| Scoped non-regulated pilot | Conditional | n/a | 87 | Reasonable after code hardening, domain-agnostic MVP work, Phase 0 fail-closed cleanup, and DB proof if Phase E checks pass, risky integrations stay constrained, provider drills are bounded, and pilot scope is explicit. |
| $100k customer | Conditional pilot | 58 | 84 | More plausible after Phase B/Stage 3, current MVP work, and Phase 0 cleanup, but still depends on live proof, constrained integrations, committed release hygiene, and provider drills. |
| $500k customer | Not ready | 43 | 69 | Better security/governance/domain-agnostic primitives, but procurement/security/compliance gaps remain large. |
| $1M customer | Not ready | 34 | 56 | Needs live production proof, compliance, real integrations, DR/SLO proof, operator runbooks, and mature intelligence workflows. |
| Fortune 500 | Not ready | 25 | 41 | Below expected security/compliance/change-control/supply-chain bar. |
| Regulated enterprise | Not ready | 20 | 45 | Data-protection/KMS controls exist, but formal compliance, retention/legal operations, and live evidence are incomplete. |

Scoped-pilot safety verdict: conditionally safe for a narrow, non-regulated pilot only if Phase E/S-10 checks are recaptured against current HEAD, AWS/Terraform local artifacts are cleaned or quarantined, current untracked/modified evidence is intentionally reviewed and committed, generated bytecode remains absent, irreversible provider actions stay constrained behind proven connector/idempotency paths, tenant-config DB proof is promoted to CI/normal-shell evidence, live provider drills pass, and operators do not present S-10 or compliance evidence as complete. It is not yet safe for broad enterprise production.

## Red Team Review

Most likely breach paths now:

1. Production ingress/Auth0 misconfiguration or override reopens header authority.
2. S-10 gaps: RLS/worker/DLQ/secrets not actually correct in deployed environment.
3. Real refund/repair/warranty/replacement/warehouse connector connected before provider idempotency, callback signatures, and action side-effect tests.
4. Local AWS CLI archive/vendor tree or placeholder Terraform scaffold accidentally committed/deployed.
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
| 1 | Closed/High residual | Auth | S-01 closed in code; direct spoof rejection archived for Fly v235 / `c65fda5`; current-head proof still pending under S-10 | Recapture direct spoof rejection and bearer success proof against current release candidate |
| 2 | Medium | Deployment | Fly/prod posture improved; partial v235 evidence exists; current-head proxy/secrets/provider proof pending | Verify `TRUSTED_PROXIES`, secrets, health, RLS, workers, CORS, rate-limit IP keying against current release |
| 3 | Closed/Medium residual | Frontend | Command center defaults to verified bearer | Fail production if tenant-header mode is configured |
| 4 | Closed/Medium residual | RBAC | S-02 closed; domain capabilities and object-RBAC sweep added | Verify live Auth0 roles and extend object-scope policy for uncovered/future routes |
| 5 | Closed/Medium residual | Governance | `applied_by` persisted: service.apply() records applier, router threads principal, schema exposes it (spec 1a) | UI workflow + expiry remain |
| 6 | Closed/High residual | Voice | S-04 auth closed; load harness repaired; frame byte/count/duration/idle/rate caps enforced; provider/issuance maturity remains | Prove issuance/STT/TTS and keep cap/load tests in CI |
| 7 | Closed/Medium residual | Agent | S-05 replay closed by durable grants; connector invocation ledger and work-order states improve side-effect replay; approval-path stub DI is fixed | Add live provider idempotency tests |
| 8 | Closed/Medium residual | SSRF | S-06 closed for generic outbound; deterministic DNS-rebinding tests exist | Archive normal-shell/CI loopback proof and live egress proof |
| 9 | Closed/High residual | RAG | S-07 original path closed | Add reviewer UX, evals, source trust policy |
| 10 | Closed/Medium residual | Auth0 | S-08 code closed | Add live token contract fixture |
| 11 | Closed/Medium residual | Quota | S-09 diagnostic TPM closed; Redis pre-call quota loss fails closed | Add enterprise budgets, provider-wide quotas, and live outage drills |
| 12 | Open/High | Readiness | S-10 open with partial live evidence against `c65fda5`, not current-head-complete | Recapture full Phase E live verification against current release candidate |
| 13 | High | Voice | Real STT/TTS provider proof missing | Integrate/prove providers or keep voice disabled |
| 14 | Partial/High | Actions | Refund, repair, warranty/replacement, inventory-check, and generic connector operations now have connector/work-order/governance coverage; automatic and manager-approved unconfigured commerce actions fail closed in production; warehouse remains unintegrated | Add CI/production provider drills, then implement warehouse |
| 15 | High | Governance | Tenant-specific policy residue risk remains | Move hardcoded proof policies to tenant data |
| 16 | Closed/Medium residual | CORS/Auth | CORS credential flags respect config, wildcard is rejected, production readiness requires explicit origins, and hardcoded fallback is removed | Archive live allowed/disallowed origin preflight proof |
| 17 | Medium | Secrets | Boot gate checks audit secret; live proof missing | Set, rotate, verify secret in Phase E |
| 18 | High | RLS | One-table production-role RLS proof exists for v235; full production FORCE-RLS catalog proof missing; nullable-tenant semantics remain defense-in-depth work | Run and archive full prod FORCE-RLS/catalog proof, then continue nullable tenant hardening |
| 19 | High | Workers | Worker/DLQ proof exists for v235; current-head worker health/process proof missing | Verify all process groups, DLQ, alerts, and clean smoke against current release |
| 20 | Medium | Channel | Credentials and connector config are gated/read-redacted; live provider proof incomplete | Channel-specific admin/approval/live proof |
| 21 | Medium | Topology | Ledger-gated; live workflow proof missing | Verify topology flow in CI/live |
| 22 | Closed/Medium residual | Policy | Ledger revocation implemented: REVOKED status, revoke() service, /revoke endpoint, TENANT_CONFIG_CHANGE_REVOKE act (spec 1a) | Expiry (time-based) and UI workflow remain |
| 23 | Closed/Medium residual | Webhook | Twilio/voice canonical URLs are server-derived in code/tests | Commit/readiness-gate `PUBLIC_BASE_URL`; archive live provider proof |
| 24 | Closed/Medium residual | Webhook | Uniform `401 webhook_rejected` closes content oracle; timing oracle mitigated by rate limiting | Do not pursue constant-time DB lookups; keep rate limits live |
| 25 | Closed/Medium residual | Auth | Authority-state and malformed auth/header parse errors coarsen in production posture with tests | Recapture live auth/coarsening proof against current release |
| 26 | Closed/Medium residual | Tenant | Domain gates plus object-RBAC sweep cover selected sensitive tenant-scoped surfaces | Live Auth0 proof and route-coverage invariant expansion |
| 27 | High | Audit | LLM prompts/completions are sensitive | Encrypt/redact/retain by policy |
| 28 | Closed/Medium residual | Prompt/RAG | Baseline injection controls added | Add adversarial evals and policy tuning |
| 29 | Partial/Medium | Cognition | Customer replies now pass grounded generation/governance, but universal production citation policy and evals are not complete | Keep grounding mandatory and add prod tenant eval gates |
| 30 | Closed/Medium residual | RAG | Real OpenAI embedding provider is wired into production composition, native pgvector/HNSW is dimension-coherent at 1536, and DB-backed retrieval/re-embed tests pass | Execute and archive production snapshot -> migrate -> re-embed -> retrieval/eval proof |
| 31 | Medium | Provider | Boot gate and real translation-provider path help; provider health proof missing | Provider health checks and override governance |
| 32 | Partial/Medium | Deployment | Backend runtime image is digest-pinned and non-root; SBOM/pip-audit artifacts and CodeQL exist, but signing/attestation are incomplete | Add image signing, provenance, and minimal multi-stage runtime |
| 33 | Partial/Medium | Supply chain | SBOM, `pip-audit`, dependency-review, license audit, CodeQL, and alert triage improved; artifact signing/attestation still incomplete | Add artifact attestations, image signing, and release provenance |
| 34 | High | Local secrets | Local `.env` hygiene risk | Keep gitignore and secret scanners |
| 35 | High | Owner DB | Owner sessions bypass RLS | Separate creds, lint owner usage |
| 36 | Closed/Medium residual | Migrations | RLS coverage invariant added | Keep invariant in CI and prove prod RLS |
| 37 | Partial/Medium | Queue | Per-tenant queue QoS reservations added for diagnostic publication; broker still not isolated per tenant | Prove QoS live, extend priority/rate limits, and consider broker isolation |
| 38 | Closed/Medium residual | Admission | Rate-limit, quota, and queue-admission audited paths fail closed for Redis-backed write/admission failures; idempotent rate-limit behavior still degrades open | Archive live Redis outage drills and runbooks |
| 39 | Closed/Medium residual | Rate limit | Per-IP and tenant/principal rate limits are wired; Fly `Fly-Client-IP` trusted-proxy keying is code/test-covered | Archive current-deploy bucket proof behind Fly/proxy |
| 40 | Closed/Low residual | WebSocket | Voice frame byte/count plus wall-clock/idle/rate caps are enforced and tested | Keep handler-level cap proof in CI |
| 41 | Medium | UX/Product | Demo proof sessions remain | Remove/isolate proof sessions |
| 42 | Medium | Business | Claims can outrun live proof | Align claims to S-10 status |
| 43 | Medium | Docs | S-10 probe tooling exists, but archived live evidence is still missing | Make Phase E checklist blocking and attach probe output |
| 44 | Closed/Low residual | Codebase | `_deprecated` backend package deleted and invariant-tested | Keep quarantine test and avoid recreation |
| 45 | Medium | Codebase | Duplicate app histories and 522 tracked dead Python files remain | Declare active apps and archive/delete dead trees |
| 46 | Medium | Frontend | Browser token exposure/XSS blast radius | Harden CSP/BFF option |
| 47 | Medium | Frontend | Local storage authority labels risk confusion | Store display state only |
| 48 | Medium | CSRF | Cookie-auth token route deserves review | POST + CSRF or BFF proxy |
| 49 | Medium | CSP | CSP review incomplete | Add CSP/reporting |
| 50 | Medium | Webhook | Tenant context reset discipline should be audited | Use scoped context managers |
| 51 | Medium | Webhook | Semantic circuit advisory/fail-open risk | Make response mode configurable |
| 52 | Closed/Medium residual | Nonce | Nonce cleanup backlog growth signal added | Add live alert/runbook and cleanup SLO |
| 53 | Closed/Low residual | Outbound | Redirects disabled in generic adapter | Keep invariant tests |
| 54 | Partial/Medium | Credentials | Tenant connector credentials are encrypted/write-only; OMS credential update stores only ciphertext hash sentinel; KMS path exists but live custody/rotation proof pending | CI/live-prove OMS path, verify injection, rotation, and KMS custody |
| 55 | Partial/Medium | Encryption | Envelope encryption, crypto-shred, and GCP KMS custody path implemented; live custody/rotation evidence missing | Prove KMS rotation/custody and live erasure evidence |
| 56 | Partial/Medium | Retention | Retention policy API and purge behavior exist for covered data; universal archival/legal operations incomplete | Expand coverage, schedule jobs, and archive live purge/hold evidence |
| 57 | Medium | DR | Backup/restore proof absent | Run restore drills |
| 58 | Medium | Observability | Alert tasks best-effort | Alert on evaluator failure |
| 59 | Medium | Metrics | Beat/queue observability gaps remain | Track beat health |
| 60 | Closed/Low residual | Testing | CI exists | Add artifact attestations/security gates |
| 61 | Medium | Testing | Current-head live Auth0 `/auth/me` contract missing; older 2026-06-06 fixture exists | Archive real current token fixture |
| 62 | Closed/Low residual | Testing | SSRF tests exist | Add live egress proof |
| 63 | Closed/Low residual | Testing | Voice auth and load/capacity harnesses now pass with provider-signature contract | Keep load/capacity tests in CI; add real provider load proof |
| 64 | Closed/Medium residual | Testing | Dual-control tests now exist | Keep in CI and add UI workflow tests |
| 65 | Partial/Medium | DB | ORM tenant_id nullability is improved, but forensic F-009 shows nullable tenant columns plus `row_tenant_id IS NULL OR ...` RLS semantics still need defense-in-depth hardening | Add no-nullable-tenant-on-RLS introspection and cross-tenant NULL regression tests |
| 66 | Medium | DB | Knowledge query plan unproven | Explain/analyze and indexes |
| 67 | Medium | DB | Large JSON metadata can become hot blobs | Promote indexed fields |
| 68 | Medium | DB | Tenant partitioning deferred | Partition when volume warrants |
| 69 | Closed/Medium residual | Execution | Execution records bind governance config id/version/sha and workers verify the bound config | Add replay tooling, cache-invalidation proof, and live drills |
| 70 | Closed/Medium residual | Execution | Completion-event emission failures are dead-lettered | Add replay/drill proof and alerting |
| 71 | Partial/Medium | Execution | Connector invocation, generic operation metadata, and work-order ledgers model refund/repair/warranty/replacement side effects; broader provider outbox/callback proof incomplete | Add provider-specific outbox/drills and callback signatures |
| 72 | Partial/Medium | Action | Automatic and manager-approved unconfigured commerce actions fail closed in production; generic connector operations reduce unreleased-tool pressure, but production provider proof is still missing | Keep stub policy regression guards and explicit stub labels/flags |
| 73 | Medium | Shopify | Enrichment fallback risk remains | Fail explicit in prod |
| 74 | Low | Translation | Anthropic provider exists and config dependency was fixed; fallback policy remains | Provider health and failure policy |
| 75 | Partial/Medium | Governance | Per-tenant action policies and connector config persist through the change-request ledger; other in-memory capability paths may remain | Persist all prod decisions |
| 76 | Partial/Medium | Governance | Work-order awaiting-fulfillment plus durable crisis handoff/outbox tests improve action/escalation handoff; live operator queue maturity remains | Live escalation drills and operator queue runbooks |
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
| 88 | Closed/Low residual | License | Dependency license audit gate added | Keep gate in CI and review exceptions |
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
| Architecture | 62 | 94 |
| Security | 57 | 98 |
| Scalability | 49 | 74 |
| Reliability | 55 | 92 |
| Governance | 72 | 98 |
| Code quality | 68 | 92 |
| Enterprise readiness | 43 | 86 |

## Customer Survival Verdict

Could Operious survive 10 customers?

Yes, as a controlled pilot platform if verified bearer auth is used, risky features stay constrained, operators accept manual monitoring, and the current release candidate recaptures the partial v235 S-10 evidence before real customers are added.

Could Operious survive 100 customers?

Not safely as a general production platform today. A narrow non-regulated pilot cohort is plausible after current-head S-10 proof, clean provider smoke, and repo/infra cleanup, but queue, provider, support, compliance, and production verification gaps would surface quickly outside a constrained scope.

Could Operious survive 1,000 customers?

No. The architecture has promising primitives but lacks hard operational, compliance, scaling, and isolation guarantees.

Would I allow Anker production operations?

No, not production. I would allow a scoped pilot after Phase E environment checks and repo/infra cleanup, with irreversible refund/replacement side effects constrained behind proven connectors.

Would I allow Samsung production operations?

No. Enterprise change control, compliance evidence, and integration hardening remain below bar.

Would I allow Microsoft production operations?

No. Auth/RBAC code improved, but live proof, supply chain, audit, and compliance posture remain below bar.

Would I allow Amazon production operations?

No. Scale, abuse resistance, isolation proof, and operational rigor are not close enough yet.
