'use client';

import Link from 'next/link';
import {
  motion as fm,
  useScroll,
  useTransform,
  useReducedMotion,
} from 'framer-motion';
import { useRef } from 'react';
import { Reveal } from '../ui/reveal';
import { SectionLabel } from '../ui/section-label';

interface Surface {
  readonly id: string;
  readonly name: string;
  readonly subtitle: string;
  readonly body: string;
  readonly cta: string;
  readonly mockup: 'command' | 'trace' | 'cognition';
}

const SURFACES: ReadonlyArray<Surface> = [
  {
    id: 'command-center',
    name: 'COMMAND CENTER',
    subtitle: 'The operator surface.',
    body: 'A formal operational dashboard for managers, auditors, and compliance officers. Review escalations, inspect forensic traces, approve organizational knowledge proposals, and configure agent topology — all from a single tenant-scoped interface.',
    cta: 'Explore the Command Center',
    mockup: 'command',
  },
  {
    id: 'trace-inspector',
    name: 'TRACE INSPECTOR',
    subtitle: 'Forensic decision reconstruction.',
    body: 'Every operational action emits a canonical event with cryptographic lineage. The Trace Inspector reconstructs any historical decision deterministically — proving exactly which policy chain applied, which knowledge source informed the reasoning, and which authority approved the outcome.',
    cta: 'See how replay works',
    mockup: 'trace',
  },
  {
    id: 'cognition-hub',
    name: 'COGNITION HUB',
    subtitle: 'Governed knowledge evolution.',
    body: 'Organizational knowledge improves continuously through observed successful resolutions. Proposals are surfaced to human managers for review and approval — never auto-applied. Every knowledge version is versioned, attributed, and reversible.',
    cta: 'Read the cognition doctrine',
    mockup: 'cognition',
  },
];

