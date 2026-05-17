"""Coordination topology substrate — controlled operational graph semantics.

Sprint L3 introduces a **separate** substrate dedicated to one job:
constraining and authorising the structural shape of coordination
communication. Topology is DECLARATIVE; execution is PROCEDURAL —
this substrate never inverts that.

Architectural disciplines enforced here:

* Topology is static + explicit. Paths are declared, never
  "discovered dynamically".
* Topology never orchestrates execution, never dispatches messages,
  never invokes other runtimes. The coordination runtime composes
  with this substrate via injection.
* Topology evaluation runs BEFORE coordination-policy evaluation in
  the `CoordinationRuntime.dispatch()` lifecycle (illegal topology
  paths must fail before policy / governance run).
* Topology denial, policy denial, and governance denial are
  semantically distinct — each carries its own outcome /
  envelope-status pairing.
* Topology artifacts are immutable. The `version` field is reserved
  for future versioned-declaration support; Sprint L3 does not
  implement versioning logic.

Public surface (commonly imported as `from app.coordination.topology
import …`):

* Enums:
    * `CoordinationTopologyDecision`
    * `TopologyNodeKind`
    * `TopologyEdgeKind`
    * `TopologyBoundaryKind`
    * `TopologyBoundaryCrossing`
* Identity: `CoordinationTopologyId`,
  `CoordinationTopologyEvaluationId`,
  `CoordinationTopologyChainId`, `TopologyNodeId`, `TopologyEdgeId`
  + generators / derivers.
* Models: `CoordinationTopology`, `CoordinationNode`,
  `CoordinationEdge`, `CoordinationPath`, `EscalationPath`,
  `AuthorityBoundary`, `CoordinationTopologyFinding`.
* Contracts: `CoordinationTopologyEvaluationRequest`,
  `CoordinationTopologyEvaluationResult`.
* Envelopes / tracing: `CoordinationTopologyEnvelope`,
  `CoordinationTopologyTrace`, `CoordinationTopologyTraceContext`.
* Registry + evaluators:
  `CoordinationTopologyRegistry`,
  `BaseCoordinationTopologyEvaluator`, four built-in evaluators.
* Runtime: `CoordinationTopologyRuntime`, `build_topology_decision`.
* Persistence: `CoordinationTopologyPersistenceProtocol`,
  `CoordinationTopologyRecord`,
  `CoordinationTopologyFindingRecord`,
  `InMemoryCoordinationTopologyPersistence`,
  `CoordinationTopologyQuery`, `RecordPage`,
  `result_to_record`, `envelope_to_record`.
* Taxonomy: `CoordinationTopologyFindingCode`,
  `CoordinationTopologyMetadataKey`,
  `coordination_topology_precedence`,
  `is_blocking_topology_decision`,
  `is_allow_topology_decision`.
"""

