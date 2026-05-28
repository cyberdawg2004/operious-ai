# Operious Warning Governance Strategy

Status: DRAFT CONTROL PLAN
Date: 2026-05-28
Branch: phase-2-2-stabilized
Current backend Pyright baseline: 0 errors, 651 warnings

This document defines how Operious governs type warnings, Any propagation,
contract drift, and invisible production-risk defects. The goal is not to
make Pyright quiet for aesthetics. The goal is to make the system harder to
break in the places that carry operational authority: governance, execution,
auth, memory, policy, adapters, queues, and customer-facing resolution.

## Current Warning Baseline

Command:

```bash
venv/bin/pyright apps/backend/app --outputjson
```

Observed on 2026-05-28:

| Metric | Value |
| --- | ---: |
| Files analyzed | 849 |
| Pyright errors | 0 |
| Pyright warnings | 651 |
| App Python files scanned | 928 |
| Files with warnings | 178 |
| Clean app files | 750 |
| Clean-file coverage | 80.82% |

Warning classes:

| Rule | Count |
| --- | ---: |
| reportUnknownVariableType | 395 |
| reportUnknownMemberType | 163 |
| reportUnknownArgumentType | 84 |
| reportUnknownLambdaType | 6 |
| reportUntypedFunctionDecorator | 3 |

Warning count by top module:

| Module | Count |
| --- | ---: |
| boundary | 166 |
| governance | 113 |
| coordination | 91 |
| supervisor | 48 |
| organizational_intelligence | 38 |
| session | 33 |
| arbitration | 31 |
| hardening | 30 |
| api | 22 |
| agents | 14 |
| core | 13 |
| runtime | 12 |
| workers | 8 |
| observability | 7 |
| tenant | 7 |
| execution | 5 |
| events | 4 |
| auth | 3 |
| resolution | 3 |
| db | 1 |
| models | 1 |
| survivability | 1 |

Warning count by risk plane:

| Risk plane | Count |
| --- | ---: |
| Orchestration kernel | 196 |
| Adapters | 166 |
| Governance engine | 112 |
| Memory consistency layer | 83 |
| Observability/hardening | 30 |
| APIs | 22 |
| Queues/core pressure controls | 13 |
| Execution plane | 13 |
| Auth/security | 11 |
| Other | 4 |
| Policy evaluator | 1 |

Any/Unknown propagation indicators:

| Indicator | Count |
| --- | ---: |
| Diagnostics mentioning Unknown | 419 |
| dict[Unknown, Unknown] | 241 |
| list[Unknown] | 34 |
| Diagnostics mentioning Any | 16 |

Top warning files:

| File | Count |
| --- | ---: |
| apps/backend/app/governance/persistence/postgres.py | 88 |
| apps/backend/app/boundary/adapters/builtin/whatsapp.py | 34 |
| apps/backend/app/coordination/persistence/postgres.py | 34 |
| apps/backend/app/boundary/adapters/channel_webhooks.py | 29 |
| apps/backend/app/supervisor/persistence/postgres.py | 28 |
| apps/backend/app/boundary/adapters/builtin/twilio_voice.py | 20 |
| apps/backend/app/boundary/adapters/builtin/zendesk.py | 16 |
| apps/backend/app/arbitration/evaluators/builtin/finding_conflict.py | 13 |
| apps/backend/app/organizational_intelligence/contracts/requests.py | 13 |
| apps/backend/app/core/deterministic_identity.py | 12 |

## Governance Rule

No PR may increase warning count. A PR that touches a high-risk plane must
reduce warnings in that plane unless the PR is an emergency production fix.

Hard stop conditions:

1. Pyright errors are non-negotiable: 0 required.
2. Warning count may never increase above the current checked-in baseline.
3. New `Any`, `Unknown`, untyped `dict`, or untyped `list` in governance,
   execution, auth/security, policy, queue, memory, or financial/action
   planes is a release blocker.
4. Any new persisted event payload, governance subject, execution envelope,
   memory record, or adapter output must have typed schema coverage.
5. Any new warning in a migration helper is allowed only if isolated to
   Alembic typing and documented with a local `# type: ignore[...]` plus
   a justification. Prefer typed SQLAlchemy operations first.
6. No warning suppression may be added without a nearby reason, owner, and
   planned removal milestone.

## Risk Plane Definitions

### Governance Engine

Includes governance decisions, enforcement, persistence, capability gates,
and subjects. Warnings here are dangerous because an unknown type can hide
policy bypass, malformed decision payloads, or persisted audit drift.

Required standard:

