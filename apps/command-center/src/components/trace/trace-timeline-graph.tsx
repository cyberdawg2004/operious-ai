'use client';

import { motion as fm, useReducedMotion } from 'framer-motion';
import { useMemo } from 'react';
import type { TraceBundleDto, TraceNodeDto } from '@operious/types';
import { renderableTraceNodes } from '@operious/observability';
import { SubstrateDot, type SubstrateKind } from '@/components/ui/substrate-dot';
import { traceKindLabel, traceKindSubstrate } from '@/lib/classifications';
import { cn } from '@/lib/cn';
import { easings, ms, TRACE_NODE_ENTRY } from '@/lib/motion';

interface TraceTimelineGraphProps {
  readonly bundle: TraceBundleDto;
  readonly selectedKey: string | null;
  readonly onSelect: (key: string, node: TraceNodeDto) => void;
}

const titleFor = (node: TraceNodeDto): string => {
  switch (node.kind) {
    case 'session_timeline_event':
      return node.payload.summary;
    case 'governance_trace':
      return `${node.payload.stage} \u2192 ${node.payload.decision}`;
    case 'agent_execution_trace':
      return node.payload.agentLabel;
    case 'arbitration_decision':
      return `${node.payload.outcome}`;
    case 'topology_evaluation':
      return `${node.payload.decision} (depth ${node.payload.chainDepth}/${node.payload.maxChainDepth})`;
    case 'boundary_ingress':
      return `${node.payload.sourceType} \u2192 ${node.payload.adapterName}`;
    case 'boundary_egress':
      return `${node.payload.adapterName} \u2192 ${node.payload.sourceType}`;
    case 'translation':
      return `translation \u2014 ${node.payload.kind}`;
    case 'voice':
      return `voice \u2014 ${node.payload.kind}`;
  }
};

const sequenceFor = (node: TraceNodeDto): number => {
  if (node.kind === 'session_timeline_event') return node.payload.sequence;
  return node.payload.lineage.sequence;
};

const observedAtFor = (node: TraceNodeDto): string => node.payload.observedAt;

const correlationFor = (node: TraceNodeDto): string | undefined => {
  if (node.kind === 'session_timeline_event') return undefined;
  return node.payload.lineage.parentCorrelationId as unknown as string;
};