from app.coordination.topology.contracts import (
    CoordinationTopologyEvaluationRequest,
    CoordinationTopologyEvaluationResult,
    CoordinationTopologyFinding,
)
from app.coordination.topology.envelopes import (
    CoordinationTopologyEnvelope,
)
from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
    TopologyBoundaryCrossing,
    TopologyBoundaryKind,
    TopologyEdgeKind,
    TopologyNodeKind,
)
from app.coordination.topology.evaluators import (
    AllowedPathEvaluator,
    BaseCoordinationTopologyEvaluator,
    BoundaryIsolationEvaluator,
    ChainDepthEvaluator,
    EscalationPathEvaluator,
)
from app.coordination.topology.exceptions import (
    CoordinationTopologyConfigurationError,
    CoordinationTopologyDeniedError,
    CoordinationTopologyError,
    CoordinationTopologyEvaluationError,
    CoordinationTopologyPersistenceError,
)
from app.coordination.topology.identity import (
    CoordinationTopologyChainId,
    CoordinationTopologyEvaluationId,
    CoordinationTopologyId,
    TopologyEdgeId,
    TopologyNodeId,
    as_chain_id,
    as_edge_id,
    as_evaluation_id,
    as_node_id,
    as_topology_id,
    derive_chain_id,
    derive_edge_id,
    derive_evaluation_id,
    derive_finding_id,
    derive_node_id,
    derive_topology_id,
    generate_edge_id,
    generate_evaluation_id,
    generate_node_id,
    generate_topology_id,
)
from app.coordination.topology.models import (
    AuthorityBoundary,
    CoordinationEdge,
    CoordinationNode,
    CoordinationPath,
    CoordinationTopology,
    EscalationPath,
)
from app.coordination.topology.persistence import (
    CoordinationTopologyFindingRecord,
    CoordinationTopologyPersistenceProtocol,
    CoordinationTopologyQuery,
    CoordinationTopologyRecord,
    InMemoryCoordinationTopologyPersistence,
    RecordPage,
    envelope_to_record,
    result_to_record,
)
from app.coordination.topology.registry import (
    CoordinationTopologyRegistry,
)
from app.coordination.topology.runtime import (
    CoordinationTopologyRuntime,
    build_topology_decision,
)
from app.coordination.topology.taxonomy import (
    CoordinationTopologyFindingCode,
    CoordinationTopologyMetadataKey,
    coordination_topology_precedence,
    is_allow_topology_decision,
    is_blocking_topology_decision,
)
from app.coordination.topology.tracing import (
    CoordinationTopologyTrace,
    CoordinationTopologyTraceContext,
)

__all__ = [
    "AllowedPathEvaluator",
    "AuthorityBoundary",
    "BaseCoordinationTopologyEvaluator",
    "BoundaryIsolationEvaluator",
    "ChainDepthEvaluator",
    "CoordinationEdge",
    "CoordinationNode",
    "CoordinationPath",
    "CoordinationTopology",
    "CoordinationTopologyChainId",
    "CoordinationTopologyConfigurationError",
    "CoordinationTopologyDecision",
    "CoordinationTopologyDeniedError",
    "CoordinationTopologyEnvelope",
    "CoordinationTopologyError",
    "CoordinationTopologyEvaluationError",
    "CoordinationTopologyEvaluationId",
    "CoordinationTopologyEvaluationRequest",
    "CoordinationTopologyEvaluationResult",
    "CoordinationTopologyFinding",
    "CoordinationTopologyFindingCode",
    "CoordinationTopologyFindingRecord",
    "CoordinationTopologyId",
    "CoordinationTopologyMetadataKey",
    "CoordinationTopologyPersistenceError",
    "CoordinationTopologyPersistenceProtocol",
    "CoordinationTopologyQuery",
    "CoordinationTopologyRecord",
    "CoordinationTopologyRegistry",
    "CoordinationTopologyRuntime",
    "CoordinationTopologyTrace",
    "CoordinationTopologyTraceContext",
    "EscalationPath",
    "EscalationPathEvaluator",
    "InMemoryCoordinationTopologyPersistence",
    "RecordPage",
    "TopologyBoundaryCrossing",
    "TopologyBoundaryKind",
    "TopologyEdgeId",
    "TopologyEdgeKind",
    "TopologyNodeId",
    "TopologyNodeKind",
    "as_chain_id",
    "as_edge_id",
    "as_evaluation_id",
    "as_node_id",
    "as_topology_id",
    "build_topology_decision",
    "coordination_topology_precedence",
    "derive_chain_id",
    "derive_edge_id",
    "derive_evaluation_id",
    "derive_finding_id",
    "derive_node_id",
    "derive_topology_id",
    "envelope_to_record",
    "generate_edge_id",
    "generate_evaluation_id",
    "generate_node_id",
    "generate_topology_id",
    "is_allow_topology_decision",
    "is_blocking_topology_decision",
    "result_to_record",
]
