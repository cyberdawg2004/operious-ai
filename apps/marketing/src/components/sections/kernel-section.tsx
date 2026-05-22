'use client';

import {
  motion as fm,
  useScroll,
  useTransform,
  useReducedMotion,
  type MotionValue,
} from 'framer-motion';
import { useRef } from 'react';
import { CountUp } from '../ui/count-up';
import { SectionLabel } from '../ui/section-label';

interface Layer {
  readonly id: string;
  readonly name: string;
  readonly tagline: string;
  readonly detail: string;
  /** Scroll-progress threshold at which this layer illuminates. */
  readonly progress: number;
}

const LAYERS: ReadonlyArray<Layer> = [
  {
    id: 'governance',
    name: 'GOVERNANCE',
    tagline: 'Mathematical policy enforcement',
    detail:
      'The constitutional layer. Every proposed action passes through deterministic policy chains. Empty chains return deny — fail-closed by construction, not configuration.',
    progress: 0.25,
  },
  {
    id: 'topology',
    name: 'TOPOLOGY',
    tagline: 'Authorized agent coordination pathways',
    detail:
      'Coordination graphs are immutable per-tenant. Agents may only invoke peers along pre-declared pathways. Untyped edges are a deployment-time error, not a runtime exception.',
    progress: 0.33,
  },
  {
    id: 'policy',
    name: 'POLICY',
    tagline: 'Capability-gated execution legality',
    detail:
      'Capabilities are bound to authority and tenant. The same agent invocation produces different policy results in different authority contexts — by mathematical contract, not branching logic.',
    progress: 0.42,
  },
  {
    id: 'arbitration',
    name: 'ARBITRATION',
    tagline: 'Deterministic conflict resolution',
    detail:
      'When multiple agents propose contradictory actions, the arbitration substrate selects deterministically by signal precedence — replayable, reviewable, and immune to time-of-day variance.',
    progress: 0.51,
  },
  {
    id: 'execution',
    name: 'EXECUTION',
    tagline: 'Claim-before-run worker sovereignty',
    detail:
      'Every worker claims a unit of work atomically before execution. Claims are revocable, recoverable, and auditable. No action runs without a recorded claim under tenant authority.',
    progress: 0.6,
  },
  {
    id: 'hardening',
    name: 'HARDENING',
    tagline: 'Lineage, replay, and containment invariants',
    detail:
      'Lineage chains are persisted per event. Replay reproduces any historical decision deterministically. Containment invariants prevent cross-tenant authority leakage at compile time.',
    progress: 0.69,
  },
];

const AUTHORITY_LEVELS = [
  { name: 'CONSTITUTION', tone: 'gold' as const },
  { name: 'TENANT', tone: 'gold' as const },
  { name: 'SUBSTRATE', tone: 'gold' as const },
  { name: 'POLICY', tone: 'gold' as const },
  { name: 'AGENT', tone: 'gold' as const },
  { name: 'WORKER', tone: 'dim' as const },
];

/**
 * SECTION 3 — THE OPERATIONAL KERNEL  (dark canvas, signature section)
 *
 * Spec contract: this section must scrub bidirectionally with scroll
 * progress. The substrate stack lights up sequentially as the user
 * descends, and reverses cleanly as the user scrolls back up.
 *
 * Implementation: Framer Motion's `useScroll({ target, offset })` gives
 * us per-section scroll progress without GSAP. The minimum section
 * height is 200vh (per spec) so the choreography breathes.
 *
 * Reduced-motion: substrate stack renders as a static lit list, no
 * scroll binding, no stagger.
 */

interface LayerRowProps {
  readonly layer: Layer;
  readonly index: number;
  readonly progress: MotionValue<number>;
  readonly reduceMotion: boolean;
}

interface AuthorityRowProps {
  readonly name: string;
  readonly tone: 'gold' | 'dim';
  readonly index: number;
  readonly progress: MotionValue<number>;
  readonly reduceMotion: boolean;
}

const AuthorityRow = ({
  name,
  tone,
  index,
  progress,
  reduceMotion,
}: AuthorityRowProps) => {
  const opacity = useTransform(
    progress,
    [0.7 + index * 0.02, 0.74 + index * 0.02],
    reduceMotion ? [1, 1] : [0.2, 1],
  );
  return (
    <fm.li style={{ opacity }} className="flex items-center gap-3">
      <span
        className={[
          'flex h-6 w-6 items-center justify-center rounded-sm border data-s',
          tone === 'gold'
            ? 'border-gold/60 text-gold-highlight'
            : 'border-dark-line-strong text-dark-ink-dim',
        ].join(' ')}
      >
        {String(index + 1).padStart(2, '0')}
      </span>
      <span
        className={[
          'eyebrow',
          tone === 'gold' ? 'text-dark-ink' : 'text-dark-ink-dim',
        ].join(' ')}
      >
        {name}
      </span>
    </fm.li>
  );
};

const BottomStats = ({
  progress,
  reduceMotion,
}: {
  readonly progress: MotionValue<number>;
  readonly reduceMotion: boolean;
}) => {
  const opacity = useTransform(
    progress,
    [0.85, 0.95],
    reduceMotion ? [1, 1] : [0, 1],
  );
  return (
    <fm.div
      style={{ opacity }}
      className="mt-20 grid gap-6 border-t border-dark-line pt-10 sm:grid-cols-3"
    >
      <p className="body-m">
        <CountUp
          value={1927}
          className="data-l text-gold-highlight text-3xl"
        />
        <span className="eyebrow text-dark-ink-muted mt-1 block">
          deterministic tests
        </span>
      </p>
      <p className="body-m">
        <span className="data-l text-gold-highlight text-3xl">0</span>
        <span className="eyebrow text-dark-ink-muted mt-1 block">
          substrate violations
        </span>
      </p>
      <p className="body-m">
        <span className="data-l text-gold-highlight text-3xl">100%</span>
        <span className="eyebrow text-dark-ink-muted mt-1 block">
          replay fidelity
        </span>
      </p>
    </fm.div>
  );
};

