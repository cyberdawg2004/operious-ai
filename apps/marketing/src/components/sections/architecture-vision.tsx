import { SectionShell } from '@/components/section-shell';

const SUBSTRATES = [
  {
    name: 'Memory & RAG',
    description: 'Governed memory artifacts. Retrieval that respects authority.',
  },
  {
    name: 'Governance',
    description: 'Operational restrictions, compliance, and explicit precedence.',
  },
  {
    name: 'Coordination',
    description: 'Deterministic communication envelopes. No ad-hoc agent calls.',
  },
  {
    name: 'Topology',
    description: 'Static authorized paths. Bounded coordination chains.',
  },
  {
    name: 'Arbitration',
    description: 'Conflict interpretation, never autonomous resolution.',
  },
  {
    name: 'Boundary',
    description: 'External chaos isolated. Idempotent, replay-safe ingestion.',
  },
  {
    name: 'Session',
    description: 'Append-only continuity ledger. Reconstructible operational history.',
  },
  {
    name: 'Organizational Intelligence',
    description: 'Governed memory evolution. Approvals are human authority.',
  },
];

export const ArchitectureVisionSection = () => (
  <SectionShell
    id="architecture"
    eyebrow="Architecture Vision"
    title={
      <>
        Eleven substrates.
        <br />
        <span className="text-fg-muted">One governing law.</span>
      </>
    }
    description="Inside Operious, every substrate has singular semantic authority. Runtime stays deterministic. Intelligence evolves only through governed asynchronous memory evolution. The two layers never merge."
  >
    <div className="grid gap-px overflow-hidden rounded-md border border-line bg-line md:grid-cols-2 lg:grid-cols-4">
      {SUBSTRATES.map((substrate) => (
        <div key={substrate.name} className="bg-bg-raised p-6">
          <p className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
            substrate
          </p>
          <h3 className="mt-2 font-display text-xl text-fg">{substrate.name}</h3>
          <p className="mt-3 text-sm text-fg-muted">{substrate.description}</p>
        </div>
      ))}
    </div>
  </SectionShell>
);
