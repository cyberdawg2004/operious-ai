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
      {ordered.map((node, index) => (
        <TraceNode
          key={`${node.kind}-${index}`}
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
