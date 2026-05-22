import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export type StatusTone =
  | 'active'
  | 'pending'
  | 'denied'
  | 'info'
  | 'governed'
  | 'neutral'
  | 'open'
  | 'executing'
  | 'completed'
  | 'escalated'
  | 'failed';

interface StatusPillProps extends HTMLAttributes<HTMLSpanElement> {
  readonly tone?: StatusTone;
  readonly dot?: boolean;
  readonly pulse?: boolean;
}

const TONE_CLASSES: Record<StatusTone, string> = {
  active: 'bg-signal-allow/10 text-signal-allow border-signal-allow/30',
  pending: 'bg-signal-escalate/10 text-signal-escalate border-signal-escalate/30',
  denied: 'bg-signal-deny/10 text-signal-deny border-signal-deny/30',
  info: 'bg-signal-info/10 text-signal-info border-signal-info/30',
  governed: 'bg-signal-governed/10 text-signal-governed border-signal-governed/30',
  neutral: 'bg-bg-raised text-fg-subtle border-line',
  open: 'bg-bg-raised text-fg-subtle border-line',
  executing: 'bg-signal-info/10 text-signal-info border-signal-info/30',
  completed: 'bg-signal-allow/10 text-signal-allow border-signal-allow/30',
  escalated: 'bg-signal-escalate/10 text-signal-escalate border-signal-escalate/30',
  failed: 'bg-signal-deny/10 text-signal-deny border-signal-deny/30',
};

const DOT_CLASSES: Record<StatusTone, string> = {
  active: 'bg-signal-allow',
  pending: 'bg-signal-escalate',
  denied: 'bg-signal-deny',
  info: 'bg-signal-info',
  governed: 'bg-signal-governed',
  neutral: 'bg-fg-dim',
  open: 'bg-fg-dim',
  executing: 'bg-signal-info',
  completed: 'bg-signal-allow',
  escalated: 'bg-signal-escalate',
  failed: 'bg-signal-deny',
};

/**
 * Status pill.
 *
 * A compact, uppercase, monospaced status badge. Always renders the text
 * label (color is never the only signal \u2014 accessibility requirement).
 * Optional pulsing dot for live states (e.g. PENDING escalation).
 */
export const StatusPill = ({
  tone = 'neutral',
  dot = false,
  pulse = false,
  className,
  children,
  ...rest
}: StatusPillProps) => (
  <span
    className={cn(
      'inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5',
      'font-mono text-2xs uppercase tracking-wider transition-colors duration-[250ms]',
      TONE_CLASSES[tone],
      className,
    )}
    {...rest}
  >
    {dot ? (
      <span
        aria-hidden
        className={cn(
          'inline-block h-1.5 w-1.5 rounded-full',
          DOT_CLASSES[tone],
          pulse && 'animate-pulse-amber',
        )}
      />
    ) : null}
    {children}
  </span>
);
