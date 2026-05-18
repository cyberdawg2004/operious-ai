import { SectionShell } from '@/components/section-shell';

export const CognitionNarrativeSection = () => (
  <SectionShell
    id="cognition"
    eyebrow="Organizational Cognition"
    title={
      <>
        Your operations don&apos;t need an AI agent.
        <br />
        <span className="text-fg-muted">They need governed memory.</span>
      </>
    }
    description="Most enterprises don&apos;t fail because their AI is too dumb. They fail because their operations layer cannot remember, cannot replay, and cannot prove who decided what. Operious treats organizational cognition as infrastructure: an explicit, governed, append-only continuity ledger that preserves every authority transition."
  >
    <div className="grid gap-6 md:grid-cols-3">
      {[
        {
          eyebrow: 'Interaction',
          headline: 'Captured deterministically',
          body: 'Every customer interaction lands in an immutable session timeline. No silent retries, no implicit transitions, no event spaghetti.',
        },
        {
          eyebrow: 'Evaluation',
          headline: 'Supervised, not autonomous',
          body: 'Supervisors are read-only evaluators. They surface contradictions, classify outcomes, and propose memory candidates. They never mutate operational state.',
        },
        {
          eyebrow: 'Approval',
          headline: 'Human authority is final',
          body: 'Memory evolution proposals are gated by explicit approval workflows. Operious never auto-rewrites SOPs, governance, or operational policy.',
        },
      ].map((card) => (
        <div
          key={card.eyebrow}
          className="surface-raised rounded-md p-6 space-y-3"
        >
          <p className="font-mono text-2xs uppercase tracking-widest text-accent">
            {card.eyebrow}
          </p>
          <h3 className="font-display text-xl text-fg">{card.headline}</h3>
          <p className="text-sm text-fg-muted">{card.body}</p>
        </div>
      ))}
    </div>
  </SectionShell>
);
