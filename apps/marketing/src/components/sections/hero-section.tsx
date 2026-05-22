'use client';

import Link from 'next/link';
import { motion as fm, useReducedMotion } from 'framer-motion';
import { useEffect, useMemo, useState } from 'react';
import { KernelSeal } from '../brand/kernel-seal';
import { HexLattice } from '../atmospherics/hex-lattice';
import { HERO_TIMELINE, easings, ms } from '@/lib/motion';

/**
 * SECTION 1 — HERO  (dark canvas, 100vh, frame-by-frame load sequence)
 *
 * Timeline reference (see HERO_TIMELINE in lib/motion.ts):
 *   t = 0      lattice fades in (handled by HexLattice itself)
 *   t = 400    KernelSeal phase 1 (outer ring)
 *   t = 700    KernelSeal phase 2 (inner sigil)
 *   t = 1000   KernelSeal phase 3 (bond)
 *   t = 1100   eyebrow label slides in (x: -8 → 0, 400ms)
 *   t = 1300   headline begins word-by-word reveal (600ms each, stagger 80ms)
 *              ONE word is italicised — the editorial signature.
 *   t = 2000   subhead fades up (y: 16 → 0, 600ms)
 *   t = 2300   primary CTA scales in (0.96 → 1, 400ms)
 *   t = 2400   secondary CTA fades in (300ms)
 *   t = 2600   scroll indicator + pulse
 *
 * Implementation note: a single boot-clock state advances through discrete
 * "tick" labels via setTimeout. Components animate on tick crossings; this
 * avoids the per-frame component re-render that a continuous clock would
 * cause, while keeping every animation observable from one source of truth.
 */

const HEADLINE_PRE = 'Operational infrastructure that cannot';
const HEADLINE_ITALIC = 'deviate.';

type Tick =
  | 'lattice'
  | 'eyebrow'
  | 'headline'
  | 'subhead'
  | 'ctaPrimary'
  | 'ctaSecondary'
  | 'scroll';

const TICK_TIMES: Record<Tick, number> = {
  lattice: HERO_TIMELINE.latticeBegin,
  eyebrow: HERO_TIMELINE.eyebrowIn,
  headline: HERO_TIMELINE.headlineStart,
  subhead: HERO_TIMELINE.subheadIn,
  ctaPrimary: HERO_TIMELINE.ctaPrimaryIn,
  ctaSecondary: HERO_TIMELINE.ctaSecondaryIn,
  scroll: HERO_TIMELINE.scrollIndicatorIn,
};

