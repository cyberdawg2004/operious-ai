"""Pure metric calculations shared by observability backends."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.observability.persistence.records import (
    OperationalMetricsSnapshotRecord,
    QAScoreBucketRecord,
)


@dataclass(frozen=True, slots=True)
class ExecutionLatencySample:
    requested_at: datetime
    completed_at: datetime | None
    failed_at: datetime | None
    state: str


def build_metrics_snapshot(
    *,
    tenant_id: str,
    window_start: datetime,
    window_end: datetime,
    ticket_throughput: int,
    governance_decisions: tuple[str, ...],
    executions: tuple[ExecutionLatencySample, ...],
    qa_scores: tuple[float, ...],
    escalation_count: int,
    dlq_count: int,
) -> OperationalMetricsSnapshotRecord:
    deny_count = sum(1 for decision in governance_decisions if decision == "deny")
    decision_count = len(governance_decisions)
    latencies = tuple(
        latency
        for sample in executions
        if (latency := _latency_ms(sample)) is not None
    )
    completed_count = sum(
        1 for sample in executions if sample.completed_at is not None
    )
    qa_average = (
        round(sum(qa_scores) / len(qa_scores), 6) if qa_scores else None
    )
    return OperationalMetricsSnapshotRecord(
        tenant_id=tenant_id,
        window_start=window_start,
        window_end=window_end,
        ticket_throughput=ticket_throughput,
        governance_decision_count=decision_count,
        governance_deny_count=deny_count,
        governance_deny_rate=_rate(deny_count, decision_count),
        execution_count=len(executions),
        completed_execution_count=completed_count,
        execution_latency_ms_avg=_average(latencies),
        execution_latency_ms_p50=_percentile(latencies, 0.50),
        execution_latency_ms_p95=_percentile(latencies, 0.95),
        execution_latency_ms_p99=_percentile(
            latencies,
            0.99,
            minimum_count=100,
        ),
        qa_score_count=len(qa_scores),
        qa_score_average=qa_average,
        qa_score_distribution=_qa_distribution(qa_scores),
        escalation_count=escalation_count,
        escalation_rate=_rate(escalation_count, ticket_throughput),
        dlq_count=dlq_count,
    )


def metric_value(
    snapshot: OperationalMetricsSnapshotRecord,
    metric_name: str,
) -> float:
    if metric_name == "ticket_throughput":
        return float(snapshot.ticket_throughput)
    if metric_name == "governance_deny_rate":
        return snapshot.governance_deny_rate
    if metric_name == "execution_latency_ms_avg":
        return float(snapshot.execution_latency_ms_avg or 0.0)
    if metric_name == "execution_latency_ms_p50":
        return float(snapshot.execution_latency_ms_p50 or 0.0)
    if metric_name == "execution_latency_ms_p95":
        return float(snapshot.execution_latency_ms_p95 or 0.0)
    if metric_name == "execution_latency_ms_p99":
        return float(snapshot.execution_latency_ms_p99 or 0.0)
    if metric_name == "qa_score_average":
        return float(snapshot.qa_score_average or 0.0)
    if metric_name == "escalation_rate":
        return snapshot.escalation_rate
    if metric_name == "dlq_count":
        return float(snapshot.dlq_count)
    raise ValueError(f"unsupported metric_name: {metric_name}")


def _latency_ms(sample: ExecutionLatencySample) -> float | None:
    ended_at = sample.completed_at or sample.failed_at
    if ended_at is None:
        return None
    return max((ended_at - sample.requested_at).total_seconds() * 1000.0, 0.0)


def _average(values: tuple[float, ...]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _percentile(
    values: tuple[float, ...],
    percentile: float,
    *,
    minimum_count: int = 1,
) -> float | None:
    if not values or len(values) < minimum_count:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile + 0.999999) - 1))
    return round(ordered[index], 6)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _qa_distribution(scores: tuple[float, ...]) -> tuple[QAScoreBucketRecord, ...]:
    buckets = [
        [0.0, 0.2, 0],
        [0.2, 0.4, 0],
        [0.4, 0.6, 0],
        [0.6, 0.8, 0],
        [0.8, 1.0, 0],
    ]
    for score in scores:
        bounded = max(0.0, min(1.0, score))
        if bounded >= 1.0:
            buckets[-1][2] += 1
            continue
        for bucket in buckets:
            if bucket[0] <= bounded < bucket[1]:
                bucket[2] += 1
                break
    return tuple(
        QAScoreBucketRecord(
            lower_bound=float(lower),
            upper_bound=float(upper),
            count=int(count),
        )
        for lower, upper, count in buckets
    )


__all__ = [
    "ExecutionLatencySample",
    "build_metrics_snapshot",
    "metric_value",
]
