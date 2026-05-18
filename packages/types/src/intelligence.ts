import type { IsoTimestamp, Lineage } from './common';
import type {
  ApprovalRecordId,
  MemoryProposalId,
  PrincipalId,
  RecommendationId,
  SOPProposalId,
} from './ids';

/**
 * Organizational Intelligence DTO mirror.
 *
 * Frontend visualizes governed memory evolution. The intelligence layer
 * NEVER mutates runtime behavior; the frontend therefore NEVER auto-approves.
 * Approval is exclusively a human authority operation, mediated by the
 * Cognition Hub UI.
 */

export const ProposalStatus = {
  DRAFT: 'draft',
  PENDING_APPROVAL: 'pending_approval',
  APPROVED: 'approved',
  REJECTED: 'rejected',
  WITHDRAWN: 'withdrawn',
  EXPIRED: 'expired',
} as const;
export type ProposalStatus =
  (typeof ProposalStatus)[keyof typeof ProposalStatus];

export const ProposalKind = {
  SOP: 'sop',
  MEMORY: 'memory',
  COMMUNICATION_PATTERN: 'communication_pattern',
  ESCALATION_PATTERN: 'escalation_pattern',
} as const;
export type ProposalKind = (typeof ProposalKind)[keyof typeof ProposalKind];

export const RecommendationKind = {
  SOP_OPTIMIZATION: 'sop_optimization',
  ESCALATION_IMPROVEMENT: 'escalation_improvement',
  COMMUNICATION_IMPROVEMENT: 'communication_improvement',
  WORKFLOW_AMBIGUITY: 'workflow_ambiguity',
  OPERATIONAL_BOTTLENECK: 'operational_bottleneck',
} as const;
export type RecommendationKind =
  (typeof RecommendationKind)[keyof typeof RecommendationKind];

export interface ProposalDiffSegmentDto {
  readonly path: string;
  readonly before?: string;
  readonly after?: string;
  readonly changeType: 'added' | 'removed' | 'modified' | 'unchanged';
}

export interface MemoryProposalDto {
  readonly proposalId: MemoryProposalId;
  readonly kind: ProposalKind;
  readonly status: ProposalStatus;
  readonly title: string;
  readonly summary: string;
  readonly proposedBy: 'system' | 'supervisor' | 'human';
  readonly diff: readonly ProposalDiffSegmentDto[];
  readonly observedAt: IsoTimestamp;
  readonly lineage: Lineage;
}

export interface SOPProposalDto {
  readonly proposalId: SOPProposalId;
  readonly status: ProposalStatus;
  readonly sopName: string;
  readonly version: string;
  readonly summary: string;
  readonly diff: readonly ProposalDiffSegmentDto[];
  readonly observedAt: IsoTimestamp;
  readonly lineage: Lineage;
}

export interface RecommendationDto {
  readonly recommendationId: RecommendationId;
  readonly kind: RecommendationKind;
  readonly title: string;
  readonly summary: string;
  readonly evidence: Readonly<Record<string, unknown>>;
  readonly observedAt: IsoTimestamp;
  readonly lineage: Lineage;
}

export interface ApprovalRecordDto {
  readonly approvalId: ApprovalRecordId;
  readonly proposalId: SOPProposalId | MemoryProposalId;
  readonly approverId: PrincipalId;
  readonly status: ProposalStatus;
  readonly justification: string;
  readonly observedAt: IsoTimestamp;
}
