'use client';

import type { TraceBundleDto, TraceNodeDto } from '@operious/types';
import { TraceNode, type BadgeTone } from '@operious/ui';
import { renderableTraceNodes } from './ordering';

interface TraceTimelineProps {
  readonly bundle: TraceBundleDto;
}

/**
 * Tone assignment per `TraceNodeKind`.
 *
 * PR-A2: extended to cover all 9 backend trace-node kinds. The previous
 * 4-kind subset silently dropped `topology_evaluation`, `boundary_ingress`,
 * `boundary_egress`, `translation`, `voice` — those nodes rendered as
 * "unknown" tone and lost forensic signal. Coverage is now enforced by
 * `tests-frontend/src/trace-render-coverage.test.ts`.
 *
 * Tone semantics:
 *   * `info`     — neutral observation (session events, declarative graphs)
 *   * `escalate` — governance attention required
 *   * `pending`  — in-flight cognition (agent execution)
 *   * `deadlock` — arbitration conflict / deadlock
 *   * `neutral`  — boundary protocol translation (no operational verdict)
 */
const traceTone: Record<TraceNodeDto['kind'], BadgeTone> = {
  session_timeline_event: 'info',
  governance_trace: 'escalate',
  agent_execution_trace: 'pending',
  arbitration_decision: 'deadlock',
  topology_evaluation: 'info',
  boundary_ingress: 'neutral',
  boundary_egress: 'neutral',
  translation: 'info',
  voice: 'info',
};

const titleFor = (node: TraceNodeDto): string => {
  switch (node.kind) {
    case 'session_timeline_event':
      return node.payload.summary;
    case 'governance_trace':
      return `${node.payload.stage} → ${node.payload.decision}`;
    case 'agent_execution_trace':
      return node.payload.agentLabel;
    case 'arbitration_decision':
      return `${node.payload.outcome} (${node.payload.precedingAuthority})`;
    case 'topology_evaluation':
      return `topology → ${node.payload.decision} (depth ${node.payload.chainDepth}/${node.payload.maxChainDepth})`;
    case 'boundary_ingress':
      return `${node.payload.sourceType} → ${node.payload.adapterName} (ingress)`;
    case 'boundary_egress':
      return `${node.payload.adapterName} → ${node.payload.sourceType} (egress)`;
    case 'translation':
      return `translation → ${node.payload.kind}${
        node.payload.providerName ? ` (${node.payload.providerName})` : ''
      }`;
    case 'voice':
      return `voice → ${node.payload.kind}${
        node.payload.providerName ? ` (${node.payload.providerName})` : ''
      }`;
  }
};

const sequenceFor = (node: TraceNodeDto): number => {
  switch (node.kind) {
    case 'session_timeline_event':
      return node.payload.sequence;
    default:
      return node.payload.lineage.sequence;
  }
};

const observedAtFor = (node: TraceNodeDto): string => node.payload.observedAt;

/**
 * Stable React key per trace node.
 *
 * Pre-2.5-J3 the timeline used ``${kind}-${index}`` which made keys
 * re-shuffle every time the bundle reordered. Using a payload id keeps
 * reconciliation stable so animations / focus / scroll position survive a
 * re-fetch. The id chosen is the substrate's canonical join axis (the one
 * that appears on the persisted record) so the key is a 1:1 mirror of the
 * audit/replay identity of the node.
 *
 * PR-A2: extended to all 9 kinds; every new trace kind has a canonical
 * `traceId` / `evaluationId` projection on its payload.
 */
const stableKeyFor = (node: TraceNodeDto): string => {
  switch (node.kind) {
    case 'session_timeline_event':
      return `session:${node.payload.eventId as unknown as string}`;
    case 'governance_trace':
      return `governance:${node.payload.traceId as unknown as string}`;
    case 'agent_execution_trace':
      return `agent:${node.payload.executionId as unknown as string}`;
    case 'arbitration_decision':
      return `arbitration:${node.payload.decisionId as unknown as string}`;
    case 'topology_evaluation':
      return `topology:${node.payload.evaluationId as unknown as string}`;
    case 'boundary_ingress':
      return `boundary_ingress:${node.payload.traceId}`;
    case 'boundary_egress':
      return `boundary_egress:${node.payload.traceId}`;
    case 'translation':
      return `translation:${node.payload.traceId}`;
    case 'voice':
      return `voice:${node.payload.traceId}`;
  }
};

export const TraceTimeline = ({ bundle }: TraceTimelineProps) => {
  const ordered = renderableTraceNodes(bundle);
  if (ordered.length === 0) {
    return (
      <div className="text-mono text-fg-subtle border border-line rounded-md p-6 text-center">
        No trace nodes recorded for this correlation.
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {ordered.map((node) => (
        <TraceNode
          key={stableKeyFor(node)}
          kind={node.kind.replace(/_/g, ' ')}
          tone={traceTone[node.kind]}
          title={titleFor(node)}
          observedAt={observedAtFor(node)}
          sequence={sequenceFor(node)}
          payload={node.payload}
        />
      ))}
    </div>
  );
};
