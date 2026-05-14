"""Structured logging for the governance runtime.

Two emission seams:

* `log_governance_evaluation` — one per `GovernanceRuntime.evaluate()`
  call. Carries the final decision, stage, policy chain id, violation
  + restriction counts, and the enforcement outcome.

* `log_policy_evaluation`     — one per individual policy invocation
  inside that evaluation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.governance.tracing import GovernanceTrace, PolicyEvaluationTrace

_logger = get_logger("governance")


def log_governance_evaluation(trace: "GovernanceTrace") -> None:
    payload: dict[str, Any] = {
        "decision_id": str(trace.decision_id),
        "request_id": trace.request_id,
        "status": trace.status,
        "stage": trace.stage.value,
        "action": trace.action,
        "resource": trace.resource,
        "actor": trace.actor,
        "tenant_id": trace.tenant_id,
        "policy_chain_id": trace.policy_chain_id,
        "policy_count": len(trace.policy_traces),
        "rule_count": trace.rule_count,
        "violation_count": trace.violation_count,
        "restriction_count": trace.restriction_count,
        "final_decision": trace.final_decision.value,
        "enforcement_handler": trace.enforcement_handler,
        "enforcement_status": trace.enforcement_status,
        "enforcement_latency_ms": trace.enforcement_latency_ms,
        "latency_ms": trace.latency_ms,
        "error": trace.error,
        "started_at": trace.started_at.isoformat(),
        "ended_at": trace.ended_at.isoformat(),
    }
    log_fn = _logger.info if trace.status == "ok" else _logger.warning
    log_fn("governance_evaluation", extra={"governance_evaluation": payload})


def log_policy_evaluation(trace: "PolicyEvaluationTrace") -> None:
    payload: dict[str, Any] = {
        "policy_name": trace.policy_name,
        "status": trace.status,
        "rule_count": trace.rule_count,
        "decision_counts": {k.value: v for k, v in trace.decision_counts.items()},
        "latency_ms": trace.latency_ms,
        "error": trace.error,
    }
    log_fn = _logger.info if trace.status == "ok" else _logger.warning
    log_fn("policy_evaluation", extra={"policy_evaluation": payload})


__all__ = ["log_governance_evaluation", "log_policy_evaluation"]
