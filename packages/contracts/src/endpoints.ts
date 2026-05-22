/**
 * Pinned endpoint paths.
 *
 * These are the ONLY URLs the frontend may target. Direct construction of a
 * URL anywhere else in the codebase is forbidden and will be flagged by
 * `tests/test_frontend_invariants.ts`.
 *
 * Versioning: the v1 prefix is intentional — every contract change increments
 * a path version, never silently mutates an existing one.
 */

export const ENDPOINT = {
  auth: {
    me: '/api/v1/auth/me',
  },
  operations: {
    queue: '/api/v1/operations/queue',
    queueItem: (id: string) => `/api/v1/operations/queue/${encodeURIComponent(id)}`,
  },
  traces: {
    bundle: (correlationId: string) =>
      `/api/v1/traces/${encodeURIComponent(correlationId)}`,
    sessionTimeline: (sessionId: string) =>
      `/api/v1/traces/session/${encodeURIComponent(sessionId)}/timeline`,
  },
  cognition: {
    proposals: '/api/v1/cognition/proposals',
    proposal: (id: string) => `/api/v1/cognition/proposals/${encodeURIComponent(id)}`,
    sopProposals: '/api/v1/cognition/sop-proposals',
    recommendations: '/api/v1/cognition/recommendations',
    approvalRequest: (proposalId: string) =>
      `/api/v1/cognition/proposals/${encodeURIComponent(proposalId)}/approval-request`,
  },
  topology: {
    graph: '/api/v1/topology/graph',
    evaluations: '/api/v1/topology/evaluations',
  },
  governance: {
    traces: '/api/v1/governance/traces',
    trace: (id: string) => `/api/v1/governance/traces/${encodeURIComponent(id)}`,
  },
  tenant: {
    channels: '/api/v1/tenant/channels',
    channel: (id: string) => `/api/v1/tenant/channels/${encodeURIComponent(id)}`,
    verifyChannel: (id: string) =>
      `/api/v1/tenant/channels/${encodeURIComponent(id)}/verify`,
    knowledge: '/api/v1/tenant/knowledge',
    knowledgeDocument: (id: string) =>
      `/api/v1/tenant/knowledge/${encodeURIComponent(id)}`,
    policies: '/api/v1/tenant/policies',
    policy: (id: string) =>
      `/api/v1/tenant/policies/${encodeURIComponent(id)}`,
  },
} as const;

export type EndpointMap = typeof ENDPOINT;
