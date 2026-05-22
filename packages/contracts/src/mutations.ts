import type {
  ApprovalRecordDto,
  ChannelConfigurationId,
  CorrelationId,
  GovernancePolicyId,
  KnowledgeDocumentId,
  MemoryProposalId,
  PrincipalId,
  QueueItemDto,
  SOPProposalId,
  TenantChannelConfigurationDto,
  TenantChannelStatus,
  TenantChannelType,
  TenantGovernancePolicyDto,
  TenantGovernancePolicyStatus,
  TenantKnowledgeDocumentDto,
  TenantKnowledgeDocumentStatus,
  TenantKnowledgeDocumentType,
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

// ---------------------------------------------------------------------------
// Tenant configuration mutations
// ---------------------------------------------------------------------------

export interface CreateChannelMutation {
  readonly channelType: TenantChannelType;
  readonly routingAddress: string;
  readonly credentials: Readonly<Record<string, unknown>>;
  readonly webhookSecret: string;
  readonly status?: TenantChannelStatus;
}
export type CreateChannelResult = TenantChannelConfigurationDto;

export interface UpdateChannelMutation {
  readonly configId: ChannelConfigurationId;
  readonly routingAddress?: string;
  readonly credentials?: Readonly<Record<string, unknown>>;
  readonly webhookSecret?: string;
  readonly status?: TenantChannelStatus;
}
export type UpdateChannelResult = TenantChannelConfigurationDto;

export interface VerifyChannelMutation {
  readonly configId: ChannelConfigurationId;
}
export type VerifyChannelResult = TenantChannelConfigurationDto;

export interface CreateKnowledgeDocumentMutation {
  readonly title: string;
  readonly content: string;
  readonly documentType: TenantKnowledgeDocumentType;
  readonly status?: TenantKnowledgeDocumentStatus;
}
export type CreateKnowledgeDocumentResult = TenantKnowledgeDocumentDto;

export interface UpdateKnowledgeDocumentMutation {
  readonly documentId: KnowledgeDocumentId;
  readonly content?: string;
  readonly status?: TenantKnowledgeDocumentStatus;
}
export type UpdateKnowledgeDocumentResult = TenantKnowledgeDocumentDto;

export interface CreatePolicyMutation {
  readonly policyType: string;
  readonly parameters: Readonly<Record<string, unknown>>;
  readonly status?: TenantGovernancePolicyStatus;
  /** ISO-8601 timestamp. */
  readonly effectiveFrom: string;
}
export type CreatePolicyResult = TenantGovernancePolicyDto;

export interface UpdatePolicyMutation {
  readonly policyId: GovernancePolicyId;
  readonly parameters?: Readonly<Record<string, unknown>>;
  readonly status?: TenantGovernancePolicyStatus;
  readonly effectiveFrom?: string;
}
export type UpdatePolicyResult = TenantGovernancePolicyDto;
