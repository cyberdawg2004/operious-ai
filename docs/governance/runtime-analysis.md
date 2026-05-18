I have rich, grounded context. Here is the read-only governance routing analysis.

Governance Routing Analysis — Read-Only
Grounded in the existing runtime, not speculative. Every claim references a file currently in the active runtime.

1. Where governance visibility naturally belongs in the current runtime
The runtime already has one canonical governance pipeline that is the only correct integration model:

build GovernanceContext
evaluate
PolicyChain
results
GovernanceDecision
GovernanceEnvelope
stamp decision_id, chain_id
Substrate Runtime
GovernanceContext (actor, subject, stage)
GovernanceRuntime
PolicyEvaluationEngine
build_decision (pure)
EnforcementHandler
Persisted substrate envelope
This pipeline is already deployed end-to-end in exactly one substrate: coordination. app/coordination/runtime/runtime.py lines 21–25 document the doctrine, and the governance_decision_id / governance_chain_id fields on app/coordination/envelopes.py lines 109–110 are the constitutional shape for "governance reference attached to a persisted operational envelope".

Substrates that already carry governance visibility (no work needed)
Substrate	Envelope field	Mechanism
coordination
CoordinationEnvelope.governance_decision_id + .governance_chain_id
Runtime invokes GovernanceRuntime.evaluate() between topology+policy and persistence.
agents (tool invocation)
ToolInvocationEnvelope.governance_envelope
One full envelope per tool call.
agents (execution)
AgentExecutionEnvelope.governance_envelopes: tuple[...]
Collects every evaluation under one execution.
supervisor (findings)
EvaluationEvidenceRecord.governance_decision_ids: tuple[str, ...]
Findings cite the decisions they observed.
governance itself
GovernanceEnvelope.trace
Apex emission.
Substrates that currently have no governance reference on their envelopes
Substrate	Envelope	Observation
boundary (ingress)
BoundaryIngressEnvelope
Carries BoundaryTrace with correlation_id, tenant_id, external_message_id, but no governance reference.
boundary (egress)
BoundaryEgressEnvelope
Same.
session
SessionEnvelope
SessionTrace-only; timeline events have correlation_id but no decision pointer.
arbitration
ArbitrationEnvelope
The substrate IS a decision-maker; carries no upstream governance reference.
translation (ingress/egress)
TranslationEnvelope family
None.
voice (ingress/egress)
VoiceEnvelope family
None.
hardening
HardeningEnvelope family
Hardening IS quasi-governance; no separate hook needed.
organizational_intelligence
All sub-runtime envelopes
None.
Natural placement principle: governance visibility belongs only on substrates that perform externally-observable operational acts — those whose envelopes are themselves persisted and replayed as evidence. Currently that maps to coordination and agents only. Boundary and session are next-natural because they sit at the request and timeline frontiers respectively.

2. Where authority propagation already exists implicitly
Authority is already a first-class field in multiple substrates, but not under that name. Renaming or formalizing is the constitutional risk surface, not introducing the field.

