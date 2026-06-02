# Operious Full Repository Security Audit - Phase B

Date: 2026-06-01
Audited HEAD: `4694d63` (`security(P0): voice provider handshake signature verification (S-04)`)
Baseline: `docs/audit/operious-full-repository-audit-2026-05-31.md`
Audit scope: re-examine S-01 through S-10 after Phase B commits.

## Closure Standard

A finding is marked `CLOSED` only when all three conditions are materially met:

1. The control exists in production code, not only docs or a stub.
2. A test proves the control.
3. Commit history contains negative or break-control evidence: the test targets the vulnerable path and would fail if the control is removed. Where a separate test-only break-control commit exists, it is called out. Where the negative proof lives in the same security commit, that weaker evidence is stated explicitly.

`S-10` is handled by the special Phase B rule: the boot gate and CI checks are committed, but live production verification is not done. `S-10` remains `OPEN` until Phase E deployment verification proves spoofing is rejected in production, production RLS is active, and workers, DLQ, and secrets are verified live.

## Verification Runs

Clean current-state proof supplied during this audit:

| Command scope | Result |
| --- | --- |
| Header authority, Auth0 claim config, tenant RBAC, domain capabilities, direct-apply authorization | `28 passed in 5.40s` |
| Header authority subset | `15 passed in 2.70s` |
| SSRF guard, quota runtime, production readiness CLI/gate | `44 passed in 1.46s` |
| DB-backed tenant config ledger, action grants, RLS coverage invariant | `17 passed in 1.66s` |
| Voice session token and provider signature tests | `13 passed in 2.13s` |

Additional observed verification caveats:

| Scope | Result | Interpretation |
| --- | --- | --- |
| Full combined audit suite | Timed out at 300s | Not counted as a pass. Smaller proof bundles above are used instead. |
| Voice session/provider/load/capacity bundle | `5 failed, 16 passed` | Current `apps/backend/tests/load/test_voice_capacity.py` and `apps/backend/tests/load/test_voice_load.py` fake websocket harnesses do not satisfy the new provider-signature handshake contract in `apps/backend/app/api/v1/routers/voice.py:71-80`. Security auth tests pass, but the committed load/capacity tests need repair. |
| SSRF DNS rebinding bundle in this sandbox | `4 failed, 52 passed, 1 skipped` | Failures were environmental: live DNS for `httpbin.org` failed and the sandbox could not bind `127.0.0.1`. The committed DNS pinning code and tests remain present, but this run did not re-demonstrate those tests passing locally. |

## Finding Closure Table