- No untyped governance subject payloads.
- No `Mapping[str, Any]` in enforcement-critical paths unless validated at
  the boundary into a typed dataclass or Pydantic model.
- Every persisted decision must round-trip through a typed serializer.
- Empty or missing policy chains must fail closed.

### Execution Plane

Includes execution runtime, persistence, workers, outbox, Celery publishers,
DLQ replay, and recovery tasks. Warnings here can hide duplicate execution,
lost outbox rows, claim races, stale-worker completion, or retry loops.

Required standard:

- Claim, complete, fail, dead-letter, and outbox state transitions must be
  typed end to end.
- Worker task input signatures must be typed and tenant-scoped.
- Outbox `PENDING`, `PUBLISHING`, `PUBLISHED`, and `FAILED` recovery
  semantics must be explicit.
- No publish path may run before the corresponding database transaction is
  committed.

### Auth/Security

Includes authority context, middleware, tenant ContextVar, RLS session setup,
dependencies, role separation, and tenant credentials.

Required standard:

- No endpoint should read `request.state` directly when a dependency exists.
- No database read/write may depend on ambient tenant data unless the RLS
  session variable has been set in the same async/thread context.
- Owner-session use must be marked `PRIVILEGED_PATH` and must not return
  tenant data to callers.
- Tenant credentials must be fetched at runtime and never hardcoded.

### Orchestration Kernel

Includes service layer, cross-substrate runtime composition, coordination,
arbitration, supervisor, QA, agents, and dispatch.

Required standard:

- Routers call services only.
- Services compose runtimes and repositories.
- Leaf substrates do not import sibling substrates.
- Runtime contracts must be typed protocols or concrete dataclasses.

### Memory Consistency Layer

Includes session timeline, events, knowledge, cognition usage, organizational
intelligence memory, replay, chronology, and audit records.

Required standard:

- Append-only event payloads must use stable schemas.
- Historical evidence must include immutable identifiers or hashes.
- Any rehydrated JSONB must be validated before use.
- Replays must be deterministic.

### Financial/Action Systems

This plane is mostly future work: refunds, replacements, warranty claims,
warehouse repair reports, credits, cancellations, and any external mutation.

Required standard before implementation:

- Every action must have a typed command, typed result, idempotency key,
  policy subject, governance decision ID, tool invocation record, and
  tenant credential resolution.
- No action may execute from an LLM free-form string.
- No action may execute without a persisted allow decision from central
  governance.
- High-value or policy-exception actions require explicit approval policy.

### APIs

Includes REST routers and schemas.

Required standard:

- Routers should not import repositories or runtimes directly.
- Response schemas should be typed and stable.
- Public routes must be listed as constitutional exceptions.
- Operator-sensitive endpoints must require operator authority.

### Adapters

Includes WhatsApp, Zendesk, Twilio voice, webhook adapters, translation, and
egress serialization.

Required standard:

- Raw provider payloads are untrusted at the boundary.
- Adapter normalization must convert raw JSON into typed canonical envelopes.
- No adapter may silently drop security-relevant fields like source IDs,
  external message IDs, routing addresses, language, or signature metadata.

### Queues

Includes Celery, Redis queue depth/age checks, admission, DLQ, and maintenance
tasks.

Required standard:

- Queue names live in `app.queues`.
- Admission checks must target real producer queues.
- Backpressure behavior must be explicit: fail-open is allowed only with a
  documented risk and compensating circuit breaker.
- Replays must be atomic and tenant-scoped.

### Integration Services

Includes composition root and dependency providers.

Required standard:

- `create_app()` remains the only composition root.
- Dependency providers are allowed to compose, but not to bypass tenancy,
  governance, or service boundaries.

### Observability

Includes metrics, health, alert evaluator, Sentry capture, logs, and audit
export.

Required standard:

- Observability may use privileged reads only with `PRIVILEGED_PATH`.
- Privileged observability must return aggregate/system state only.
- Alert evaluators must avoid N+1 scans.

### Prototypes, Playgrounds, Temporary Glue

Includes `_deprecated`, experimental scripts, playgrounds, and demo-only glue.

Required standard:

- Quarantined code must be excluded by path and must not be imported by active
  application code.
- Any temporary glue in active paths must carry an owner and removal milestone.

### Migrations

Includes Alembic files.

Required standard:

- Revision IDs must fit the widened Alembic version policy.
- RLS and FORCE RLS must be applied in the same migration for new
  tenant-scoped tables.
- Tenant FKs must be added for durable tenant-scoped tables.
- Migrations must fail explicitly on unsafe existing data; they must not
  silently delete or mutate production data.

