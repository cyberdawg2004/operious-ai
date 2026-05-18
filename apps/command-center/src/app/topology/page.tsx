'use client';

import { useState } from 'react';
import { useTopologyGraph } from '@operious/sdk';
import { TopologyCanvas } from '@operious/topology';
import {
  Badge,
  Card,
  EnvelopeRenderer,
  JsonInspector,
} from '@operious/ui';
import type { TopologyEdgeDto, TopologyNodeDto } from '@operious/types';
import { useLocale } from '@/locale/provider';

export default function TopologyPage() {
  const { t } = useLocale();
  const query = useTopologyGraph();
  const [selectedNode, setSelectedNode] = useState<TopologyNodeDto | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<TopologyEdgeDto | null>(null);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-mono text-fg-subtle">/ topology &amp; governance</p>
        <h1 className="font-display text-3xl text-fg">{t.topology.title}</h1>
        <p className="max-w-3xl text-sm text-fg-muted">{t.topology.description}</p>
      </header>

      <EnvelopeRenderer
        status={query.isLoading ? 'pending' : query.isError ? 'error' : 'ok'}
        value={query.data}
        error={
          query.error
            ? { code: 'sdk_error', message: query.error.message }
            : undefined
        }
      >
        {(graph) => (
          <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
            <Card tone="inset" className="h-[640px] p-0 overflow-hidden">
              <TopologyCanvas
                graph={graph}
                onSelectNode={(node) => {
                  setSelectedNode(node);
                  setSelectedEdge(null);
                }}
                onSelectEdge={(edge) => {
                  setSelectedEdge(edge);
                  setSelectedNode(null);
                }}
              />
            </Card>
            <aside className="space-y-4">
              <Card tone="default" className="space-y-2">
                <p className="text-mono text-fg-subtle">graph</p>
                <p className="font-display text-lg text-fg">
                  {graph.nodes.length} nodes · {graph.edges.length} edges
                </p>
                <p className="text-2xs text-fg-muted font-mono">
                  version {graph.version} · {graph.observedAt}
                </p>
              </Card>
              {selectedNode ? (
                <Card tone="default" className="space-y-3">
                  <Badge tone="pending">node inspection</Badge>
                  <p className="font-display text-lg text-fg">{selectedNode.label}</p>
                  <p className="text-mono text-fg-subtle">
                    kind: {selectedNode.kind}
                  </p>
                  {selectedNode.tenantScope ? (
                    <p className="text-mono text-fg-subtle">
                      scope: {selectedNode.tenantScope}
                    </p>
                  ) : null}
                  <JsonInspector value={selectedNode.metadata} />
                </Card>
              ) : selectedEdge ? (
                <Card tone="default" className="space-y-3">
                  <Badge tone="info">edge inspection</Badge>
                  <p className="font-display text-lg text-fg">
                    {selectedEdge.kind.replace(/_/g, ' ')}
                  </p>
                  <p className="text-mono text-fg-subtle">
                    {selectedEdge.source as unknown as string} →{' '}
                    {selectedEdge.target as unknown as string}
                  </p>
                  <JsonInspector value={selectedEdge.metadata} />
                </Card>
              ) : (
                <Card tone="inset" className="text-mono text-fg-subtle">
                  {t.topology.inspectionEmpty}
                </Card>
              )}
              <Card tone="inset" className="text-mono text-fg-subtle">
                {t.common.authorityNotice}
              </Card>
            </aside>
          </div>
        )}
      </EnvelopeRenderer>
    </div>
  );
}
