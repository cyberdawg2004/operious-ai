"""Agent runtime substrate — Sprint J Foundations.

This package is a **runtime kernel** for future agents, not a set of
agents. It defines:

* identity primitives (`AgentIdentity`, `ExecutionIdentity`),
* capability contracts (`AgentCapability`, `CapabilitySet`,
  `ExecutionConstraints`),
* a typed execution state machine (`ExecutionState` + `state_machine`),
* execution contracts (`AgentExecutionContext`, `AgentExecutionEnvelope`,
  `AgentExecutionTrace`, `AgentExecutionResult`),
* tool invocation contracts (`ToolInvocationRequest`,
  `ToolInvocationResult`, `BaseTool`, `ToolRegistry`,
  `ToolInvoker`, `AgentToolSession`),
* runtime composition (`BaseAgent`, `AgentRegistry`, `AgentRuntime`),
* governance integration via the `ToolInvoker` composition seam,
* a storage-agnostic persistence layer (`persistence/`).

Architectural invariants:

* **Substrate only** — no autonomous planning, memory loops, or LLM
  improvisation. Future sprints add concrete agents that implement
  `BaseAgent`.
* **Replay-safe** — every value object is `frozen=True, slots=True`;
  every record is JSON-serializable; every trace carries the lineage
  (correlation_id, parent_execution_id, tool envelopes, governance
  decisions).
* **Governance-aware via composition** — the runtime never imports
  governance internals. The integration seam is `ToolInvoker`, which
  optionally accepts a `GovernanceRuntime`. Agents see only the
  per-execution `AgentToolSession` API.
* **Explicit ordering** — `AgentRegistry` and `ToolRegistry` iterate
  in sorted-name order (mirrors `PolicyRegistry`).
* **Provider-firewalled** — no vendor SDKs, no direct provider
  imports. The substrate is a leaf in the dependency graph.

Layered topology:

    enums, identity, capabilities, value_objects,
    state_machine, results, context, tracing, envelopes,
    exceptions                                ← vocabulary
    tools/                                    ← tool runtime
    runtime/                                  ← agent runtime
    persistence/                              ← record contracts
"""
