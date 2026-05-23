"""Workflow runtime + task orchestration substrate.

This package owns deterministic, inspectable, single-process workflow
execution. Concretely:

* `enums`        — workflow / task / phase taxonomies
* `models`       — `TaskInput`, `TaskResult`, `WorkflowResult`
* `context`      — `OrchestrationContext`, `TaskContext`
* `tracing`      — `WorkflowTrace`, `TaskTrace` (durable execution shape)
* `envelopes`    — `WorkflowEnvelope[T]`, `TaskEnvelope[T]` (never-raise)
* `scheduler`    — `ScheduledTask` primitive (for future data-driven flows)
* `tasks/`       — atomic units of work; one explicit `execute()` method
* `workflows/`   — explicit async functions that drive tasks via a runner
* `runtime`      — coordinates registries + persistence + tracing

Architectural rules enforced here:

* workflows are CODE, not data — `async def execute(payload, ctx, runner)`
* tasks are atomic — one method, returns or raises, no side channels
* no decorators, no reflection, no auto-discovery, no hidden DAG resolver
* envelopes never raise; failure surfaces as `envelope.error`
* `request_id` propagates from middleware → service → runtime → workflow
  → task → trace → audit, with zero call-site wiring
"""