const LayerRow = ({ layer, index, progress, reduceMotion }: LayerRowProps) => {
  // Each layer interpolates opacity / x over a small slice of progress
  // starting at its declared threshold and lasting 0.05 progress units.
  const opacity = useTransform(
    progress,
    [layer.progress, layer.progress + 0.05],
    reduceMotion ? [1, 1] : [0.3, 1],
  );
  const x = useTransform(
    progress,
    [layer.progress, layer.progress + 0.05],
    reduceMotion ? [0, 0] : [-4, 0],
  );
  const dotScale = useTransform(
    progress,
    [layer.progress, layer.progress + 0.05],
    reduceMotion ? [1, 1] : [0.6, 1],
  );

  return (
    <fm.li
      style={{ opacity, x }}
      className="relative grid grid-cols-[28px_minmax(0,1fr)] items-stretch gap-4 rounded-md border border-dark-line bg-dark-surface/70 px-5 py-4 backdrop-blur-sm"
    >
      <span className="flex flex-col items-center pt-1">
        <fm.span
          style={{ scale: dotScale }}
          className="block h-2.5 w-2.5 rounded-full bg-gold-highlight"
        />
      </span>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[140px_minmax(0,1fr)] sm:gap-6">
        <p className="eyebrow text-gold">
          <span className="opacity-60">§ {String(index + 1).padStart(2, '0')}</span>
          <span className="mx-2 opacity-40">·</span>
          {layer.name}
        </p>
        <div className="space-y-2">
          <p className="body-s text-dark-ink">{layer.tagline}</p>
          <p className="body-m text-dark-ink-muted">{layer.detail}</p>
        </div>
      </div>
    </fm.li>
  );
};

export const KernelSection = () => {
  const reduceMotion = useReducedMotion() ?? false;
  const sectionRef = useRef<HTMLElement | null>(null);

  // Scrub the section between [start enters viewport bottom] and
  // [end leaves viewport top]. Smoothed with framer's built-in lerp.
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ['start end', 'end start'],
  });

  // Connecting line: draws from 0% (top) → 100% (bottom).
  const linePathLength = useTransform(
    scrollYProgress,
    [0.1, 0.85],
    reduceMotion ? [1, 1] : [0, 1],
  );

  return (
    <section
      id="kernel"
      ref={sectionRef}
      className="relative ambient-dark overflow-hidden bg-dark-canvas text-dark-ink"
      style={{ minHeight: '200vh' }}
    >
      <div className="relative mx-auto max-w-hero px-6 py-32 md:px-16 md:py-40">
        <SectionLabel index="02" tone="dark">
          THE KERNEL
        </SectionLabel>
        <h2 className="heading-xl text-dark-ink mt-6 max-w-4xl">
          An execution substrate, not a chatbot wrapper.
        </h2>
        <p className="body-l text-dark-ink-muted mt-6 max-w-prose">
          Operious is built on a layered operational kernel. Each layer enforces
          a specific constitutional guarantee. Layers are isolated by
          mathematical contract, not convention. Violations break deployment,
          not runtime.
        </p>

        <div className="mt-20 grid gap-12 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="relative">
            {/* Connecting line — gold at top, blue at bottom, draws with scroll. */}
            <svg
              aria-hidden
              className="pointer-events-none absolute left-3 top-3 h-[calc(100%-1.5rem)] w-px"
              viewBox="0 0 1 100"
              preserveAspectRatio="none"
            >
              <defs>
                <linearGradient id="kernel-line" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#A8882C" />
                  <stop offset="100%" stopColor="#1A4A9A" />
                </linearGradient>
              </defs>
              <fm.line
                x1="0.5"
                x2="0.5"
                y1="0"
                y2="100"
                stroke="url(#kernel-line)"
                strokeWidth="1"
                style={{ pathLength: linePathLength }}
              />
            </svg>

            <ol className="space-y-3">
              {LAYERS.map((layer, i) => (
                <LayerRow
                  key={layer.id}
                  layer={layer}
                  index={i}
                  progress={scrollYProgress}
                  reduceMotion={reduceMotion}
                />
              ))}
            </ol>
          </div>

          <aside className="space-y-8">
            <div>
              <p className="eyebrow text-gold">AUTHORITY PRECEDENCE</p>
              <div className="mt-4 rounded-md border border-dark-line bg-dark-surface px-5 py-6">
                <ul className="space-y-3">
                  {AUTHORITY_LEVELS.map((level, i) => (
                    <AuthorityRow
                      key={level.name}
                      name={level.name}
                      tone={level.tone}
                      index={i}
                      progress={scrollYProgress}
                      reduceMotion={reduceMotion}
                    />
                  ))}
                </ul>
                <p className="body-xs text-dark-ink-muted mt-6">
                  Authority cascades downward. A worker cannot override a
                  substrate. A substrate cannot override a tenant. A tenant
                  cannot override the constitution. Precedence is enforced by
                  the type system, validated by the test suite, and persisted
                  in every event envelope.
                </p>
              </div>
            </div>
          </aside>
        </div>

        {/* Bottom stats — fade in 0.85 → 0.95 with scroll. */}
        <BottomStats progress={scrollYProgress} reduceMotion={reduceMotion} />

        {/* Reserve real scrubbable real-estate to keep the section breathable. */}
        <div aria-hidden className="h-[40vh]" />
      </div>
    </section>
  );
};

export default KernelSection;
