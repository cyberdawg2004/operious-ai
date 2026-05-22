import { cn } from '@/lib/cn';

interface ConfidenceBarProps {
  /** 0-100. */
  readonly value: number;
  readonly className?: string;
  readonly showLabel?: boolean;
}

/**
 * Thin confidence bar visualization.
 *
 * Renders a percentage as a 4px-tall bar with a tabular monospace numeric
 * suffix. Tone shifts at 50% and 80% thresholds so glance value is preserved
 * (the percent text remains the canonical signal).
 */
export const ConfidenceBar = ({
  value,
  className,
  showLabel = true,
}: ConfidenceBarProps) => {
  const clamped = Math.max(0, Math.min(100, value));
  const tone =
    clamped >= 80
      ? 'bg-signal-allow'
      : clamped >= 50
        ? 'bg-signal-escalate'
        : 'bg-signal-deny';
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div className="h-1 w-20 overflow-hidden rounded-full bg-line">
        <div
          className={cn('h-full rounded-full transition-all', tone)}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel ? (
        <span className="font-mono text-2xs text-fg-muted">
          {clamped.toFixed(0)}%
        </span>
      ) : null}
    </div>
  );
};
