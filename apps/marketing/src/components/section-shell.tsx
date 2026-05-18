import type { ReactNode } from 'react';
import { cn } from '@operious/ui';

interface SectionShellProps {
  readonly id?: string;
  readonly eyebrow?: string;
  readonly title: ReactNode;
  readonly description?: ReactNode;
  readonly children?: ReactNode;
  readonly className?: string;
}

export const SectionShell = ({
  id,
  eyebrow,
  title,
  description,
  children,
  className,
}: SectionShellProps) => (
  <section id={id} className={cn('border-b border-line py-24', className)}>
    <div className="mx-auto max-w-7xl px-6">
      <header className="max-w-3xl space-y-4">
        {eyebrow ? (
          <p className="font-mono text-2xs uppercase tracking-widest text-accent">
            {eyebrow}
          </p>
        ) : null}
        <h2 className="font-display text-3xl text-fg md:text-5xl">{title}</h2>
        {description ? (
          <p className="text-base text-fg-muted md:text-lg">{description}</p>
        ) : null}
      </header>
      {children ? <div className="mt-12">{children}</div> : null}
    </div>
  </section>
);
