'use client';

import { useEffect, useRef, useState } from 'react';

interface CountUpProps {
  readonly value: number;
  readonly durationMs?: number;
  readonly format?: (n: number) => string;
  readonly className?: string;
}

/**
 * CountUp — animates a numeric value from 0 to target over a duration when
 * the element scrolls into view. Uses requestAnimationFrame.
 *
 * Server-renders the final value so it is correct without JS.
 */
export const CountUp = ({
  value,
  durationMs = 1200,
  format = (n) => n.toLocaleString('en-US'),
  className,
}: CountUpProps) => {
  const [display, setDisplay] = useState(value);
  const ref = useRef<HTMLSpanElement | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduceMotion) {
      setDisplay(value);
      return;
    }
    setDisplay(0);
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !startedRef.current) {
            startedRef.current = true;
            const start = performance.now();
            const tick = (now: number) => {
              const elapsed = now - start;
              const t = Math.min(1, elapsed / durationMs);
              const eased = 1 - Math.pow(1 - t, 3);
              setDisplay(Math.round(eased * value));
              if (t < 1) {
                window.requestAnimationFrame(tick);
              }
            };
            window.requestAnimationFrame(tick);
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.4 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [value, durationMs]);

  return (
    <span ref={ref} className={className}>
      {format(display)}
    </span>
  );
};

export default CountUp;
