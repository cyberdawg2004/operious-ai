'use client';

import { useMemo, useState } from 'react';
import { Check, Save } from 'lucide-react';
import { useTopologyGraph } from '@operious/sdk';
import { TopologyCanvas } from '@operious/topology';
import type { TopologyEdgeDto, TopologyGraphDto, TopologyNodeDto } from '@operious/types';
import { toast } from 'sonner';
import { PageHeader } from '@/components/layout/page-header';
import { StatusPill } from '@/components/ui/status-pill';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { useRightPanel } from '@/components/layout/right-panel';
import { cn } from '@/lib/cn';

/**
 * Detects cycles in the topology graph via DFS coloring.
 *
 * Returns the list of node ids that participate in a cycle. The frontend
 * NEVER mutates topology \u2014 this is purely a visualization assist for the
 * "Validate DAG" action; the backend remains the source of truth for
 * topology admission.
 */
const findCycles = (graph: TopologyGraphDto): readonly string[] => {
  const adjacency = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const source = edge.source as unknown as string;
    const target = edge.target as unknown as string;
    const arr = adjacency.get(source) ?? [];
    arr.push(target);
    adjacency.set(source, arr);
  }
  const WHITE = 0;
  const GRAY = 1;
  const BLACK = 2;
  const color = new Map<string, number>();
  const offenders = new Set<string>();
  const dfs = (node: string): void => {
    color.set(node, GRAY);
    for (const next of adjacency.get(node) ?? []) {
      const c = color.get(next) ?? WHITE;
      if (c === GRAY) {
        offenders.add(node);
        offenders.add(next);
        continue;
      }
      if (c === WHITE) dfs(next);
    }
    color.set(node, BLACK);
  };
  for (const node of graph.nodes) {
    const id = node.nodeId as unknown as string;
    if ((color.get(id) ?? WHITE) === WHITE) dfs(id);
  }
  return Array.from(offenders);
};

