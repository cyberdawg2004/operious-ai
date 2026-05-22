'use client';

import type { ButtonHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

interface FilterPillProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly active?: boolean;
}

/**
 * Filter pill \u2014 small toggleable chip used on operations / cognition / etc.
 *
 * Active state: solid accent border + raised background.
 * Inactive: subtle border, hovers to ink-body text.
 */
export const FilterPill = ({
  active = false,
  className,
  children,
  ...rest
}: FilterPillProps) => (
  <button
    type="button"
    {...rest}
    className={cn(
      'rounded-sm border px-2.5 py-1 font-mono text-2xs uppercase tracking-wider',
      'transition-colors duration-100',
      active
        ? 'border-accent/60 bg-accent/10 text-fg shadow-inset'
        : 'border-line bg-bg-inset text-fg-subtle hover:border-line-strong hover:text-fg',
      className,
    )}
  >
    {children}
  </button>
);
