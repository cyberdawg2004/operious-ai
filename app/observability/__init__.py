"""Observability primitives.

Three small modules that together provide the substrate every later
layer of the platform — orchestration runtimes, workflow engines,
multi-agent coordinators, governance pipelines — relies on:

* `context`  — ContextVars for request-scoped state (request_id today,
               trace/span/actor identifiers tomorrow).
* `logging`  — logging.Filter that enriches every record with the
               current request context, with zero call-site changes.
* `audit`    — minimal `AuditEvent` shape + `emit_audit_event` shim.
               Routes through structured logs today; a single seam
               becomes a bus emitter when one is justified.
"""
