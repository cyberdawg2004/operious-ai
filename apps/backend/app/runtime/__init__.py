"""Runtime adapters that compose existing substrate runtimes."""

from app.runtime.arbitration_event_projection import (
    ArbitrationEvaluationEventLineage,
    ArbitrationEventProjectionError,
    ArbitrationOperationalEventProjection,
    ArbitrationOperationalEventProjector,
    make_postgres_dispatch_arbitration_runtime,
    project_arbitration_record,
)
from app.runtime.boundary_event_projection import (
    BoundaryEventProjectionError,
    BoundaryOperationalEventProjection,
    BoundaryOperationalEventProjector,
    project_boundary_ingress_record,
)
from app.runtime.coordination_event_projection import (
    CoordinationEventProjectionError,
    CoordinationOperationalEventProjection,
    CoordinationOperationalEventProjector,
    project_coordination_record,
)
from app.runtime.execution_event_projection import (
    ExecutionEventProjectionError,
    ExecutionOperationalEventProjection,
    ExecutionOperationalEventProjector,
    project_execution_records,
)
from app.runtime.defect_cluster_runtime import (
    CLUSTER_THRESHOLD,
    CLUSTER_WINDOW_HOURS,
    DefectClusterCandidate,
    DefectClusterDetectionRuntime,
    derive_defect_cluster_id,
)
from app.runtime.failure_pattern_runtime import (
    DLQ_THRESHOLD,
    DLQ_WINDOW_HOURS,
    FailurePattern,
    FailurePatternDetectionRuntime,
    RecordedFailurePattern,
    derive_sop_failure_pattern_id,
)
from app.runtime.escalation_event_projection import (
    EscalationEventProjectionError,
    EscalationOperationalEventProjection,
    EscalationOperationalEventProjector,
    project_escalation_record,
)
from app.runtime.execution_governance import (
    ExecutionGovernanceEvaluation,
    ExecutionGovernanceRuntime,
)
from app.runtime.provider_circuit_breaker import (
    ProviderCircuitBreaker,
    ProviderCircuitOpenError,
    ProviderCircuitSnapshot,
    ProviderCircuitState,
)
from app.runtime.resolution_runtime import (
    ResolutionGovernanceGateProtocol,
    ResolutionGovernanceGateRequest,
    ResolutionGovernanceGateResult,
    ResolutionOutboundDraftRuntime,
    ResolutionProposalRequest,
    ResolutionRuntime,
    resolution_outbound_draft_status_for_proposal,
    resolution_outbound_draft_timeline_payload,
    resolution_proposal_is_send_eligible,
    resolution_proposal_timeline_payload,
)
from app.runtime.resolution_governance_gate import (
    ResolutionCommunicationPolicy,
    ResolutionGovernanceGate,
    build_resolution_governance_runtime,
)
from app.runtime.governance_event_projection import (
    GovernanceDecisionEventLineage,
    GovernanceEventProjectionError,
    GovernanceOperationalEventProjection,
    GovernanceOperationalEventProjector,
    project_governance_decision_record,
)
from app.runtime.qa_event_projection import (
    QAEventProjectionError,
    QAOperationalEventProjection,
    QAOperationalEventProjector,
    project_qa_score_record,
)
from app.runtime.session_event_projection import (
    SESSION_EVENT_KIND_TO_OPERATIONAL_ACT,
    SessionEventProjectionError,
    SessionOperationalEventProjection,
    SessionOperationalEventProjector,
    project_session_timeline_event,
)
from app.runtime.sop_approval_event_projection import (
    SOPApprovalEventProjectionError,
    SOPApprovalOperationalEventProjection,
    SOPApprovalOperationalEventProjector,
    make_postgres_sop_approval_event_projector,
    project_sop_approval_record,
)
from app.runtime.supervisor_event_projection import (
    SupervisorEventProjectionError,
    SupervisorOperationalEventProjection,
    SupervisorOperationalEventProjector,
    project_supervisor_inspection_record,
)
from app.runtime.dispatch_arbitration import (
    DispatchArbitrationEvaluation,
    DispatchArbitrationProposal,
    DispatchArbitrationRuntime,
)
from app.runtime.tenant_topology import (
    TenantCoordinationTopologyRuntimeProvider,
    build_coordination_topology_runtime,
)
from app.runtime.timeline_runtime import TimelineRuntime

