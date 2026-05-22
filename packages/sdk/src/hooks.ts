'use client';

import { useQuery } from '@tanstack/react-query';
import { ENDPOINT } from '@operious/contracts';
import type {
  CorrelationId,
  GovernanceTraceDto,
  GovernanceTraceId,
  MePrincipalDto,
  Page,
  MemoryProposalDto,
  QueueItemDto,
  QueueItemKind,
  QueueItemStatus,
  RecommendationDto,
  SOPProposalDto,
  SessionId,
  SessionTimelineEventDto,
  TenantChannelConfigurationPage,
  TenantChannelStatus,
  TenantChannelType,
  TenantGovernancePolicyPage,
  TenantGovernancePolicyStatus,
  TenantKnowledgeDocumentPage,
  TenantKnowledgeDocumentStatus,
  TenantKnowledgeDocumentType,
  TopologyGraphDto,
  TraceBundleDto,
} from '@operious/types';
import { isErr, type Result, type ResultError } from '@operious/shared';
import type { RequestEnvelope } from './client';

import { useAuthedRequest } from './client';
import {
  authMeKey,
  cognitionProposalsKey,
  cognitionRecommendationsKey,
  cognitionSopProposalsKey,
  governanceTraceKey,
  operationsQueueKey,
  sessionTimelineKey,
  tenantChannelsKey,
  tenantKnowledgeKey,
  tenantPoliciesKey,
  topologyGraphKey,
  traceBundleKey,
} from './query';

/**
 * All read hooks return TanStack Query state with a `data` field that is a
 * `Result<T, ResultError>` envelope. The UI branches on `data?.ok` and
 * renders either the success or error envelope deterministically.
 *
 * `staleTime` and `retry` are deliberately conservative:
 *   - retry is OFF; the backend is the authority and a denied / failed call
 *     should not be silently retried by the frontend.
 *   - staleTime favours forensic stability over freshness.
 */

const FORENSIC_STALE_MS = 30_000;

const settle = <T>(envelope: RequestEnvelope<T>): T => {
  const result: Result<T, ResultError> = envelope.result;
  if (isErr(result)) throw result.error;
  return result.value;
};

export const useOperationsQueue = (filters: {
  readonly status?: QueueItemStatus;
  readonly kind?: QueueItemKind;
  readonly cursor?: string;
  readonly limit?: number;
}) => {
  const request = useAuthedRequest();
  return useQuery<Page<QueueItemDto>>({
    queryKey: operationsQueueKey(filters),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      const envelope = await request<Page<QueueItemDto>>(ENDPOINT.operations.queue, {
        query: {
          status: filters.status,
          kind: filters.kind,
          cursor: filters.cursor,
          limit: filters.limit,
        },
      });
      return settle(envelope);
    },
  });
};

export const useTraceBundle = (correlationId: CorrelationId | undefined) => {
  const request = useAuthedRequest();
  return useQuery<TraceBundleDto>({
    queryKey: traceBundleKey(
      correlationId ?? ('' as unknown as CorrelationId),
    ),
    enabled: Boolean(correlationId),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      if (!correlationId) throw new Error('trace bundle requires correlationId');
      const envelope = await request<TraceBundleDto>(
        ENDPOINT.traces.bundle(correlationId as unknown as string),
      );
      return settle(envelope);
    },
  });
};

export const useSessionTimeline = (sessionId: SessionId | undefined) => {
  const request = useAuthedRequest();
  return useQuery<{ readonly sessionId: SessionId; readonly events: readonly SessionTimelineEventDto[] }>(
    {
      queryKey: sessionTimelineKey(sessionId ?? ('' as unknown as SessionId)),
      enabled: Boolean(sessionId),
      staleTime: FORENSIC_STALE_MS,
      retry: false,
      queryFn: async () => {
        if (!sessionId) throw new Error('session timeline requires sessionId');
        const envelope = await request<{
          sessionId: SessionId;
          events: readonly SessionTimelineEventDto[];
        }>(ENDPOINT.traces.sessionTimeline(sessionId as unknown as string));
        return settle(envelope);
      },
    },
  );
};

export const useGovernanceTrace = (traceId: GovernanceTraceId | undefined) => {
  const request = useAuthedRequest();
  return useQuery<GovernanceTraceDto>({
    queryKey: governanceTraceKey(
      traceId ?? ('' as unknown as GovernanceTraceId),
    ),
    enabled: Boolean(traceId),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      if (!traceId) throw new Error('governance trace requires traceId');
      const envelope = await request<GovernanceTraceDto>(
        ENDPOINT.governance.trace(traceId as unknown as string),
      );
      return settle(envelope);
    },
  });
};