export const HeroSection = () => {
  const reduceMotion = useReducedMotion() ?? false;
  const [reached, setReached] = useState<Record<Tick, boolean>>(() => ({
    lattice: reduceMotion,
    eyebrow: reduceMotion,
    headline: reduceMotion,
    subhead: reduceMotion,
    ctaPrimary: reduceMotion,
    ctaSecondary: reduceMotion,
    scroll: reduceMotion,
  }));
  // Headline word offsets are derived from a single per-word index, so we
  // only need one extra counter (number of words revealed) to drive the
  // word stagger. This re-renders at the stagger frequency (≈12 Hz max),
  // not every frame.
  const [wordsRevealed, setWordsRevealed] = useState<number>(
    reduceMotion ? 99 : 0,
  );

  useEffect(() => {
    if (reduceMotion) return;
    const timers: number[] = [];

    (Object.entries(TICK_TIMES) as [Tick, number][]).forEach(([key, when]) => {
      timers.push(
        window.setTimeout(() => {
          setReached((prev) => (prev[key] ? prev : { ...prev, [key]: true }));
        }, when),
      );
    });

    const words = HEADLINE_PRE.split(' ').length + 1; // +1 italic
    for (let i = 1; i <= words; i += 1) {
      timers.push(
        window.setTimeout(
          () => setWordsRevealed(i),
          HERO_TIMELINE.headlineStart + i * HERO_TIMELINE.headlineWordStaggerMs,
        ),
      );
    }

    return () => timers.forEach((id) => window.clearTimeout(id));
  }, [reduceMotion]);

  const preWords = useMemo(() => HEADLINE_PRE.split(' '), []);

  return (
    <section
      id="hero"
      className="relative isolate overflow-hidden bg-dark-canvas text-dark-ink"
      style={{ minHeight: '100vh' }}
    >
      <HexLattice />

      <div className="relative z-10 mx-auto flex min-h-[100vh] max-w-hero flex-col px-6 pb-24 pt-32 md:px-16 md:pt-40">
        <div className="grid flex-1 items-center gap-16 lg:grid-cols-[420px_minmax(0,1fr)] lg:gap-24">
          {/* KernelSeal — 280px per spec, -20px optical compensation. */}
          <fm.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: ms(400), delay: ms(100), ease: easings.expoOut }}
            className="flex justify-center lg:justify-start"
            style={{ transform: 'translateY(-20px)' }}
          >
            <KernelSeal size={280} variant="dark" animated />
          </fm.div>

          <div className="max-w-3xl">
            {/* Eyebrow — t=1100ms, x:-8 → 0 */}
            <fm.p
              initial={{ opacity: 0, x: -8 }}
              animate={reached.eyebrow ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: ms(400), ease: easings.expoOut }}
              className="eyebrow text-gold-highlight mb-6"
            >
              OPERATIONAL INFRASTRUCTURE · v1.0
            </fm.p>

            {/* Headline — Display L (Cormorant SC 700), italic on ONE word. */}
            <h1 className="display-l text-dark-ink mb-8 max-w-[760px]">
              {preWords.map((word, i) => {
                const visible = wordsRevealed > i;
                return (
                  <fm.span
                    key={`${word}-${i}`}
                    initial={{ opacity: 0, y: 24 }}
                    animate={visible ? { opacity: 1, y: 0 } : {}}
                    transition={{ duration: ms(600), ease: easings.cinematic }}
                    style={{ display: 'inline-block', marginRight: '0.18em' }}
                  >
                    {word}
                  </fm.span>
                );
              })}
              {/* Italic word — added scale + tracking decompression. */}
              <fm.span
                initial={{
                  opacity: 0,
                  y: 24,
                  scale: 0.96,
                  letterSpacing: '-0.03em',
                }}
                animate={
                  wordsRevealed > preWords.length
                    ? {
                        opacity: 1,
                        y: 0,
                        scale: 1,
                        letterSpacing: '-0.01em',
                      }
                    : {}
                }
                transition={{ duration: ms(800), ease: easings.cinematic }}
                className="italic-emph"
                style={{ display: 'inline-block' }}
              >
                {HEADLINE_ITALIC}
              </fm.span>
            </h1>

            {/* Subhead — t=2000ms, y:16 → 0, body-xl (Geist 22px). */}
            <fm.p
              initial={{ opacity: 0, y: 16 }}
              animate={reached.subhead ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: ms(600), ease: easings.expoOut }}
              className="body-xl text-dark-ink-muted mb-12 max-w-[540px]"
            >
              Operious AI is a deterministic execution substrate for enterprise
              operations. Every action is governed by mathematically enforced
              policy. Every decision is cryptographically reconstructible. Every
              workflow runs identically, indefinitely, without drift.
            </fm.p>

            {/* CTAs — 24px gap. */}
            <div className="flex flex-wrap items-center gap-6">
              <fm.div
                initial={{ opacity: 0, scale: 0.96 }}
                animate={reached.ctaPrimary ? { opacity: 1, scale: 1 } : {}}
                transition={{ duration: ms(400), ease: easings.authoritative }}
              >
                <Link
                  href="#contact"
                  data-cursor="interactive"
                  className="group inline-flex items-center gap-2 rounded-sm bg-gold px-6 py-3 body-s text-dark-canvas transition-colors duration-[160ms] hover:bg-gold-deep focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-gold-highlight"
                >
                  Request Enterprise Access
                  <span
                    aria-hidden
                    className="transition-transform duration-200 group-hover:translate-x-1"
                  >
                    →
                  </span>
                </Link>
              </fm.div>
              <fm.div
                initial={{ opacity: 0 }}
                animate={reached.ctaSecondary ? { opacity: 1 } : {}}
                transition={{ duration: ms(300), ease: easings.expoOut }}
              >
                <Link
                  href="#kernel"
                  data-cursor="interactive"
                  className="group inline-flex items-center gap-2 body-s text-gold-highlight"
                >
                  <span className="editorial-link">Read the architecture</span>
                  <span
                    aria-hidden
                    className="transition-transform duration-200 group-hover:translate-x-1"
                  >
                    →
                  </span>
                </Link>
              </fm.div>
            </div>
          </div>
        </div>

        {/* Scroll indicator — t=2600ms, gold vertical line, gentle pulse. */}
        <fm.div
          initial={{ opacity: 0 }}
          animate={reached.scroll ? { opacity: 1 } : {}}
          transition={{ duration: ms(400), ease: easings.expoOut }}
          className="mt-16 flex flex-col items-center gap-3"
        >
          <span
            aria-hidden
            className="block h-12 w-px origin-top animate-scroll-pulse bg-gradient-to-b from-gold-highlight to-transparent"
          />
          <span className="eyebrow text-dark-ink-muted">Scroll to explore</span>
        </fm.div>
      </div>
    </section>
  );
};

export default HeroSection;
