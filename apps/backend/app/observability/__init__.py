"""Constitutional observability primitives.

Modules every constitutional substrate is allowed to import:

* `context`              — ContextVars for request-scoped state
                           (request id today, tenant / principal /
                           authority envelope after Phase 2.4).
* `logging`              — logging.Filter that enriches every record
                           with the current request context, with zero
                           call-site changes.
* `audit`                — frozen `AuditEvent` value object and the
                           single `emit_audit_event` seam. Used by the
                           constitutional governance enforcement
                           runtime; will be replaced by the canonical
                           event fabric (Phase 2.3) as the single
                           emission seam — `audit` will then become a
                           thin adapter.
* `governance_logging`   — typed log helpers for the governance
                           substrate (`log_governance_evaluation`,
                           `log_policy_evaluation`).
* `governance_metrics`   — typed metric counters for the governance
                           substrate (`record_enforcement_action`,
                           `record_governance_evaluation`).
* `runtime`              — tenant-scoped operational metrics, SLO
                           thresholds, structured spans, and DLQ read
                           authority.

Phase 2.1 quarantine note:

* The per-domain emitters that belong to the legacy stack were
  quarantined under `app._deprecated.observability.*`:
  `ai_*`, `context_assembly_*`, `embedding_*`, `orchestration_*`,
  `rag_retrieval_*`, `retrieval_*`. They are not imported here and
  must never be imported from constitutional code.
"""

from app.observability.enums import (
    AlertSeverity,
    AlertThresholdOperator,
    OperationalMetricName,
    OperationalTraceStatus,
)
from app.observability.identity import (
    OperationalAlertId,
    OperationalSLODefinitionId,
    OperationalTraceSpanId,
    as_operational_slo_id,
    as_operational_trace_span_id,
    derive_alert_id,
    derive_slo_definition_id,
    derive_trace_span_id,
)

__all__ = [
    "AlertSeverity",
    "AlertThresholdOperator",
    "OperationalAlertId",
    "OperationalMetricName",
    "OperationalSLODefinitionId",
    "OperationalTraceSpanId",
    "OperationalTraceStatus",
    "as_operational_slo_id",
    "as_operational_trace_span_id",
    "derive_alert_id",
    "derive_slo_definition_id",
    "derive_trace_span_id",
]
