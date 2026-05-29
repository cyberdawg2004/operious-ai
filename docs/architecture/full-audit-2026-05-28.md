# Full Audit 2026-05-28

Redo date: 2026-05-29, Asia/Makassar.
Project: Operious AI.
Branch audited: phase-2-2-stabilized.
Mode: read-only audit; no application code changes, no migrations, no production actions.

## Gate Snapshot

- Warning governance report: 442 diagnostics, 442 warnings, 0 errors; 932 total files, 853 analyzed, 157 files with warnings, 775 clean files, 83.15 percent clean-file coverage. High-risk files: 475 total, 86 with warnings, 389 warning-free, 81.89 percent warning-free.
- Warning risk-plane counts: Adapters 166, Orchestration kernel 106, Memory consistency layer 62, APIs 22, Observability/hardening 21, Governance engine 17, Policy evaluator 14, Queues/core pressure controls 13, Auth/security 10, Execution plane 9, Other 2.
- Full backend suite, excluding load and chaos: 2580 passed, 2 skipped in 67.48s.
- Pyright: 0 errors, 442 warnings, 0 informations.
- Invariant command: 18 passed in 1.23s.
- Smoke, with explicit local test DB env: 4 passed in 5.30s.
- Smoke caveat: the exact smoke command without explicit `TEST_DATABASE_URL` can load `.env` because `apps/backend/tests/test_system_smoke.py:47` iterates `TEST_DATABASE_URL`, `apps/backend/tests/test_system_smoke.py:56` checks `database_url_skip_reason()`, and `apps/backend/tests/test_system_smoke.py:57` writes `DATABASE_URL` from that env var. I used the local test DB env to stay inside the audit rule.
- RLS local DB query: all checked tenant-scoped tables returned `relforcerowsecurity=true` and `relrowsecurity=true`: `boundary_egress`, `boundary_ingress`, `dead_letter_tasks`, `execution_attempts`, `execution_outbox`, `execution_records`, `governance_decisions`, `governance_enforcement_actions`, `governance_traces`, `operational_sessions`, `resolution_outbound_drafts`, `resolution_proposals`, `session_correlations`, `session_events`, `tenant_execution_circuit_breakers`, `tenant_execution_governance_configurations`, `tenant_governance_policies`, `tenant_knowledge_document_versions`, `tenant_knowledge_documents`, `tenant_topology_configurations`.

## DOMAIN 1 - Governance Bypass

Status: FINDINGS

### Findings

[P1] Dormant provider egress runtimes can proceed when capability governance is omitted

File: apps/backend/app/governance/capability/adoption.py:128

Proven: YES, with active production exposure UNVERIFIED.

Evidence: `evaluate_capability_gate` accepts `GovernanceRuntime | None` at `apps/backend/app/governance/capability/adoption.py:128` and explicitly returns `denial=None, decision_id=None, chain_id=None` when `governance is None` at `apps/backend/app/governance/capability/adoption.py:150`. `gate_or_deny` documents that `None` means "gate inert OR verdict ALLOW" at `apps/backend/app/governance/capability/adoption.py:193` and `apps/backend/app/governance/capability/adoption.py:209`. Voice egress makes `capability_governance` optional at `apps/backend/app/boundary/voice/egress/runtime.py:85`, calls the gate at `apps/backend/app/boundary/voice/egress/runtime.py:121`, then calls the provider at `apps/backend/app/boundary/voice/egress/runtime.py:136`. Translation egress has the same shape at `apps/backend/app/boundary/translation/egress/runtime.py:108`, `apps/backend/app/boundary/translation/egress/runtime.py:148`, and `apps/backend/app/boundary/translation/egress/runtime.py:175`. Translation ingress does the same at `apps/backend/app/boundary/translation/ingress/runtime.py:113`, `apps/backend/app/boundary/translation/ingress/runtime.py:157`, and `apps/backend/app/boundary/translation/ingress/runtime.py:184`.

Impact: A future composition site, test harness promoted to runtime, or direct internal caller can instantiate these provider runtimes without governance and still reach an external provider. The only construction sites found in this audit output were test helpers at `apps/backend/tests/test_translation_runtime.py:30`, `apps/backend/tests/test_translation_runtime.py:33`, and `apps/backend/tests/test_voice_runtime.py:35`; I did not prove an active API path. The dormant contract is still risky because the runtime signature permits fail-open construction.

Fix: Make governance mandatory for provider runtimes that call external systems, or make `gate_or_deny(None, ...)` fail closed for external-provider acts. Add an AST invariant that provider egress/ingress runtimes cannot expose optional governance for external acts.

[P2] Coordination topology and policy aggregators default ALLOW on empty findings

File: apps/backend/app/coordination/policy/runtime/aggregator.py:58

Proven: YES.

Evidence: The policy aggregator converts an empty findings tuple into `CoordinationPolicyDecision.ALLOW` and reason `"no findings; baseline allow"` at `apps/backend/app/coordination/policy/runtime/aggregator.py:58` through `apps/backend/app/coordination/policy/runtime/aggregator.py:65`. The topology aggregator converts empty findings into `CoordinationTopologyDecision.ALLOWED` at `apps/backend/app/coordination/topology/runtime/aggregator.py:47` through `apps/backend/app/coordination/topology/runtime/aggregator.py:52`.

Impact: Central governance still fail-closes later in the dispatch path, but these structural sublayers can silently allow if an evaluator set is empty or misconfigured. That weakens the "empty/missing policy chain returns DENY everywhere" invariant outside the central governance engine.

Fix: Require an explicit evaluator/policy configuration marker for empty-allow cases, and otherwise return a blocking degraded/denied outcome when no findings were produced.

### Clean Proof

