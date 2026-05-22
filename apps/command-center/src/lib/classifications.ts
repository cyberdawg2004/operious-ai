import type {
  EscalationClassification,
  QueueItemStatus,
  TraceNodeKind,
} from '@operious/types';
import type { StatusTone } from '@/components/ui/status-pill';
import type { SubstrateKind } from '@/components/ui/substrate-dot';

export const classificationTone: Record<EscalationClassification, StatusTone> = {
  governance_deny: 'denied',
  governance_require_approval: 'pending',
  arbitration_deadlock: 'denied',
  arbitration_inconclusive: 'pending',
  topology_boundary_violation: 'denied',
  topology_depth_exceeded: 'pending',
  session_human_handoff: 'pending',
};

export const classificationLabel: Record<EscalationClassification, string> = {
  governance_deny: 'Governance Deny',
  governance_require_approval: 'Require Approval',
  arbitration_deadlock: 'Arbitration Deadlock',
  arbitration_inconclusive: 'Inconclusive',
  topology_boundary_violation: 'Boundary Violation',
  topology_depth_exceeded: 'Depth Exceeded',
  session_human_handoff: 'Human Handoff',
};

export const statusTone: Record<QueueItemStatus, StatusTone> = {
  open: 'open',
  claimed: 'info',
  actioned: 'completed',
  deferred: 'pending',
  archived: 'neutral',
};

export const statusLabel: Record<QueueItemStatus, string> = {
  open: 'Open',
  claimed: 'Claimed',
  actioned: 'Actioned',
  deferred: 'Deferred',
  archived: 'Archived',
};

export const traceKindSubstrate: Record<TraceNodeKind, SubstrateKind> = {
  session_timeline_event: 'session',
  governance_trace: 'governance',
  agent_execution_trace: 'execution',
  arbitration_decision: 'arbitration',
  topology_evaluation: 'coordination',
  boundary_ingress: 'boundary',
  boundary_egress: 'boundary',
  translation: 'hardening',
  voice: 'hardening',
};

export const traceKindLabel: Record<TraceNodeKind, string> = {
  session_timeline_event: 'Session',
  governance_trace: 'Governance',
  agent_execution_trace: 'Execution',
  arbitration_decision: 'Arbitration',
  topology_evaluation: 'Coordination',
  boundary_ingress: 'Boundary In',
  boundary_egress: 'Boundary Out',
  translation: 'Translation',
  voice: 'Voice',
};

/** Relative time, deterministic to a 5-second tick. */
export const relativeTime = (iso: string, now: Date = new Date()): string => {
  const observed = new Date(iso);
  const diffMs = Math.max(0, now.getTime() - observed.getTime());
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ${min % 60}m`;
  const day = Math.floor(hr / 24);
  return `${day}d ${hr % 24}h`;
};
