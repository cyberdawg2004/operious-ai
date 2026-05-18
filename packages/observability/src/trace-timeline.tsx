'use client';

import type { TraceBundleDto, TraceNodeDto } from '@operious/types';
import { TraceNode, type BadgeTone } from '@operious/ui';
import { renderableTraceNodes } from './ordering';

interface TraceTimelineProps {
  readonly bundle: TraceBundleDto;
}

const traceTone: Record<TraceNodeDto['kind'], BadgeTone> = {
  session_timeline_event: 'info',
  governance_trace: 'escalate',
  agent_execution_trace: 'pending',
  arbitration_decision: 'deadlock',
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
 * 2.5-J3: stable React key per trace node.
 *
 * Pre-2.5-J3 the timeline used ``${kind}-${index}`` which makes
 * keys re-shuffle every time the bundle reorders. Using a payload
 * id keeps reconciliation stable so animations / focus / scroll
 * position survive a re-fetch. The id chosen is the substrate's
 * canonical join axis (the one that appears on the persisted
 * record) so the key is a 1:1 mirror of the audit/replay identity
 * of the node.
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
