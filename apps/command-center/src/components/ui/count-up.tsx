'use client';

import { useEffect, useState } from 'react';

interface CountUpProps {
  readonly end: number;
  /** Duration in ms. */
  readonly duration?: number;
  /** Decimal places to show. */
  readonly decimals?: number;
  /** Optional fixed start; defaults to 0. */
  readonly start?: number;
}

const easeOutQuint = (t: number): number => 1 - Math.pow(1 - t, 5);

/**
 * Numeric value that counts up from `start` to `end` on mount.
 *
 * Driven by `requestAnimationFrame`, easing is `easeOutQuint` (calm). The
 * component is a span; format your suffix outside.
 */
export const CountUp = ({
  end,
  duration = 800,
  decimals = 0,
  start = 0,
}: CountUpProps) => {
  const [value, setValue] = useState(start);

  useEffect(() => {
    let raf = 0;
    const startTime = performance.now();
    const tick = (now: number) => {
      const elapsed = now - startTime;
      const t = Math.min(1, elapsed / duration);
      const eased = easeOutQuint(t);
      setValue(start + (end - start) * eased);
      if (t < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        setValue(end);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [end, start, duration]);

  const formatted = decimals > 0 ? value.toFixed(decimals) : Math.round(value).toString();
  // Tabular nums prevent layout shift while counting.
  return <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatted}</span>;
};