const keyFor = (node: TraceNodeDto): string => {
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

const SUBSTRATE_LEGEND: readonly { kind: SubstrateKind; label: string }[] = [
  { kind: 'boundary', label: 'Boundary' },
  { kind: 'governance', label: 'Governance' },
  { kind: 'coordination', label: 'Coordination' },
  { kind: 'session', label: 'Session' },
  { kind: 'execution', label: 'Execution' },
  { kind: 'supervisor', label: 'Supervisor' },
  { kind: 'arbitration', label: 'Arbitration' },
  { kind: 'hardening', label: 'Hardening' },
];

/**
 * Vertical timeline graph.
 *
 * Renders the trace bundle as a chronologically-ordered list of nodes.
 * Each node is keyed by substrate via a colored dot; causality (parent
 * \u2192 child) is shown by a left rail; lineage edges (governance,
 * supervisor, etc.) are rendered as inline pills.
 */
export const TraceTimelineGraph = ({
  bundle,
  selectedKey,
  onSelect,
}: TraceTimelineGraphProps) => {
  const nodes = useMemo(() => renderableTraceNodes(bundle), [bundle]);
  const reduceMotion = useReducedMotion() ?? false;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-line bg-bg-inset px-3 py-2">
        <span className="text-mono text-fg-dim">substrates</span>
        {SUBSTRATE_LEGEND.map((entry) => (
          <span
            key={entry.kind}
            className="inline-flex items-center gap-1.5 font-mono text-2xs text-fg-subtle"
          >
            <SubstrateDot kind={entry.kind} size="xs" />
            {entry.label}
          </span>
        ))}
      </div>

      <ol className="relative space-y-1.5 pl-7">
        <span
          aria-hidden
          className="absolute left-3 top-0 bottom-0 w-px bg-line"
        />
        {nodes.length === 0 ? (
          <li className="rounded-md border border-line bg-bg-inset px-4 py-6 text-center text-mono text-fg-subtle">
            No trace nodes recorded for this correlation.
          </li>
        ) : (
          nodes.map((node, index) => {
            const k = keyFor(node);
            const selected = k === selectedKey;
            const substrate = traceKindSubstrate[node.kind];
            const glow = substrateColor(substrate, 0.45);
            // Node entry — this is the ONE place an overshoot easing is
            // permitted in the entire Command Center. Per spec we also
            // emit a brief substrate-colour glow that fades out over 800ms.
            return (
              <fm.li
                key={k}
                initial={
                  reduceMotion
                    ? { opacity: 1, scale: 1 }
                    : { opacity: 0, scale: 0.6, boxShadow: `0 0 0 0 ${glow}` }
                }
                animate={
                  reduceMotion
                    ? { opacity: 1, scale: 1 }
                    : {
                        opacity: 1,
                        scale: 1,
                        boxShadow: [
                          `0 0 0 8px ${glow}`,
                          `0 0 0 0 ${substrateColor(substrate, 0)}`,
                        ],
                      }
                }
                transition={{
                  opacity: { duration: ms(TRACE_NODE_ENTRY.opacityMs), ease: easings.precise },
                  scale: {
                    duration: ms(TRACE_NODE_ENTRY.scaleMs),
                    ease: easings.traceOvershoot,
                  },
                  boxShadow: {
                    duration: ms(TRACE_NODE_ENTRY.glowMs),
                    ease: easings.expoOut,
                  },
                  delay: reduceMotion ? 0 : Math.min(index * 0.04, 0.32),
                }}
                className="relative rounded-md"
              >
                <span
                  aria-hidden
                  className={cn(
                    'absolute left-[-1.0rem] top-3 z-10 flex h-3 w-3 items-center justify-center rounded-full',
                    'bg-bg-inset ring-2 ring-bg',
                  )}
                >
                  <SubstrateDot kind={substrate} size="xs" />
                </span>
                <button
                  type="button"
                  onClick={() => onSelect(k, node)}
                  className={cn(
                    'group block w-full rounded-md border bg-bg-inset px-3 py-2 text-left',
                    'transition-colors duration-150',
                    selected
                      ? 'border-accent shadow-card-hover'
                      : 'border-line hover:border-line-strong hover:bg-bg-raised',
                  )}
                >
                  <header className="flex items-center gap-2 text-mono text-fg-subtle">
                    <span>seq#{sequenceFor(node).toString().padStart(4, '0')}</span>
                    <span className="text-fg-dim">\u00b7</span>
                    <span className="truncate">{observedAtFor(node)}</span>
                    <span
                      className="ml-auto inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-2xs uppercase tracking-wider"
                      style={{
                        borderColor: substrateColor(substrate, 0.3),
                        color: substrateColor(substrate, 1),
                      }}
                    >
                      {traceKindLabel[node.kind]}
                    </span>
                  </header>
                  <p className="mt-1 font-sans text-sm text-fg">
                    {titleFor(node)}
                  </p>
                  {correlationFor(node) ? (
                    <p className="mt-0.5 font-mono text-2xs text-fg-dim">
                      parent: {correlationFor(node)?.slice(0, 12)}
                    </p>
                  ) : null}
                </button>
              </fm.li>
            );
          })
        )}
      </ol>
    </div>
  );
};

// Hex values mirror the tailwind config substrate palette.
const SUBSTRATE_HEX: Record<SubstrateKind, string> = {
  boundary: '#1A4A9A',
  governance: '#A8882C',
  coordination: '#4A5468',
  session: '#2E7D5C',
  execution: '#0D2860',
  supervisor: '#6B5418',
  arbitration: '#A6342D',
  hardening: '#8A93A4',
};
const substrateColor = (kind: SubstrateKind, alpha: number): string => {
  const hex = SUBSTRATE_HEX[kind];
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};
