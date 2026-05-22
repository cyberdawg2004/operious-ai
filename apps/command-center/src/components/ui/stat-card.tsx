import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { CountUp } from '@/components/ui/count-up';

interface StatCardProps {
  readonly label: string;
  readonly value: number | string;
  readonly hint?: string;
  readonly suffix?: string;
  readonly trend?: ReactNode;
  readonly className?: string;
}

/**
 * Summary-strip statistic card.
 *
 * Used at the top of every dashboard page. Numeric values count up from
 * zero on mount via `requestAnimationFrame`. String values render verbatim.
 */
export const StatCard = ({
  label,
  value,
  hint,
  suffix,
  trend,
  className,
}: StatCardProps) => (
  <div
    className={cn(
      'flex flex-col gap-1 rounded-md border border-line bg-bg-inset px-4 py-3',
      'shadow-card',
      className,
    )}
  >
    <p className="text-mono text-fg-dim">{label}</p>
    <p className="font-mono text-2xl font-medium text-fg">
      {typeof value === 'number' ? <CountUp end={value} /> : value}
      {suffix ? (
        <span className="ml-1 text-base text-fg-subtle">{suffix}</span>
      ) : null}
    </p>
    {hint ? <p className="text-2xs text-fg-subtle">{hint}</p> : null}
    {trend}
  </div>
);
