import Link from 'next/link';
import { Reveal } from '../ui/reveal';
import { SectionLabel } from '../ui/section-label';

interface Solution {
  readonly label: string;
  readonly body: string;
}

const SOLUTIONS: ReadonlyArray<Solution> = [
  {
    label: 'Hardware & Consumer Electronics',
    body: 'RMA workflows, warranty triage, and refund authorization across multilingual customer touchpoints with cryptographic policy compliance.',
  },
  {
    label: 'Financial Services & Insurance',
    body: 'KYC exception handling, claims triage, dispute resolution, and underwriting workflow exceptions with full audit lineage.',
  },
  {
    label: 'Healthcare Operations',
    body: 'Prior authorization, claims appeals, eligibility verification, and patient intake exception handling within HIPAA-aligned tenant boundaries.',
  },
  {
    label: 'Telecommunications',
    body: 'Service provisioning exceptions, billing dispute resolution, and technical escalation routing with deterministic SLA tracking.',
  },
  {
    label: 'Logistics & Supply Chain',
    body: 'Carrier exception routing, shipment dispute resolution, and customs documentation triage across multi-jurisdictional workflows.',
  },
  {
    label: 'Public Sector Operations',
    body: 'Permit processing exceptions, eligibility determination, and compliance verification with full procedural audit reconstruction.',
  },
];

// 3 × 2 diagonal stagger schedule from the spec.
const STAGGER: ReadonlyArray<number> = [0, 80, 160, 120, 200, 280];

/**
 * SECTION 4 — SOLUTIONS BY DOMAIN  (light canvas, 3×2 grid)
 *
 * Diagonal stagger reveal (top-left → bottom-right). Cards lift on hover
 * with the spec's card-hover shadow + 4px translateY. No border-color
 * transitions (only transform + box-shadow per spec).
 */
export const SolutionsSection = () => (
  <section
    id="solutions"
    className="relative bg-canvas-raised border-y border-line-subtle"
  >
    <div className="mx-auto max-w-hero px-6 py-40 md:px-16">
      <Reveal>
        <SectionLabel index="03">DOMAINS</SectionLabel>
      </Reveal>
      <Reveal delay={120}>
        <h2 className="heading-xl text-ink-primary mt-6 max-w-3xl">
          Built for operationally regulated environments.
        </h2>
      </Reveal>
      <Reveal delay={240}>
        <p className="body-l text-ink-body mt-6 max-w-prose">
          Operious deploys across industries where execution correctness,
          policy compliance, and forensic auditability are non-negotiable.
          Each deployment is tenant-isolated by default. Configuration,
          policies, and knowledge corpus are owned by the customer
          organization, not the platform.
        </p>
      </Reveal>

      <div className="mt-16 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {SOLUTIONS.map((solution, i) => (
          <Reveal
            key={solution.label}
            delay={STAGGER[i] ?? 0}
            className="group flex flex-col justify-between rounded-md border border-line-subtle bg-canvas-surface p-6 transition-[transform,box-shadow] duration-[240ms] ease-[cubic-bezier(0.4,0,0.2,1)] hover:-translate-y-1 hover:shadow-card-hover"
          >
            <div className="space-y-4">
              <p className="eyebrow text-ink-tertiary">
                {solution.label.toUpperCase()}
              </p>
              <p className="body-m text-ink-body">{solution.body}</p>
            </div>
            <Link
              href="#contact"
              data-cursor="interactive"
              className="mt-6 inline-flex items-center gap-2 body-s text-gold transition-colors hover:text-gold-highlight"
            >
              <span className="editorial-link">Learn more</span>
              <span
                aria-hidden
                className="transition-transform duration-200 group-hover:translate-x-1"
              >
                →
              </span>
            </Link>
          </Reveal>
        ))}
      </div>
    </div>
  </section>
);

export default SolutionsSection;