Implicit authority carriers (already present)
Substrate	Carrier	Authority dimension
governance
GovernanceContext.actor line 65
Initiating authority
governance
GovernanceContext.subject line 68 (typed BaseGovernanceSubject)
Subject identity authority
governance
ExecutionGovernanceSubject.downstream_targets line 54
Delegation target authority
governance
CorrelationContext.correlation_id line 46
Pipeline-level authority continuity
supervisor
EscalationDecisionRecord lines 155–193
Escalation authority
coordination
CoordinationEnvelope.governance_decision_id (line 109)
Apex-decision-derived authority
arbitration
apex evaluator name + ArbitrationResult outcome
Arbitration authority
boundary
BoundaryTraceContext.tenant_id + .source_id + .external_message_id
Originating-tenant + external-source authority
session
SessionTimelineEvent.correlation_id (line)
Causal/lineage authority across the timeline
agents
AgentExecutionTrace.parent_execution_id + .parent_chain
Delegated execution authority
Authority dimensions that exist but are not yet propagated through envelopes
escalation authority — EscalationDecisionRecord exists in supervisor persistence but is NOT referenced by any operational envelope (coordination/agents/session). Escalations live in supervisor inspection records only.
arbitration authority — ArbitrationEnvelope.result.apex_evaluator is determined inside the arbitration substrate but no other substrate's envelope carries a reference to "the arbitration decision id that authorised this operational act".
supervisor authority — supervisor inspection decisions (SupervisorDecisionRecord) are NOT referenced by any operational substrate. The supervisor reads from operational substrates; the reverse edge does not exist.
This is the asymmetry the authority-propagation doctrine implicitly targets: authority flows OUTWARD (governance → coordination → agents → tool) but the reverse audit edges are partial (supervisor sees governance but not vice-versa; arbitration outcomes don't appear on substrate envelopes).

3. Where governance context should attach to operational envelopes
Three classes of attachment site, ranked by constitutional safety:

Class A — Identifier-only attachment (safest, replay-trivial)
Attach governance_decision_id: uuid.UUID | None + governance_chain_id: str | None to envelopes. Exact precedent already exists in CoordinationEnvelope lines 109–110. This is replay-safe because:

IDs are deterministically generated (generate_decision_id).
Fingerprinting is unaffected (the decision is persisted separately under its own id).
Replay reconstruction joins by id, not by re-deriving the decision.
Candidate sites in order of constitutional alignment:

BoundaryIngressEnvelope / BoundaryEgressEnvelope — boundary is the natural classification point. Attaching the decision id lets every downstream substrate query "which boundary call was governed by which decision?" without coupling.
SessionTimelineEvent — adding governance_decision_id: SessionCorrelationId | None (or a typed wrapper) to the event payload would let replay reconstruct "the governance state at this exact timeline position". This is the chronology-visible governance the doctrine explicitly calls for.
ArbitrationEnvelope — attaching governance_decision_id would close the lineage between governance authorisation and arbitration apex.
Class B — Correlation-only attachment (safe, deferred)
Attach correlation_id: uuid.UUID | None propagation through substrate envelopes where it's already implicit but not first-class. CorrelationContext (app/governance/identity/correlation.py lines 33–47) is the existing primitive — substrates can adopt it without coupling to GovernanceDecision directly.

Class C — Full envelope embedding (DANGEROUS, forbidden by current architecture)
Do not embed GovernanceEnvelope instances directly inside operational substrate envelopes (except where it already happens — AgentExecutionEnvelope.governance_envelopes). Reasons:

Couples persisted operational artifacts to governance schema evolution.
Breaks the "envelopes are bytes-stable" invariant when governance trace shape evolves.
Creates fan-out replay cost (each operational replay has to deserialize a full governance trace).
The existing precedent in AgentExecutionEnvelope is the only place this embedding is correct, because agents are governance-density-hotspots (one execution → many governance evaluations) and the embedding is the supervisor's primary read shape.

4. Where chronology persistence should observe governance state
Two existing chronology-bearing surfaces are the natural observers:

4a. Session timeline (app/session/timeline/builder.py)
The session timeline is the platform's primary chronology substrate. SessionTimelineEvent already has:

deterministic event_id = derive_event_id(session_id, sequence)
monotonic sequence
correlation_id: SessionCorrelationId | None
payload: Mapping[str, Any] (canonicalized via canonicalize_payload)
Governance-state observation belongs in payload (Class A: id-only) keyed under a stable taxonomy entry (session.governance.decision_id, session.governance.chain_id, session.governance.final_decision). The session substrate then becomes chronology-of-governance-state without taking on governance authority itself.

The append_event invariant (line 92: if event.sequence != expected: raise SessionLineageError) PROTECTS chronology — adding governance reference fields to the payload (not to the event header) preserves the contiguous-sequence guarantee.

4b. Coordination envelope sequence (app/coordination/envelopes.py line 102)
CoordinationEnvelope.sequence is already a per-runtime-instance monotonic. Combined with governance_decision_id (already present), it is the only existing chronology-of-governance-observation surface in the runtime today. This works.

4c. Boundary ingress sequence (app/boundary/ingress/runtime.py line 106)
The boundary runtime has a private _sequence counter and BoundaryTrace.sequence field but does NOT yet expose a governance-reference field on the trace. If governance starts emitting decisions at boundary classification time (per docs/governance/operation-classification.md), this trace is the natural observer.

Chronology rules being respected (do not violate)
SessionTimelineEvent.recorded_at monotonicity is enforced by append_event line 100.
CoordinationEnvelope.sequence deterministic per-instance ordering.
BoundaryTrace.sequence deterministic per-instance ordering.
derive_event_id(session_id, sequence) — deterministic and replay-derivable; do not introduce non-deterministic id sources.
5. Where replay reconstruction will require governance lineage
Replay-reconstruction surfaces already exist; governance lineage is partially present and partially missing.

Replay surfaces currently in the runtime
Substrate	Reconstruction path	Reads governance lineage today?
supervisor
view_builder.build_inspection_view_from_records (replay path)
Yes — _record_governance_view (the function I pyright-suppressed) is the single-source decision-classification used by both live and replay paths. This was the invariant pinned by test_runtime_integrity.py.
session
app/session/reconstruction/
No — session reconstruction rebuilds timelines without governance reference.
hardening
app/hardening/replay/
Partial — hardening's replay-verification path observes operational fingerprints but not governance decision chains.
coordination
record_to_envelope (app/coordination/persistence/serializers.py)
Yes — governance_decision_id round-trips through persistence.
agents
view_builder agent-replay path
Yes — governance envelopes are reconstructed inline.
Replay-reconstruction requirements going forward
Per docs/chronology/propagation.md ("Replay is historical reconstruction, NOT operational re-execution"):

Governance decisions MUST NOT be re-evaluated during replay. They must be read from persistence by decision_id and projected into the reconstructed view.
This means every substrate that gains a governance_decision_id envelope field MUST also gain a replay-time persistence loader that joins by that id. Adding the field without the loader creates silent lineage gaps (decision ID dangling against nothing).
The existing _record_governance_view is the single-source projection helper. Future substrate-replay paths should reuse it, not re-implement.
6. Safest future hook points (ranked)
Ranked by constitutional alignment with the existing runtime — each is a place where the shape already exists and adoption preserves existing invariants.

Tier 1 — direct shape parity with existing precedent
Hook	Why safe
BoundaryIngressEnvelope / BoundaryEgressEnvelope add governance_decision_id/governance_chain_id fields
Exact mirror of CoordinationEnvelope lines 109–110. Boundary persistence serializers already pattern-match the same shape. No new types.
SessionTimelineEvent.payload taxonomy keys for governance reference
payload is already canonical Mapping; taxonomy.py already declares namespaced keys. Adding session.governance.* keys is zero-coupling.
BoundaryTrace.metadata taxonomy keys for operation classification
metadata already Mapping[str, Any]; BoundaryMetadataKey already exists.
ArbitrationEnvelope add `governance_decision_id: uuid.UUID
None`
Tier 2 — small new envelope field, no new substrate dependency
Hook	Why safe
SessionEnvelope.trace add optional governance reference
Trace-only attachment (not result) means it does not affect is_ok semantics or the typed-result union.
BoundaryTraceContext add operation_classification: OperationClassification | None
BoundaryTraceContext is propagation-only; doesn't affect persistence.
Tier 3 — composition-layer hook (new module, no envelope mutation)
Hook	Why safe
New app/governance/routing/ module — a composition-root helper that builds GovernanceContext from a substrate's request shape
Pure builder; no runtime mutation; substrate runtimes opt in by calling it. Mirrors CorrelationContext pattern.
New app/governance/classification.py — pure function classify_operation(action, subject) → OperationClassification
Pure function; replay-trivial.
7. Dangerous coupling risks
Ranked by constitutional severity.

Risk DC-1 (HIGH) — A new central "GovernanceRouter" service
The most likely architectural mistake when implementing the routing-map doctrine. A central router that "sits between substrates and governance" would:

Centralize substrate orchestration (violates architecture/backend-conventions.md).
Couple every substrate to one routing module's evolution.
Become an implicit decision sink for governance-context construction.
The existing runtime DOES NOT NEED A ROUTER. GovernanceRuntime.evaluate(context) is the router. Substrates call it directly with their own typed GovernanceContext. The current coordination/runtime/runtime.py pattern is the model — duplicate it per substrate, do not introduce a mediator.

Risk DC-2 (HIGH) — Governance becomes a substrate-import dependency
If a substrate's envelopes.py directly imports GovernanceDecision, the substrate's wire format becomes coupled to governance schema evolution. The existing precedent already shows the safe pattern: CoordinationEnvelope imports only uuid.UUID (line 109 — governance_decision_id: uuid.UUID | None). It carries the ID, not the decision.

Constraint: Future hooks must carry uuid.UUID / str references, not GovernanceDecision / GovernanceEnvelope instances (except in the documented agent-execution embedding).

Risk DC-3 (MEDIUM) — app/governance/routing/ module becoming an orchestrator
If the proposed Tier-3 routing module starts CALLING substrates instead of providing pure builders, it becomes hidden orchestration. The architectural constraint is: it builds GovernanceContext; it does not invoke GovernanceRuntime.evaluate(); it does not coordinate substrates.

Risk DC-4 (MEDIUM) — Operation classification embedded in GovernanceContext
GovernanceContext.metadata: Mapping[str, Any] (line 70) already accepts opaque classification data. Adding a typed classification: OperationClassification field to GovernanceContext would either:

Force every existing call site to declare a classification (breaking change), or
Default to a "GENERIC" value (silent semantic drift — opposite of the operation-classification doctrine's intent).
Safer pattern: classification goes into GovernanceContext.subject (use the typed-subject discriminator), not into the context envelope.

Risk DC-5 (MEDIUM) — Supervisor reaching back into operational substrates
The recent stabilization pinned _record_governance_view cross-module reference at tests/test_runtime_integrity.py:354. If new "supervisor authority" propagation requires supervisor to write back references into operational envelopes, the direction of dependency would invert and the substrate isolation under test_forbidden_dependencies.py would fail.

Safer pattern: supervisor remains read-only over operational substrates; operational substrates persist references that supervisor projects via pure builders.

Risk DC-6 (LOW–MEDIUM) — Boundary substrate adopting governance
Boundary is currently a pure translation substrate (see app/boundary/ingress/runtime.py lines 1–15: "translation substrate, not an orchestration runtime"). Calling GovernanceRuntime.evaluate() from inside boundary ingest() would promote boundary into an orchestration role.

Safer pattern: boundary stamps an operation_classification and emits the envelope. A composition-layer caller (the future app/governance/routing/ builder, or an existing coordination dispatcher) reads the boundary envelope and constructs the GovernanceContext. Boundary remains translation-only.

8. Replay-sensitive governance risks
Replay risk RG-1 (HIGH) — Re-evaluation during replay
Per docs/chronology/propagation.md: "Replay is historical reconstruction, NOT operational re-execution." If a replay path calls GovernanceRuntime.evaluate() to "re-derive" a decision, it:

Uses datetime.now(timezone.utc) (app/governance/enforcement/runtime.py lines 101, 211) — non-deterministic.
Uses generate_decision_id() — non-deterministic UUID.
Emits new audit events.
Replay paths MUST load GovernanceDecisionRecord from persistence by id; they MUST NOT re-evaluate. This is the constitutional rule that view_builder.build_inspection_view_from_records (replay path) already follows. Future substrate replay paths must follow the same rule.

Replay risk RG-2 (HIGH) — Adding governance_decision_id without persistence-projection
If BoundaryIngressEnvelope gains governance_decision_id but GovernanceDecisionRecord is never persisted under a queryable index keyed by boundary, replay reconstruction will have a dangling ID. The existing GovernancePersistenceProtocol 1 already supports id-keyed lookup — future hooks MUST use it, not invent new lookup paths.

Replay risk RG-3 (MEDIUM) — Wall-clock fields leaking into governance metadata
GovernanceTrace.started_at / .ended_at / .latency_ms (governance/tracing.py) are wall-clock; they are correctly NOT used for ordering. If future hooks start ordering by these fields (e.g. "governance evaluation timeline"), replay determinism breaks. Ordering must use decision_id + correlation_id + sequence (substrate-specific monotonic) — never timestamps.

Replay risk RG-4 (MEDIUM) — metadata: Mapping[str, Any] semantic drift
Every governance-adjacent shape has a metadata field. The intelligence canonicalization stabilization (recent PR) verified that canonical-payload byte-stability holds for Mappings. BUT: if future hooks put non-Mapping values into metadata (e.g. a GovernanceDecision instance) via Python's duck-typing, the canonicalizer raises TypeError (post-recent-PR) — which is correct fail-fast but means the canonicalize guards are now load-bearing for governance-data shape.

Replay risk RG-5 (LOW) — Aggregator-style governance evaluation
Doctrine warns against "runtime centralization". If a future composition root calls GovernanceRuntime.evaluate() once and shares the result across multiple substrates, those substrates collectively reference the same decision_id. This is FINE for replay (id-keyed loading is idempotent) but it creates a non-obvious lineage shape ("one decision authorises three operational acts"). Replay reconstruction tooling must handle 1:N decision→envelope joins.

9. Chronology-sensitive governance risks
Chronology risk CG-1 (HIGH) — Governance decisions inserted into the session timeline out-of-order
SessionTimelineEvent.sequence is enforced contiguous by append_event (app/session/timeline/builder.py line 92). If a future hook tries to inject "governance decided at time T" events into the timeline based on GovernanceTrace.ended_at (wall-clock), it will:

Violate the contiguous-sequence invariant if events arrive out of order, OR
Force a re-sort that breaks deterministic event_id = derive_event_id(session_id, sequence).
Constraint: if governance state lands on the session timeline, it MUST do so as a new SessionEventKind value emitted in-line at the moment of evaluation, with the next monotonic sequence assigned by the session runtime — NOT back-filled from governance traces.

Chronology risk CG-2 (HIGH) — Multi-substrate governance correlation without shared sequence
correlation_id (governance CorrelationContext) groups decisions across stages of one pipeline, but it does NOT impose ordering between substrates. If "boundary classification → coordination governance → agents governance" is meant to be observable as a chronology, the only deterministic ordering key spanning substrates today is correlation_id + request_id, and even those don't impose total order.

The existing precedent (app/governance/identity/correlation.py line 33) explicitly documents the substrate isolation: "carried through every governance evaluation under the pipeline". No total order is guaranteed across substrates. Future chronology-of-governance reconstruction must accept this — querying "what governance state did boundary observe at time T?" requires joining by correlation_id + substrate's own sequence, not by a global clock.

Chronology risk CG-3 (MEDIUM) — decided_at vs substrate sequence
GovernanceDecision.decided_at (app/governance/decisions.py line 96) is wall-clock. CoordinationEnvelope.sequence is monotonic per-instance. Joining "decision happened at decided_at, envelope happened at sequence N" creates a two-clock chronology — fine for the persisted artifacts but treacherous for replay reconstruction queries. The correct invariant (already implicit in coordination's existing implementation): decision_id is the join key; timestamps are observational, not authoritative.

Chronology risk CG-4 (MEDIUM) — policy_traces order vs replay
GovernanceTrace.policy_traces: tuple[PolicyEvaluationTrace, ...] (app/governance/tracing.py line 71) is ordered by chain execution. Future hooks that re-order this tuple (e.g. "for display") break replay byte-equivalence. The tuple ordering IS the chronology of policy evaluation; treat it as immutable.

Chronology risk CG-5 (LOW) — Asynchronous governance evaluation creating sequence gaps
GovernanceRuntime.evaluate() is async. If a substrate awaits governance evaluation in the middle of a sequence-assigning critical section, other dispatches can progress past the awaited point and assign higher sequences. The existing coordination runtime (line 99 onwards — under a lock) handles this correctly: it assigns the sequence AFTER governance returns. Future substrates adopting governance evaluation MUST do the same — assign monotonic sequence post-governance, not pre-governance.

Summary verdict against the merge-review checklist
Applying docs/constitution/merge-review.md to "future governance routing work":

Question	Answer (analysis-only finding)
Does this preserve replay reconstruction?
Only if governance references are persisted as IDs joined by decision_id, never re-evaluated.
Does this preserve chronology continuity?
Only if substrate-local sequence is assigned post-governance and event_id derivation is preserved.
Does this preserve lineage continuity?
Yes — adopting the existing correlation_id propagation pattern is sufficient.
Does this bypass governance visibility?
The opposite — the question is how to attach it without coupling.
Does this weaken authority propagation?
Only if authority is implicitly mutated by composition-layer routing helpers.
Does this introduce nondeterministic execution?
Only if replay paths call GovernanceRuntime.evaluate(). They must not.
Does this weaken bounded context integrity?
Only if a central GovernanceRouter is introduced (DC-1).
Does this introduce hidden orchestration?
Only if boundary or session start calling GovernanceRuntime.evaluate() directly (DC-6) or a router emerges (DC-1, DC-3).
Recommended hook-point posture (analysis only — no implementation)
Adopt the existing precedent. CoordinationEnvelope.governance_decision_id is the constitutional shape. Other substrates that need governance visibility should mirror this exactly.
Build governance contexts at the composition root, not inside substrates. Substrates remain authorities over their own translation/storage; composition layers thread governance through.
Carry IDs, not envelopes. Embed full GovernanceEnvelope only in AgentExecutionEnvelope (already done; constitutional precedent).
Operation classification rides on the typed subject discriminator (SubjectKind), not on a new GovernanceContext field. Add new subject kinds; do not add classification axes to the context shape.
Replay reconstruction reads GovernanceDecisionRecord by id. Never re-evaluate.
Chronology adoption goes through SessionTimelineEvent.payload taxonomy keys, not new top-level event fields. Preserve derive_event_id determinism.
No new routing/ orchestrator. If a governance/routing/ module is needed at all, it must be a pure-function build_governance_context_from_*(...) library — never an invoker.
The repository is already well-positioned for governance routing: the canonical pipeline runs end-to-end in coordination and agents, the typed-subject discriminator generalizes to new operation kinds, and the persistence + replay paths already join by decision id. Future routing work is shape replication, not architecture invention.