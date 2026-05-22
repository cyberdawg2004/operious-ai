/**
 * Pinned query keys.
 *
 * TanStack Query keys are part of the SDK contract. UI consumers MUST NOT
 * fabricate keys — they always go through these helpers. Stable, deterministic
 * key shapes are required for cache continuity across navigation and replay.
 */

import type {
  CorrelationId,
  GovernanceTraceId,
  QueueItemKind,
  QueueItemStatus,
  SessionId,
  TenantChannelStatus,
  TenantChannelType,
  TenantGovernancePolicyStatus,
  TenantKnowledgeDocumentStatus,
  TenantKnowledgeDocumentType,
} from '@operious/types';

export const operationsQueueKey = (filters: {
  readonly status?: QueueItemStatus;
  readonly kind?: QueueItemKind;
  readonly cursor?: string;
}) =>
  [
    'operations-queue',
    filters.status ?? 'any-status',
    filters.kind ?? 'any-kind',
    filters.cursor ?? 'first-page',
  ] as const;

export const traceBundleKey = (correlationId: CorrelationId) =>
  ['trace-bundle', correlationId] as const;

export const sessionTimelineKey = (sessionId: SessionId) =>
  ['session-timeline', sessionId] as const;

export const governanceTraceKey = (traceId: GovernanceTraceId) =>
  ['governance-trace', traceId] as const;

export const topologyGraphKey = (version: string | undefined) =>
  ['topology-graph', version ?? 'latest'] as const;

export const cognitionProposalsKey = (cursor: string | undefined) =>
  ['cognition-proposals', cursor ?? 'first-page'] as const;

export const cognitionSopProposalsKey = (cursor: string | undefined) =>
  ['cognition-sop-proposals', cursor ?? 'first-page'] as const;

export const cognitionRecommendationsKey = (cursor: string | undefined) =>
  ['cognition-recommendations', cursor ?? 'first-page'] as const;

export const tenantChannelsKey = (filters: {
  readonly channelType?: TenantChannelType;
  readonly status?: TenantChannelStatus;
  readonly offset?: number;
}) =>
  [
    'tenant-channels',
    filters.channelType ?? 'any-type',
    filters.status ?? 'any-status',
    filters.offset ?? 0,
  ] as const;

export const tenantKnowledgeKey = (filters: {
  readonly documentType?: TenantKnowledgeDocumentType;
  readonly status?: TenantKnowledgeDocumentStatus;
  readonly offset?: number;
}) =>
  [
    'tenant-knowledge',
    filters.documentType ?? 'any-type',
    filters.status ?? 'any-status',
    filters.offset ?? 0,
  ] as const;

export const tenantPoliciesKey = (filters: {
  readonly policyType?: string;
  readonly status?: TenantGovernancePolicyStatus;
  readonly offset?: number;
}) =>
  [
    'tenant-policies',
    filters.policyType ?? 'any-type',
    filters.status ?? 'any-status',
    filters.offset ?? 0,
  ] as const;

export const authMeKey = () => ['auth-me'] as const;