## Metrics To Build

The warning governance report should produce these outputs on every PR:

1. Total Pyright errors, warnings, and information count.
2. Warning count by rule.
3. Warning count by top-level module.
4. Warning count by risk plane.
5. Warning count by file, sorted descending.
6. Warnings introduced by the current branch compared to `origin/main` or
   the chosen baseline branch.
7. Warnings resolved by the current branch.
8. Any propagation map:
   - `dict[Unknown, Unknown]` sources.
   - `list[Unknown]` sources.
   - `UnknownMemberType` call/member propagation.
   - `UnknownArgumentType` sinks where unknown data enters constructors,
     persistence, governance, worker tasks, or event payloads.
9. Type coverage:
   - Clean file percentage.
   - Warning-free high-risk-plane percentage.
   - Warnings per 1000 lines by module.
10. Weekly burn-down trend:
   - warnings opened,
   - warnings closed,
   - net warning delta,
   - high-risk warning delta,
   - top five modules by remaining debt.

Suggested storage:

```text
docs/architecture/warning-governance-snapshots/
  2026-05-28.json
  2026-06-04.json
  ...
```

Suggested generated report:

```text
docs/architecture/warning-governance-report.md
```

## Recommended Implementation Plan

### Phase WGS-1: Warning Metrics Tooling

Create a script that runs Pyright JSON mode, classifies diagnostics, and emits
both JSON and Markdown snapshots. It must run read-only by default.

Proposed path:

```text
apps/backend/scripts/warning_governance_report.py
```

Required outputs:

- `summary`
- `by_rule`
- `by_module`
- `by_risk_plane`
- `top_files`
- `any_propagation`
- `clean_file_coverage`
- `warnings_per_kloc`
- `new_warning_count` when a baseline is provided

### Phase WGS-2: Zero New Warnings Gate

Add a CI/local gate that compares current warning count to a stored baseline.
The gate fails if:

- error count is above 0,
- total warning count increases,
- high-risk warning count increases,
- any new warning appears in governance, execution, auth/security, policy,
  queue, memory, or financial/action planes.

### Phase WGS-3: Immediate Regression Reset

Fix the current +3 warning regression in
`apps/backend/app/resolution/persistence/postgres.py`.

Expected result:

- Pyright returns from 651 warnings to 648 warnings.
- No runtime behavior change.

### Phase WGS-4: JSON Boundary Type Aliases

Create central JSON types:

```python
JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject = dict[str, JSONValue]
JSONArray = list[JSONValue]
```

Use these for event payloads, metadata, adapter payloads, governance payloads,
and memory records. This phase should reduce the biggest warning family:
`dict[Unknown, Unknown]`.

### Phase WGS-5: Persistence Row Typing

Start with:

- `governance/persistence/postgres.py`
- `coordination/persistence/postgres.py`
- `supervisor/persistence/postgres.py`

Use typed SQLAlchemy `Select[...]`, explicit result scalar typing, and local
JSONB coercion helpers. This targets the heaviest top files.

### Phase WGS-6: Contract Alignment Audit

Create tests that compare:

- agent result contracts to timeline event payloads,
- governance subject schemas to persisted governance records,
- execution envelope fields to worker task signatures,
- memory records to JSONB serializer/deserializer outputs,
- API response schemas to service return objects.

No warning burn-down is accepted if it hides a contract mismatch.

### Phase WGS-7: High-Risk Runtime Hardening

Address production-risk findings:

- resolution send eligibility must be backed by central governance,
- failed execution outbox rows need a deliberate recovery/retry policy,
- fail-open queue pressure checks need a compensating safety strategy,
- resolution citations need immutable evidence fields.

## Existing Audit Findings To Fix

### Finding A: Pyright +3 Regression In Resolution Persistence

Severity: P1
Risk: type looseness around JSONB record hydration.
File: `apps/backend/app/resolution/persistence/postgres.py`

Problem:

`_as_list_of_dict()` uses `cast(list[Any], value)` and iterates `.items()`
after only checking `isinstance(item, dict)`. Pyright reports unknown
argument/key/value types.

Required fix:

- Replace the cast-based list comprehension with explicit iteration.
- Use `collections.abc.Mapping`.
- Keep runtime behavior equivalent.
- Require Pyright warning count to drop by 3.

### Finding B: Resolution Governance Verdict Is Local, Not Central

Severity: P0 before external sending
Risk: a future delivery adapter could treat local `ALLOW` as a true governance
allow decision.
File: `apps/backend/app/runtime/resolution_runtime.py`

Problem:

