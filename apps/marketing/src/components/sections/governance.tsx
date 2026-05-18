import { SectionShell } from '@/components/section-shell';
import { Badge } from '@operious/ui';

export const GovernanceSection = () => (
  <SectionShell
    id="governance"
    eyebrow="Governance & Explainability"
    title={
      <>
        Every operational decision,
        <br />
        <span className="text-fg-muted">explainable on demand.</span>
      </>
    }
    description="Governance is its own substrate. It evaluates pre-request, pre-retrieval, post-retrieval, pre-grounding, pre-execution, and post-execution. Every verdict is recorded as an immutable trace with violations, restrictions, and authority precedence."
  >
    <div className="grid gap-6 md:grid-cols-2">
      <div className="surface-raised rounded-md p-6 space-y-4">
        <p className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
          Authority precedence
        </p>
        <ol className="space-y-2 text-sm">
          {[
            'GOVERNANCE',
            'TOPOLOGY',
            'POLICY',
            'ARBITRATION',
            'SUPERVISOR',
            'EXECUTION',
          ].map((authority, index) => (
            <li
              key={authority}
              className="flex items-center justify-between rounded-sm border border-line bg-bg-inset px-3 py-2 font-mono text-2xs uppercase tracking-wider text-fg"
            >
              <span>{authority}</span>
              <span className="text-fg-subtle">precedence {index + 1}</span>
            </li>
          ))}
        </ol>
      </div>
      <div className="surface-raised rounded-md p-6 space-y-4">
        <p className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
          Verdict vocabulary
        </p>
        <div className="flex flex-wrap gap-2">
          {(
            [
              ['allow', 'allow'],
              ['escalate', 'escalate'],
              ['escalate', 'require_approval'],
              ['escalate', 'degrade'],
              ['deny', 'redact'],
              ['deny', 'deny'],
            ] as const
          ).map(([tone, label]) => (
            <Badge key={label} tone={tone}>
              {label}
            </Badge>
          ))}
        </div>
        <p className="text-sm text-fg-muted">
          Verdicts are most-restrictive-wins — never majority voting.
          Arbitration <em>interprets</em> conflicts; it does not autonomously resolve them.
        </p>
      </div>
    </div>
  </SectionShell>
);
