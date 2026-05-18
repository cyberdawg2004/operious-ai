import type {
  TopologyEdgeDto,
  TopologyGraphDto,
  TopologyNodeDto,
} from '@operious/types';
import { stableSortBy } from '@operious/shared';

export interface TopologyLayoutOptions {
  readonly columnWidth?: number;
  readonly rowHeight?: number;
  readonly originX?: number;
  readonly originY?: number;
}

export interface PositionedNode {
  readonly id: string;
  readonly position: { readonly x: number; readonly y: number };
  readonly data: TopologyNodeDto;
}

export interface PositionedEdge {
  readonly id: string;
  readonly source: string;
  readonly target: string;
  readonly data: TopologyEdgeDto;
}

const kindRow: Record<TopologyNodeDto['kind'], number> = {
  agent: 1,
  supervisor: 0,
  governance_domain: 0,
  authority_boundary: 2,
  escalation_target: 0,
};

/**
 * Deterministic, dependency-free layout.
 *
 * We do NOT use a force-directed layout because force layouts are
 * non-deterministic across renders. Operations operators must see the same
 * topology in the same place every time — replay safety extends to layout.
 *
 * Strategy:
 *   - bucket nodes by kind into rows
 *   - sort each row alphabetically by node id
 *   - place each node at deterministic (column, row) coordinates
 */
export const layoutTopology = (
  graph: TopologyGraphDto,
  options: TopologyLayoutOptions = {},
): { nodes: PositionedNode[]; edges: PositionedEdge[] } => {
  const columnWidth = options.columnWidth ?? 240;
  const rowHeight = options.rowHeight ?? 140;
  const originX = options.originX ?? 0;
  const originY = options.originY ?? 0;

  const sortedNodes = stableSortBy(
    [...graph.nodes],
    (node) => `${kindRow[node.kind]}:${node.label}:${node.nodeId}`,
  );

  const rowCounters: Record<number, number> = {};
  const positioned: PositionedNode[] = sortedNodes.map((node) => {
    const row = kindRow[node.kind];
    const column = rowCounters[row] ?? 0;
    rowCounters[row] = column + 1;
    return {
      id: node.nodeId as unknown as string,
      position: {
        x: originX + column * columnWidth,
        y: originY + row * rowHeight,
      },
      data: node,
    };
  });

  const sortedEdges = stableSortBy(
    [...graph.edges],
    (edge) =>
      `${edge.kind}:${edge.source as unknown as string}:${edge.target as unknown as string}:${
        edge.edgeId as unknown as string
      }`,
  );

  const edges: PositionedEdge[] = sortedEdges.map((edge) => ({
    id: edge.edgeId as unknown as string,
    source: edge.source as unknown as string,
    target: edge.target as unknown as string,
    data: edge,
  }));

  return { nodes: positioned, edges };
};