PR_RT1 is safe because it does not send externally. But
`ResolutionGovernanceVerdict.ALLOW` is produced by local deterministic logic,
not by `GovernanceRuntime` with a persisted `GovernanceDecision`.

Required fix before any outbound delivery:

- Add a central governance evaluation for customer communication.
- Use `CommunicationGovernanceSubject`.
- Persist the governance decision.
- Store the governance decision ID on the proposal or draft.
- Send eligibility must require that persisted decision to be `allow`.

### Finding C: Failed Execution Outbox Recovery Gap

Severity: P0 under production transport instability
Risk: transient Celery/Redis failure after request commit can leave an
execution outbox row in `FAILED` with no automatic retry.
Files:

- `apps/backend/app/dependencies/services.py`
- `apps/backend/app/execution/runtime.py`
- `apps/backend/app/execution/persistence/postgres.py`
- `apps/backend/app/workers/execution_recovery_tasks.py`

Problem:

The deferred publisher claims the outbox, commits, calls transport, and marks
outbox failed on delegate error. Current recovery reconciles stale
`PUBLISHING`, not `FAILED`.

Required fix:

- Define whether `FAILED` is terminal or retryable.
- If retryable, add bounded recovery from `FAILED` to `PENDING`.
- If terminal, add operator-visible alert and manual replay path.
- Add tests for publish failure, failed recovery, duplicate prevention, and
  no double publish.

### Finding D: Queue Pressure Checks Fail Open

Severity: P1 for async ticketing, P0 for realtime voice/chat
Risk: when Redis pressure checks fail, admission may admit work while the
queue system is unhealthy.
Files:

- `apps/backend/app/hardening/admission/gate.py`
- `apps/backend/app/core/queue_admission.py`

Problem:

Fail-open behavior protects availability but can hide catastrophic backlog
growth under Redis or queue telemetry failure.

Required fix:

- Keep current behavior only for non-realtime async channels if product policy
  accepts it.
- Add channel-aware admission policy.
- Realtime voice/chat must fail closed or degrade to a controlled callback
  path when pressure telemetry is unavailable.
- Emit explicit `admission_telemetry_unavailable` metrics.

### Finding E: Resolution Evidence Is Not Immutable Enough

Severity: P1 now, P0 before autonomous send
Risk: later reindexing can change what `document_id + chunk_ordinal` resolves
to, making historical proof weaker.
Files:

- `apps/backend/app/cognition/diagnostic_runtime.py`
- `apps/backend/app/runtime/resolution_runtime.py`
- knowledge persistence/runtime files

Problem:

`retrieved_citations` includes rank, document_id, title, document_type,
document_status, score, chunk_ordinal, and token_count. It does not include
chunk_id, vector_id, document_version, vector_index_name, content excerpt, or
excerpt/content hash.

Required fix:

- Extend citations going forward with immutable chunk/vector/version IDs.
- Add excerpt hash and optional safe excerpt.
- Use these fields in resolution proposals and trace UI.
- Old events must remain renderable.

## Hyperprompts

### Hyperprompt 1: Warning Governance Metrics Tooling

```text
# MASTER DIRECTIVE: WGS-1 - Warning Governance Metrics Tooling
# Project: Operious AI | Branch: phase-2-2-stabilized
# Baseline: Pyright 0 errors, 651 warnings

## WHAT THIS BUILDS

Build a read-only warning governance reporter that converts Pyright JSON
output into enforceable metrics:
- warning count by rule
- warning count by module
- warning count by risk plane
- top warning files
- Any/Unknown propagation indicators
- clean-file type coverage percentage
- warning-free high-risk-plane percentage
- optional baseline diff

## CONSTITUTIONAL RULES

- Do not modify application behavior.
- Do not change Pyright config to hide warnings.
- Do not add type ignores.
- The reporter must be deterministic.
- The reporter must run locally without network access.
- Generated snapshots must be explicit artifacts, not hidden state.

## HARD STOP CONDITIONS

1. Pyright errors appear.
2. The reporter changes app code.
3. The reporter suppresses or filters warnings without recording them.
4. The reporter cannot classify governance, execution, auth/security,
   memory, policy, APIs, adapters, queues, observability, migrations, and
   prototypes.

## STEP 0 - READ ONLY

Read:
- pyrightconfig.json or pyproject type settings
- apps/backend/app directory layout
- docs/architecture/warning-governance-strategy.md

Report:
1. Where Pyright config lives.
2. How many app Python files exist.
3. Proposed risk-plane mapping.
4. Proposed output JSON schema.

Pause for confirmation.

## PHASE 1 - IMPLEMENT REPORTER

Create:
apps/backend/scripts/warning_governance_report.py

Requirements:
- Run `venv/bin/pyright apps/backend/app --outputjson`.
- Parse diagnostics.
- Classify by rule, module, file, risk plane.
- Count Any/Unknown indicators.
- Compute clean-file coverage.
- Support `--json-output <path>`.
- Support `--markdown-output <path>`.
- Support `--baseline-json <path>` for delta comparison.
- Exit nonzero only when `--fail-on-regression` is passed and current
  warnings exceed baseline.

## PHASE 2 - TESTS

Add focused tests for:
- risk-plane classification
- clean-file coverage math
- baseline delta math
- Any/Unknown propagation counters

## VERIFICATION GATE

venv/bin/python apps/backend/scripts/warning_governance_report.py \
  --markdown-output /tmp/warning-governance-report.md \
  --json-output /tmp/warning-governance-report.json

venv/bin/pyright apps/backend/app 2>&1 | tail -5

Expected:
- reporter exits 0
- Pyright 0 errors
- warning count unchanged

Commit:
git add -A
git commit -m "test: add warning governance metrics reporter"
```

