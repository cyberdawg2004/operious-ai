import type { IsoTimestamp, Lineage } from './common';
import type {
  AgentId,
  TopologyEdgeId,
  TopologyEvaluationId,
  TopologyNodeId,
} from './ids';

/**
 * Coordination topology DTO mirror.
 *
 * Topology is DECLARATIVE. Edges describe authorized communication paths;
 * they NEVER imply runtime orchestration. The frontend renders the graph as
 * a static authority structure, not as a workflow.
 */

export const TopologyOutcome = {
  ALLOWED: 'topology_allowed',
  DENIED: 'topology_denied',
  ESCALATED: 'topology_escalated',
  DEPTH_EXCEEDED: 'topology_depth_exceeded',
  BOUNDARY_VIOLATION: 'topology_boundary_violation',
  ERROR: 'topology_error',
} as const;
export type TopologyOutcome =
  (typeof TopologyOutcome)[keyof typeof TopologyOutcome];

export const NodeKind = {
  AGENT: 'agent',
  SUPERVISOR: 'supervisor',
  GOVERNANCE_DOMAIN: 'governance_domain',
  AUTHORITY_BOUNDARY: 'authority_boundary',
  ESCALATION_TARGET: 'escalation_target',
} as const;
export type NodeKind = (typeof NodeKind)[keyof typeof NodeKind];

export const EdgeKind = {
  COORDINATION: 'coordination',
  ESCALATION: 'escalation',
  GOVERNANCE_ATTACHMENT: 'governance_attachment',
  AUTHORITY_BOUNDARY: 'authority_boundary',
} as const;
export type EdgeKind = (typeof EdgeKind)[keyof typeof EdgeKind];

export interface TopologyNodeDto {
  readonly nodeId: TopologyNodeId;
  readonly kind: NodeKind;
  readonly label: string;
  readonly agentId?: AgentId;
  readonly tenantScope?: string;
  readonly metadata: Readonly<Record<string, unknown>>;
}

export interface TopologyEdgeDto {
  readonly edgeId: TopologyEdgeId;
  readonly kind: EdgeKind;
  readonly source: TopologyNodeId;
  readonly target: TopologyNodeId;
  readonly label?: string;
  readonly metadata: Readonly<Record<string, unknown>>;
}

export interface TopologyGraphDto {
  readonly nodes: readonly TopologyNodeDto[];
  readonly edges: readonly TopologyEdgeDto[];
  readonly observedAt: IsoTimestamp;
  readonly version: string;
}

export interface TopologyEvaluationDto {
  readonly evaluationId: TopologyEvaluationId;
  readonly outcome: TopologyOutcome;
  readonly chainDepth: number;
  readonly maxChainDepth: number;
  readonly observedAt: IsoTimestamp;
  readonly lineage: Lineage;
}
