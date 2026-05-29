"""Operational observability enum vocabulary."""

from __future__ import annotations

from enum import StrEnum


class OperationalMetricName(StrEnum):
    """Closed metric names exposed by the tenant observability surface."""

    TICKET_THROUGHPUT = "ticket_throughput"
    GOVERNANCE_DENY_RATE = "governance_deny_rate"
    EXECUTION_LATENCY_MS_AVG = "execution_latency_ms_avg"
    EXECUTION_LATENCY_MS_P50 = "execution_latency_ms_p50"
    EXECUTION_LATENCY_MS_P95 = "execution_latency_ms_p95"
    EXECUTION_LATENCY_MS_P99 = "execution_latency_ms_p99"
    QA_SCORE_AVERAGE = "qa_score_average"
    ESCALATION_RATE = "escalation_rate"
    DLQ_COUNT = "dlq_count"


class AlertThresholdOperator(StrEnum):
    """Comparison operators supported by SLO alert thresholds."""

    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"


class AlertSeverity(StrEnum):
    """Operational severity attached to a threshold breach."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class OperationalTraceStatus(StrEnum):
    """Outcome state of one structured trace span."""

    OK = "ok"
    FAILED = "failed"


__all__ = [
    "AlertSeverity",
    "AlertThresholdOperator",
    "OperationalMetricName",
    "OperationalTraceStatus",
]