### Hyperprompt 2: Reset Current Pyright Regression

```text
# MASTER DIRECTIVE: WGS-2 - Reset Current Pyright Warning Regression
# Project: Operious AI | Branch: phase-2-2-stabilized
# Baseline: Pyright 0 errors, 651 warnings

## WHAT THIS FIXES

Remove the three new warnings in:
apps/backend/app/resolution/persistence/postgres.py

The target is to return from 651 warnings to 648 warnings without changing
runtime behavior.

## HARD STOP CONDITIONS

1. Pyright errors appear.
2. Warning count does not decrease by exactly 3.
3. Behavior of resolution proposal persistence changes.
4. Tests fail.

## STEP 0 - READ ONLY

Read:
- apps/backend/app/resolution/persistence/postgres.py
- apps/backend/app/resolution/persistence/records.py
- apps/backend/tests/test_resolution_runtime.py

Report why `_as_list_of_dict()` creates the 3 warnings.
Pause for confirmation.

## PHASE 1 - SURGICAL FIX

Replace the cast/list-comprehension helper with explicit iteration using
`collections.abc.Mapping`.

Do not touch any other file unless imports require cleanup.

## VERIFICATION GATE

venv/bin/pyright apps/backend/app/resolution/persistence/postgres.py
venv/bin/pyright apps/backend/app 2>&1 | tail -5
venv/bin/python -m pytest apps/backend/tests/test_resolution_runtime.py -q

Expected:
- file-level Pyright: 0 warnings
- full app Pyright: 0 errors, 648 warnings
- resolution tests pass

Commit:
git add -A
git commit -m "fix: remove resolution persistence pyright warning regression"
```

### Hyperprompt 3: Governance-Backed Resolution Send Eligibility

```text
# MASTER DIRECTIVE: RT-SAFE-1 - Central Governance For Resolution Send Eligibility
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS FIXES

Resolution proposals currently produce local governance verdict strings.
Before any external delivery adapter exists, send eligibility must require a
persisted central GovernanceDecision built from CommunicationGovernanceSubject.

## CONSTITUTIONAL RULES

- No external send path may be added in this PR.
- Router -> service -> runtime layering preserved.
- Resolution substrate must not import sibling substrates.
- Cross-substrate governance composition belongs in app.runtime or service
  layer, not in app.resolution leaf code.
- Tenant isolation enforced on all reads/writes.
- Governance fail-closed.

## HARD STOP CONDITIONS

1. Any proposal can become send_eligible without a persisted governance
   decision ID.
2. GovernanceRuntime is bypassed.
3. `require_approval`, `escalate`, `deny`, `degrade`, or `redact` becomes
   send eligible.
4. Existing diagnostic completion breaks.
5. Pyright errors appear.

## STEP 0 - READ ONLY

Read:
- app/runtime/resolution_runtime.py
- app/governance/subjects/communication.py
- app/governance/enforcement/runtime.py
- app/services/dispatch_service.py governance pattern
- app/workers/agent_tasks.py resolution hook
- resolution proposal migration/model/persistence

Answer:
1. Where should central governance be called?
2. What fields does CommunicationGovernanceSubject require?
3. Where should governance_decision_id be persisted?
4. How will old proposal rows remain compatible?

Pause for confirmation.

## PHASE 1 - MODEL AND MIGRATION

Add nullable governance_decision_id to resolution_proposals.
Add index tenant_id + governance_decision_id.
Do not make it NOT NULL yet because old rows exist.

## PHASE 2 - RUNTIME COMPOSITION

Add an application-layer governance gate that:
- builds CommunicationGovernanceSubject from tenant/session/execution/proposal
- evaluates through GovernanceRuntime
- persists the decision
- stores decision_id on the proposal
- maps only final decision allow to send_eligible
- maps all other decisions to pending_human_approval or denied

## PHASE 3 - TESTS

Add tests:
- allow decision makes proposal send_eligible
- require_approval blocks send eligibility
- deny blocks send eligibility
- missing governance runtime fails closed
- governance decision ID is stored
- old proposal rows still hydrate

## VERIFICATION GATE

TEST_DATABASE_URL=postgresql+asyncpg://operious_app_test:operious@localhost:5433/operious_test \
  venv/bin/python -m pytest apps/backend -q 2>&1 | tail -5

venv/bin/pyright apps/backend/app 2>&1 | tail -5

Expected:
- full suite green
- 0 Pyright errors
- no warning increase

Commit:
git add -A
git commit -m "fix: require central governance for resolution send eligibility"
```

