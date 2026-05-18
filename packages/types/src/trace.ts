import type { ArbitrationDecisionDto } from './arbitration';
import type { IsoTimestamp, Lineage } from './common';
import type { GovernanceTraceDto } from './governance';
import type { AgentExecutionId, CorrelationId, SessionId } from './ids';
import type { SessionTimelineEventDto } from './session';

/**
 * Cross-substrate trace assemblies — the raw shapes the Trace Inspector renders.
 *
 * These DTOs are read-only forensic artifacts; the frontend NEVER constructs
 * them from scratch and NEVER mutates fields. Replay evidence preserves
 * deterministic chronological ordering and lineage continuity end-to-end.
 */

export const TraceNodeKind = {
  SESSION_TIMELINE_EVENT: 'session_timeline_event',
  GOVERNANCE_TRACE: 'governance_trace',
  AGENT_EXECUTION_TRACE: 'agent_execution_trace',
  ARBITRATION_DECISION: 'arbitration_decision',
  TOPOLOGY_EVALUATION: 'topology_evaluation',
  BOUNDARY_INGRESS: 'boundary_ingress',
  BOUNDARY_EGRESS: 'boundary_egress',
  TRANSLATION: 'translation',
  VOICE: 'voice',
} as const;
export type TraceNodeKind =
  (typeof TraceNodeKind)[keyof typeof TraceNodeKind];

export interface AgentExecutionTraceDto {
  readonly executionId: AgentExecutionId;
  readonly agentLabel: string;
  readonly inputDigest: string;
  readonly outputDigest: string;
  readonly observedAt: IsoTimestamp;
  readonly durationMs: number;
  readonly lineage: Lineage;
}

/**
 * A unified inspector node — the renderer dispatches on `kind`.
 * Every node exposes `lineage` so the Trace Inspector can reconstruct
 * parent/child hierarchy purely from data, never from inferred order.
 */
export type TraceNodeDto =
  | (Readonly<{ kind: typeof TraceNodeKind.SESSION_TIMELINE_EVENT; payload: SessionTimelineEventDto }>)
  | (Readonly<{ kind: typeof TraceNodeKind.GOVERNANCE_TRACE; payload: GovernanceTraceDto }>)
  | (Readonly<{ kind: typeof TraceNodeKind.AGENT_EXECUTION_TRACE; payload: AgentExecutionTraceDto }>)
  | (Readonly<{ kind: typeof TraceNodeKind.ARBITRATION_DECISION; payload: ArbitrationDecisionDto }>);

export interface TraceBundleDto {
  readonly correlationId: CorrelationId;
  readonly sessionId?: SessionId;
  readonly nodes: readonly TraceNodeDto[];
  readonly observedAt: IsoTimestamp;
  readonly replayDigest: string;
}
