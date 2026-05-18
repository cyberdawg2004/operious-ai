import type { IsoTimestamp, Lineage } from './common';
import type { CorrelationId, SessionId } from './ids';

/**
 * Operations Queue DTO.
 *
 * The Operations Queue surfaces ONLY artifacts that require human authority
 * recovery: escalated sessions, denied governance verdicts, arbitration
 * deadlocks, topology escalations.
 *
 * The frontend NEVER acts on these — it only exposes them so a human
 * authority can act through governed backend mutation paths.
 */

export const QueueItemKind = {
  ESCALATED_SESSION: 'escalated_session',
  DENIED_GOVERNANCE_DECISION: 'denied_governance_decision',
  ARBITRATION_DEADLOCK: 'arbitration_deadlock',
  TOPOLOGY_ESCALATION: 'topology_escalation',
} as const;
export type QueueItemKind =
  (typeof QueueItemKind)[keyof typeof QueueItemKind];

export const QueueItemStatus = {
  OPEN: 'open',
  CLAIMED: 'claimed',
  ACTIONED: 'actioned',
  DEFERRED: 'deferred',
  ARCHIVED: 'archived',
} as const;
export type QueueItemStatus =
  (typeof QueueItemStatus)[keyof typeof QueueItemStatus];

export const EscalationClassification = {
  GOVERNANCE_DENY: 'governance_deny',
  GOVERNANCE_REQUIRE_APPROVAL: 'governance_require_approval',
  ARBITRATION_DEADLOCK: 'arbitration_deadlock',
  ARBITRATION_INCONCLUSIVE: 'arbitration_inconclusive',
  TOPOLOGY_BOUNDARY_VIOLATION: 'topology_boundary_violation',
  TOPOLOGY_DEPTH_EXCEEDED: 'topology_depth_exceeded',
  SESSION_HUMAN_HANDOFF: 'session_human_handoff',
} as const;
export type EscalationClassification =
  (typeof EscalationClassification)[keyof typeof EscalationClassification];

export interface QueueItemDto {
  readonly itemId: CorrelationId;
  readonly kind: QueueItemKind;
  readonly status: QueueItemStatus;
  readonly classification: EscalationClassification;
  readonly title: string;
  readonly summary: string;
  readonly sessionId?: SessionId;
  readonly tenantLabel?: string;
  readonly raisedAt: IsoTimestamp;
  readonly observedAt: IsoTimestamp;
  readonly lineage: Lineage;
}
