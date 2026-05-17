"""Governance metric emission seam.

One function per metric event, single canonical log record. Future
metrics backend swap-in updates this file; call sites do not change.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

_logger = get_logger("governance.metrics")


def record_governance_evaluation(
    *,
    stage: str,
    action: str,
    tenant_id: str | None,
    policy_chain_id: str,
    final_decision: str,
    policy_count: int,
    rule_count: int,
    violation_count: int,
    restriction_count: int,
    latency_ms: float,
    status: str,
) -> None:
    payload: dict[str, Any] = {
        "stage": stage,
        "action": action,
        "tenant_id": tenant_id,
        "policy_chain_id": policy_chain_id,
        "final_decision": final_decision,
        "policy_count": policy_count,
        "rule_count": rule_count,
        "violation_count": violation_count,
        "restriction_count": restriction_count,
        "latency_ms": latency_ms,
        "status": status,
    }
    _logger.info("governance_metric", extra={"governance_metric": payload})


def record_enforcement_action(
    *,
    handler_name: str,
    decision: str,
    outcome: str,
    latency_ms: float,
) -> None:
    payload: dict[str, Any] = {
        "handler_name": handler_name,
        "decision": decision,
        "outcome": outcome,
        "latency_ms": latency_ms,
    }
    _logger.info("enforcement_metric", extra={"enforcement_metric": payload})


__all__ = [
    "record_governance_evaluation",
    "record_enforcement_action",
]
