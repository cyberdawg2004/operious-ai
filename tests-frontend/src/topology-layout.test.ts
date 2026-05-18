import { test } from 'node:test';
import { strictEqual, deepStrictEqual } from 'node:assert';

import { layoutTopology } from '../../packages/topology/src/layout.js';
import type { TopologyGraphDto } from '../../packages/types/src/index.js';

const sampleGraph: TopologyGraphDto = {
  observedAt: '2026-05-15T10:00:00Z',
  version: 'v1',
  nodes: [
    { nodeId: 'b' as never, kind: 'agent', label: 'b-agent', metadata: {} },
    { nodeId: 'a' as never, kind: 'agent', label: 'a-agent', metadata: {} },
    {
      nodeId: 'c' as never,
      kind: 'supervisor',
      label: 'c-supervisor',
      metadata: {},
    },
  ],
  edges: [
    {
      edgeId: 'eb' as never,
      kind: 'coordination',
      source: 'b' as never,
      target: 'a' as never,
      metadata: {},
    },
    {
      edgeId: 'ea' as never,
      kind: 'coordination',
      source: 'a' as never,
      target: 'b' as never,
      metadata: {},
    },
  ],
};

test('layoutTopology produces deterministic node ordering', () => {
  const a = layoutTopology(sampleGraph);
  const b = layoutTopology(sampleGraph);
  deepStrictEqual(
    a.nodes.map((n) => n.id),
    b.nodes.map((n) => n.id),
  );
  deepStrictEqual(
    a.edges.map((e) => e.id),
    b.edges.map((e) => e.id),
  );
});

test('layoutTopology assigns deterministic positions', () => {
  const { nodes } = layoutTopology(sampleGraph);
  // Same kind goes on same row; alphabetical labels assigned column 0,1
  const supervisor = nodes.find((n) => n.id === 'c');
  const agentA = nodes.find((n) => n.id === 'a');
  const agentB = nodes.find((n) => n.id === 'b');
  strictEqual(supervisor?.position.y, 0);
  strictEqual(agentA?.position.y, 140);
  strictEqual(agentB?.position.y, 140);
  strictEqual(agentA?.position.x !== agentB?.position.x, true);
});