| Finding | Status | Production control evidence | Test evidence | Commit / break-control evidence |
| --- | --- | --- | --- | --- |
| S-01 Header authority spoofing | CLOSED | Production disables legacy authority headers by default in `apps/backend/app/core/config.py:415-424`; authority middleware rejects legacy headers when disabled in `apps/backend/app/middleware/authority_context.py:221-226`; deployed app wires trusted proxies in `apps/backend/app/main.py:762-768`; Fly config documents fail-closed header posture in `apps/backend/fly.toml:29`. | `apps/backend/tests/test_authority_header_disabled.py:59-62`, `apps/backend/tests/test_main_legacy_header_disabled.py:46`, `apps/backend/tests/test_config_security_posture.py:33-35`, current header/RBAC bundle `28 passed`. | `c9a2712` added production guard and negative spoofing tests. No separate red-only commit found; break-control proof is embedded in the same security commit. |
| S-02 Tenant config RBAC | CLOSED | Tenant mutation routes require capability dependencies in `apps/backend/app/api/v1/routers/tenant.py:90-116`; domain proposal checks run in `apps/backend/app/api/v1/routers/tenant.py:671-684`; domain capabilities and role mappings are in `apps/backend/app/auth/providers/jwt.py:78-112`; authority dependency defines distinct domain capabilities in `apps/backend/app/dependencies/authority.py:112-150`. | `apps/backend/tests/test_tenant_rbac_dependency.py`, `apps/backend/tests/test_domain_capabilities.py:282-350`, current header/RBAC bundle `28 passed`. | `8a7a7b1` added `tenant_admin` capability enforcement; `fe985fb` split broad admin into domain capabilities with negative cross-domain tests. |
| S-03 Self-approval | CLOSED | Direct self-approval is fail-closed in production in `apps/backend/app/core/config.py:434-442`; propose/approve/apply ledger endpoints exist in `apps/backend/app/api/v1/routers/tenant.py:126-240`; service rejects same proposer/approver in `apps/backend/app/services/tenant_config_change_request_service.py:117-124`; DB check constraint enforces approver distinctness in `apps/backend/migrations/versions/0063_tenant_config_change_requests.py:72-73`; RLS is enabled and forced in `apps/backend/migrations/versions/0063_tenant_config_change_requests.py:83-96`. | `apps/backend/tests/test_tenant_config_apply_authorization.py:71-82`, `apps/backend/tests/test_tenant_config_change_requests.py:116-190`, DB-backed bundle `17 passed`. | `7602507` added durable ledger, DB constraints, RLS, and lifecycle tests. Negative self-approval proof is embedded in that commit. |
| S-04 Voice unauthenticated | CLOSED for authentication control; load-test regression remains | Voice must be explicitly enabled and requires signed session token before accept in `apps/backend/app/api/v1/routers/voice.py:51-69`; provider auth token is loaded from tenant channel credentials in `apps/backend/app/services/voice_provider_auth.py:19-48`; provider signature is required in `apps/backend/app/api/v1/routers/voice.py:71-80`; Twilio signature verification is constant-time in `apps/backend/app/core/twilio_signature.py:38-55`. | `apps/backend/tests/test_voice_session_token.py:23-110`, `apps/backend/tests/test_voice_provider_signature.py:99-171`, voice auth bundle `13 passed`. | `6454bb7` added signed voice session token; `4694d63` added provider handshake signature tests. Negative auth tests are embedded in those commits. Load/capacity tests currently need harness repair. |
| S-05 Replayable decisions | CLOSED | Durable one-time grants are persisted in `apps/backend/app/agents/tools/grants.py:36-49`; consumption atomically sets `consumed_at` and `consumed_by` in `apps/backend/app/agents/tools/grants.py:97-103`; actor mismatch and already-consumed errors are enforced in `apps/backend/app/agents/tools/grants.py:262-291`; invoker requires binding hash, durable repository, actor match, unconsumed grant, and provider idempotency key in `apps/backend/app/agents/tools/invoker.py:263-356`; grant table has RLS and uniqueness in `apps/backend/migrations/versions/0064_agent_action_grants.py:31-94`. | `apps/backend/tests/test_action_grant_durability.py:102-242`, `apps/backend/tests/test_action_grant_durability.py:315-337`, `apps/backend/tests/test_tool_governance_mandatory.py:306-489`, DB-backed bundle `17 passed`. | `942b131` added durable grants; `4e6451c` is explicit test-only break-control evidence for actor binding and the five Phase B invariants. |
| S-06 SSRF | CLOSED for outbound dispatch guard | URL validation requires HTTPS, optional allowlist, full DNS resolution, blocked IP rejection, and pinned IP selection in `apps/backend/app/core/ssrf.py:173-233`; transport dials only the pinned validated IP in `apps/backend/app/core/ssrf.py:49-120`; outbound adapter runs validation before dispatch and uses pinned transport with redirects disabled in `apps/backend/app/boundary/outbound/adapter.py:81-107`. | `apps/backend/tests/test_ssrf_guard.py:26-133`, `apps/backend/tests/test_ssrf_dns_rebinding.py:27-153`; current SSRF guard bundle excluding sandbox-sensitive DNS pinning tests `44 passed` together with quota/readiness. | `cd8c6bc` added the primary guard and negative private/metadata tests; `20a890a` added DNS-rebinding pin-to-IP tests. The DNS-rebinding proof is committed, but this sandbox did not re-run it cleanly. |
| S-07 RAG poisoning | CLOSED for original tenant-knowledge poisoning path | New documents default to quarantined review status in `apps/backend/migrations/versions/0065_knowledge_review_status.py:26-35`; indexing scans content and carries review metadata in `apps/backend/app/knowledge/runtime.py:94-115`; scanner failures fail closed to quarantine in `apps/backend/app/knowledge/runtime.py:386-425`; retrieval only returns active approved documents in `apps/backend/app/knowledge/persistence/postgres.py:133-141`; prompts mark retrieved content as untrusted and structurally delimit chunks in `apps/backend/app/cognition/diagnostic_runtime.py:95-99` and `apps/backend/app/cognition/diagnostic_runtime.py:1007-1030`. | `apps/backend/tests/test_knowledge_poisoning_controls.py:150-278`, `apps/backend/tests/test_knowledge_poisoning_controls.py:307-348`. | `42a9c5c` added quarantine, injection scan, structural delimiting, and negative poisoning tests. Residual prompt-injection risk remains a general AI safety risk, but the audited S-07 write-to-retrieval path is controlled. |
| S-08 Auth0 claims | CLOSED | Auth0 namespace is configurable in `apps/backend/app/core/config.py:124-130`; Auth0 provider uses namespaced tenant/org/env/capabilities/roles claims in `apps/backend/app/main.py:733-753`; frontend defaults to verified bearer mode in `apps/command-center2/frontend/lib/api-client.ts:58` and only sends tenant headers in header mode at `apps/command-center2/frontend/lib/api-client.ts:101-104`. | `apps/backend/tests/test_config_security_posture.py:93-96`, current header/RBAC bundle `28 passed`. | `c9a2712` added namespaced mapping tests and verified-bearer frontend behavior. No separate red-only commit found; proof is embedded in the security commit. |
| S-09 Token quota | CLOSED for diagnostic LLM token quota | Token-per-minute pre-check blocks new calls once the window is exhausted in `apps/backend/app/agents/runtime/quota_runtime.py:139-156`; token usage is recorded in `apps/backend/app/agents/runtime/quota_runtime.py:253-282`; diagnostic runtime checks quota before LLM call and records post-call tokens in `apps/backend/app/cognition/diagnostic_runtime.py:261-309`. | `apps/backend/tests/test_quota_runtime.py:212-268`, `apps/backend/tests/test_diagnostic_agent_quota_integration.py:82-103`, quota/readiness bundle `44 passed`. | `4cdf202` added token quota enforcement and negative budget-exhaustion tests. Redis unavailable behavior remains intentionally fail-open and should stay documented as residual risk. |
| S-10 Production readiness | OPEN | Boot gate exists: `apps/backend/app/core/production_readiness.py:39-105` collects problems and raises; `apps/backend/app/main.py:468-473` runs it when enforced; readiness CLI exists in `apps/backend/scripts/check_production_readiness.py:23-39`; CI runs backend/frontend and DB-backed tests in `.github/workflows/ci.yml:64`. | `apps/backend/tests/test_production_readiness.py:38-95`, `apps/backend/tests/test_check_production_readiness_script.py:24-32`, `apps/backend/tests/test_rls_coverage_invariant.py:43-92`, quota/readiness bundle `44 passed`, DB-backed bundle `17 passed`. | `0a7f8af` added boot gate; `ac24b5d` added release-gate CLI, CI, and RLS invariant. Still OPEN because live Phase E production verification is absent. |