### Hyperprompt 4: Failed Execution Outbox Recovery Policy

```text
# MASTER DIRECTIVE: EXEC-SAFE-1 - Failed Execution Outbox Recovery
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS FIXES

If execution publish fails after request commit, execution_outbox can be marked
FAILED. Current stale reconciliation handles PUBLISHING leases, not FAILED
rows. Define and implement a safe recovery policy.

## CONSTITUTIONAL RULES

- No duplicate execution publish.
- No worker claim without execution authority.
- No cross-tenant leakage.
- Recovery sweeps using owner sessions must be marked PRIVILEGED_PATH and
  must never return tenant data.
- At-least-once queueing is acceptable only with idempotent execution claim.

## HARD STOP CONDITIONS

1. A failed publish can be published twice concurrently.
2. A failed outbox row is silently ignored forever.
3. Recovery returns tenant payload data.
4. Pyright errors appear.
5. Full execution tests fail.

## STEP 0 - READ ONLY

Read:
- app/dependencies/services.py _DeferredExecutionPublisher
- app/execution/runtime.py outbox methods
- app/execution/persistence/postgres.py outbox methods
- app/workers/execution_recovery_tasks.py
- tests/test_execution_outbox_publisher.py
- tests/test_execution_runtime.py

Answer:
1. Is FAILED terminal today?
2. What code marks FAILED?
3. What recovery path can see FAILED?
4. What idempotency prevents duplicate execution?

Pause for confirmation.

## PHASE 1 - POLICY

Choose one:
- Retryable FAILED with bounded attempt count and cooldown.
- Terminal FAILED with operator-visible replay endpoint.

For Operious production reliability, prefer retryable FAILED with bounded
attempt count, then terminal DLQ/alert.

## PHASE 2 - IMPLEMENT

Add runtime/persistence methods to requeue eligible FAILED outbox rows to
PENDING only when:
- state is FAILED
- publish_attempt_count is below configured limit
- optional last failure age has passed

Add recovery task coverage.

## PHASE 3 - TESTS

Add tests:
- delegate publish error marks FAILED
- failed row requeues to PENDING
- requeued row publishes once
- concurrent recovery does not double publish
- exceeded attempt limit does not requeue
- tenant-scoped recovery filters correctly

## VERIFICATION GATE

venv/bin/python -m pytest \
  apps/backend/tests/test_execution_outbox_publisher.py \
  apps/backend/tests/test_execution_runtime.py \
  apps/backend/tests/test_execution_persistence_postgres.py \
  apps/backend/tests/test_celery_backlog_physics.py -q

venv/bin/pyright apps/backend/app 2>&1 | tail -5

Commit:
git add -A
git commit -m "fix: add bounded recovery for failed execution outbox publishes"
```

### Hyperprompt 5: Channel-Aware Admission Fail-Open Hardening

