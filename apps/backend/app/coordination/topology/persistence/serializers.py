"""Coordination-topology serializers — runtime types → records.

Pure functions. Replay-safe. No I/O. Used by the
`CoordinationTopologyRuntime` to convert internal results and
envelopes to wire-format records for the persistence layer.
"""

from __future__ import annotations

from app.coordination.topology.contracts.results import (
    CoordinationTopologyEvaluationResult,
)
from app.coordination.topology.envelopes import (
    CoordinationTopologyEnvelope,
)
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.persistence.records import (
    CoordinationTopologyFindingRecord,
    CoordinationTopologyRecord,
)
from app.coordination.topology.tracing import (
    CoordinationTopologyTrace,
)


def _finding_to_record(
    finding: CoordinationTopologyFinding,
) -> CoordinationTopologyFindingRecord:
    return CoordinationTopologyFindingRecord(
        finding_id=str(finding.finding_id),
        evaluator_name=finding.evaluator_name,
        decision=finding.decision.value,
        code=finding.code,
        message=finding.message,
        edge_id=(
            str(finding.edge_id) if finding.edge_id is not None else None
        ),
        path_id=finding.path_id,
        boundary_id=finding.boundary_id,
        source_node_id=(
            str(finding.source_node_id)
            if finding.source_node_id is not None
            else None
        ),
        target_node_id=(
            str(finding.target_node_id)
            if finding.target_node_id is not None
            else None
        ),
        detected_at=(
            finding.detected_at.isoformat()
            if finding.detected_at is not None
            else ""
        ),
        metadata=dict(finding.metadata),
    )


def result_to_record(
    *,
    result: CoordinationTopologyEvaluationResult,
    trace: CoordinationTopologyTrace,
) -> CoordinationTopologyRecord:
    """Convert a result + trace pair to a persistable record."""
    return CoordinationTopologyRecord(
        evaluation_id=str(result.evaluation_id),
        chain_id=str(result.chain_id),
        topology_id=str(result.topology_id),
        topology_name=result.topology_name,
        topology_version=result.topology_version,
        runtime_instance_id=str(result.runtime_instance_id),
        sequence=result.sequence,
        coordination_id=str(result.coordination_id),
        coordination_message_id=str(result.coordination_message_id),
        sender_id=result.sender_id,
        recipient_id=result.recipient_id,
        recipient_kind=result.recipient_kind,
        direction=trace.direction.value,
        message_type=trace.message_type.value,
        priority=int(trace.priority.value),
        aggregate_decision=result.aggregate_decision.value,
        evaluator_names=tuple(result.evaluator_names),
        finding_count=len(result.findings),
        chain_depth=result.chain_depth,
        max_chain_depth=result.max_chain_depth,
        matched_edge_id=(
            str(result.matched_edge_id)
            if result.matched_edge_id is not None
            else None
        ),
        matched_path_id=result.matched_path_id,
        correlation_id=(
            str(result.correlation_id)
            if result.correlation_id is not None
            else None
        ),
        parent_coordination_id=(
            str(result.parent_coordination_id)
            if result.parent_coordination_id is not None
            else None
        ),
        parent_message_id=(
            str(result.parent_message_id)
            if result.parent_message_id is not None
            else None
        ),
        request_id=result.request_id,
        tenant_id=result.tenant_id,
        started_at=result.started_at.isoformat(),
        ended_at=result.ended_at.isoformat(),
        latency_ms=result.latency_ms,
        reason=result.reason,
        error=result.error,
        findings=tuple(_finding_to_record(f) for f in result.findings),
        metadata=dict(result.metadata),
    )


def envelope_to_record(
    envelope: CoordinationTopologyEnvelope,
) -> CoordinationTopologyRecord | None:
    """Convert an envelope's result (if any) to a persistable record."""
    if envelope.result is None:
        return None
    return result_to_record(result=envelope.result, trace=envelope.trace)


__all__ = ["envelope_to_record", "result_to_record"]