- Central governance empty/missing chain is fail-closed. Missing chain returns a failed envelope at `apps/backend/app/governance/enforcement/runtime.py:140`; empty policy results synthesize DENY at `apps/backend/app/governance/decisions.py:189` through `apps/backend/app/governance/decisions.py:210`.
- ToolInvoker action tools now require central governance. Constructor rejects action-capable tools without governance at `apps/backend/app/agents/tools/invoker.py:71` through `apps/backend/app/agents/tools/invoker.py:80`; action invocation requires a nonblocking ALLOW at `apps/backend/app/agents/tools/invoker.py:177` through `apps/backend/app/agents/tools/invoker.py:193`; it then fetches the persisted decision for the expected tenant at `apps/backend/app/agents/tools/invoker.py:194` through `apps/backend/app/agents/tools/invoker.py:198`; action tools without runtime are denied at `apps/backend/app/agents/tools/invoker.py:230` through `apps/backend/app/agents/tools/invoker.py:242`; actual `tool.invoke` occurs after those gates at `apps/backend/app/agents/tools/invoker.py:244`.
- Boundary egress now requires a persisted central ALLOW before sinks. `BoundaryEgressRuntime.emit` validates governance before adapter/sink resolution at `apps/backend/app/boundary/egress/runtime.py:151`; the validator requires tenant authority, `governance_decision_id`, repository presence, a persisted decision lookup with expected tenant, and ALLOW at `apps/backend/app/boundary/egress/runtime.py:304` through `apps/backend/app/boundary/egress/runtime.py:343`. The result and trace stamp `governance_decision_id` at `apps/backend/app/boundary/egress/runtime.py:216` through `apps/backend/app/boundary/egress/runtime.py:230` and `apps/backend/app/boundary/egress/runtime.py:245` through `apps/backend/app/boundary/egress/runtime.py:260`.
- There is now an AST/invariant test for egress governance. It checks request/record fields at `apps/backend/tests/test_egress_governance_invariant.py:92`, checks persisted ALLOW before sinks at `apps/backend/tests/test_egress_governance_invariant.py:117`, and checks adapters/send bridges require governance at `apps/backend/tests/test_egress_governance_invariant.py:163`.
- Resolution runtime is wired to central governance. It builds a local gate at `apps/backend/app/runtime/resolution_runtime.py:229`, then calls `_evaluate_central_governance` at `apps/backend/app/runtime/resolution_runtime.py:252`. Missing central gate fails closed at `apps/backend/app/runtime/resolution_runtime.py:306`; exceptions fail closed at `apps/backend/app/runtime/resolution_runtime.py:315`. Send eligibility requires `SEND_ELIGIBLE` plus `governance_decision_id` at `apps/backend/app/runtime/resolution_runtime.py:413` through `apps/backend/app/runtime/resolution_runtime.py:421`; missing central decision id fails closed at `apps/backend/app/runtime/resolution_runtime.py:428` through `apps/backend/app/runtime/resolution_runtime.py:433`.
- Dispatch uses central governance before accepted execution. Coordination calls governance at `apps/backend/app/coordination/runtime/runtime.py:476` through `apps/backend/app/coordination/runtime/runtime.py:482`; accepted/degraded records carry the decision id at `apps/backend/app/coordination/runtime/runtime.py:521` through `apps/backend/app/coordination/runtime/runtime.py:529`; blocking decisions raise at `apps/backend/app/coordination/runtime/runtime.py:939`, and only `Decision.ALLOW` maps to accepted at `apps/backend/app/coordination/runtime/runtime.py:943` through `apps/backend/app/coordination/runtime/runtime.py:947`. Dispatch refuses an accepted result without a governance decision id at `apps/backend/app/services/dispatch_service.py:157` through `apps/backend/app/services/dispatch_service.py:172`, and diagnostic execution creation requires a governance admission token at `apps/backend/app/services/dispatch_service.py:262` through `apps/backend/app/services/dispatch_service.py:273`.
- LLM free-form diagnostic output is parsed into a typed envelope before execution persistence. The parser loads JSON and validates `DiagnosticLLMOutput` at `apps/backend/app/cognition/diagnostic_runtime.py:809` through `apps/backend/app/cognition/diagnostic_runtime.py:819`; `DiagnosticLLMOutput` forbids extra fields at `apps/backend/app/cognition/models.py:66` through `apps/backend/app/cognition/models.py:72`.

## DOMAIN 2 - Invisible Contracts

Status: FINDINGS

### Findings

[P2] Session timeline API drops governance join axes that persistence stores

File: apps/backend/app/session/models/timeline_event.py:67

Proven: YES.

Evidence: Session traces carry `governance_decision_id` and `governance_chain_id` at `apps/backend/app/session/traces/trace.py:68` through `apps/backend/app/session/traces/trace.py:75`. The persistence record carries the same fields at `apps/backend/app/session/persistence/records.py:69` through `apps/backend/app/session/persistence/records.py:71`, the DB row has columns at `apps/backend/app/session/db/models.py:212` through `apps/backend/app/session/db/models.py:218`, and Postgres row mapping writes/reads them at `apps/backend/app/session/persistence/postgres.py:500` through `apps/backend/app/session/persistence/postgres.py:512` and `apps/backend/app/session/persistence/postgres.py:565` through `apps/backend/app/session/persistence/postgres.py:584`. But `SessionTimelineEvent` stops at `idempotency_key` and has no governance fields at `apps/backend/app/session/models/timeline_event.py:67` through `apps/backend/app/session/models/timeline_event.py:78`. `event_to_record` and `event_record_to_model` omit those fields at `apps/backend/app/session/persistence/serializers.py:115` through `apps/backend/app/session/persistence/serializers.py:148`. The timeline route projects through `SessionTimelineResponse.from_timeline` at `apps/backend/app/api/v1/routers/session.py:86` through `apps/backend/app/api/v1/routers/session.py:99`, which maps to `TimelineEvent.from_session_event` at `apps/backend/app/api/v1/schemas/session.py:180` through `apps/backend/app/api/v1/schemas/session.py:204`. `TimelineEvent` itself has no governance fields at `apps/backend/app/models/timeline.py:13` through `apps/backend/app/models/timeline.py:24`.

