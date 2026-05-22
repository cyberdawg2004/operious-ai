import { Reveal } from '../ui/reveal';
import { SectionLabel } from '../ui/section-label';

interface Column {
  readonly heading: string;
  readonly subtitle: string;
  readonly body: string;
  readonly resolution: string;
  readonly icon: 'warning' | 'silhouette' | 'fracture';
}

const COLUMNS: ReadonlyArray<Column> = [
  {
    heading: 'The Improvisation Risk',
    subtitle: 'Workflows that improvise create liability.',
    body: 'Language models trained to be helpful will exceed authorized parameters under pressure — granting refunds beyond limit, approving exceptions outside policy, generating commitments the organization did not authorize. Without mathematical boundaries, helpfulness becomes exposure.',
    resolution: 'Resolved through Governance Substrate enforcement.',
    icon: 'warning',
  },
  {
    heading: 'The Knowledge Loss Problem',
    subtitle: 'Institutional knowledge that lives in people is lost when they leave.',
    body: 'The most effective operational workflows are discovered by frontline practitioners and never formally captured. When that person leaves, the organization restarts from documented baseline. Years of refinement disappear quarterly.',
    resolution: 'Resolved through Organizational Cognition Engine.',
    icon: 'silhouette',
  },
  {
    heading: 'The Forensic Audit Failure',
    subtitle: 'Decisions that cannot be reconstructed cannot be defended.',
    body: 'Regulators, auditors, and litigation increasingly demand deterministic reconstruction of automated decisions. Most AI systems cannot prove what context produced a specific output. That gap is becoming legally untenable.',
    resolution: 'Resolved through Operational Event Fabric and replay-safe lineage.',
    icon: 'fracture',
  },
];

const Glyph = ({ kind }: { readonly kind: Column['icon'] }) => {
  if (kind === 'warning') {
    return (
      <svg width="40" height="46" viewBox="0 0 40 46" aria-hidden>
        <polygon
          points="20,2 38,12 38,34 20,44 2,34 2,12"
          fill="none"
          stroke="#A8882C"
          strokeWidth="1.4"
        />
        <line x1="20" y1="14" x2="20" y2="26" stroke="#A8882C" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="20" cy="32" r="1.4" fill="#A8882C" />
      </svg>
    );
  }
  if (kind === 'silhouette') {
    return (
      <svg width="40" height="46" viewBox="0 0 40 46" aria-hidden>
        <defs>
          <linearGradient id="fade-silh" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#A8882C" stopOpacity="1" />
            <stop offset="100%" stopColor="#A8882C" stopOpacity="0" />
          </linearGradient>
        </defs>
        <circle cx="20" cy="14" r="6" fill="none" stroke="url(#fade-silh)" strokeWidth="1.4" />
        <path
          d="M6 44c0-9 6-16 14-16s14 7 14 16"
          fill="none"
          stroke="url(#fade-silh)"
          strokeWidth="1.4"
        />
      </svg>
    );
  }
  return (
    <svg width="40" height="46" viewBox="0 0 40 46" aria-hidden>
      <path d="M6 16h10l4-4 4 4h10" fill="none" stroke="#A8882C" strokeWidth="1.4" />
      <path d="M6 32h10l4-4 4 4h10" fill="none" stroke="#A8882C" strokeWidth="1.4" />
      <line x1="20" y1="14" x2="22" y2="20" stroke="#A8882C" strokeWidth="1.4" />
      <line x1="20" y1="32" x2="18" y2="26" stroke="#A8882C" strokeWidth="1.4" />
    </svg>
  );
};

/**
 * SECTION 2 — THE OPERATIONAL TRUST PROBLEM  (light canvas)
 *
 * Three columns, top-aligned. Reveal stagger: 0ms / 150ms / 300ms.
 * Column heading uses the heading-l Cormorant scale (≥ 28px).
 */
export const ProblemSection = () => (
  <section id="problem" className="relative grain-light bg-canvas">
    <div className="mx-auto max-w-hero px-6 py-40 md:px-16">
      <Reveal>
        <SectionLabel index="01">THE PROBLEM</SectionLabel>
      </Reveal>
      <Reveal delay={120}>
        <h2 className="heading-xl text-ink-primary mt-6 max-w-3xl">
          Enterprise operations were never built for autonomy.
        </h2>
      </Reveal>
      <Reveal delay={240}>
        <p className="body-l text-ink-body mt-6 max-w-prose">
          For decades, mission-critical operational workflows have depended on
          human improvisation, undocumented knowledge, and audit trails that
          exist only in case management software. Generative AI promised
          automation but introduced three new failure modes that are
          structurally incompatible with regulated enterprise environments.
        </p>
      </Reveal>

      <div className="mt-20 grid gap-12 md:grid-cols-3">
        {COLUMNS.map((column, i) => (
          <Reveal
            key={column.heading}
            delay={i * 150}
            className="space-y-5"
          >
            <Glyph kind={column.icon} />
            <p className="eyebrow text-ink-tertiary">{column.heading}</p>
            <h3 className="heading-l text-ink-primary">{column.subtitle}</h3>
            <p className="body-m text-ink-body">{column.body}</p>
            <p className="body-s text-gold italic pt-2">{column.resolution}</p>
          </Reveal>
        ))}
      </div>
    </div>
  </section>
);

export default ProblemSection;
