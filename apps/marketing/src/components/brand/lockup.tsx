import type { ComponentProps } from 'react';
import { KernelSeal } from './kernel-seal';

/**
 * Brand Lockup — KernelSeal + "Operious" wordmark.
 *
 * The wordmark is set in Cormorant SC at the same optical weight as the
 * seal, never in a heavier display style. Tracking is editorial (0.04em).
 * Wordmark is treated as a small heading instance (≥ 28px is the
 * Cormorant floor — we set 1.25rem here only when the lockup is used as
 * a compact lockup; standalone wordmarks should use heading-m or larger).
 */

interface LockupProps {
  readonly variant?: 'dark' | 'light';
  readonly sealSize?: number;
  readonly wordmarkClassName?: string;
  readonly className?: string;
  readonly animated?: ComponentProps<typeof KernelSeal>['animated'];
}

export const Lockup = ({
  variant = 'light',
  sealSize = 32,
  wordmarkClassName,
  className,
  animated = false,
}: LockupProps) => {
  const ink = variant === 'dark' ? 'text-dark-ink' : 'text-ink-primary';
  return (
    <span className={`inline-flex items-center gap-3 ${className ?? ''}`}>
      <KernelSeal size={sealSize} variant={variant} animated={animated} />
      <span
        // Geist Sans wordmark with display weight — the institutional
        // mark. Cormorant SC at this scale is forbidden (<28px), so
        // we deliberately use Geist 600 here instead.
        className={`body-s font-semibold leading-none ${ink} ${wordmarkClassName ?? ''}`}
        style={{ letterSpacing: '0.04em', fontSize: '1rem' }}
      >
        Operious
      </span>
    </span>
  );
};

export default Lockup;
