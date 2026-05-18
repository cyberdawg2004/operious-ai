import type { HTMLAttributes } from 'react';
import { cn } from '../utils';

export type BadgeTone =
  | 'allow'
  | 'escalate'
  | 'deny'
  | 'deadlock'
  | 'neutral'
  | 'pending'
  | 'info';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  readonly tone?: BadgeTone;
}

const toneClasses: Record<BadgeTone, string> = {
  allow: 'bg-signal-allow/10 text-signal-allow border-signal-allow/30',
  escalate: 'bg-signal-escalate/10 text-signal-escalate border-signal-escalate/30',
  deny: 'bg-signal-deny/10 text-signal-deny border-signal-deny/30',
  deadlock: 'bg-signal-deadlock/15 text-signal-deadlock border-signal-deadlock/30',
  neutral: 'bg-bg-inset text-fg-muted border-line',
  pending: 'bg-accent/10 text-accent border-accent/30',
  info: 'bg-bg-raised text-fg-muted border-line-subtle',
};

export const Badge = ({ tone = 'neutral', className, ...rest }: BadgeProps) => (
  <span
    className={cn(
      'inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-2xs uppercase tracking-wider',
      toneClasses[tone],
      className,
    )}
    {...rest}
  />
);
