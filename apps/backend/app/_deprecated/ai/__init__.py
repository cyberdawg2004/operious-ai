"""AI execution gateway and primitives.

This package owns provider dispatch, retry policy, timeout enforcement,
execution envelopes, and tracing. It is the seam between the
provider-agnostic infrastructure (`app.providers`) and the orchestration
layer (`app.services`, future `app.orchestration`, `app.agents`).

What lives here:

* `envelopes`  — `ExecutionEnvelope[T]`: result + trace + error.
* `execution`  — `ExecutionContext`: per-call options.
* `tracing`    — `ExecutionTrace`: durable shape of an execution.
* `retry`      — generic bounded-retry helper.
* `gateway`    — `AIGateway`: composes registry + retry + tracing.

What MUST NOT live here:

* HTTP / FastAPI imports — the gateway is transport-agnostic,
* prompt registries, agent frameworks, workflow DAGs — those land in
  later sprints and consume this package, not the other way around.
"""
