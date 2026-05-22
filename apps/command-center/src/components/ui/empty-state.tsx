import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';

interface EmptyStateProps {
  readonly icon?: LucideIcon;
  readonly title: string;
  readonly description?: string;
  readonly action?: React.ReactNode;
  readonly className?: string;
}

export const EmptyState = ({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) => (
  <div
    className={cn(
      'flex flex-col items-center justify-center gap-3 rounded-md border border-line bg-bg-inset px-6 py-10',
      'text-center',
      className,
    )}
  >
    {Icon ? <Icon className="h-6 w-6 text-fg-dim" /> : null}
    <div className="space-y-1">
      <p className="font-display text-lg text-fg">{title}</p>
      {description ? (
        <p className="mx-auto max-w-md text-sm text-fg-subtle">{description}</p>
      ) : null}
    </div>
    {action ? <div>{action}</div> : null}
  </div>
);
