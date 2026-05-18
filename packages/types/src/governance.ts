import type { IsoTimestamp, Lineage } from './common';
import type { GovernanceEvaluationId, GovernanceTraceId } from './ids';

/**
 * Governance substrate DTO mirror.
 *
 * Pinned wire values match `apps/backend/app/governance/enums.py`.
 * Frontend visualizes governance verdicts; it never produces them.
 */

export const GovernanceDecision = {
  DENY: 'deny',
  REQUIRE_APPROVAL: 'require_approval',
  ESCALATE: 'escalate',
  DEGRADE: 'degrade',
  REDACT: 'redact',
  ALLOW: 'allow',
} as const;
export type GovernanceDecision =
  (typeof GovernanceDecision)[keyof typeof GovernanceDecision];

export const EnforcementStage = {
  PRE_REQUEST: 'pre_request',
  PRE_RETRIEVAL: 'pre_retrieval',
  POST_RETRIEVAL: 'post_retrieval',
  PRE_GROUNDING: 'pre_grounding',
  PRE_EXECUTION: 'pre_execution',
  POST_EXECUTION: 'post_execution',
} as const;
export type EnforcementStage =
  (typeof EnforcementStage)[keyof typeof EnforcementStage];

export const ViolationSeverity = {
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
  CRITICAL: 'critical',
} as const;
export type ViolationSeverity =
  (typeof ViolationSeverity)[keyof typeof ViolationSeverity];

export const RestrictionKind = {
  MODEL_RESTRICTION: 'model_restriction',
  SOURCE_RESTRICTION: 'source_restriction',
  CHUNK_CAP: 'chunk_cap',
  TOKEN_CAP: 'token_cap',
  CONTENT_REDACTION: 'content_redaction',
  RATE_LIMIT: 'rate_limit',
  CAPABILITY_RESTRICTION: 'capability_restriction',
} as const;
export type RestrictionKind =
  (typeof RestrictionKind)[keyof typeof RestrictionKind];

export interface GovernanceViolationDto {
  readonly ruleId: string;
  readonly severity: ViolationSeverity;
  readonly message: string;
}

export interface GovernanceRestrictionDto {
  readonly kind: RestrictionKind;
  readonly description: string;
  readonly metadata: Readonly<Record<string, unknown>>;
}

export interface GovernanceTraceDto {
  readonly traceId: GovernanceTraceId;
  readonly evaluationId: GovernanceEvaluationId;
  readonly stage: EnforcementStage;
  readonly decision: GovernanceDecision;
  readonly violations: readonly GovernanceViolationDto[];
  readonly restrictions: readonly GovernanceRestrictionDto[];
  readonly observedAt: IsoTimestamp;
  readonly lineage: Lineage;
}
