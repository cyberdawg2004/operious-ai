# `app/agents/` — Agent Runtime Substrate (Sprint J)

A **runtime kernel** for future agents, not a set of agents. This sprint
ships the deterministic execution substrate, lifecycle semantics,
capability contracts, governance integration, tool invocation contracts,
typed state machine, causality foundations, and persistence contracts.

It does **NOT** ship: autonomous planning, memory reasoning loops,
recursive agents, swarm coordination, LLM improvisation. Those land
in future sprints behind the substrate this package defines.

## Topology

```
app/agents/
├── enums.py             ExecutionState, CapabilityScope, ToolInvocationStatus
├── identity.py          AgentIdentity, ExecutionIdentity
├── capabilities.py      AgentCapability, CapabilitySet, ExecutionConstraints
├── value_objects.py     CausalityMetadata, StateTransition
├── exceptions.py        typed AgentError vocabulary
├── state_machine.py     pure transition table + assert_transition()
├── results.py           ToolInvocationRequest/Result, AgentExecutionResult
├── tracing.py           ToolInvocationTrace, AgentExecutionTrace
├── envelopes.py         ToolInvocationEnvelope, AgentExecutionEnvelope
├── context.py           AgentExecutionContext
│
├── tools/               tool runtime
│   ├── base.py          BaseTool contract
│   ├── registry.py      ToolRegistry (sorted iter)
│   ├── invoker.py       ToolInvoker — single governance bridge
│   └── session.py       AgentToolSession — per-execution wrapper
│
├── runtime/             agent runtime
│   ├── base_agent.py    BaseAgent contract
│   ├── registry.py      AgentRegistry (sorted iter)
│   └── runtime.py       AgentRuntime — apex orchestrator
│
└── persistence/         storage-agnostic contracts
    ├── records.py       AgentExecutionRecord, ToolInvocationRecord, ...
    ├── models.py        ExecutionQuery, RecordPage
    ├── serializers.py   trace → record (pure functions)
    ├── repository.py    BaseAgentRepository Protocol
    └── memory.py        InMemoryAgentRepository (reference)
```

## Architectural invariants

- **Substrate-only** — no concrete agents, no concrete tools.
- **Replay-safe** — every value object is `frozen=True, slots=True`;
  every record is JSON-serializable; every trace carries the full
  lineage.
- **Governance-aware via composition** — the runtime never imports
  governance internals. The integration seam is `ToolInvoker`, which
  optionally accepts a `GovernanceRuntime`. Audit rule
  `test_agents_runtime_does_not_import_governance_internals` enforces.
- **Provider-firewalled** — no vendor SDKs, no concrete provider
  imports. Audit rules `test_agents_layer_does_not_import_*` enforce.
- **Substrate is a leaf** — no imports of `app.rag`, `app.memory`,
  `app.embeddings`, `app.ai`. Concrete tools that need those subsystems
  live OUTSIDE the substrate. Audit rule
  `test_agents_substrate_does_not_import_rag_or_memory_runtimes`
  enforces.
- **Persistence is contracts-only** — no ORM, no DB drivers. Audit
  rule `test_agents_persistence_layer_is_storage_agnostic` enforces.
- **Closed exception vocabulary** — all `raise` calls go through
  typed agent errors. Audit rule
  `test_agents_substrate_only_raises_typed_agent_errors` enforces.
- **Explicit ordering** — `AgentRegistry`, `ToolRegistry` iterate in
  sorted-name order (mirrors `PolicyRegistry`).
- **Never raises** — every public API method
  (`AgentRuntime.execute`, `ToolInvoker.invoke`,
  `AgentToolSession.invoke`) returns a typed envelope; failure modes
  land on `envelope.error`.

## Lifecycle (single execution)

```
AgentRuntime.execute(agent_id, request, …)
  ↓
  resolve agent           [AgentNotFoundError → fast-fail envelope]
  build identity + ctx
  ↓
  drive state machine:
    CREATED → READY → RUNNING
  ↓
  agent.run(request, context, session)
    ↓
    session.invoke(req) → ToolInvoker.invoke(req, ctx)
       ↓ constraint check (allowed_tools)
       ↓ capability check (required_capabilities)
       ↓ governance evaluate (PRE_EXECUTION)        ← optional
       ↓ tool.invoke(req, ctx)
       → ToolInvocationEnvelope (captured by session)
  ↓
  on success: RUNNING → COMPLETED
  on raise:   RUNNING → FAILED
  ↓
  AgentExecutionEnvelope
    ├─ trace (full state-transition sequence + lineage IDs)
    ├─ result (when COMPLETED)
    ├─ error  (when FAILED)
    ├─ tool_envelopes        (every tool call, in order)
    └─ governance_envelopes  (every governance evaluation, in order)
```

## Causality foundations

Sprint J ships **only** the data primitives:

- `parent_execution_id` on every execution context,
- `parent_chain` tuple on `CausalityMetadata` (built up by the runtime
  as nested executions occur),
- causality metadata recorded on the trace AND on the persistence
  record.

There is no graph storage, no live lineage index, no causality query
engine. Future sprints (K supervisor / L coordination) consume the
persistence-record causality fields and build query infrastructure on
top.

## Governance integration semantics

The `ToolInvoker` is the single integration seam. When a
`GovernanceRuntime` is wired:

- every tool call builds an `AgentActionGovernanceSubject`
  (kind=`AGENT_ACTION`, with `agent_id`, `tool_name`, `capability`,
  `target_resource`, `execution_scope`),
- the evaluation runs at `EnforcementStage.PRE_EXECUTION`,
- the action vocabulary is `"agent.tool_invocation"`,
- the resulting `decision_id` is captured on the
  `ToolInvocationTrace.governance_decision_id` AND on the
  `AgentExecutionTrace.governance_decision_ids` lineage tuple,
- blocking decisions (DENY / REQUIRE_APPROVAL / ESCALATE) produce a
  denied invocation envelope — the tool never runs.

When no `GovernanceRuntime` is wired the gate is skipped silently
(`governance_decision_id` is `None`). This makes governance opt-in at
DI composition time without changing the substrate API.

## Persistence contracts

`AgentExecutionRecord` + `ToolInvocationRecord` are write-once,
storage-agnostic, JSON-serializable. The `BaseAgentRepository`
Protocol mirrors `BaseGovernanceRepository` (Sprint I Hardening) and
ships an `InMemoryAgentRepository` reference implementation.

Production backends (Postgres, Elasticsearch, S3) ship in NEW modules
behind the same Protocol. The substrate is untouched.

## What concrete agents will look like (illustrative; not in this sprint)

```python
class RetrieverAgent(BaseAgent):
    agent_id: ClassVar[str] = "retriever"
    declared_capabilities: ClassVar[tuple[AgentCapability, ...]] = (
        AgentCapability(name="tool.retrieve", scope=CapabilityScope.INVOKE),
    )

    async def run(self, request, context, session) -> AgentExecutionResult:
        env = await session.invoke(
            ToolInvocationRequest(
                tool_name="retrieve",
                payload={"query": request["query"]},
            )
        )
        if not env.is_ok:
            raise RuntimeError("retrieval failed")
        return AgentExecutionResult(output={"chunks": env.result.output["chunks"]})
```

The `RetrievalTool` it uses is a concrete `BaseTool` — and lives in a
deployment-specific package, NOT in the substrate. The substrate
ships only the contract.