const Mockup = ({ kind }: { readonly kind: Surface['mockup'] }) => {
  const base =
    'rounded-md border border-dark-line bg-dark-surface text-dark-ink p-5 shadow-dropdown';
  if (kind === 'command') {
    return (
      <div className={base}>
        <div className="flex items-center gap-2 border-b border-dark-line pb-3">
          <span className="h-2 w-2 rounded-full bg-success" />
          <span className="eyebrow text-dark-ink-muted">
            COMMAND CENTER · TENANT-A1
          </span>
        </div>
        <div className="mt-4 space-y-3 data-s text-dark-ink-muted">
          <div className="flex justify-between"><span>queue · escalations</span><span className="text-gold-highlight">7</span></div>
          <div className="flex justify-between"><span>queue · approvals</span><span className="text-gold-highlight">2</span></div>
          <div className="flex justify-between"><span>traces · today</span><span>1,284</span></div>
          <div className="flex justify-between"><span>policy · pass-rate</span><span className="text-success">99.78%</span></div>
        </div>
        <div className="mt-5 grid grid-cols-3 gap-px bg-dark-line">
          {['allow', 'allow', 'deny'].map((tone, i) => (
            <div
              key={i}
              className="bg-dark-canvas px-2 py-2 data-s uppercase"
              style={{
                color:
                  tone === 'allow'
                    ? '#3aa67c'
                    : tone === 'deny'
                      ? '#cc6464'
                      : '#d6a14a',
              }}
            >
              {tone}
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (kind === 'trace') {
    return (
      <div className={base}>
        <div className="flex items-center gap-2 border-b border-dark-line pb-3">
          <span className="eyebrow text-dark-ink-muted">TRACE · 0a4f-ed8c-…</span>
        </div>
        <ul className="mt-4 space-y-2 data-s text-dark-ink-muted">
          <li className="flex items-center gap-3">
            <span className="h-1.5 w-1.5 rounded-full bg-gold-highlight" />
            <span className="text-dark-ink">ingress</span>
            <span className="ml-auto">+0ms</span>
          </li>
          <li className="flex items-center gap-3">
            <span className="h-1.5 w-1.5 rounded-full bg-gold-highlight" />
            <span className="text-dark-ink">policy.evaluate</span>
            <span className="ml-auto">+12ms</span>
          </li>
          <li className="flex items-center gap-3">
            <span className="h-1.5 w-1.5 rounded-full bg-gold-highlight" />
            <span className="text-dark-ink">arbitration.resolve</span>
            <span className="ml-auto">+38ms</span>
          </li>
          <li className="flex items-center gap-3">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            <span className="text-dark-ink">execution.commit</span>
            <span className="ml-auto">+74ms</span>
          </li>
        </ul>
      </div>
    );
  }
  return (
    <div className={base}>
      <div className="flex items-center gap-2 border-b border-dark-line pb-3">
        <span className="eyebrow text-dark-ink-muted">COGNITION · KNOWLEDGE</span>
      </div>
      <div className="mt-4 space-y-3">
        <div className="rounded-sm border border-dark-line bg-dark-canvas px-3 py-2">
          <p className="eyebrow text-gold-highlight">PROPOSAL · 2026-05-20</p>
          <p className="mt-1 body-s text-dark-ink">
            Update SOP-217 to require dual approval on refunds &gt; threshold-A.
          </p>
        </div>
        <div className="rounded-sm border border-dark-line bg-dark-canvas px-3 py-2">
          <p className="eyebrow text-dark-ink-muted">VERSION · v8 · APPROVED</p>
          <p className="mt-1 body-s text-dark-ink-muted">
            Authored by tenant-A1.ops.lead · ratified by tenant-A1.compliance
          </p>
        </div>
      </div>
    </div>
  );
};

interface SurfaceRowProps {
  readonly surface: Surface;
  readonly flipped: boolean;
}

const SurfaceRow = ({ surface, flipped }: SurfaceRowProps) => {
  const reduceMotion = useReducedMotion() ?? false;
  const rowRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({
    target: rowRef,
    offset: ['start end', 'end start'],
  });
  // Mockup parallax: 0.6× scroll speed (text stays 1.0×).
  const yMockup = useTransform(
    scrollYProgress,
    [0, 1],
    reduceMotion ? ['0px', '0px'] : ['40px', '-40px'],
  );
  const opacityMockup = useTransform(
    scrollYProgress,
    [0, 0.2],
    reduceMotion ? [1, 1] : [0, 1],
  );
  const scaleMockup = useTransform(
    scrollYProgress,
    [0, 0.2],
    reduceMotion ? [1, 1] : [0.95, 1],
  );

  return (
    <div
      ref={rowRef}
      className={[
        'grid items-center gap-12 lg:grid-cols-2 lg:gap-24',
        flipped ? 'lg:[direction:rtl]' : '',
      ].join(' ')}
    >
      <div className="space-y-5 lg:[direction:ltr]">
        <p className="eyebrow text-ink-tertiary">{surface.name}</p>
        <h3 className="heading-l text-ink-primary">{surface.subtitle}</h3>
        <p className="body-m text-ink-body">{surface.body}</p>
        <Link
          href="#contact"
          data-cursor="interactive"
          className="group inline-flex items-center gap-2 body-s text-gold transition-colors hover:text-gold-highlight"
        >
          <span className="editorial-link">{surface.cta}</span>
          <span
            aria-hidden
            className="transition-transform duration-200 group-hover:translate-x-1"
          >
            →
          </span>
        </Link>
      </div>
      <fm.div
        style={{ y: yMockup, opacity: opacityMockup, scale: scaleMockup }}
        className="lg:[direction:ltr]"
      >
        <Mockup kind={surface.mockup} />
      </fm.div>
    </div>
  );
};

/**
 * SECTION 5 — PRODUCT SURFACES  (light canvas)
 *
 * Three stacked product cards. Mockups parallax at 0.6×; text stays still
 * (per spec — text never parallaxes).
 */
export const ProductsSection = () => (
  <section id="products" className="relative grain-light bg-canvas">
    <div className="mx-auto max-w-hero px-6 py-40 md:px-16">
      <Reveal>
        <SectionLabel index="04">PRODUCT</SectionLabel>
      </Reveal>
      <Reveal delay={120}>
        <h2 className="heading-xl text-ink-primary mt-6 max-w-3xl">
          Three interfaces, one substrate.
        </h2>
      </Reveal>

      <div className="mt-20 space-y-24">
        {SURFACES.map((surface, i) => (
          <SurfaceRow key={surface.id} surface={surface} flipped={i % 2 === 1} />
        ))}
      </div>
    </div>
  </section>
);

export default ProductsSection;