Impact: The DB has governance lineage, but common timeline consumers cannot see or round-trip it through the domain/API projection. Forensics and replay can lose the join axis even though storage is correct.

Fix: Add governance fields to `SessionTimelineEvent` and `TimelineEvent`, update serializers both ways, and add a contract test that appending and reading a session event preserves governance ids through the public timeline API.

[P2] Resolution proposal and draft references are stored without referential integrity to session, execution, diagnostic event, proposal, or governance decision

File: apps/backend/app/resolution/db/models.py:42

Proven: YES.

Evidence: `ResolutionProposalRow.tenant_id` has a tenant FK at `apps/backend/app/resolution/db/models.py:36` through `apps/backend/app/resolution/db/models.py:40`, so tenant orphans are blocked. But `session_id`, `execution_id`, `dispatch_id`, and `diagnostic_event_id` are plain UUID columns without `ForeignKey` at `apps/backend/app/resolution/db/models.py:42` through `apps/backend/app/resolution/db/models.py:53`; `governance_decision_id` is also a plain nullable UUID at `apps/backend/app/resolution/db/models.py:79` through `apps/backend/app/resolution/db/models.py:81`. Drafts have a tenant FK at `apps/backend/app/resolution/db/models.py:168` through `apps/backend/app/resolution/db/models.py:172`, but `proposal_id` is not an FK at `apps/backend/app/resolution/db/models.py:174` through `apps/backend/app/resolution/db/models.py:176`, and the session/execution/dispatch/diagnostic ids are plain short strings at `apps/backend/app/resolution/db/models.py:177` through `apps/backend/app/resolution/db/models.py:188`.

Impact: A resolution proposal cannot point at a missing tenant, but it can point at a missing diagnostic event/session/execution/dispatch or a missing governance decision. A draft can also point at a missing proposal. This is an invisible lineage contract; the application usually writes records in order, but the database does not enforce it.

Fix: Add FKs where lifecycle allows, or add a persisted unresolved-reference state plus integrity sweeper if hard FKs are intentionally avoided. Fix the draft id column widths to use UUID columns or validated UUID-width strings.

[P2] High-risk contract planes still use opaque `Any` / `Mapping[str, Any]` payloads without schema-version guards

File: apps/backend/app/runtime/resolution_runtime.py:141

Proven: YES.

Evidence: Resolution proposal inputs accept `retrieved_citations: Sequence[Mapping[str, Any]]` at `apps/backend/app/runtime/resolution_runtime.py:141`, and governance-gate request fields include `recommended_actions` and `evidence` as `tuple[Mapping[str, Any], ...]` at `apps/backend/app/runtime/resolution_runtime.py:160` through `apps/backend/app/runtime/resolution_runtime.py:161`. Boundary egress accepts `artifact: Any` at `apps/backend/app/boundary/contracts/requests.py:95` through `apps/backend/app/boundary/contracts/requests.py:104`. Agent tool and agent outputs are metadata maps at `apps/backend/app/agents/results.py:37` through `apps/backend/app/agents/results.py:66`. Execution repository completion accepts `result: Mapping[str, Any]` at `apps/backend/app/execution/persistence/repository.py:77` through `apps/backend/app/execution/persistence/repository.py:85`. Operational events document metadata as opaque at `apps/backend/app/events/event.py:20` through `apps/backend/app/events/event.py:22`, store `metadata: Mapping[str, Any]` at `apps/backend/app/events/event.py:87`, and persist/read it as raw JSONB at `apps/backend/app/events/persistence/postgres.py:218` through `apps/backend/app/events/persistence/postgres.py:253`.

Impact: Producers can add, remove, or rename payload keys without a type checker or schema migration failing. Some tests pin current alignment, but the risk remains where opaque maps are the contract itself.

Fix: Promote high-risk payloads to versioned Pydantic/dataclass envelopes or require a `schema_version` and compatibility parser for each opaque JSONB payload that crosses runtime/persistence/API boundaries.

### Contract Alignment Table

