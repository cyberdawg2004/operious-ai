/**
 * @operious/sdk
 *
 * Typed API client + TanStack Query hooks for the Operious backend.
 *
 * SEMANTIC RULES (enforced by frontend invariant tests):
 *   - The SDK NEVER constructs a URL outside `@operious/contracts/endpoints`.
 *   - The SDK NEVER throws on backend errors — it returns a `Result` envelope.
 *   - The SDK NEVER performs an optimistic mutation. Every mutation hook
 *     waits for an explicit backend confirmation envelope before settling.
 *   - The SDK forwards a client correlation id on every request so the
 *     backend can attach canonical lineage; the SDK never asserts canonical
 *     lineage itself.
 */

export {
  OperiousClient,
  OperiousClientProvider,
  useOperiousClient,
  useAuthedRequest,
} from './client';
export type { OperiousClientConfig, RequestEnvelope } from './client';

export {
  authMeKey,
  operationsQueueKey,
  traceBundleKey,
  sessionTimelineKey,
  governanceTraceKey,
  topologyGraphKey,
  cognitionProposalsKey,
  cognitionSopProposalsKey,
  cognitionRecommendationsKey,
  tenantChannelsKey,
  tenantKnowledgeKey,
  tenantPoliciesKey,
} from './query';

export {
  useOperationsQueue,
  useTraceBundle,
  useSessionTimeline,
  useGovernanceTrace,
  useTopologyGraph,
  useMemoryProposals,
  useSOPProposals,
  useRecommendations,
  useMe,
  useTenantChannels,
  useTenantKnowledge,
  useTenantPolicies,
} from './hooks';

export {
  useRequestApproval,
  useClaimQueueItem,
  useCreateChannel,
  useUpdateChannel,
  useVerifyChannel,
  useCreateKnowledgeDocument,
  useUpdateKnowledgeDocument,
  useCreatePolicy,
  useUpdatePolicy,
} from './mutations';
