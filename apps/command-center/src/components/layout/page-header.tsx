import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface PageHeaderProps {
  readonly breadcrumb: readonly string[];
  readonly title: string;
  readonly description?: string;
  readonly actions?: ReactNode;
  readonly className?: string;
}

/**
 * Page header strip.
 *
 * Renders breadcrumb (small IBM Plex Mono) + page title (Cormorant SC 28px)
 * + page-level actions (right-aligned). Cormorant SC is reserved for page
 * titles only \u2014 it is NOT used for general UI headings.
 */
export const PageHeader = ({
  breadcrumb,
  title,
  description,
  actions,
  className,
}: PageHeaderProps) => (
  <header
    className={cn(
      'flex flex-wrap items-end justify-between gap-4 pb-6',
      className,
    )}
  >
    <div className="min-w-0 space-y-1.5">
      <nav aria-label="Breadcrumb">
        <ol className="flex items-center gap-1 font-mono text-2xs text-fg-subtle">
          {breadcrumb.map((segment, index) => (
            <li key={`${segment}-${index}`} className="flex items-center gap-1">
              <span
                className={cn(
                  index === breadcrumb.length - 1
                    ? 'text-fg-muted'
                    : 'text-fg-dim',
                )}
              >
                {segment}
              </span>
              {index < breadcrumb.length - 1 ? (
                <span className="text-fg-dim">/</span>
              ) : null}
            </li>
          ))}
        </ol>
      </nav>
      <h1 className="font-display text-[28px] leading-tight text-fg">
        {title}
      </h1>
      {description ? (
        <p className="max-w-3xl text-sm text-fg-muted">{description}</p>
      ) : null}
    </div>
    {actions ? (
      <div className="flex shrink-0 items-center gap-2">{actions}</div>
    ) : null}
  </header>
);