| Producer | Consumer | Fields matched | Fields at risk | Typed? | Drift risk |
| --- | --- | --- | --- | --- | --- |
| Agent diagnostic result, `apps/backend/tests/test_contract_alignment.py:222` and `apps/backend/app/cognition/models.py:157` | Diagnostic timeline payload append at `apps/backend/app/workers/agent_tasks.py:733` | Summary, category, confidence, provider/model, token counts, cost, usage id, governance id, citations are emitted into `result_payload.model_dump()` at `apps/backend/app/workers/agent_tasks.py:738` | `retrieved_citations` is `list[dict[str, Any]]` at `apps/backend/app/cognition/models.py:172` | Partly typed | Medium |
| Resolution proposal record, `apps/backend/app/resolution/persistence/records.py:27` | `resolution_proposal_created` payload at `apps/backend/app/runtime/resolution_runtime.py:374` and worker append at `apps/backend/app/workers/agent_tasks.py:1048` | Proposal id, tenant, session, execution, dispatch, diagnostic event, reply, category, confidence, verdicts, governance id, status, timestamps, send eligibility | `recommended_actions` and `evidence` are mappings at `apps/backend/app/resolution/persistence/records.py:47` through `apps/backend/app/resolution/persistence/records.py:51` | Partly typed | Medium |
| Worker task kwargs, `apps/backend/app/workers/agent_tasks.py:129` | Typed work item at `apps/backend/app/workers/agent_tasks.py:244` | Contract test asserts task kwargs align with work-item fields at `apps/backend/tests/test_contract_alignment.py:301` through `apps/backend/tests/test_contract_alignment.py:334` | `_enqueued_at` intentionally transport-only and absent from work item | Mostly typed | Low |
| Governance context subject, `apps/backend/app/governance/context.py:90` | Governance decision record at `apps/backend/app/governance/persistence/records.py:294` | Decision id, verdict, stage, chain, reason, request id, tenant id, subject kind, governance version are persisted at `apps/backend/app/governance/persistence/records.py:303` through `apps/backend/app/governance/persistence/records.py:329` | `metadata: Mapping[str, Any]` at `apps/backend/app/governance/context.py:101` | Partly typed | Medium |
| Execution envelope/outbox, `apps/backend/app/execution/persistence/records.py:24` | Worker task signature and Celery publisher contract | Execution id and tenant id align with worker signature at `apps/backend/app/workers/agent_tasks.py:129` through `apps/backend/app/workers/agent_tasks.py:134`; outbox and publisher are pinned by `apps/backend/tests/test_contract_alignment.py:324` through `apps/backend/tests/test_contract_alignment.py:327` | Execution result remains mapping at `apps/backend/app/execution/persistence/records.py:43` | Partly typed | Medium |
| Memory/event record, `apps/backend/app/events/event.py:80` | JSONB serializer/deserializer at `apps/backend/app/events/persistence/postgres.py:223` | Core event axes and governance ids round-trip at `apps/backend/app/events/persistence/postgres.py:224` through `apps/backend/app/events/persistence/postgres.py:253` | Metadata has no schema version at `apps/backend/app/events/event.py:87` | Partly typed | Medium |
| KnowledgeRetrievalItem, `apps/backend/app/knowledge/models.py:41` | Persisted citation evidence and resolution evidence | Immutable fields exist on retrieval item at `apps/backend/app/knowledge/models.py:43` through `apps/backend/app/knowledge/models.py:47`; vector/chunk persistence carries them at `apps/backend/app/knowledge/persistence/records.py:17` through `apps/backend/app/knowledge/persistence/records.py:48`; SQL row mapping preserves them at `apps/backend/app/knowledge/persistence/postgres.py:493` through `apps/backend/app/knowledge/persistence/postgres.py:523`; diagnostic payload emits schema version, chunk id, vector id, document version, index, hashes at `apps/backend/app/cognition/diagnostic_runtime.py:720` through `apps/backend/app/cognition/diagnostic_runtime.py:748`; resolution normalization preserves optional immutable fields at `apps/backend/app/runtime/resolution_runtime.py:109` through `apps/backend/app/runtime/resolution_runtime.py:120` and `apps/backend/app/runtime/resolution_runtime.py:715` through `apps/backend/app/runtime/resolution_runtime.py:743` | Citation carrier is still `dict[str, Any]`; schema version exists | Partly typed | Low/Medium |

## DOMAIN 3 - Race Conditions & Concurrency

Status: FINDINGS

### Findings

[P2] Session open is deterministic but not idempotent under duplicate concurrent inserts

File: apps/backend/app/session/persistence/postgres.py:74

Proven: YES.

Evidence: Dispatch derives a deterministic session id from ingress at `apps/backend/app/services/dispatch_service.py:223` through `apps/backend/app/services/dispatch_service.py:235`. `save_session` then does a `SELECT SessionRow.revision` at `apps/backend/app/session/persistence/postgres.py:74` through `apps/backend/app/session/persistence/postgres.py:79`, enters a nested transaction, and inserts if no row was seen at `apps/backend/app/session/persistence/postgres.py:91` through `apps/backend/app/session/persistence/postgres.py:94`. It catches `IntegrityError` and raises `SessionPersistenceError` at `apps/backend/app/session/persistence/postgres.py:103` through `apps/backend/app/session/persistence/postgres.py:106`. The runtime folds generic exceptions into failed envelopes at `apps/backend/app/session/runtime/runtime.py:342` through `apps/backend/app/session/runtime/runtime.py:354`.

Impact: Two identical ingress deliveries should not double-open because the primary key/unique constraint rejects one insert, but one concurrent dispatch can fail instead of returning the already-open session. That is a user-visible race, not a duplication bug.

Fix: Replace the SELECT-then-INSERT with `INSERT ... ON CONFLICT DO UPDATE/NOTHING RETURNING`, or retry on duplicate by loading the existing session and validating deterministic equivalence.

### Clean Proof

- DLQ replay claim paths use row locks and CAS. Recovery sweep uses `with_for_update(skip_locked=True)` at `apps/backend/app/services/queue_operations_service.py:317` through `apps/backend/app/services/queue_operations_service.py:339`. Individual replay claim uses `with_for_update(skip_locked=True)` at `apps/backend/app/services/queue_operations_service.py:373` through `apps/backend/app/services/queue_operations_service.py:388`, then CASes replay state, tenant, replayed flag, and attempt count at `apps/backend/app/services/queue_operations_service.py:414` through `apps/backend/app/services/queue_operations_service.py:450`.
- Execution claim and completion transitions use atomic updates. Execution claim updates `REQUESTED -> CLAIMED` and checks rowcount at `apps/backend/app/execution/persistence/postgres.py:124` through `apps/backend/app/execution/persistence/postgres.py:166`. Completion CASes state, attempt number, and worker id at `apps/backend/app/execution/persistence/postgres.py:209` through `apps/backend/app/execution/persistence/postgres.py:256`.
- Execution outbox claim and publish transitions use atomic updates. Claim updates `PENDING -> PUBLISHING` at `apps/backend/app/execution/persistence/postgres.py:536` through `apps/backend/app/execution/persistence/postgres.py:564`. Publish requires `PUBLISHING` and `claim_id` at `apps/backend/app/execution/persistence/postgres.py:598` through `apps/backend/app/execution/persistence/postgres.py:612`.
- Commit-before-publish holds for DLQ replay: claim is committed at `apps/backend/app/services/queue_operations_service.py:220` through `apps/backend/app/services/queue_operations_service.py:233`, then publisher is called at `apps/backend/app/services/queue_operations_service.py:239` through `apps/backend/app/services/queue_operations_service.py:244`.
- Commit-before-publish holds for execution outbox: service commit occurs before deferred publisher flush at `apps/backend/app/dependencies/services.py:392` through `apps/backend/app/dependencies/services.py:396`; the deferred publisher commits the outbox claim before calling the delegate at `apps/backend/app/dependencies/services.py:763` through `apps/backend/app/dependencies/services.py:781`, then commits publish/failure state at `apps/backend/app/dependencies/services.py:782` through `apps/backend/app/dependencies/services.py:806`.

