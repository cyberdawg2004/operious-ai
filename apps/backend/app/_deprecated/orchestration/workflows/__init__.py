"""Workflow layer.

A workflow is the platform's deterministic unit of orchestration. It
is plain Python: `async def execute(payload, context, runner) -> WorkflowResult`.

The workflow author writes the steps in code; the `runner` (provided
by the runtime) handles per-task persistence, tracing, and envelope
construction. There is no DAG resolver, no decorator, no graph engine
— what you read in the workflow file is exactly what the runtime
executes.

Workflows MUST NOT:

* import the runtime or persistence layer (only the runner protocol)
* spawn background tasks (orchestration is single-process and
  deterministic in Sprint F)
* call providers / gateways / repositories directly — those are reached
  through tasks
"""
