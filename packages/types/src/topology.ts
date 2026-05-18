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
 * Wire-format pinning: every value in this file matches the backend
 * `apps/backend/app/coordination/topology/enums.py` byte-for-byte
 * (verified by `tests-frontend/src/wire-format-pinning.test.ts`).
 *
 * Topology is DECLARATIVE. Edges describe authorized communication
 * paths; they NEVER imply runtime orchestration. The frontend
 * renders the graph as a static authority structure, not as a
 * workflow.
 */

/**
 * Wire-pinned mirror of `CoordinationTopologyDecision`.
 */
export const CoordinationTopologyDecision = {
  ALLOWED: 'allowed',
  ESCALATED: 'escalated',
  DENIED: 'denied',
  DEPTH_EXCEEDED: 'depth_exceeded',
  BOUNDARY_VIOLATION: 'boundary_violation',
} as const;
export type CoordinationTopologyDecision =
  (typeof CoordinationTopologyDecision)[keyof typeof CoordinationTopologyDecision];

/**
 * Wire-pinned mirror of `TopologyNodeKind`.
 */
export const TopologyNodeKind = {
  AGENT: 'agent',
  SUPERVISOR: 'supervisor',
  BROADCAST: 'broadcast',
  SYSTEM: 'system',
  EXTERNAL: 'external',
} as const;
export type TopologyNodeKind =
  (typeof TopologyNodeKind)[keyof typeof TopologyNodeKind];

/**
 * Wire-pinned mirror of `TopologyEdgeKind`.
 */
export const TopologyEdgeKind = {
  PEER: 'peer',
  HANDOFF: 'handoff',
  ESCALATION: 'escalation',
  SUPERVISION: 'supervision',
  BROADCAST: 'broadcast',
  SYSTEM: 'system',
} as const;
export type TopologyEdgeKind =
  (typeof TopologyEdgeKind)[keyof typeof TopologyEdgeKind];

/**
 * Wire-pinned mirror of `TopologyBoundaryKind`.
 */
export const TopologyBoundaryKind = {
  TENANT: 'tenant',
  GOVERNANCE_DOMAIN: 'governance_domain',
  OPERATIONAL_DOMAIN: 'operational_domain',
  ENVIRONMENT: 'environment',
} as const;
export type TopologyBoundaryKind =
  (typeof TopologyBoundaryKind)[keyof typeof TopologyBoundaryKind];

/**
 * Wire-pinned mirror of `TopologyBoundaryCrossing`.
 */
export const TopologyBoundaryCrossing = {
  FORBIDDEN: 'forbidden',
  DECLARED_EDGES: 'declared_edges',
  ALLOWLIST: 'allowlist',
} as const;
export type TopologyBoundaryCrossing =
  (typeof TopologyBoundaryCrossing)[keyof typeof TopologyBoundaryCrossing];

export interface TopologyNodeDto {
  readonly nodeId: TopologyNodeId;
  readonly kind: TopologyNodeKind;
  readonly label: string;
  readonly agentId?: AgentId;
  readonly tenantScope?: string;
  readonly metadata: Readonly<Record<string, unknown>>;
}

export interface TopologyEdgeDto {
  readonly edgeId: TopologyEdgeId;
  readonly kind: TopologyEdgeKind;
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
  readonly decision: CoordinationTopologyDecision;
  readonly chainDepth: number;
  readonly maxChainDepth: number;
  readonly observedAt: IsoTimestamp;
  readonly lineage: Lineage;
}
