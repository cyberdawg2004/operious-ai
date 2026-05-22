/**
 * Motion contract for the Command Center surface.
 *
 * Operators read this dashboard for hours; motion must communicate
 * causality (state change, focus shift, authority decision) and never
 * decorate. The forensic surfaces (Trace Inspector, Operations Queue,
 * Cognition Hub) are alive — the chrome is restrained.
 *
 * Every motion in this app must source its easing and duration from
 * this file.
 */

export const easings = {
  expoOut: [0.16, 1, 0.3, 1] as const,
  expoInOut: [0.87, 0, 0.13, 1] as const,
  cinematic: [0.22, 1, 0.36, 1] as const,
  precise: [0.4, 0, 0.2, 1] as const,
  authoritative: [0.32, 0.72, 0, 1] as const,
  /**
   * Subtle overshoot — the ONLY overshoot easing allowed in the Command
   * Center. Reserved for Trace Inspector node entry (per spec).
   */
  traceOvershoot: [0.34, 1.56, 0.64, 1] as const,
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

export const ms = (n: number): number => n / 1000;

/** Standard right-panel slide-in (spec: 320ms open, 240ms close). */
export const RIGHT_PANEL = {
  openMs: 320,
  closeMs: 240,
  backdropOpenMs: 240,
  backdropBlurMs: 320,
  staggerMs: 60,
  staggerInitialDelayMs: 120,
} as const;

/** Trace Inspector node entry — the ONLY overshoot we ship. */
export const TRACE_NODE_ENTRY = {
  opacityMs: 240,
  scaleMs: 240,
  glowMs: 800,
} as const;

/** Toast notification timing. */
export const TOAST = {
  enterMs: 320,
  exitMs: 240,
  defaultAutoDismissMs: 5000,
  progressTailMs: 400,
  maxVisible: 3,
} as const;

/** Tenant switcher ceremony. */
export const TENANT_CEREMONY = {
  overlayInMs: 200,
  sealRotateMs: 800,
  contentInMs: 400,
} as const;

export const motion = (
  ease: EasingName = 'precise',
  duration: DurationName = 'medium',
  extra: Record<string, unknown> = {},
) => ({
  duration: durations[duration],
  ease: easings[ease] as unknown as number[],
  ...extra,
});

export const cssEasing = {
  expoOut: 'cubic-bezier(0.16, 1, 0.3, 1)',
  expoInOut: 'cubic-bezier(0.87, 0, 0.13, 1)',
  cinematic: 'cubic-bezier(0.22, 1, 0.36, 1)',
  precise: 'cubic-bezier(0.4, 0, 0.2, 1)',
  authoritative: 'cubic-bezier(0.32, 0.72, 0, 1)',
  traceOvershoot: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
} as const;