## Open Findings

Only one original S finding remains open:

| Finding | Why it remains open | Required proof to close |
| --- | --- | --- |
| S-10 Production readiness | The repository now has fail-closed boot and CI gates, but there is no live production proof in this audit. No evidence was produced that the deployed environment rejects spoofed authority headers, enforces RLS under production roles, has worker/DLQ paths operating, and has production secrets/providers correctly configured. | Phase E deployment verification: live spoofing rejection, live RLS tenant isolation, worker and DLQ smoke proof, secrets/provider proof, readiness CLI output from the deployment target, and rollback evidence. |

## Non-S Blocking / Residual Items Found In This Pass

These do not reopen the original S findings by themselves, but they block a clean "green current repository" claim:

| Item | Evidence | Required change |
| --- | --- | --- |
| Voice load/capacity tests are stale after provider signature gate | Running `apps/backend/tests/test_voice_session_token.py`, `apps/backend/tests/test_voice_provider_signature.py`, `apps/backend/tests/load/test_voice_capacity.py`, and `apps/backend/tests/load/test_voice_load.py` produced `5 failed, 16 passed`. Failures were in `test_voice_capacity_admission_blocks_at_limit`, `test_counter_released_on_call_termination`, `test_admission_fails_closed_when_redis_unavailable`, `test_oversized_frame_closes_call_and_releases_capacity`, and `test_voice_admission_under_overload`. | Update load/capacity fake websocket harnesses to expose `app.state.voice_provider_auth_token_loader` and valid provider signature headers, or split admission/capacity logic into a helper that can be tested after authentication has succeeded. Do not bypass production signature verification to make tests pass. |
| DNS-rebinding tests are environment-sensitive | This sandbox failed live DNS for `httpbin.org` and could not bind `127.0.0.1`. | Remove live DNS from `test_validator_returns_pinned_ip` by injecting a resolver, and mark local socket/SNI tests with clear environment requirements or rewrite with socket fixtures that work in CI. |
| S-09 quota is not a universal budget system | The closed control covers diagnostic LLM TPM enforcement. Redis unavailable behavior is fail-open by design. | For enterprise readiness, add provider-wide budgets, fail-closed or operator-selectable quota posture, billing alerts, and live Redis availability proof. |
| RAG poisoning is controlled, not solved universally | S-07 tenant write-to-retrieval path is gated by quarantine/review/approved-only retrieval and prompt delimiting. | Continue with human review workflow, reviewer UX, policy-tuned scanners, and evals against adversarial documents before high-stakes tenants. |

