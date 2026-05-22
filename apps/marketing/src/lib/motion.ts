/**
 * Motion contract for the Marketing surface.
 *
 * Per the Visual Execution Hyperprompt every page must use only these
 * easing and duration constants. No arbitrary `duration: 0.35`. No
 * arbitrary `cubic-bezier(...)`. If a movement does not fit one of
 * these tokens, the design is wrong — open the spec, find the closest
 * intent, use that token.
 */

export const easings = {
  /** Primary reveal — confident deceleration. */
  expoOut: [0.16, 1, 0.3, 1] as const,
  /** Section transitions. */
  expoInOut: [0.87, 0, 0.13, 1] as const,
  /** Generous, premium — used for hero word reveal & substrate stack. */
  cinematic: [0.22, 1, 0.36, 1] as const,
  /** Utility easing for short UI motion. */
  precise: [0.4, 0, 0.2, 1] as const,
  /** CTA + accent reveals — gold strokes, focus underline draw. */
  authoritative: [0.32, 0.72, 0, 1] as const,
} as const;

export const durations = {
  micro: 0.16,
  short: 0.24,
  medium: 0.4,
  long: 0.6,
  hero: 1.2,
  epic: 1.8,
} as const;

export type EasingName = keyof typeof easings;
export type DurationName = keyof typeof durations;

/**
 * The frame-by-frame hero load timeline (in milliseconds since mount).
 * Each label is a directorial cue — the hero section consumes these
 * values directly so timing edits are reviewed in one place.
 */
export const HERO_TIMELINE = {
  latticeBegin: 0,
  navIn: 100,
  sealPhase1: 400,
  sealPhase2: 700,
  sealPhase3: 1000,
  eyebrowIn: 1100,
  headlineStart: 1300,
  headlineWordStaggerMs: 80,
  subheadIn: 2000,
  ctaPrimaryIn: 2300,
  ctaSecondaryIn: 2400,
  scrollIndicatorIn: 2600,
} as const;

/** Convert a numeric ms to seconds for Framer Motion. */
export const ms = (n: number): number => n / 1000;

/**
 * Helper — Framer Motion transition factory.
 * Usage:  transition: motion('cinematic', 'medium')
 */
export const motion = (
  ease: EasingName = 'cinematic',
  duration: DurationName = 'medium',
  extra: Record<string, unknown> = {},
) => ({
  duration: durations[duration],
  ease: easings[ease] as unknown as number[],
  ...extra,
});

/**
 * Useful in CSS-driven contexts (transition-timing-function strings).
 */
export const cssEasing = {
  expoOut: 'cubic-bezier(0.16, 1, 0.3, 1)',
  expoInOut: 'cubic-bezier(0.87, 0, 0.13, 1)',
  cinematic: 'cubic-bezier(0.22, 1, 0.36, 1)',
  precise: 'cubic-bezier(0.4, 0, 0.2, 1)',
  authoritative: 'cubic-bezier(0.32, 0.72, 0, 1)',
} as const;
