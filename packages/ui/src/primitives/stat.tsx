import type { ReactNode } from 'react';
import { cn } from '../utils';

interface StatProps {
  readonly label: string;
  readonly value: ReactNode;
  readonly hint?: string;
  readonly className?: string;
}

export const Stat = ({ label, value, hint, className }: StatProps) => (
  <div
    className={cn(
      'rounded-md border border-line bg-bg-raised px-4 py-3 space-y-1',
      className,
    )}
  >
    <p className="text-mono text-fg-subtle">{label}</p>
    <p className="text-xl font-display text-fg">{value}</p>
    {hint ? <p className="text-xs text-fg-muted">{hint}</p> : null}
  </div>
);
