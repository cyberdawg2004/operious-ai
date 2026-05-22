'use client';

import { useEffect, useId, useState } from 'react';

/**
 * KernelSeal — Operious AI brand mark.
 *
 * The seal is a layered governance glyph:
 *   - Phase 1 (the SUBSTRATE): outer hexagonal ring strokes in.
 *   - Phase 2 (the AUTHORITY): inner gold sigil etches in.
 *   - Phase 3 (the BOND): the central determinacy node ignites.
 *
 * Each phase is a constitutional stage of the substrate doctrine. The
 * animation is intentionally restrained — no easing flourishes, no
 * elastic bounces. The seal asserts authority, it does not perform.
 */
type Variant = 'dark' | 'light';

interface KernelSealProps {
  readonly size?: number;
  readonly variant?: Variant;
  readonly animated?: boolean;
  readonly className?: string;
  readonly title?: string;
}

const PALETTES = {
  dark: {
    ring: '#C9A84C',
    ringFaint: 'rgba(201, 168, 76, 0.32)',
    inner: '#A8882C',
    bondCore: '#FBF9F4',
    bondHalo: 'rgba(251, 249, 244, 0.24)',
    field: '#0B1120',
    fieldStroke: 'rgba(201, 168, 76, 0.18)',
  },
  light: {
    ring: '#A8882C',
    ringFaint: 'rgba(168, 136, 44, 0.30)',
    inner: '#0A0F1C',
    bondCore: '#0A0F1C',
    bondHalo: 'rgba(10, 15, 28, 0.10)',
    field: '#FFFFFF',
    fieldStroke: 'rgba(10, 15, 28, 0.08)',
  },
} as const;

/** A regular hexagon centred at (cx, cy) with radius r, flat-top oriented. */
const hexPoints = (cx: number, cy: number, r: number): string => {
  const points: string[] = [];
  for (let i = 0; i < 6; i += 1) {
    const angle = (Math.PI / 3) * i + Math.PI / 6;
    points.push(`${(cx + r * Math.cos(angle)).toFixed(3)},${(cy + r * Math.sin(angle)).toFixed(3)}`);
  }
  return points.join(' ');
};

export const KernelSeal = ({
  size = 200,
  variant = 'dark',
  animated = true,
  className,
  title = 'Operious Kernel Seal',
}: KernelSealProps) => {
  const palette = PALETTES[variant];
  const uid = useId();
  const [phase, setPhase] = useState<0 | 1 | 2 | 3>(animated ? 0 : 3);

  useEffect(() => {
    if (!animated) return;
    const t1 = window.setTimeout(() => setPhase(1), 160);
    const t2 = window.setTimeout(() => setPhase(2), 720);
    const t3 = window.setTimeout(() => setPhase(3), 1320);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      window.clearTimeout(t3);
    };
  }, [animated]);

  const cx = 100;
  const cy = 100;

  return (
    <svg
      role="img"
      aria-label={title}
      viewBox="0 0 200 200"
      width={size}
      height={size}
      className={className}
      style={{ display: 'block' }}
    >
      <defs>
        <radialGradient id={`${uid}-bond`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={palette.bondCore} stopOpacity="1" />
          <stop offset="60%" stopColor={palette.bondCore} stopOpacity="0.2" />
          <stop offset="100%" stopColor={palette.bondHalo} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${uid}-ring`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={palette.ring} />
          <stop offset="100%" stopColor={palette.inner} />
        </linearGradient>
      </defs>

      {/* Field plate (faintly fills the seal so it reads on either canvas). */}
      <polygon
        points={hexPoints(cx, cy, 92)}
        fill={palette.field}
        stroke={palette.fieldStroke}
        strokeWidth="0.75"
        opacity={variant === 'dark' ? 0.55 : 0.0}
      />

      {/* Phase 1 — outer ring (the substrate). */}
      <polygon
        points={hexPoints(cx, cy, 86)}
        fill="none"
        stroke={`url(#${uid}-ring)`}
        strokeWidth="1.6"
        strokeLinejoin="miter"
        style={{
          opacity: phase >= 1 ? 1 : 0,
          transition: 'opacity 480ms cubic-bezier(0.22, 1, 0.36, 1)',
        }}
      />
      <polygon
        points={hexPoints(cx, cy, 78)}
        fill="none"
        stroke={palette.ringFaint}
        strokeWidth="0.75"
        style={{
          opacity: phase >= 1 ? 1 : 0,
          transition: 'opacity 480ms cubic-bezier(0.22, 1, 0.36, 1) 80ms',
        }}
      />

      {/* Phase 2 — inner authority sigil (the inverted hex + spokes). */}
      <g
        style={{
          opacity: phase >= 2 ? 1 : 0,
          transform: phase >= 2 ? 'scale(1)' : 'scale(0.94)',
          transformOrigin: '100px 100px',
          transition:
            'opacity 520ms cubic-bezier(0.22, 1, 0.36, 1), transform 520ms cubic-bezier(0.22, 1, 0.36, 1)',
        }}
      >
        <polygon
          points={hexPoints(cx, cy, 56)}
          fill="none"
          stroke={palette.inner}
          strokeWidth="1.2"
        />
        <polygon
          points={hexPoints(cx, cy, 40)}
          fill="none"
          stroke={palette.inner}
          strokeWidth="0.85"
          strokeOpacity="0.65"
        />

        {/* Six spokes connecting outer to inner — authority precedence channels. */}
        {Array.from({ length: 6 }).map((_, i) => {
          const a = (Math.PI / 3) * i + Math.PI / 6;
          const x1 = cx + 56 * Math.cos(a);
          const y1 = cy + 56 * Math.sin(a);
          const x2 = cx + 40 * Math.cos(a);
          const y2 = cy + 40 * Math.sin(a);
          return (
            <line
              key={i}
              x1={x1.toFixed(3)}
              y1={y1.toFixed(3)}
              x2={x2.toFixed(3)}
              y2={y2.toFixed(3)}
              stroke={palette.inner}
              strokeWidth="0.85"
              strokeOpacity="0.5"
            />
          );
        })}
      </g>

      {/* Phase 3 — the bond. Determinacy node at center. */}
      <g
        style={{
          opacity: phase >= 3 ? 1 : 0,
          transition: 'opacity 600ms cubic-bezier(0.22, 1, 0.36, 1)',
        }}
      >
        <circle cx={cx} cy={cy} r="28" fill={`url(#${uid}-bond)`} />
        <circle
          cx={cx}
          cy={cy}
          r="6"
          fill={palette.bondCore}
          opacity={variant === 'dark' ? 0.92 : 1}
        />
        <circle
          cx={cx}
          cy={cy}
          r="14"
          fill="none"
          stroke={palette.bondCore}
          strokeWidth="0.5"
          strokeOpacity="0.55"
        />
      </g>
    </svg>
  );
};

export default KernelSeal;
