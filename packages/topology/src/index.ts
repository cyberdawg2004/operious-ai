/**
 * @operious/topology
 *
 * React Flow primitives for visualizing the coordination topology.
 *
 * CRITICAL: this package renders the graph as a STATIC AUTHORITY STRUCTURE.
 * It MUST NEVER:
 *   - support drag-to-reroute (would imply orchestration)
 *   - allow node creation in the canvas (topology is declarative)
 *   - emit "execute" actions on edge selection
 *
 * It only inspects.
 */

export { TopologyCanvas } from './canvas';
export { layoutTopology } from './layout';
export type { TopologyLayoutOptions } from './layout';