## DOMAIN 4 - Phantom State & Orphaned Records

Status: FINDINGS

### Findings

[P1] Queue backpressure can leave a committed execution and PENDING outbox without a publisher intent

File: apps/backend/app/services/dispatch_service.py:262

Proven: YES.

Evidence: Dispatch creates the diagnostic execution and PENDING outbox before publishing at `apps/backend/app/services/dispatch_service.py:262` through `apps/backend/app/services/dispatch_service.py:285`. It then calls `publish_execution` at `apps/backend/app/services/dispatch_service.py:287` through `apps/backend/app/services/dispatch_service.py:291`. If that call raises `QueueBackpressureError`, dispatch returns a halted degraded result with execution id and session id at `apps/backend/app/services/dispatch_service.py:292` through `apps/backend/app/services/dispatch_service.py:318`; it does not raise. The request-scoped dependency commits after service return and then flushes deferred publishers at `apps/backend/app/dependencies/services.py:392` through `apps/backend/app/dependencies/services.py:396`. But deferred `publish_execution` checks backpressure before appending an intent at `apps/backend/app/dependencies/services.py:748` through `apps/backend/app/dependencies/services.py:761`. Therefore, under backpressure, an execution/outbox can commit with no in-memory intent to claim/publish it in that request. Execution creation itself creates the PENDING outbox at `apps/backend/app/execution/runtime.py:396` through `apps/backend/app/execution/runtime.py:409`.

Impact: A user-facing dispatch can return degraded/halted while durable execution state exists but is never handed to the normal publisher path. The stale-outbox reconciler may eventually help only if scheduled for PENDING rows; the current immediate request loses the publish intent.

Fix: Treat backpressure before durable execution creation as an admission failure, or commit an explicit deferred/retryable outbox intent and rely on a scheduled reconciler that covers PENDING rows. Add a test that backpressure leaves either no execution/outbox or a recoverable published/requeued intent.

[P1] FAILED execution outbox recovery exists but is not scheduled or present in the DLQ replay allow map

File: apps/backend/app/workers/celery_app.py:99

Proven: YES.

Evidence: Failed publisher attempts set outbox state to FAILED at `apps/backend/app/execution/persistence/postgres.py:651` through `apps/backend/app/execution/persistence/postgres.py:666`. Retryable FAILED rows can be listed at `apps/backend/app/execution/persistence/postgres.py:720` through `apps/backend/app/execution/persistence/postgres.py:761` and CAS-requeued to PENDING at `apps/backend/app/execution/persistence/postgres.py:763` through `apps/backend/app/execution/persistence/postgres.py:828`. Runtime APIs exist at `apps/backend/app/execution/runtime.py:934` through `apps/backend/app/execution/runtime.py:1029` and `apps/backend/app/execution/runtime.py:1031` through `apps/backend/app/execution/runtime.py:1075`. A Celery task exists at `apps/backend/app/workers/execution_recovery_tasks.py:134` through `apps/backend/app/workers/execution_recovery_tasks.py:151`. However, `task_routes` includes stale execution/escalation outbox tasks but not `reconcile_failed_execution_outbox` at `apps/backend/app/workers/celery_app.py:69` through `apps/backend/app/workers/celery_app.py:88`, and `beat_schedule` has cleanup, stale escalation outbox, queue depth, and alerts but no failed execution outbox schedule at `apps/backend/app/workers/celery_app.py:99` through `apps/backend/app/workers/celery_app.py:122`. DLQ replay defaults include stale execution/escalation outbox but not failed execution outbox at `apps/backend/app/queue_operations/dlq_replay.py:17` through `apps/backend/app/queue_operations/dlq_replay.py:29`, and replay kwargs omit it at `apps/backend/app/queue_operations/dlq_replay.py:180` through `apps/backend/app/queue_operations/dlq_replay.py:192`.

Impact: FAILED outbox rows are no longer unrecoverable in code, but automatic recovery is not wired. They require a manual operator path that may not be discoverable through normal DLQ replay tooling.

Fix: Add a beat schedule and task route for `reconcile_failed_execution_outbox`, add it to `TASK_DEFAULT_QUEUES` and replay kwarg mapping, and add a smoke/invariant test that FAILED outbox recovery is routable and scheduled.

[P2] Resolution proposals can orphan relative to diagnostic/session/execution lineage

File: apps/backend/app/resolution/db/models.py:42

Proven: YES.

Evidence: Same as Domain 2: tenant FK is present at `apps/backend/app/resolution/db/models.py:36` through `apps/backend/app/resolution/db/models.py:40`; session/execution/dispatch/diagnostic ids are plain indexed UUID columns at `apps/backend/app/resolution/db/models.py:42` through `apps/backend/app/resolution/db/models.py:53`; draft proposal id is plain UUID at `apps/backend/app/resolution/db/models.py:174` through `apps/backend/app/resolution/db/models.py:176`.

Impact: A proposal can point at a missing diagnostic event or execution after manual data repair, partial test seeding, failed migrations, or code paths that bypass the runtime.

Fix: Add referential integrity or explicit unresolved-reference tracking with repair tooling.

## DOMAIN 5 - Execution Duplication

Status: CLEAN

### Findings

None proven in the active diagnostic worker path.

### Clean Proof

