'use client';

import { useMemo, type ReactNode } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  type Edge,
  type Node,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { TopologyEdgeDto, TopologyGraphDto, TopologyNodeDto } from '@operious/types';
import { layoutTopology } from './layout';
import { TopologyNode } from './node';

interface TopologyCanvasProps {
  readonly graph: TopologyGraphDto;
  readonly onSelectNode?: (node: TopologyNodeDto) => void;
  readonly onSelectEdge?: (edge: TopologyEdgeDto) => void;
  readonly emptyState?: ReactNode;
}

const nodeTypes: NodeTypes = {
  operiousNode: TopologyNode,
};

/**
 * Topology inspection canvas — read-only React Flow.
 *
 * `nodesDraggable` and `nodesConnectable` are hard-disabled. The canvas is
 * purely visualization; any operator who wants to mutate topology must do so
 * through governed backend channels.
 */
export const TopologyCanvas = ({
  graph,
  onSelectNode,
  onSelectEdge,
  emptyState,
}: TopologyCanvasProps) => {
  const { nodes, edges } = useMemo(() => {
    const positioned = layoutTopology(graph);
    const flowNodes: Node[] = positioned.nodes.map((node) => ({
      id: node.id,
      type: 'operiousNode',
      position: { x: node.position.x, y: node.position.y },
      data: node.data as unknown as Record<string, unknown>,
      draggable: false,
      selectable: true,
    }));
    const flowEdges: Edge[] = positioned.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      animated: false,
      data: edge.data as unknown as Record<string, unknown>,
      style: { stroke: '#2a3140', strokeWidth: 1 },
    }));
    return { nodes: flowNodes, edges: flowEdges };
  }, [graph]);

  if (graph.nodes.length === 0 && emptyState) {
    return <>{emptyState}</>;
  }

  return (
    <div className="h-full w-full bg-bg-inset">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
        fitView
        onNodeClick={(_, n) => onSelectNode?.(n.data as unknown as TopologyNodeDto)}
        onEdgeClick={(_, e) => onSelectEdge?.(e.data as unknown as TopologyEdgeDto)}
      >
        <Background gap={32} size={1} color="#1a1f29" />
        <Controls
          showInteractive={false}
          className="!bg-bg-raised !border !border-line"
        />
      </ReactFlow>
    </div>
  );
};