export default function AgentTopologyPage() {
  const query = useTopologyGraph();
  const [validation, setValidation] = useState<
    | { state: 'idle' }
    | { state: 'ok' }
    | { state: 'cycles'; ids: readonly string[] }
  >({ state: 'idle' });
  const { open } = useRightPanel();

  const summary = useMemo(() => {
    if (!query.data) return null;
    return {
      nodes: query.data.nodes.length,
      edges: query.data.edges.length,
      version: query.data.version,
      observedAt: query.data.observedAt,
    };
  }, [query.data]);

  const validate = () => {
    if (!query.data) return;
    const offenders = findCycles(query.data);
    if (offenders.length === 0) {
      setValidation({ state: 'ok' });
      toast.success('Topology is a DAG', {
        description: 'No cycles detected. The backend remains the canonical authority for admission.',
      });
    } else {
      setValidation({ state: 'cycles', ids: offenders });
      toast.error('Cycles detected', {
        description: `${offenders.length} node(s) participate in a cycle. Cycles are admitted only by the backend.`,
      });
    }
  };

  const handleSelectNode = (node: TopologyNodeDto) => {
    open({
      key: node.nodeId as unknown as string,
      title: node.label,
      subtitle: `${node.kind} \u00b7 ${node.tenantScope ?? 'unscoped'}`,
      body: <NodeConfigView node={node} />,
    });
  };

  const handleSelectEdge = (edge: TopologyEdgeDto) => {
    open({
      key: edge.edgeId as unknown as string,
      title: edge.label ?? edge.kind,
      subtitle: `${edge.source as unknown as string} \u2192 ${edge.target as unknown as string}`,
      body: (
        <pre className="rounded-sm border border-line bg-bg-inset p-3 font-mono text-2xs text-fg-muted">
          {JSON.stringify(edge.metadata, null, 2)}
        </pre>
      ),
    });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb={['Coordination', 'Topology']}
        title="Agent Topology"
        actions={
          <>
            <button
              type="button"
              onClick={validate}
              disabled={!query.data}
              className={cn(
                'flex h-8 items-center gap-1.5 rounded-sm border border-line bg-bg-inset px-3',
                'font-mono text-2xs uppercase tracking-wider text-fg-muted',
                'transition-colors hover:border-line-strong hover:text-fg',
                !query.data && 'opacity-50',
              )}
            >
              <Check className="h-3.5 w-3.5" />
              Validate DAG
            </button>
            <button
              type="button"
              onClick={() =>
                toast.info('Save topology', {
                  description:
                    'Topology admission is owned by the backend. The frontend records intent; the backend confirms admission.',
                })
              }
              className={cn(
                'flex h-8 items-center gap-1.5 rounded-sm border border-accent bg-accent/15 px-3',
                'font-mono text-2xs uppercase tracking-wider text-accent',
                'transition-colors hover:bg-accent/25',
              )}
            >
              <Save className="h-3.5 w-3.5" />
              Save Topology
            </button>
          </>
        }
      />

      {validation.state === 'ok' ? (
        <div className="rounded-md border border-signal-allow/40 bg-signal-allow/5 px-4 py-2">
          <StatusPill tone="active">DAG verified</StatusPill>
        </div>
      ) : null}
      {validation.state === 'cycles' ? (
        <div className="rounded-md border border-signal-deny/40 bg-signal-deny/5 px-4 py-2">
          <StatusPill tone="failed">cycles detected</StatusPill>
          <p className="mt-1 font-mono text-2xs text-signal-deny">
            Nodes participating in a cycle: {validation.ids.join(', ')}
          </p>
        </div>
      ) : null}

      {query.isLoading ? (
        <Skeleton className="h-[70vh]" rounded="md" />
      ) : query.isError ? (
        <div className="rounded-md border border-signal-deny/30 bg-signal-deny/5 p-6">
          <StatusPill tone="failed">backend error</StatusPill>
          <p className="mt-2 font-mono text-2xs text-signal-deny">
            {query.error?.message}
          </p>
        </div>
      ) : !query.data || query.data.nodes.length === 0 ? (
        <EmptyState
          title="No topology recorded for this tenant."
          description="The backend's coordination substrate emits topology on first admission. Connect channels and configure agents to begin."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <section
            aria-label="Topology canvas"
            className="dot-grid h-[70vh] rounded-md border border-line bg-bg-inset shadow-card overflow-hidden"
          >
            <TopologyCanvas
              graph={query.data}
              onSelectNode={handleSelectNode}
              onSelectEdge={handleSelectEdge}
            />
          </section>

          <aside className="space-y-3">
            <div className="rounded-md border border-line bg-bg-inset p-4 shadow-card">
              <p className="text-mono text-fg-dim">graph</p>
              <p className="mt-1 font-display text-2xl text-fg">
                {summary?.nodes ?? 0} nodes
              </p>
              <p className="font-mono text-2xs text-fg-subtle">
                {summary?.edges ?? 0} edges \u00b7 v{summary?.version}
              </p>
              <p className="mt-1 font-mono text-2xs text-fg-dim">
                observed {summary?.observedAt}
              </p>
            </div>
            <div className="rounded-md border border-line bg-bg-inset p-4 shadow-card">
              <p className="text-mono text-fg-dim">authority</p>
              <p className="mt-1 text-2xs text-fg-subtle">
                The frontend visualises authority; the backend owns it. Cycles
                are rejected by backend admission; the validate button here is
                a courtesy preview only.
              </p>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

const NodeConfigView = ({ node }: { node: TopologyNodeDto }) => (
  <div className="space-y-4">
    <div className="grid grid-cols-2 gap-2 text-mono text-fg-subtle">
      <span>kind \u00b7 {node.kind}</span>
      <span>scope \u00b7 {node.tenantScope ?? 'unscoped'}</span>
      {node.agentId ? (
        <span className="col-span-2 truncate">
          agent \u00b7 {node.agentId as unknown as string}
        </span>
      ) : null}
    </div>
    <section>
      <p className="mb-2 text-mono text-fg-dim">capabilities &amp; constraints</p>
      <pre className="rounded-sm border border-line bg-bg p-3 font-mono text-2xs text-fg-muted">
        {JSON.stringify(node.metadata, null, 2)}
      </pre>
    </section>
    <p className="text-2xs text-fg-subtle">
      Edits to capabilities, governance constraints, retry policy and
      arbitration precedence flow through governed backend mutations. The
      frontend never edits topology in place.
    </p>
  </div>
);
