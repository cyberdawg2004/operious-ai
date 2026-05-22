import { CountUp } from '../ui/count-up';
import { Reveal } from '../ui/reveal';
import { SectionLabel } from '../ui/section-label';

interface Guarantee {
  readonly value: string;
  readonly numeric?: number;
  readonly explanation: string;
}

const GUARANTEES: ReadonlyArray<Guarantee> = [
  {
    value: '1,927',
    numeric: 1927,
    explanation: 'Deterministic invariant tests enforce the substrate doctrine.',
  },
  {
    value: '100%',
    explanation: 'Replay fidelity for every operational decision.',
  },
  {
    value: 'Zero',
    explanation: 'Substrate isolation violations across the codebase.',
  },
  {
    value: 'UUID5',
    explanation: 'Cryptographic identity for every event in lineage.',
  },
];

/**
 * SECTION 6 — TRUST AND PROOF  (dark canvas)
 *
 * Four numerical statements in a grid. Numerics count up from zero
 * with a stable tabular-nums width (no layout shift).
 *
 * Closing italic editorial line in gold-highlight.
 */
export const TrustSection = () => (
  <section
    id="trust"
    className="relative ambient-dark overflow-hidden bg-dark-canvas text-dark-ink"
  >
    <div className="relative mx-auto max-w-hero px-6 py-40 md:px-16">
      <Reveal>
        <SectionLabel index="05" tone="dark">
          GUARANTEES
        </SectionLabel>
      </Reveal>
      <Reveal delay={120}>
        <h2 className="heading-xl text-dark-ink mt-6 max-w-4xl">
          Mathematical guarantees, not marketing claims.
        </h2>
      </Reveal>

      <div className="mt-16 grid gap-px overflow-hidden rounded-md border border-dark-line bg-dark-line sm:grid-cols-2">
        {GUARANTEES.map((g, i) => (
          <Reveal
            key={g.value}
            delay={i * 100}
            className="space-y-4 bg-dark-surface px-8 py-12"
          >
            <p className="data-l text-gold-highlight text-[clamp(2.75rem,5vw,4.25rem)] leading-none">
              {g.numeric ? <CountUp value={g.numeric} /> : g.value}
            </p>
            <p className="heading-m italic text-dark-ink max-w-md leading-snug">
              {g.explanation}
            </p>
          </Reveal>
        ))}
      </div>

      <Reveal delay={400} className="mt-16">
        <p className="heading-l italic text-gold-highlight max-w-3xl leading-snug">
          “Determinism is the precondition for trust. We refuse to ship
          anything that cannot be reconstructed.”
        </p>
      </Reveal>
    </div>
  </section>
);

export default TrustSection;
