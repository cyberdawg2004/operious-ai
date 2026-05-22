import type { IsoTimestamp } from './common';
import type { Brand } from '@operious/shared';

/**
 * Tenant-owned configuration DTOs.
 *
 * These DTOs mirror the backend tenant API schemas
 * byte-for-byte. The frontend visualizes; the backend owns.
 *
 * Wire-format pinning: every enum value matches the backend
 * `app/tenant/enums.py` byte-for-byte. Drift is a type-check failure.
 */

// ---------------------------------------------------------------------------
// Branded identifiers
// ---------------------------------------------------------------------------

export type ChannelConfigurationId = Brand<string, 'ChannelConfigurationId'>;
export type KnowledgeDocumentId = Brand<string, 'KnowledgeDocumentId'>;
export type GovernancePolicyId = Brand<string, 'GovernancePolicyId'>;

// ---------------------------------------------------------------------------
// Channel configuration
// ---------------------------------------------------------------------------

export const TenantChannelType = {
  EMAIL: 'email',
  WHATSAPP: 'whatsapp',
  LARK: 'lark',
  SMS: 'sms',
  WEB_FORM: 'web_form',
  API: 'api',
} as const;
export type TenantChannelType =
  (typeof TenantChannelType)[keyof typeof TenantChannelType];

export const TenantChannelStatus = {
  PENDING_VERIFICATION: 'pending_verification',
  ACTIVE: 'active',
  PAUSED: 'paused',
  ERROR: 'error',
} as const;
export type TenantChannelStatus =
  (typeof TenantChannelStatus)[keyof typeof TenantChannelStatus];

/**
 * Credential-redacted channel response.
 *
 * The backend NEVER returns decrypted credentials. The frontend may only
 * inspect status, routing address, verification state, and counters.
 */
export interface TenantChannelConfigurationDto {
  readonly configId: ChannelConfigurationId;
  readonly channelType: TenantChannelType;
  readonly routingAddress: string;
  readonly status: TenantChannelStatus;
  readonly verifiedAt?: IsoTimestamp;
}

export interface TenantChannelConfigurationPage {
  readonly items: readonly TenantChannelConfigurationDto[];
  readonly total: number;
  readonly offset: number;
}

// ---------------------------------------------------------------------------
// Knowledge document
// ---------------------------------------------------------------------------

export const TenantKnowledgeDocumentType = {
  SOP: 'sop',
  POLICY: 'policy',
  PRODUCT_GUIDE: 'product_guide',
  FAQ: 'faq',
  ESCALATION_MATRIX: 'escalation_matrix',
} as const;
export type TenantKnowledgeDocumentType =
  (typeof TenantKnowledgeDocumentType)[keyof typeof TenantKnowledgeDocumentType];

export const TenantKnowledgeDocumentStatus = {
  PENDING_INDEX: 'pending_index',
  ACTIVE: 'active',
  INDEXING: 'indexing',
  FAILED: 'failed',
  ARCHIVED: 'archived',
} as const;
export type TenantKnowledgeDocumentStatus =
  (typeof TenantKnowledgeDocumentStatus)[keyof typeof TenantKnowledgeDocumentStatus];

export interface TenantKnowledgeDocumentDto {
  readonly documentId: KnowledgeDocumentId;
  readonly title: string;
  readonly content: string;
  readonly documentType: TenantKnowledgeDocumentType;
  readonly status: TenantKnowledgeDocumentStatus;
  readonly version: number;
  readonly uploadedBy: string;
  readonly vectorIndexedAt?: IsoTimestamp;
  readonly createdAt: IsoTimestamp;
}

export interface TenantKnowledgeDocumentPage {
  readonly items: readonly TenantKnowledgeDocumentDto[];
  readonly total: number;
  readonly offset: number;
}

// ---------------------------------------------------------------------------
// Governance policy
// ---------------------------------------------------------------------------

export const TenantGovernancePolicyStatus = {
  DRAFT: 'draft',
  PENDING_APPROVAL: 'pending_approval',
  ACTIVE: 'active',
  RETIRED: 'retired',
} as const;
export type TenantGovernancePolicyStatus =
  (typeof TenantGovernancePolicyStatus)[keyof typeof TenantGovernancePolicyStatus];

export interface TenantGovernancePolicyDto {
  readonly policyId: GovernancePolicyId;
  readonly policyType: string;
  readonly parameters: Readonly<Record<string, unknown>>;
  readonly status: TenantGovernancePolicyStatus;
  readonly version: number;
  readonly approvedBy: string;
  readonly effectiveFrom: IsoTimestamp;
  readonly createdAt: IsoTimestamp;
}

export interface TenantGovernancePolicyPage {
  readonly items: readonly TenantGovernancePolicyDto[];
  readonly total: number;
  readonly offset: number;
}
