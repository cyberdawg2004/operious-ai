import { SectionShell } from '@/components/section-shell';
import { Badge } from '@operious/ui';

const MODULES = [
  {
    name: 'Operations Queue',
    summary:
      'The human authority recovery surface. Escalated sessions, denied governance verdicts, arbitration deadlocks, topology escalations — all in one inspectable queue.',
    badges: ['escalated session', 'governance deny', 'arbitration deadlock'],
  },
  {
    name: 'Trace Inspector',
    summary:
      'Forensic decision explainability. SessionTimelineEvents, GovernanceTrace, AgentExecutionTrace, and lineage chronology rendered deterministically.',
    badges: ['session timeline', 'governance trace', 'replay digest'],
  },
  {
    name: 'Cognition Hub',
    summary:
      'Governed organizational evolution. Memory proposals, SOP evolution, recommendation review, approval workflows. The frontend never auto-approves.',
    badges: ['memory proposal', 'SOP evolution', 'pending approval'],
  },
  {
    name: 'Topology & Governance',
    summary:
      'Visual cognition topology. Agents, coordination edges, authority boundaries, governance attachments. Inspection only — never orchestration.',
    badges: ['authority boundary', 'coordination edge', 'governance domain'],
  },
];

export const CommandCenterPreviewSection = () => (
  <SectionShell
    id="command-center"
    eyebrow="Command Center"
    title={
      <>
        Inspect every operational decision.
        <br />
        <span className="text-fg-muted">Authorize through governed channels.</span>
      </>
    }
    description="The Command Center is the operational cognition dashboard for your enterprise. It is a visualization layer — not an orchestration authority. Every mutation it surfaces is gated by backend governance."
  >
    <div className="grid gap-6 md:grid-cols-2">
      {MODULES.map((module) => (
        <article key={module.name} className="surface-raised rounded-md p-6 space-y-3">
          <p className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
            module
          </p>
          <h3 className="font-display text-2xl text-fg">{module.name}</h3>
          <p className="text-sm text-fg-muted">{module.summary}</p>
          <div className="flex flex-wrap gap-2 pt-2">
            {module.badges.map((badge) => (
              <Badge key={badge} tone="info">
                {badge}
              </Badge>
            ))}
          </div>
        </article>
      ))}
    </div>
  </SectionShell>
);
