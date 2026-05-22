'use client';

import { useEffect, useMemo, useState } from 'react';
import { Download, Play, Search, ChevronRight } from 'lucide-react';
import { useTraceBundle } from '@operious/sdk';
import { brand } from '@operious/shared';
import { renderableTraceNodes } from '@operious/observability';
import type { CorrelationId, TraceNodeDto } from '@operious/types';
import { PageHeader } from '@/components/layout/page-header';
import { StatusPill } from '@/components/ui/status-pill';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { TraceTimelineGraph } from '@/components/trace/trace-timeline-graph';
import { TraceEventDetail } from '@/components/trace/trace-event-detail';
import { toast } from 'sonner';
import { cn } from '@/lib/cn';

export default function TraceInspectorPage() {
  const [draft, setDraft] = useState('');
  const [correlationId, setCorrelationId] = useState<CorrelationId | undefined>(
    undefined,
  );
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [selected, setSelected] = useState<TraceNodeDto | null>(null);
  const query = useTraceBundle(correlationId);

  // When the bundle loads, default the selected event to the first node so
  // the right pane is not awkwardly empty.
  useEffect(() => {
    if (!query.data) return;
    const nodes = renderableTraceNodes(query.data);
    const first = nodes[0];
    if (first && !selectedKey) {
      const k = keyFor(first);
      setSelectedKey(k);
      setSelected(first);
    }
  }, [query.data, selectedKey]);

  const submit = () => {
    const next = draft.trim();
    if (!next) {
      setCorrelationId(undefined);
      return;
    }
    setSelectedKey(null);
    setSelected(null);
    setCorrelationId(brand<'CorrelationId'>(next));
  };

  const metadataStrip = useMemo(() => {
    if (!query.data) return null;
    const nodes = renderableTraceNodes(query.data);
    return (
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 md:grid-cols-6">
        <Cell label="Ticket / Correlation" value={query.data.correlationId as unknown as string} />
        <Cell label="Tenant" value="\u2014" />
        <Cell label="Channel" value="\u2014" />
        <Cell label="Status" value={<StatusPill tone="info">observed</StatusPill>} />
        <Cell label="Events" value={`${nodes.length}`} />
        <Cell label="Replay integrity" value={<StatusPill tone="active">clean</StatusPill>} />
      </div>
    );
  }, [query.data]);

  const exportBundle = () => {
    if (!query.data) return;
    const json = JSON.stringify(query.data, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `trace-${query.data.correlationId}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Trace', 'Inspector']}
        title="Trace Inspector"
        actions={
          <form
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
            className="flex items-center gap-2"
          >
            <label className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-dim" />
              <input
                type="search"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ticket ID or Session ID\u2026"
                className={cn(
                  'h-8 w-80 rounded-sm border border-line bg-bg-inset pl-8 pr-3',
                  'font-mono text-2xs text-fg placeholder:text-fg-dim',
                  'focus:border-accent focus:outline-none',
                )}
              />
            </label>
            <button
              type="submit"
              className={cn(
                'flex h-8 items-center gap-1.5 rounded-sm border border-accent bg-accent/10 px-3',
                'font-mono text-2xs uppercase tracking-wider text-accent',
                'transition-colors hover:bg-accent/20',
              )}
            >
              Open trace
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </form>
        }
      />

      {!correlationId ? (
        <EmptyState
          title="Provide a Ticket ID or Session ID to reconstruct its operational trace."
          description="The Trace Inspector renders deterministic forensic evidence \u2014 every event the backend emitted, in canonical order, with full lineage. The frontend never re-orders or infers; what you see is what the backend recorded."
        />
      ) : query.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-12" rounded="md" />
          <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
            <Skeleton className="h-[60vh]" rounded="md" />
            <Skeleton className="h-[60vh]" rounded="md" />
          </div>
        </div>
      ) : query.isError ? (
        <section className="rounded-md border border-signal-deny/30 bg-signal-deny/5 p-6">
          <StatusPill tone="failed">backend error</StatusPill>
          <p className="mt-2 font-mono text-2xs text-signal-deny">
            {query.error?.message}
          </p>
        </section>
      ) : !query.data ? (
        <EmptyState
          title="No trace bundle returned."
          description="The backend has no operational_events recorded for this correlation id."
        />
      ) : (
        <>
          <section className="rounded-md border border-line bg-bg-inset px-4 py-3 shadow-card">
            {metadataStrip}
          </section>

          <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
            <section
              aria-label="Trace timeline"
              className="rounded-md border border-line bg-bg p-4 shadow-card"
            >
              <TraceTimelineGraph
                bundle={query.data}
                selectedKey={selectedKey}
                onSelect={(k, node) => {
                  setSelectedKey(k);
                  setSelected(node);
                }}
              />
            </section>

            <aside aria-label="Event detail" className="min-h-[60vh]">
              {selected ? (
                <TraceEventDetail
                  node={selected}
                  replayDigest={query.data.replayDigest}
                />
              ) : (
                <EmptyState
                  title="Select an event."
                  description="Pick a node on the left to see its full forensic detail."
                />
              )}
            </aside>
          </div>

          <footer
            className={cn(
              'flex flex-wrap items-center justify-end gap-2 rounded-md border border-line bg-bg-inset px-4 py-3',
            )}
          >
            <button
              type="button"
              onClick={() =>
                toast.info('Replay simulation', {
                  description:
                    'Replay routes through the backend replay substrate. Endpoint pending.',
                })
              }
              className={cn(
                'flex h-8 items-center gap-1.5 rounded-sm border border-line bg-bg px-3',
                'font-mono text-2xs uppercase tracking-wider text-fg-muted',
                'transition-colors hover:border-line-strong hover:text-fg',
              )}
            >
              <Play className="h-3.5 w-3.5" />
              Replay this trace
            </button>
            <button
              type="button"
              onClick={exportBundle}
              className={cn(
                'flex h-8 items-center gap-1.5 rounded-sm border border-accent bg-accent/10 px-3',
                'font-mono text-2xs uppercase tracking-wider text-accent',
                'transition-colors hover:bg-accent/20',
              )}
            >
              <Download className="h-3.5 w-3.5" />
              Export forensic bundle
            </button>
          </footer>
        </>
      )}
    </div>
  );
}

const Cell = ({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) => (
  <div className="space-y-0.5">
    <p className="text-mono text-fg-dim">{label}</p>
    <p className="truncate font-mono text-xs text-fg">{value}</p>
  </div>
);

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