- The diagnostic Celery task takes only `execution_id` and `tenant_id` as required lineage handles at `apps/backend/app/workers/agent_tasks.py:129` through `apps/backend/app/workers/agent_tasks.py:134`.
- The worker claims the durable execution before doing work at `apps/backend/app/workers/agent_tasks.py:271` through `apps/backend/app/workers/agent_tasks.py:300`; if the claim is refused, it returns `claim_refused` at `apps/backend/app/workers/agent_tasks.py:288` through `apps/backend/app/workers/agent_tasks.py:293`.
- Started, completed, resolution-created, and draft-created timeline appends use deterministic idempotency keys at `apps/backend/app/workers/agent_tasks.py:320` through `apps/backend/app/workers/agent_tasks.py:335`, `apps/backend/app/workers/agent_tasks.py:733` through `apps/backend/app/workers/agent_tasks.py:744`, and `apps/backend/app/workers/agent_tasks.py:1048` through `apps/backend/app/workers/agent_tasks.py:1058`.
- Completion is protected by the execution CAS at `apps/backend/app/workers/agent_tasks.py:752` through `apps/backend/app/workers/agent_tasks.py:758` and the persistence CAS at `apps/backend/app/execution/persistence/postgres.py:209` through `apps/backend/app/execution/persistence/postgres.py:256`.
- Celery retries are bounded. `execute_diagnostic_agent` sets `max_retries=4` at `apps/backend/app/workers/agent_tasks.py:121` through `apps/backend/app/workers/agent_tasks.py:127`; retry policy uses max retry budgets at `apps/backend/app/agents/runtime/retry_policy.py:19` through `apps/backend/app/agents/runtime/retry_policy.py:69`; the retry decision stops at exhaustion at `apps/backend/app/workers/agent_tasks.py:1400` through `apps/backend/app/workers/agent_tasks.py:1429`.
- UUID5 determinism prevents duplicate IDs for execution/outbox/proposal/draft lineage, not arbitrary duplicate semantics. Execution id is derived from kind, dispatch, session, tenant at `apps/backend/app/execution/runtime.py:374` through `apps/backend/app/execution/runtime.py:379`; proposal id is derived from tenant/session/execution/dispatch/diagnostic event at `apps/backend/app/runtime/resolution_runtime.py:237` through `apps/backend/app/runtime/resolution_runtime.py:244`; draft id is derived from tenant and proposal id at `apps/backend/app/runtime/resolution_runtime.py:339` through `apps/backend/app/runtime/resolution_runtime.py:342`.

Residual risk: The backpressure orphan in Domain 4 can create unprocessed executions, but I did not prove duplicate diagnostic analyses for one execution after Celery retry plus manual DLQ replay because the durable execution claim CAS blocks a second worker.

## DOMAIN 6 - Deadlocks

Status: CLEAN

### Findings

None proven.

### Clean Proof

- No synchronous external LLM/provider call is held inside the transaction that loads the diagnostic snapshot. `_generate_diagnostic_reasoning_for_work_item` loads the snapshot first at `apps/backend/app/workers/agent_tasks.py:363` through `apps/backend/app/workers/agent_tasks.py:367`, then calls `_complete_diagnostic_reasoning_snapshot` outside that loader at `apps/backend/app/workers/agent_tasks.py:369`. The loader opens a DB session, calls DB-backed preparation, and commits before returning at `apps/backend/app/workers/agent_tasks.py:403` through `apps/backend/app/workers/agent_tasks.py:427`. The LLM call itself is `complete_reasoning_snapshot` at `apps/backend/app/cognition/diagnostic_runtime.py:276` through `apps/backend/app/cognition/diagnostic_runtime.py:284`.
- Provider circuit outcome recording happens in a separate DB session after the provider call at `apps/backend/app/workers/agent_tasks.py:470` through `apps/backend/app/workers/agent_tasks.py:500`.
- Authority persistence happens later in its own nested transaction at `apps/backend/app/workers/agent_tasks.py:721` through `apps/backend/app/workers/agent_tasks.py:758`.
- Claim/update paths reviewed use single-table CAS or single-row locks. DLQ replay has `FOR UPDATE SKIP LOCKED` at `apps/backend/app/services/queue_operations_service.py:373` through `apps/backend/app/services/queue_operations_service.py:388`; execution claim uses single-table update CAS at `apps/backend/app/execution/persistence/postgres.py:124` through `apps/backend/app/execution/persistence/postgres.py:166`.

Unverified: I did not build a full static lock-order graph for every repository method. To fully prove no deadlock under load, add a static lock-order checker or DB tracing under concurrent chaos tests.

## DOMAIN 7 - Tenant Isolation / RLS

Status: CLEAN

### Findings

None proven.

### Clean Proof

- `GovernanceContext` enforces tenant/authority agreement in `__post_init__` at `apps/backend/app/governance/context.py:103` through `apps/backend/app/governance/context.py:115`.
- DB begin listener sets transaction-local `app.current_tenant_id` from the ContextVar at `apps/backend/app/db/session.py:92` through `apps/backend/app/db/session.py:100`. The ContextVar defaults to `None` at `apps/backend/app/db/tenant_context.py:35` through `apps/backend/app/db/tenant_context.py:39`.
- Celery diagnostic task saves and restores the tenant context at `apps/backend/app/workers/agent_tasks.py:137` through `apps/backend/app/workers/agent_tasks.py:166`.
- Owner session factory is explicitly privileged and documented as bypassing RLS only for `PRIVILEGED_PATH` contexts at `apps/backend/app/db/session.py:150` through `apps/backend/app/db/session.py:155`. The invariant test enforces owner factory use and tenant context ordering for workers at `apps/backend/tests/test_identity_invariants.py:99` through `apps/backend/tests/test_identity_invariants.py:126`.
- Local DB query confirmed FORCE RLS and RLS enabled on all checked tenant-scoped tables listed in the Gate Snapshot.

Residual risk: Pyright still reports warning debt in auth/security and governance planes; see Domain 9.

## DOMAIN 8 - Production Load Failure Modes

