import type { IsoTimestamp, Lineage } from './common';
import type { ArbitrationCaseId, ArbitrationDecisionId } from './ids';

/**
 * Operational arbitration DTO mirror.
 *
 * The arbitration substrate INTERPRETS conflicts; it does not resolve them
 * autonomously. The frontend renders interpretations alongside the human
 * authority recovery queue.
 *
 * Wire-format pinning: every enum below mirrors the backend
 * `apps/backend/app/arbitration/enums.py` + `taxonomy.py` byte-for-byte
 * (verified by `tests-frontend/src/wire-format-pinning.test.ts`).
 */

/**
 * Wire-pinned mirror of `ArbitrationOutcome`.
 */
export const ArbitrationOutcome = {
  ARBITRATION_RESOLVED: 'arbitration_resolved',
  ARBITRATION_ESCALATED: 'arbitration_escalated',
  ARBITRATION_INCONCLUSIVE: 'arbitration_inconclusive',
  ARBITRATION_DEADLOCK: 'arbitration_deadlock',
  ARBITRATION_CONFLICT: 'arbitration_conflict',
  ARBITRATION_ERROR: 'arbitration_error',
} as const;
export type ArbitrationOutcome =
  (typeof ArbitrationOutcome)[keyof typeof ArbitrationOutcome];

/**
 * Wire-pinned mirror of `ArbitrationAuthorityLevel`.
 *
 * Sprint L4 critical authority hierarchy:
 *
 *     GOVERNANCE  > TOPOLOGY  > POLICY  >
 *     ARBITRATION > SUPERVISOR > EXECUTION
 *
 * Arbitration interprets conflicts THROUGH this hierarchy. It NEVER
 * overrides higher authority. Precedence ordering is encoded in
 * `arbitration_authority_precedence` in `app.arbitration.taxonomy`;
 * no other layer re-encodes it.
 */
export const ArbitrationAuthorityLevel = {
  GOVERNANCE: 'governance',
  TOPOLOGY: 'topology',
  POLICY: 'policy',
  ARBITRATION: 'arbitration',
  SUPERVISOR: 'supervisor',
  EXECUTION: 'execution',
} as const;
export type ArbitrationAuthorityLevel =
  (typeof ArbitrationAuthorityLevel)[keyof typeof ArbitrationAuthorityLevel];

/**
 * Wire-pinned mirror of `ArbitrationVerdictKind`.
 *
 * Two related but distinct semantic axes:
 *
 *  * Authorisation verdicts: ALLOW, DENY, ESCALATE, DEGRADE.
 *  * Quality verdicts: PASS, FAIL, SAFE, UNSAFE, VALID, INVALID, WARN.
 *
 * `UNKNOWN` is a sentinel; downstream consumers MUST treat unknown
 * values fail-safe.
 */
export const ArbitrationVerdictKind = {
  ALLOW: 'allow',
  DENY: 'deny',
  ESCALATE: 'escalate',
  DEGRADE: 'degrade',
  PASS: 'pass',
  FAIL: 'fail',
  SAFE: 'safe',
  UNSAFE: 'unsafe',
  VALID: 'valid',
  INVALID: 'invalid',
  WARN: 'warn',
  UNKNOWN: 'unknown',
} as const;
export type ArbitrationVerdictKind =
  (typeof ArbitrationVerdictKind)[keyof typeof ArbitrationVerdictKind];

/**
 * Wire-pinned mirror of `ArbitrationConflictKind`.
 */
export const ArbitrationConflictKind = {
  AUTHORISATION_CONFLICT: 'authorisation_conflict',
  QUALITY_CONFLICT: 'quality_conflict',
  AUTHORISATION_QUALITY_CROSS: 'authorisation_quality_cross',
  ESCALATION_CONFLICT: 'escalation_conflict',
  SUPERVISOR_DISAGREEMENT: 'supervisor_disagreement',
  RECOMMENDATION_CONFLICT: 'recommendation_conflict',
} as const;
export type ArbitrationConflictKind =
  (typeof ArbitrationConflictKind)[keyof typeof ArbitrationConflictKind];

/**
 * Wire-pinned mirror of `ArbitrationDeadlockKind`.
 *
 * Closed set. Detection only — arbitration NEVER recovers.
 */
export const ArbitrationDeadlockKind = {
  ITERATION_EXHAUSTED: 'iteration_exhausted',
  REPEATED_BLOCKED_STATE: 'repeated_blocked_state',
  CONTRADICTORY_ESCALATION_CHAIN: 'contradictory_escalation_chain',
  CYCLIC_CASE_LINEAGE: 'cyclic_case_lineage',
} as const;
export type ArbitrationDeadlockKind =
  (typeof ArbitrationDeadlockKind)[keyof typeof ArbitrationDeadlockKind];

/**
 * Wire-pinned mirror of `ArbitrationFindingCode`.
 *
 * Backend uses NAMESPACED codes (`arbitration.*`) so they round-trip
 * unambiguously when nested into JSON payloads alongside sibling
 * substrate codes (`coordination.*`, `governance.*`, …). Frontend
 * mirrors the namespaced form 1:1 — short literals would be wire
 * drift.
 *
 * Renamed from `ArbitrationFindingKind` in PR-A2 (wire contract
 * stabilization) to match the backend `code: str` field name used on
 * `ArbitrationFinding.code` and the persisted record column.
 */
export const ArbitrationFindingCode = {
  AUTHORITY_PRECEDENCE_APPLIED: 'arbitration.authority_precedence_applied',
  RESOLUTION_INCONCLUSIVE: 'arbitration.resolution_inconclusive',
  NO_CONFLICT: 'arbitration.no_conflict',
  INSUFFICIENT_SIGNALS: 'arbitration.insufficient_signals',
  CONTRADICTORY_FINDINGS: 'arbitration.contradictory_findings',
  CONFLICTING_RECOMMENDATIONS: 'arbitration.conflicting_recommendations',
  ESCALATION_CONFLICT: 'arbitration.escalation_conflict',
  SUPERVISOR_DISAGREEMENT: 'arbitration.supervisor_disagreement',
  AUTHORISATION_QUALITY_CROSS: 'arbitration.authorisation_quality_cross',
  DEADLOCK_DETECTED: 'arbitration.deadlock_detected',
  DEADLOCK_RISK: 'arbitration.deadlock_risk',
} as const;
export type ArbitrationFindingCode =
  (typeof ArbitrationFindingCode)[keyof typeof ArbitrationFindingCode];

export interface ArbitrationFindingDto {
  readonly code: ArbitrationFindingCode;
  readonly summary: string;
  readonly evidence: Readonly<Record<string, unknown>>;
}

export interface ArbitrationDecisionDto {
  readonly decisionId: ArbitrationDecisionId;
  readonly caseId: ArbitrationCaseId;
  readonly outcome: ArbitrationOutcome;
  readonly precedingAuthority: ArbitrationAuthorityLevel;
  readonly findings: readonly ArbitrationFindingDto[];
  readonly observedAt: IsoTimestamp;
  readonly lineage: Lineage;
}
