'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Custom cursor — the editorial pointer affordance.
 *
 * Spec:
 *   • Default     : 6px solid ink-primary dot, position lerp 0.18
 *   • Interactive : 32px outlined ring, ink-primary stroke, position lerp 0.12
 *   • Over text   : 2px × 18px vertical bar (text-cursor metaphor)
 *   • Click       : dot scales 1 → 1.6 → 1 over 200ms
 *
 * Hidden on touch / coarse-pointer devices via CSS in globals.css.
 * Hidden entirely when prefers-reduced-motion is honored.
 */

type Mode = 'default' | 'interactive' | 'text';

const isTouchDevice = (): boolean => {
  if (typeof window === 'undefined') return true;
  return window.matchMedia('(hover: none), (pointer: coarse)').matches;
};

const prefersReducedMotion = (): boolean => {
  if (typeof window === 'undefined') return true;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
};

const INTERACTIVE_SELECTOR =
  'a, button, [role="button"], [data-cursor="interactive"], input, select, textarea, label, summary';

const TEXT_SELECTOR = 'p, h1, h2, h3, h4, h5, h6, li, blockquote, [data-cursor="text"]';

export const CustomCursor = () => {
  const [mounted, setMounted] = useState(false);
  const dotRef = useRef<HTMLDivElement | null>(null);
  const ringRef = useRef<HTMLDivElement | null>(null);
  const modeRef = useRef<Mode>('default');
  const clickRef = useRef<number>(0);

  useEffect(() => {
    if (isTouchDevice() || prefersReducedMotion()) return;
    setMounted(true);

    const dot = dotRef.current;
    const ring = ringRef.current;
    if (!dot || !ring) return;

    let targetX = window.innerWidth / 2;
    let targetY = window.innerHeight / 2;
    let dotX = targetX;
    let dotY = targetY;
    let ringX = targetX;
    let ringY = targetY;

    const onMove = (event: PointerEvent) => {
      targetX = event.clientX;
      targetY = event.clientY;
      const target = event.target as Element | null;
      if (target?.closest(INTERACTIVE_SELECTOR)) {
        setMode('interactive');
      } else if (target?.closest(TEXT_SELECTOR)) {
        setMode('text');
      } else {
        setMode('default');
      }
    };

    const setMode = (next: Mode) => {
      if (modeRef.current === next) return;
      modeRef.current = next;
      ring.dataset.mode = next;
      dot.dataset.mode = next;
    };

    const onDown = () => {
      clickRef.current = performance.now();
      dot.dataset.clicked = '1';
      window.setTimeout(() => {
        if (dot) delete dot.dataset.clicked;
      }, 200);
    };

    const onLeave = () => {
      dot.style.opacity = '0';
      ring.style.opacity = '0';
    };
    const onEnter = () => {
      dot.style.opacity = '1';
      ring.style.opacity = '1';
    };

    let rafId = 0;
    const tick = () => {
      // Dot follows fast.
      dotX += (targetX - dotX) * 0.18;
      dotY += (targetY - dotY) * 0.18;
      // Ring follows slower (only used in 'interactive' mode visually).
      ringX += (targetX - ringX) * 0.12;
      ringY += (targetY - ringY) * 0.12;
      dot.style.transform = `translate3d(${dotX - 3}px, ${dotY - 3}px, 0)`;
      ring.style.transform = `translate3d(${ringX - 16}px, ${ringY - 16}px, 0)`;
      rafId = window.requestAnimationFrame(tick);
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerdown', onDown, { passive: true });
    window.addEventListener('pointerleave', onLeave);
    window.addEventListener('pointerenter', onEnter);
    rafId = window.requestAnimationFrame(tick);

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointerleave', onLeave);
      window.removeEventListener('pointerenter', onEnter);
    };
  }, []);

  if (!mounted) return null;

  return (
    <div className="custom-cursor-root" aria-hidden>
      <div
        ref={dotRef}
        data-mode="default"
        className="cursor-dot"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '6px',
          height: '6px',
          borderRadius: '9999px',
          background: '#FFFFFF',
          transition:
            'opacity 200ms cubic-bezier(0.22, 1, 0.36, 1), width 200ms cubic-bezier(0.22, 1, 0.36, 1), height 200ms cubic-bezier(0.22, 1, 0.36, 1)',
        }}
      />
      <div
        ref={ringRef}
        data-mode="default"
        className="cursor-ring"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '32px',
          height: '32px',
          borderRadius: '9999px',
          border: '1px solid rgba(255,255,255,0.8)',
          opacity: 0,
          transition:
            'opacity 220ms cubic-bezier(0.22, 1, 0.36, 1), transform 0s, border-color 220ms ease-out, width 200ms cubic-bezier(0.22, 1, 0.36, 1), height 200ms cubic-bezier(0.22, 1, 0.36, 1)',
        }}
      />
      <style>{`
        .cursor-dot[data-mode='interactive'] { width: 0px; height: 0px; opacity: 0; }
        .cursor-dot[data-mode='text'] {
          width: 2px; height: 18px; border-radius: 1px;
        }
        .cursor-dot[data-clicked='1'] {
          animation: cursor-click 200ms cubic-bezier(0.22, 1, 0.36, 1);
        }
        .cursor-ring[data-mode='interactive'] { opacity: 1; }
        .cursor-ring[data-mode='default'],
        .cursor-ring[data-mode='text']        { opacity: 0; }
        @keyframes cursor-click {
          0%   { transform-origin: center; }
          50%  { transform: translate3d(var(--dx,0), var(--dy,0), 0) scale(1.6); }
          100% { transform-origin: center; }
        }
      `}</style>
    </div>
  );
};

export default CustomCursor;