Status: FINDINGS

### Findings

[P1] Queue/admission fail-open behavior can admit async work when telemetry is unavailable

File: apps/backend/app/core/queue_admission.py:93

Proven: YES.

Evidence: Execution queue depth check catches any exception, logs it, sets `depth = 0`, and proceeds when `depth <= max_queue_depth` at `apps/backend/app/core/queue_admission.py:93` through `apps/backend/app/core/queue_admission.py:108`. Admission gate defers only realtime chat and voice when telemetry is unavailable at `apps/backend/app/hardening/admission/gate.py:251` through `apps/backend/app/hardening/admission/gate.py:263`, then returns ADMIT at `apps/backend/app/hardening/admission/gate.py:265` through `apps/backend/app/hardening/admission/gate.py:269`. Channel classes include async ticket, batch, realtime chat, voice, and internal execution at `apps/backend/app/hardening/admission/models.py:31` through `apps/backend/app/hardening/admission/models.py:38`.

Impact: Redis/telemetry outage fails open for async ticket, batch, and internal execution paths, and for execution publisher queue depth checks. Realtime chat and voice fail closed-ish with defer. This can amplify load during the exact condition where the queue telemetry is unavailable.

Fix: Make fail-open/fail-closed configurable per channel, default async execution to bounded defer when Redis/telemetry is unavailable, and expose an operator override for incident mode.

[P1] Backpressure orphan can become a load-amplified stuck-work mode

File: apps/backend/app/services/dispatch_service.py:287

Proven: YES.

Evidence: See Domain 4 finding. The specific production-load edge is that `publish_execution` backpressure is caught at `apps/backend/app/services/dispatch_service.py:287` through `apps/backend/app/services/dispatch_service.py:318`, while the dependency still commits at `apps/backend/app/dependencies/services.py:392` through `apps/backend/app/dependencies/services.py:396`.

Impact: During sustained queue pressure, the system can accumulate committed PENDING outbox rows that were never submitted by the request publisher. This creates recovery load after the incident.

Fix: Same as Domain 4, plus add metrics/alerts for PENDING outbox age and committed-but-unpublished executions.

### Clean Proof

- Provider 429 retry growth is bounded. `PROVIDER_429` has `max_retries=4` at `apps/backend/app/agents/runtime/retry_policy.py:19` through `apps/backend/app/agents/runtime/retry_policy.py:26`; retry exhaustion is checked at `apps/backend/app/workers/agent_tasks.py:1400` through `apps/backend/app/workers/agent_tasks.py:1429`.
- Provider circuit breaker blocks open/half-open providers before calls at `apps/backend/app/runtime/provider_circuit_breaker.py:110` through `apps/backend/app/runtime/provider_circuit_breaker.py:157`, and opens after threshold at `apps/backend/app/runtime/provider_circuit_breaker.py:330` through `apps/backend/app/runtime/provider_circuit_breaker.py:404`.
- 429 outcomes are recorded into the circuit breaker at `apps/backend/app/workers/agent_tasks.py:485` through `apps/backend/app/workers/agent_tasks.py:496`.
- DB engine uses `NullPool` in current settings-backed construction at `apps/backend/app/db/session.py:85` through `apps/backend/app/db/session.py:88`, reducing pool exhaustion risk but increasing connection churn under concurrency.

## DOMAIN 9 - Type Safety in High-Risk Planes

Status: FINDINGS

### Findings

[P2] WSG baseline is still warning-heavy in high-risk planes

File: apps/backend/app/workers/celery_app.py:61

Proven: YES.

Evidence: Pyright returned `0 errors, 442 warnings, 0 informations`. The warning governance report counted high-risk warnings by plane: Governance engine 17, Policy evaluator 14, Queues/core pressure controls 13, Auth/security 10, Execution plane 9. One current Pyright tail warning is in the worker/Celery configuration around `conf.update` at `apps/backend/app/workers/celery_app.py:61`. Additional high-risk `Any` examples are listed in Domain 2: resolution evidence at `apps/backend/app/runtime/resolution_runtime.py:141`, execution completion result at `apps/backend/app/execution/persistence/repository.py:77`, and cognition retrieved citations at `apps/backend/app/cognition/models.py:172`.

Impact: The WSG goal of zero warnings in governance, execution, auth/security, policy, queue, and financial/action planes is not met. This does not prove runtime failure, but it does mean static analysis cannot fully guard the invisible contract planes yet.

Fix: Burn down warnings plane by plane, starting with governance, execution, queue/admission, and auth/security. For each high-risk `Any`, either justify it with a typed boundary parser or replace it with a versioned envelope.

## DOMAIN 10 - Constitutional Invariant Verification

Status: CLEAN

### Findings

None proven.

### Pass/Fail by Invariant

| Invariant | Status | Evidence |
| --- | --- | --- |
| Router -> service -> runtime layering, no router -> repo/runtime | PASS in full backend suite; explicit router invariant tests collected separately | `apps/backend/tests/test_router_invariants.py:444` checks routers do not construct concrete repositories; tenant router layering tests exist at `apps/backend/tests/test_tenant_configuration_invariants.py:24` and `apps/backend/tests/test_tenant_configuration_invariants.py:36`. Full suite passed with only public auth/health router skips. |
| DispatchService zero Celery imports / zero `.delay()` | PASS by contract alignment and architecture shape; no explicit failure found | Dispatch uses the injected execution publisher at `apps/backend/app/services/dispatch_service.py:287` through `apps/backend/app/services/dispatch_service.py:291`; `apps/backend/tests/test_contract_alignment.py:324` through `apps/backend/tests/test_contract_alignment.py:327` pins publisher kwargs instead of a direct service-owned Celery call. |
| No `_deprecated` imports in active code | PASS in invariant/full suite | Deprecated bridge isolation is pinned at `apps/backend/tests/test_runtime_authority_consumption.py:265`; forbidden dependency and transitional vendor tests passed in full suite. |
| No sibling substrate imports | PASS in invariant/full suite | Router/substrate invariant tests include sibling-substrate checks, e.g. `apps/backend/tests/test_router_invariants.py:201`, `apps/backend/tests/test_boundary_invariants.py:67`, `apps/backend/tests/test_session_invariants.py:53`, and related substrate invariant files. |
| UUID5 in lineage paths, no uuid4 | PASS | Explicit invariant `apps/backend/tests/test_identity_invariants.py:65` requires uuid4 calls to be marked ephemeral/approved; runtime restart-safe identity tests start at `apps/backend/tests/test_identity_invariants.py:133`; full suite also includes `apps/backend/tests/test_no_uuid4_in_lineage_paths.py:22`. |
| `create_app()` sole composition root | PASS in full suite/invariant shape | `apps/backend/tests/test_router_invariants.py:467` pins `create_app` middleware stack; smoke creates the app through `create_app` at `apps/backend/tests/test_system_smoke.py:51` through `apps/backend/tests/test_system_smoke.py:62`. |