```text
# MASTER DIRECTIVE: QUEUE-SAFE-1 - Channel-Aware Admission Telemetry Failure Policy
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS FIXES

Admission and queue backpressure currently fail open when Redis telemetry is
unavailable. This is acceptable only for selected async channels. Realtime
voice/chat must fail closed or degrade to a controlled fallback.

## HARD STOP CONDITIONS

1. Realtime channels admit work when queue telemetry is unavailable.
2. Async ticket channels change behavior without explicit tests.
3. No metric/log is emitted for telemetry failure.
4. Pyright errors appear.

## STEP 0 - READ ONLY

Read:
- app/hardening/admission/gate.py
- app/core/queue_admission.py
- app/services/ticket_ingress_service.py
- app/services/batch_ingest_service.py
- queue/admission tests

Answer:
1. Which channels currently call AdmissionGate?
2. Which channels are realtime vs async?
3. What happens today when Redis info/llen/zrange fails?
4. Where should channel policy live?

Pause for confirmation.

## PHASE 1 - POLICY MODEL

Add channel-aware admission telemetry policy:
- async_email: fail_open_with_metric
- batch: fail_open_with_metric unless configured stricter
- webchat: fail_closed_or_defer
- whatsapp_live: fail_closed_or_defer
- voice: fail_closed_or_callback

## PHASE 2 - IMPLEMENT

When telemetry fails:
- async channels preserve current behavior but emit structured metrics/logs
- realtime channels return DEFER or REJECT with explicit reason
  telemetry_unavailable

## PHASE 3 - TESTS

Add tests for each channel class.

## VERIFICATION GATE

venv/bin/python -m pytest apps/backend/tests/test_admission_gate.py -q
venv/bin/pyright apps/backend/app 2>&1 | tail -5

Commit:
git add -A
git commit -m "fix: add channel-aware admission telemetry failure policy"
```

### Hyperprompt 6: Immutable Citation Evidence For Resolution

```text
# MASTER DIRECTIVE: MEMORY-SAFE-1 - Immutable Citation Evidence For Resolution
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS FIXES

Resolution evidence currently cannot prove the exact historical retrieved
chunk after reindexing. Extend citations with immutable identifiers and hashes.

## HARD STOP CONDITIONS

1. Old timeline events fail to render.
2. Citation data can expose another tenant's content.
3. Resolution proposals are created from uncited or mutable evidence while
   marked send_eligible.
4. Pyright errors appear.

## STEP 0 - READ ONLY

Read:
- app/knowledge/models.py
- app/knowledge/runtime.py
- app/cognition/diagnostic_runtime.py
- app/runtime/resolution_runtime.py
- command center Trace Inspector citation rendering

Answer:
1. Which immutable IDs already exist on KnowledgeRetrievalItem?
2. Where are citations built?
3. Where are citations persisted?
4. What fields can be added without migration?

Pause for confirmation.

## PHASE 1 - BACKEND CITATION EXTENSION

Add fields going forward:
- chunk_id
- vector_id
- document_version
- vector_index_name
- content_excerpt_sha256
- optional safe_excerpt

Do not remove old fields.

## PHASE 2 - RESOLUTION USE

Resolution proposals must copy immutable evidence fields into proposal
evidence and timeline payload.

## PHASE 3 - TESTS

Add tests:
- new diagnostic event includes immutable citation fields
- old event payload without fields still works
- cross-tenant citation cannot be loaded
- proposal evidence includes immutable fields

## VERIFICATION GATE

TEST_DATABASE_URL=postgresql+asyncpg://operious_app_test:operious@localhost:5433/operious_test \
  venv/bin/python -m pytest apps/backend/tests/test_citation_provenance.py \
  apps/backend/tests/test_resolution_runtime.py -q

venv/bin/pyright apps/backend/app 2>&1 | tail -5

Commit:
git add -A
git commit -m "fix: add immutable citation evidence for resolution proposals"
```

### Hyperprompt 7: JSON Type Alias Burn-Down

```text
# MASTER DIRECTIVE: TYPE-SAFE-1 - JSON Boundary Type Alias Burn-Down
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS FIXES

The largest warning family is untyped JSON:
dict[Unknown, Unknown] and list[Unknown].

## HARD STOP CONDITIONS

1. Runtime JSON behavior changes.
2. Event payload schemas become less permissive than production data unless
   migrations/backfills exist.
3. Pyright warning count increases.

## STEP 0 - READ ONLY

Find every local `_empty_metadata`, `_as_dict`, `_json_safe`, and
`Mapping[str, Any]` in active app paths.

Report:
1. Highest leverage shared JSON type location.
2. Which modules can migrate safely first.
3. Which persisted records require compatibility handling.

Pause for confirmation.

## PHASE 1 - TYPES

Create shared JSON aliases in a central app module.

## PHASE 2 - PILOT MODULES

Apply to low-risk schemas first:
- agents/results.py
- agents/capabilities.py
- observability/persistence/records.py

## PHASE 3 - HIGH-RISK MODULES

Apply to:
- governance persistence records
- session persistence records
- execution metadata
- cognition metadata

## VERIFICATION GATE

venv/bin/pyright apps/backend/app 2>&1 | tail -5
venv/bin/python -m pytest apps/backend/tests/test_identity_invariants.py \
  apps/backend/tests/test_session_runtime.py \
  apps/backend/tests/test_cognition_audit.py -q

Commit:
git add -A
git commit -m "refactor: type JSON boundary payloads without behavior changes"
```