__all__ = [
    "ArbitrationEvaluationEventLineage",
    "ArbitrationEventProjectionError",
    "ArbitrationOperationalEventProjection",
    "ArbitrationOperationalEventProjector",
    "BoundaryEventProjectionError",
    "BoundaryOperationalEventProjection",
    "BoundaryOperationalEventProjector",
    "CoordinationEventProjectionError",
    "CoordinationOperationalEventProjection",
    "CoordinationOperationalEventProjector",
    "CLUSTER_THRESHOLD",
    "CLUSTER_WINDOW_HOURS",
    "DefectClusterCandidate",
    "DefectClusterDetectionRuntime",
    "DispatchArbitrationEvaluation",
    "DispatchArbitrationProposal",
    "DispatchArbitrationRuntime",
    "DLQ_THRESHOLD",
    "DLQ_WINDOW_HOURS",
    "ExecutionEventProjectionError",
    "ExecutionGovernanceEvaluation",
    "ExecutionGovernanceRuntime",
    "ExecutionOperationalEventProjection",
    "ExecutionOperationalEventProjector",
    "EscalationEventProjectionError",
    "EscalationOperationalEventProjection",
    "EscalationOperationalEventProjector",
    "FailurePattern",
    "FailurePatternDetectionRuntime",
    "GovernanceDecisionEventLineage",
    "GovernanceEventProjectionError",
    "GovernanceOperationalEventProjection",
    "GovernanceOperationalEventProjector",
    "QAEventProjectionError",
    "QAOperationalEventProjection",
    "QAOperationalEventProjector",
    "ProviderCircuitBreaker",
    "ProviderCircuitOpenError",
    "ProviderCircuitSnapshot",
    "ProviderCircuitState",
    "RecordedFailurePattern",
    "ResolutionCommunicationPolicy",
    "ResolutionGovernanceGateProtocol",
    "ResolutionGovernanceGateRequest",
    "ResolutionGovernanceGateResult",
    "ResolutionGovernanceGate",
    "ResolutionOutboundDraftRuntime",
    "ResolutionProposalRequest",
    "ResolutionRuntime",
    "build_resolution_governance_runtime",
    "resolution_outbound_draft_status_for_proposal",
    "resolution_outbound_draft_timeline_payload",
    "resolution_proposal_is_send_eligible",
    "SessionEventProjectionError",
    "SessionOperationalEventProjection",
    "SessionOperationalEventProjector",
    "SESSION_EVENT_KIND_TO_OPERATIONAL_ACT",
    "SOPApprovalEventProjectionError",
    "SOPApprovalOperationalEventProjection",
    "SOPApprovalOperationalEventProjector",
    "SupervisorEventProjectionError",
    "SupervisorOperationalEventProjection",
    "SupervisorOperationalEventProjector",
    "TenantCoordinationTopologyRuntimeProvider",
    "TimelineRuntime",
    "build_coordination_topology_runtime",
    "derive_defect_cluster_id",
    "derive_sop_failure_pattern_id",
    "make_postgres_sop_approval_event_projector",
    "make_postgres_dispatch_arbitration_runtime",
    "project_arbitration_record",
    "project_boundary_ingress_record",
    "project_coordination_record",
    "project_execution_records",
    "project_escalation_record",
    "project_governance_decision_record",
    "project_qa_score_record",
    "resolution_proposal_timeline_payload",
    "project_session_timeline_event",
    "project_sop_approval_record",
    "project_supervisor_inspection_record",
]
