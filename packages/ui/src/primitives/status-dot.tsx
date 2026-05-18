import { cn } from '../utils';
import type { BadgeTone } from './badge';

interface StatusDotProps {
  readonly tone: BadgeTone;
  readonly className?: string;
}

const toneClasses: Record<BadgeTone, string> = {
  allow: 'bg-signal-allow',
  escalate: 'bg-signal-escalate',
  deny: 'bg-signal-deny',
  deadlock: 'bg-signal-deadlock',
  neutral: 'bg-signal-neutral',
  pending: 'bg-accent',
  info: 'bg-fg-subtle',
};

export const StatusDot = ({ tone, className }: StatusDotProps) => (
  <span
    className={cn(
      'inline-block h-1.5 w-1.5 rounded-full',
      toneClasses[tone],
      className,
    )}
    aria-hidden
  />
);
