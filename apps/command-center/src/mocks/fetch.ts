import { ENDPOINT } from '@operious/contracts';
import {
  MEMORY_PROPOSALS_FIXTURE,
  QUEUE_FIXTURE,
  RECOMMENDATIONS_FIXTURE,
  SESSION_TIMELINE_FIXTURE,
  SOP_PROPOSALS_FIXTURE,
  TOPOLOGY_FIXTURE,
  TRACE_BUNDLE_FIXTURE,
} from './fixtures';

/**
 * Mock fetch routed through the OperiousClient.
 *
 * IMPORTANT: this only fakes the transport layer. Every component up the
 * stack still goes through `@operious/sdk` hooks and treats responses as
 * backend-authoritative. When the real backend is wired up, this file is
 * deleted in one move and nothing else changes.
 */

const json = (value: unknown): Response =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

const notFound = (): Response =>
  new Response(JSON.stringify({ message: 'not found' }), {
    status: 404,
    headers: { 'Content-Type': 'application/json' },
  });

export const mockFetch: typeof fetch = async (input, _init) => {
  const url = new URL(typeof input === 'string' ? input : input.toString());
  const path = url.pathname;

  if (path === ENDPOINT.operations.queue) return json(QUEUE_FIXTURE);

  if (path.startsWith('/api/v1/traces/session/') && path.endsWith('/timeline')) {
    return json(SESSION_TIMELINE_FIXTURE);
  }

  if (path.startsWith('/api/v1/traces/')) {
    return json(TRACE_BUNDLE_FIXTURE);
  }

  if (path === ENDPOINT.topology.graph) return json(TOPOLOGY_FIXTURE);

  if (path === ENDPOINT.cognition.proposals) return json(MEMORY_PROPOSALS_FIXTURE);
  if (path === ENDPOINT.cognition.sopProposals) return json(SOP_PROPOSALS_FIXTURE);
  if (path === ENDPOINT.cognition.recommendations) return json(RECOMMENDATIONS_FIXTURE);

  return notFound();
};
