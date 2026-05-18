import { SectionShell } from '@/components/section-shell';
import { Code } from '@operious/ui';

export const DeterministicInfrastructureSection = () => (
  <SectionShell
    id="deterministic"
    eyebrow="Deterministic Infrastructure"
    title={
      <>
        Replayable.
        <br />
        <span className="text-fg-muted">Down to the byte.</span>
      </>
    }
    description="Operious never silently retries. It never re-executes operational behavior to recover state. Replay is historical reconstruction — not redo. Every artifact carries lineage, every lineage is byte-equivalent, every reconstruction is provable."
  >
    <div className="grid items-stretch gap-6 lg:grid-cols-[1.1fr_1fr]">
      <div className="surface-raised rounded-md p-6 space-y-3">
        <p className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
          Core Invariants
        </p>
        <ul className="space-y-3 text-sm text-fg">
          {[
            'Deterministic ordering across every substrate',
            'Immutable runtime artifacts — no in-place mutation',
            'Replay-safe canonicalization for content fingerprinting',
            'Lineage continuity preserved across every authority transition',
            'Substrate isolation enforced by import-graph invariants',
            '"Never raises" public API discipline — envelopes, not exceptions',
          ].map((line) => (
            <li
              key={line}
              className="flex items-start gap-2 border-b border-line/60 pb-3 last:border-b-0 last:pb-0"
            >
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent" />
              <span>{line}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="surface-raised rounded-md p-6 space-y-3">
        <p className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
          Trace envelope · canonicalised
        </p>
        <Code tone="block">
{`{
  "correlationId": "8e2f...c401",
  "lineage": {
    "sequence": 12,
    "parentCorrelationId": "8e2f...c0fe",
    "observedAt": "2026-05-15T12:34:56Z"
  },
  "kind": "governance_trace",
  "decision": "require_approval",
  "stage": "pre_execution",
  "violations": [],
  "restrictions": [
    { "kind": "rate_limit", "description": "tenant cap" }
  ],
  "replayDigest": "sha256:7c1a...e92"
}`}
        </Code>
      </div>
    </div>
  </SectionShell>
);