### Hyperprompt 8: Persistence Warning Burn-Down

```text
# MASTER DIRECTIVE: TYPE-SAFE-2 - Persistence Warning Burn-Down
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS FIXES

The top warning files are Postgres persistence modules. These warnings hide
row-shape drift and JSONB hydration mistakes.

## HARD STOP CONDITIONS

1. Query behavior changes.
2. Pagination totals change unintentionally.
3. Tenant filters are weakened.
4. Pyright warning count increases.

## STEP 0 - READ ONLY

Read:
- governance/persistence/postgres.py
- coordination/persistence/postgres.py
- supervisor/persistence/postgres.py
- repositories/pagination.py

Report a warning-by-function map.
Pause for confirmation.

## PHASE 1 - GOVERNANCE PERSISTENCE

Type SQLAlchemy select/update results and JSONB coercion helpers.
Target: reduce governance/persistence/postgres.py warnings by at least 50%.

## PHASE 2 - COORDINATION PERSISTENCE

Apply same pattern.

## PHASE 3 - SUPERVISOR PERSISTENCE

Apply same pattern.

## VERIFICATION GATE

venv/bin/pyright apps/backend/app 2>&1 | tail -5
venv/bin/python -m pytest \
  apps/backend/tests/test_governance_persistence_postgres.py \
  apps/backend/tests/test_coordination_persistence_postgres.py \
  apps/backend/tests/test_supervisor_persistence_postgres.py -q

Commit:
git add -A
git commit -m "refactor: tighten Postgres persistence typing"
```

### Hyperprompt 9: Contract Alignment Audit

```text
# MASTER DIRECTIVE: CONTRACT-SAFE-1 - Protocol/Event/Governance/Memory Alignment Audit
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS AUDITS

Check that protocols, agent contracts, event schemas, governance payloads,
execution envelopes, and memory records align.

## READ-ONLY FIRST

Do not write code in Step 0.

Read:
- all Protocol definitions under app/*/persistence/repository.py
- app/agents/results.py
- app/agents/diagnostic_agent.py
- app/workers/agent_tasks.py
- app/session/runtime/runtime.py
- app/governance/subjects/*
- app/execution/persistence/records.py
- app/cognition/models.py
- app/knowledge/models.py

Answer:
1. Which event payloads are untyped dicts?
2. Which persisted records have metadata Mapping[str, Any]?
3. Which protocol methods accept or return Any?
4. Which governance subject payloads can drift?
5. Which worker task kwargs are not mirrored by typed work-item records?
6. Which memory records cannot prove historical replay after reindexing?

Pause for confirmation.

## PHASE 1 - ALIGNMENT TESTS

Add invariant tests only. No behavior changes.

Tests must verify:
- diagnostic result fields are present in diagnostic timeline payload
- resolution proposal fields are present in resolution timeline payload
- worker task kwargs match work-item fields
- governance subject kinds are known and fail-safe
- persisted memory records serialize and deserialize without field loss

## VERIFICATION GATE

venv/bin/python -m pytest apps/backend/tests/test_contract_alignment.py -q
venv/bin/pyright apps/backend/app 2>&1 | tail -5

Commit:
git add -A
git commit -m "test: add contract alignment invariants"
```

## Operating Cadence

Daily:

- Run warning governance report.
- Block new warning increases.
- Check high-risk planes first.

Weekly:

- Store JSON and Markdown snapshot.
- Burn down at least one top warning file.
- Review Any propagation map.
- Review warning-free coverage percentage.

Before every production deploy:

- Pyright errors: 0.
- Warning count: no increase from last accepted baseline.
- High-risk warning count: no increase.
- Full backend gate green.
- Smoke green.
- RLS/session invariants green.
- Queue and execution recovery tests green.

Target trajectory:

| Milestone | Target |
| --- | ---: |
| Current accepted baseline | 651 warnings |
| Immediate regression reset | 648 warnings |
| After JSON alias pilot | <= 600 warnings |
| After persistence burn-down phase 1 | <= 525 warnings |
| After persistence burn-down phase 2 | <= 450 warnings |
| Before autonomous external send | <= 300 warnings |
| Before first large enterprise pilot | <= 150 warnings |
| Long-term critical surface target | 0 warnings in high-risk planes |

