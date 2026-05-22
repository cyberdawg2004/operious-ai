'use client';

import { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { JsonInspector } from '@operious/ui';
import type { TraceNodeDto } from '@operious/types';
import { SubstrateDot } from '@/components/ui/substrate-dot';
import { StatusPill } from '@/components/ui/status-pill';
import { traceKindLabel, traceKindSubstrate } from '@/lib/classifications';
import { cn } from '@/lib/cn';

interface TraceEventDetailProps {
  readonly node: TraceNodeDto;
  readonly replayDigest: string;
}

const identityFor = (node: TraceNodeDto): string => {
  switch (node.kind) {
    case 'session_timeline_event':
      return node.payload.eventId as unknown as string;
    case 'governance_trace':
      return node.payload.traceId as unknown as string;
    case 'agent_execution_trace':
      return node.payload.executionId as unknown as string;
    case 'arbitration_decision':
      return node.payload.decisionId as unknown as string;
    case 'topology_evaluation':
      return node.payload.evaluationId as unknown as string;
    case 'boundary_ingress':
    case 'boundary_egress':
    case 'translation':
    case 'voice':
      return node.payload.traceId;
  }
};

const observedFor = (node: TraceNodeDto): string => node.payload.observedAt;
const sequenceFor = (node: TraceNodeDto): number =>
  node.kind === 'session_timeline_event'
    ? node.payload.sequence
    : node.payload.lineage.sequence;

const parentFor = (node: TraceNodeDto): string | undefined => {
  if (node.kind === 'session_timeline_event') return undefined;
  return node.payload.lineage.parentCorrelationId as unknown as string;
};

const tenantFor = (node: TraceNodeDto): string | undefined => {
  if (node.kind === 'session_timeline_event') return undefined;
  return node.payload.lineage.tenantId as unknown as string;
};

export const TraceEventDetail = ({
  node,
  replayDigest,
}: TraceEventDetailProps) => {
  const substrate = traceKindSubstrate[node.kind];
  const id = identityFor(node);
  const [copied, setCopied] = useState(false);

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* noop */
    }
  };

  return (
    <article className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-bg-inset">
      <header className="border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <SubstrateDot kind={substrate} />
          <span className="font-mono text-2xs uppercase tracking-wider text-fg-muted">
            {traceKindLabel[node.kind]}
          </span>
          <span className="ml-auto text-mono text-fg-dim">
            seq#{sequenceFor(node).toString().padStart(4, '0')}
          </span>
        </div>
        <p className="mt-1 font-mono text-2xs text-fg-subtle">
          observed {observedFor(node)}
        </p>
        <div className="mt-2 flex items-center gap-2">
          <code className="truncate rounded-sm border border-line bg-bg-raised px-2 py-1 font-mono text-2xs text-accent">
            {id}
          </code>
          <button
            type="button"
            onClick={copyId}
            aria-label="Copy event id"
            className={cn(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-sm border border-line',
              'text-fg-subtle transition-colors hover:border-accent hover:text-accent',
            )}
            title="Copy"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-signal-allow" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </header>

      <div className="space-y-4 overflow-y-auto px-4 py-4">
        <Section title="Authority context">
          <KV label="Tenant" value={tenantFor(node) ?? '\u2014'} />
          <KV label="Parent" value={parentFor(node) ?? '\u2014'} />
        </Section>

        <Section title="Lineage edges">
          <p className="text-mono text-fg-subtle">
            Edges materialise from the backend's `operational_event` projection.
            Inline lineage chips will surface here as projections land.
          </p>
        </Section>

        <Section title="Replay status">
          <div className="flex items-center gap-2">
            <StatusPill tone="completed">clean</StatusPill>
            <code className="truncate font-mono text-2xs text-fg-subtle">
              {replayDigest.slice(0, 24)}\u2026
            </code>
          </div>
        </Section>

        <Section title="Payload">
          <JsonInspector value={node.payload} />
        </Section>
      </div>
    </article>
  );
};

const Section = ({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) => (
  <section>
    <p className="mb-2 text-mono text-fg-dim">{title}</p>
    <div className="space-y-2">{children}</div>
  </section>
);

const KV = ({ label, value }: { label: string; value: string }) => (
  <div className="grid grid-cols-3 gap-2">
    <span className="text-mono text-fg-dim">{label}</span>
    <span className="col-span-2 truncate font-mono text-2xs text-fg-muted">
      {value}
    </span>
  </div>
);
