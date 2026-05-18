import type { IsoTimestamp, Lineage } from './common';
import type { ArbitrationCaseId, ArbitrationDecisionId } from './ids';

/**
 * Operational arbitration DTO mirror.
 *
 * The arbitration substrate INTERPRETS conflicts; it does not resolve them
 * autonomously. The frontend renders interpretations alongside the human
 * authority recovery queue.
 */

export const ArbitrationOutcome = {
  RESOLVED: 'arbitration_resolved',
  ESCALATED: 'arbitration_escalated',
  INCONCLUSIVE: 'arbitration_inconclusive',
  DEADLOCK: 'arbitration_deadlock',
  CONFLICT: 'arbitration_conflict',
  ERROR: 'arbitration_error',
} as const;
export type ArbitrationOutcome =
  (typeof ArbitrationOutcome)[keyof typeof ArbitrationOutcome];

export const ArbitrationFindingKind = {
  AUTHORITY_PRECEDENCE_APPLIED: 'authority_precedence_applied',
  SUPERVISOR_DISAGREEMENT: 'supervisor_disagreement',
  CONFLICTING_RECOMMENDATIONS: 'conflicting_recommendations',
  ESCALATION_CONFLICT: 'escalation_conflict',
  DEADLOCK_DETECTED: 'deadlock_detected',
  DEADLOCK_RISK: 'deadlock_risk',
  CONTRADICTORY_FINDINGS: 'contradictory_findings',
  RESOLUTION_INCONCLUSIVE: 'resolution_inconclusive',
} as const;
export type ArbitrationFindingKind =
  (typeof ArbitrationFindingKind)[keyof typeof ArbitrationFindingKind];

export interface ArbitrationFindingDto {
  readonly kind: ArbitrationFindingKind;
  readonly summary: string;
  readonly evidence: Readonly<Record<string, unknown>>;
}

export interface ArbitrationDecisionDto {
  readonly decisionId: ArbitrationDecisionId;
  readonly caseId: ArbitrationCaseId;
  readonly outcome: ArbitrationOutcome;
  readonly precedingAuthority: string;
  readonly findings: readonly ArbitrationFindingDto[];
  readonly observedAt: IsoTimestamp;
  readonly lineage: Lineage;
}