## Updated Scores

| Dimension | Prior audit | Phase B score | Movement | Reason |
| --- | ---: | ---: | --- | --- |
| Architecture | 62 | 66 | +4 | Ledgered config changes, durable grants, RAG review status, and pinned outbound transport make the substrate more explicit. Architecture is still uneven around live ops and remaining GAP features. |
| Security | 57 | 73 | +16 | S-02, S-04, S-05, S-06, and S-07 now have production controls and negative tests; S-01, S-03, S-08, and S-09 were already closed earlier. S-10 live proof remains open, and some proof quality is embedded in same commits rather than separate break-control commits. |
| Scalability | 49 | 51 | +2 | Voice capacity and quota work help, but no new live scale evidence, real workload proof, or production sizing proof was demonstrated. The current voice load/capacity tests need repair. |
| Reliability | 55 | 59 | +4 | Boot/readiness gates, CI, RLS invariant, and durable grant/ledger persistence improve reliability. Live worker/DLQ verification and clean full-suite execution remain incomplete. |
| Governance | 72 | 80 | +8 | Durable dual-control ledger, domain capabilities, action grants, binding hashes, and RAG review status materially strengthen governance evidence. UI workflow maturity and production proof remain unfinished. |
| Code quality | 68 | 70 | +2 | Tests and typed controls improved. Complexity increased, and the stale voice load/capacity tests show the test harness did not fully track the new security contract. |
| Enterprise readiness | 43 | 48 | +5 | Security posture moved sharply, but enterprise readiness is capped by S-10 live production verification, remaining GAP features, external integration proof, compliance evidence, and the test hygiene issues above. |

New headline scores:

- Security: `73/100`
- Enterprise readiness: `48/100`

## Scoped Pilot Safety Verdict

Scoped pilot safety is improved but conditional.

Operious is safer than the prior audit for a tightly scoped, non-regulated pilot where:

- verified bearer authority is used, not tenant headers;
- voice is disabled unless signed session tokens and provider signatures are configured;
- tenant config changes use the propose/approve/apply ledger;
- outbound webhooks use the SSRF guard and allowed hosts;
- knowledge ingestion uses quarantine/review before retrieval;
- action side effects remain limited, idempotent, and covered by durable grants;
- operators accept that S-10 live production verification is not complete.

It is not yet safe to call enterprise-production-ready. S-10 stays open until Phase E produces live deployment evidence. The current repository also should not be described as fully green until the voice load/capacity tests are updated for the provider-signature handshake and the DNS-rebinding tests are made deterministic in CI.