Command-scope caveat: the exact invariant command requested only ran `test_identity_invariants.py` and `test_forbidden_dependencies.py`, producing 18 passed. Other constitutional invariants were covered by the full backend suite, not by that exact two-file invariant command.

## Prioritized Fix Order

1. P1: Make provider egress/ingress capability governance fail closed when omitted, or make governance construction mandatory.
2. P1: Fix queue backpressure so durable execution/outbox state is not committed without a recoverable publisher intent.
3. P1: Wire `reconcile_failed_execution_outbox` into Celery routes, beat schedule, and DLQ replay maps.
4. P1: Change queue/admission telemetry failures to bounded defer for async/internal execution or add per-channel fail-mode configuration.
5. P2: Add FK or unresolved-reference integrity for resolution proposal/draft lineage.
6. P2: Preserve governance join axes through session timeline domain/API models.
7. P2: Make session open concurrent duplicate delivery idempotent.
8. P2: Remove default ALLOW from empty coordination topology/policy aggregators unless explicitly configured.
9. P2: Replace high-risk `Any` / opaque mapping contracts with versioned typed payloads.
10. P2: Continue high-risk Pyright warning burn-down.

## Plane Ratings

| Plane | Rating | Justification |
| --- | ---: | --- |
| Governance Bypass | 7/10 | Central dispatch, ToolInvoker, boundary egress, and resolution paths are materially hardened; dormant optional provider governance and coordination empty-allow remain. |
| Invisible Contracts | 6/10 | Contract tests exist and citation provenance is much better, but timeline governance projection, raw FKs, and opaque maps still create drift surfaces. |
| Race Conditions & Concurrency | 8/10 | Execution, outbox, and DLQ claim paths are CAS/lock protected; session open duplicate race remains. |
| Phantom State & Orphans | 5/10 | Tenant orphans are blocked, but backpressure and FAILED outbox routing gaps can strand work; resolution lineage FKs are incomplete. |
| Execution Duplication | 8/10 | Durable execution claim CAS and idempotency keys are strong; residual manual/recovery edge risk is mostly around stuck work, not duplicate analyses. |
| Deadlocks | 8/10 | No external LLM call found inside DB transactions; exhaustive lock-order proof is still unverified. |
| Tenant Isolation / RLS | 8/10 | FORCE RLS confirmed locally and tenant ContextVar discipline is tested; warning debt remains in auth/security. |
| Production Load Failure Modes | 5/10 | Bounded provider retries/circuit breaker help, but queue telemetry fail-open and backpressure orphan are production-load risks. |
| Type Safety | 5/10 | 442 warnings and warnings in governance/execution/auth/queue planes mean the WSG target is not yet met. |
| Constitutional Invariants | 8/10 | Full suite and invariant suite pass; exact two-file invariant command does not cover every named invariant directly. |

## Proven vs Suspected vs Unverified

### Proven

- ToolInvoker action gating requires central governance and persisted ALLOW.
- Boundary egress requires `governance_decision_id` and persisted ALLOW before sinks.
- The egress governance AST invariant exists.
- Resolution runtime is central-governed and fails closed when decision id is missing.
- Central governance empty/missing policy chain fails closed.
- Coordination topology/policy aggregators default allow on empty findings.
- Provider voice/translation runtimes can be constructed with inert capability governance.
- Session timeline projections drop governance join axes.
- Resolution proposal/draft lineage lacks DB referential integrity beyond tenant.
- Execution/DLQ/outbox active claim paths reviewed use CAS or `FOR UPDATE SKIP LOCKED`.
- Session open has a SELECT-then-INSERT duplicate race that fails one concurrent caller.
- Backpressure can commit execution/outbox without an appended publisher intent.
- FAILED execution outbox recovery exists but is not scheduled/routed/mapped for DLQ replay.
- Diagnostic worker retries and provider 429 retries are bounded.
- LLM diagnostic completion is not held inside the snapshot-loading DB transaction.
- FORCE RLS/RLS was enabled on checked local test DB tenant tables.
- Warning count is 442 with high-risk warnings still present.

### Suspected

- Dormant provider egress/ingress optional governance may become an active external bypass if composed into a route or service later.
- Opaque JSONB payloads may drift silently under future producer/consumer changes even where current contract tests pass.
- Production incident recovery could accumulate stuck PENDING/FAILED outbox rows during Redis or publisher instability.

### Unverified

- Active production exposure for `VoiceEgressRuntime`, `TranslationEgressRuntime`, or `TranslationIngressRuntime`; current app search found only test construction, but a full deployment composition audit would be needed.
- Exhaustive cross-repository lock-order deadlock proof; this would need static lock-order tooling or concurrency tracing.
- Exact smoke behavior without explicit local `TEST_DATABASE_URL`; the DB-backed smoke run passed, and the exact command produced an incomplete tail despite exit 0 in this environment.
