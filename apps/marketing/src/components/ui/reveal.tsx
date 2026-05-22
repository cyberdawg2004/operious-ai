'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';

/**
 * Reveal — Intersection-observer scroll trigger.
 *
 * Server-renders the children visible (progressive enhancement). On mount,
 * if JS is available and reduce-motion is not requested, removes the
 * `is-visible` class until the element scrolls into view, then re-adds it.
 *
 * The base CSS class (`reveal`) sets opacity 0 + translate; `.is-visible`
 * lifts it back. This is more performant than render-gating with
 * framer-motion and works without JS.
 */
interface RevealProps {
  readonly children: ReactNode;
  readonly className?: string;
  readonly delay?: number;
  readonly threshold?: number;
}

export const Reveal = ({
  children,
  className,
  delay = 0,
  threshold = 0.3,
}: RevealProps) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    setHydrated(true);
    if (typeof window === 'undefined') return;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduceMotion) return;
    setVisible(false);
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true);
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold, rootMargin: '0px 0px -10% 0px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [threshold]);

  const classes = [
    hydrated ? 'reveal' : '',
    visible ? 'is-visible' : '',
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div
      ref={ref}
      className={classes}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children}
    </div>
  );
};

export default Reveal;
