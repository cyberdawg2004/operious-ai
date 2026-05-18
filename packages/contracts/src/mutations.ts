import type {
  ApprovalRecordDto,
  CorrelationId,
  MemoryProposalId,
  PrincipalId,
  QueueItemDto,
  SOPProposalId,
} from '@operious/types';

/**
 * Pinned mutation contracts.
 *
 * IMPORTANT ARCHITECTURAL RULE:
 *
 * The frontend NEVER performs an operational mutation. It only REQUESTS
 * a mutation through a backend governance gate. Every mutation contract
 * therefore expresses INTENT and returns a deterministic envelope from the
 * backend confirming whether the request was admitted, deferred, denied,
 * or escalated.
 *
 * No mutation contract here ever returns "success" without a backend
 * envelope. Optimistic UI is forbidden.
 */

export interface RequestApprovalMutation {
  readonly proposalId: SOPProposalId | MemoryProposalId;
  readonly approverId: PrincipalId;
  readonly justification: string;
  readonly clientCorrelationId: CorrelationId;
}

/**
 * Backend response envelope for an approval request submission.
 * `accepted` does NOT mean "the proposal is approved" — it means
 * "the request was admitted into the governance approval workflow".
 */
export interface RequestApprovalResult {
  readonly accepted: boolean;
  readonly approvalRecord?: ApprovalRecordDto;
  readonly correlationId: CorrelationId;
  readonly observedAt: string;
  readonly reason?: string;
}

export interface ClaimQueueItemMutation {
  readonly itemId: CorrelationId;
  readonly principalId: PrincipalId;
  readonly clientCorrelationId: CorrelationId;
}

export interface ClaimQueueItemResult {
  readonly accepted: boolean;
  readonly item?: QueueItemDto;
  readonly correlationId: CorrelationId;
  readonly observedAt: string;
  readonly reason?: string;
}