export const useTopologyGraph = (version?: string) => {
  const request = useAuthedRequest();
  return useQuery<TopologyGraphDto>({
    queryKey: topologyGraphKey(version),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      const envelope = await request<TopologyGraphDto>(
        ENDPOINT.topology.graph,
        version ? { query: { version } } : {},
      );
      return settle(envelope);
    },
  });
};

export const useMemoryProposals = (cursor?: string) => {
  const request = useAuthedRequest();
  return useQuery<Page<MemoryProposalDto>>({
    queryKey: cognitionProposalsKey(cursor),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      const envelope = await request<Page<MemoryProposalDto>>(
        ENDPOINT.cognition.proposals,
        cursor ? { query: { cursor } } : {},
      );
      return settle(envelope);
    },
  });
};

export const useSOPProposals = (cursor?: string) => {
  const request = useAuthedRequest();
  return useQuery<Page<SOPProposalDto>>({
    queryKey: cognitionSopProposalsKey(cursor),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      const envelope = await request<Page<SOPProposalDto>>(
        ENDPOINT.cognition.sopProposals,
        cursor ? { query: { cursor } } : {},
      );
      return settle(envelope);
    },
  });
};

export const useRecommendations = (cursor?: string) => {
  const request = useAuthedRequest();
  return useQuery<Page<RecommendationDto>>({
    queryKey: cognitionRecommendationsKey(cursor),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      const envelope = await request<Page<RecommendationDto>>(
        ENDPOINT.cognition.recommendations,
        cursor ? { query: { cursor } } : {},
      );
      return settle(envelope);
    },
  });
};

// ---------------------------------------------------------------------------
// Auth — `ENDPOINT.auth.me`
// ---------------------------------------------------------------------------

export const useMe = (enabled = true) => {
  const request = useAuthedRequest();
  return useQuery<MePrincipalDto>({
    queryKey: authMeKey(),
    enabled,
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      const envelope = await request<MePrincipalDto>(ENDPOINT.auth.me);
      return settle(envelope);
    },
  });
};

// ---------------------------------------------------------------------------
// Tenant configuration reads
// ---------------------------------------------------------------------------

export const useTenantChannels = (filters: {
  readonly channelType?: TenantChannelType;
  readonly status?: TenantChannelStatus;
  readonly limit?: number;
  readonly offset?: number;
} = {}) => {
  const request = useAuthedRequest();
  return useQuery<TenantChannelConfigurationPage>({
    queryKey: tenantChannelsKey(filters),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      const envelope = await request<TenantChannelConfigurationPage>(
        ENDPOINT.tenant.channels,
        {
          query: {
            channel_type: filters.channelType,
            status: filters.status,
            limit: filters.limit,
            offset: filters.offset,
          },
        },
      );
      return settle(envelope);
    },
  });
};

export const useTenantKnowledge = (filters: {
  readonly documentType?: TenantKnowledgeDocumentType;
  readonly status?: TenantKnowledgeDocumentStatus;
  readonly limit?: number;
  readonly offset?: number;
} = {}) => {
  const request = useAuthedRequest();
  return useQuery<TenantKnowledgeDocumentPage>({
    queryKey: tenantKnowledgeKey(filters),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      const envelope = await request<TenantKnowledgeDocumentPage>(
        ENDPOINT.tenant.knowledge,
        {
          query: {
            document_type: filters.documentType,
            status: filters.status,
            limit: filters.limit,
            offset: filters.offset,
          },
        },
      );
      return settle(envelope);
    },
  });
};

export const useTenantPolicies = (filters: {
  readonly policyType?: string;
  readonly status?: TenantGovernancePolicyStatus;
  readonly limit?: number;
  readonly offset?: number;
} = {}) => {
  const request = useAuthedRequest();
  return useQuery<TenantGovernancePolicyPage>({
    queryKey: tenantPoliciesKey(filters),
    staleTime: FORENSIC_STALE_MS,
    retry: false,
    queryFn: async () => {
      const envelope = await request<TenantGovernancePolicyPage>(
        ENDPOINT.tenant.policies,
        {
          query: {
            policy_type: filters.policyType,
            status: filters.status,
            limit: filters.limit,
            offset: filters.offset,
          },
        },
      );
      return settle(envelope);
    },
  });
};
