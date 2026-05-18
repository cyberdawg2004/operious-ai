'use client';

import { Handle, Position } from '@xyflow/react';
import type { TopologyNodeDto } from '@operious/types';
import { Badge, type BadgeTone } from '@operious/ui';

const kindTone: Record<TopologyNodeDto['kind'], BadgeTone> = {
  agent: 'info',
  supervisor: 'pending',
  governance_domain: 'escalate',
  authority_boundary: 'deny',
  escalation_target: 'escalate',
};

const kindLabel: Record<TopologyNodeDto['kind'], string> = {
  agent: 'agent',
  supervisor: 'supervisor',
  governance_domain: 'governance',
  authority_boundary: 'boundary',
  escalation_target: 'escalation',
};

export const TopologyNode = ({ data }: { data: unknown }) => {
  const node = data as TopologyNodeDto;
  return (
    <div
      className="rounded-md border border-line bg-bg-raised px-3 py-2 min-w-[160px] shadow-raised"
      style={{ width: 200 }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: '#2a3140', width: 6, height: 6 }}
      />
      <div className="flex items-center justify-between gap-2">
        <Badge tone={kindTone[node.kind]}>{kindLabel[node.kind]}</Badge>
      </div>
      <p className="mt-1 font-display text-sm text-fg truncate">{node.label}</p>
      {node.tenantScope ? (
        <p className="text-mono text-fg-subtle truncate">{node.tenantScope}</p>
      ) : null}
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: '#2a3140', width: 6, height: 6 }}
      />
    </div>
  );
};
