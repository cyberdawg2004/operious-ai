'use client';

import { useId } from 'react';

/**
 * KernelSeal \u2014 Operious AI brand mark, sized for the command-center sidebar.
 *
 * This is a static, non-animated variant. The Marketing site uses a phased
 * animation; an enterprise operator surface does not perform.
 */
interface KernelSealProps {
  readonly size?: number;
  readonly className?: string;
  readonly title?: string;
}

const PALETTE = {
  ring: '#A8882C',
  ringFaint: 'rgba(168, 136, 44, 0.30)',
  inner: '#0A0F1C',
  bondCore: '#0A0F1C',
  bondHalo: 'rgba(10, 15, 28, 0.10)',
  field: '#FFFFFF',
  fieldStroke: 'rgba(10, 15, 28, 0.08)',
} as const;

const hexPoints = (cx: number, cy: number, r: number): string => {
  const points: string[] = [];
  for (let i = 0; i < 6; i += 1) {
    const angle = (Math.PI / 3) * i + Math.PI / 6;
    points.push(
      `${(cx + r * Math.cos(angle)).toFixed(3)},${(cy + r * Math.sin(angle)).toFixed(3)}`,
    );
  }
  return points.join(' ');
};

export const KernelSeal = ({
  size = 32,
  className,
  title = 'Operious Kernel Seal',
}: KernelSealProps) => {
  const uid = useId();
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
          <stop offset="0%" stopColor={PALETTE.bondCore} stopOpacity="1" />
          <stop offset="60%" stopColor={PALETTE.bondCore} stopOpacity="0.2" />
          <stop offset="100%" stopColor={PALETTE.bondHalo} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${uid}-ring`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={PALETTE.ring} />
          <stop offset="100%" stopColor={PALETTE.inner} />
        </linearGradient>
      </defs>
      <polygon
        points={hexPoints(cx, cy, 92)}
        fill={PALETTE.field}
        stroke={PALETTE.fieldStroke}
        strokeWidth="0.75"
      />
      <polygon
        points={hexPoints(cx, cy, 86)}
        fill="none"
        stroke={`url(#${uid}-ring)`}
        strokeWidth="2.4"
        strokeLinejoin="miter"
      />
      <polygon
        points={hexPoints(cx, cy, 78)}
        fill="none"
        stroke={PALETTE.ringFaint}
        strokeWidth="1"
      />
      <g>
        <polygon
          points={hexPoints(cx, cy, 56)}
          fill="none"
          stroke={PALETTE.inner}
          strokeWidth="1.6"
        />
        <polygon
          points={hexPoints(cx, cy, 40)}
          fill="none"
          stroke={PALETTE.inner}
          strokeWidth="1.1"
          strokeOpacity="0.65"
        />
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
              stroke={PALETTE.inner}
              strokeWidth="1.1"
              strokeOpacity="0.5"
            />
          );
        })}
      </g>
      <g>
        <circle cx={cx} cy={cy} r="28" fill={`url(#${uid}-bond)`} />
        <circle cx={cx} cy={cy} r="6" fill={PALETTE.bondCore} />
        <circle
          cx={cx}
          cy={cy}
          r="14"
          fill="none"
          stroke={PALETTE.bondCore}
          strokeWidth="0.8"
          strokeOpacity="0.55"
        />
      </g>
    </svg>
  );
};

export default KernelSeal;
