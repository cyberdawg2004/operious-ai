# Phase 2.5 Stabilization Snapshot

Closes the constitutional gaps identified in the post-Phase-2 audit
before Phase 3 (storage / horizontal scale / supervisor surfaces)
begins.

## Validation

- backend pytest: 1535 passed
- frontend wire-format pinning: 31 passed (10 enum mirrors)
- frontend typecheck: PASS (all workspaces)
- frontend invariant tests (`tests-frontend/`): all green
- backend replay tests: PASS (no regressions)
- backend invariant tests: PASS (no regressions)

## Scope (17 wedges, A → K)

### Concurrency & chronology

- **2.5-A** — `OperationalArbitrationRuntime` sequence assignment is
  now atomic via an `asyncio.Lock`-guarded `_next_sequence()`. Lock
  is held ONLY for the increment; persistence runs outside the lock
  (lock-split doctrine). Concurrency regression test added.
- **2.5-B** — `SessionRuntime.append_event` now projects the
  request-level correlation string into the persisted
  `SessionTimelineEvent.correlation_id` via `derive_correlation_id`
  with namespace `"request_correlation"`. Audit-join from request to
  event restored.
- **2.5-D** — coordination, policy, and topology runtimes adopt the
  same lock-split pattern as 2.5-A: sequence assignment under lock,
  envelope construction + persistence outside. Persistence failure
  burns the assigned sequence (no contiguous-sequence invariant on
  these substrates; envelope is `None` on the result so callers
  know the sequence never became durable).

### Governance query parity

- **2.5-C1** — `GovernanceDecisionRecord` extended with
  `request_id`, `tenant_id`, `subject_kind` (mirrors
  `GovernanceTraceRecord`). Backward-compatible defaults so legacy
  records deserialize cleanly.
- **2.5-C2** — `_matches_decision` honors
  `query.request_id`, `query.tenant_id`, `query.subject_kind` at
  parity with `_matches_trace`. Pre-2.5-C2 these were silently
  ignored — multi-tenant audit queries leaked rows.
- **2.5-C3** — three regression tests pin tenant/request/subject
  isolation; one round-trip test pins serializer parity.

### Provenance + governance lineage

- **2.5-E** — `PolicyChain.governance_version` (chain-level) and
  `PolicyEvaluationResult.policy_version` (per-policy) flow through
  `EnforcementRuntime.evaluate` → `GovernanceDecision.metadata` →
  `GovernanceDecisionRecord.governance_version` /
  `PolicyEvaluationResultRecord.policy_version`. Audit can now
  answer "which governance build evaluated this?" without re-reading
  the live registry.
- **2.5-F** — `GovernanceContext` carries typed
  `principal_id` / `organization_id` / `environment_id` axes plus
  an `AuthorityContext` reference. A `__post_init__` invariant
  rejects `tenant_id` / `authority.tenant_id` drift so the
  governance substrate cannot disagree with the singular ingress
  authority resolution.
- **2.5-G1..G4** — `governance_decision_id` + `governance_chain_id`
  added to `BoundaryTrace`, `ArbitrationTrace`, `SessionTrace`,
  the `BoundaryIngressRecord` / `BoundaryEgressRecord` /
  `ArbitrationRecord` / `SessionEventRecord` shapes, and the
  `SessionMetadataKey` taxonomy. ID-only — no substrate imports
  governance internals; replay tools join by id against the
  governance repository.
- **2.5-H** — `OperationClassification` taxonomy lives in
  `app.governance.classification` (closed catalog of operational
  domains). Leaf invariant test pins no sibling-substrate imports.

### Composition root hardening

- **2.5-I** — `app.main.create_app` registers RFC 9457
  `application/problem+json` handlers for `HTTPException`,
  `RequestValidationError`, and unhandled exceptions. Production
  deployments without an explicit `trusted_proxies` tuple are
  rejected at composition time. `CORSMiddleware` is mounted from
  `CORS_ALLOW_ORIGINS` (wildcard rejected); authority headers are
  sourced exclusively from `AUTHORITY_HEADERS` so no other file
  references the canonical literals.

### Frontend wire-format + hygiene

- **2.5-J1** — `ViolationSeverity` switched to numeric (10/20/30/40)
  to match the backend `IntEnum`. Topology types (`NodeKind`,
  `EdgeKind`, `TopologyOutcome`) rewritten to mirror backend
  vocabulary byte-for-byte. `TraceNodeKind` gets a backend mirror
  in `app.observability.trace_node_kind`. Wire-format pinning test
  expanded with IntEnum support and 6 new pinnings (31 passing
  total).
- **2.5-J2** — `apps/command-center/src/app/providers.tsx` no longer
  unconditionally injects `principal-demo` / `demo-token`. Demo
  identity is gated behind the same `USE_MOCK_API` flag as the mock
  fetch transport; production builds carry `null` until a real auth
  flow hydrates them. New invariant test
  (`tests-frontend/src/demo-identity-isolation.test.ts`) pins the
  isolation.
- **2.5-J3** — `TraceTimeline` uses stable, payload-id-based React
  keys (`stableKeyFor(node)`) so reconciliation survives bundle
  reorderings. SDK now sends the canonical `X-Request-ID` header
  the backend's `RequestContextMiddleware` consumes (in addition to
  the legacy `x-operious-client-request-id` retained as an extension
  axis for client/server provenance distinction).

### Housekeeping

- **2.5-K** — this snapshot doc.

## Constitutional Guarantees Preserved

- replay semantics preserved (no UUID5 namespace touched).
- chronology semantics preserved (sequence space is monotonic; gaps
  on persistence failure are explicit and documented).
- authority propagation preserved (single canonical source of
  authority headers; governance context invariant pins
  `tenant_id` / `authority.tenant_id` agreement).
- bounded-context integrity preserved (governance-decision IDs are
  ID-only on sibling substrates; no upward imports introduced).
- runtime trust boundaries preserved (production composition root
  fail-closed on missing `trusted_proxies`; CORS wildcard
  rejected).

## Phase 3 entry criteria — met

- governance query parity gap closed.
- audit-join via `governance_decision_id` available on every
  cross-substrate trace.
- frontend wire-format aligned with backend (no silent drift
  possible without a wire-pinning test failure).
- composition root posture is fail-closed in production.
- demo identity cannot leak into production builds.
