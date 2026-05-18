import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../utils';

export const Section = ({
  className,
  ...rest
}: HTMLAttributes<HTMLElement>) => (
  <section className={cn('space-y-6', className)} {...rest} />
);

interface SectionHeaderProps {
  readonly eyebrow?: string;
  readonly title: ReactNode;
  readonly description?: ReactNode;
  readonly trailing?: ReactNode;
  readonly className?: string;
}

export const SectionHeader = ({
  eyebrow,
  title,
  description,
  trailing,
  className,
}: SectionHeaderProps) => (
  <header className={cn('flex items-start justify-between gap-6', className)}>
    <div className="space-y-1.5">
      {eyebrow ? (
        <p className="text-mono text-fg-subtle">{eyebrow}</p>
      ) : null}
      <h2 className="font-display text-2xl text-fg">{title}</h2>
      {description ? (
        <p className="text-sm text-fg-muted max-w-2xl">{description}</p>
      ) : null}
    </div>
    {trailing}
  </header>
);
