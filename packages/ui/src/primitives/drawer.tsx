'use client';

import { useEffect, type ReactNode } from 'react';
import { cn } from '../utils';

interface DrawerProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly title: string;
  readonly subtitle?: string;
  readonly children: ReactNode;
  readonly className?: string;
}

/**
 * Inspection drawer — mounted above the dashboard surface.
 * Used by every module to expose forensic detail without page navigation.
 */
export const Drawer = ({
  open,
  onClose,
  title,
  subtitle,
  children,
  className,
}: DrawerProps) => {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex">
      <button
        type="button"
        aria-label="Close inspector"
        className="flex-1 bg-black/40"
        onClick={onClose}
      />
      <aside
        className={cn(
          'h-full w-[640px] max-w-[90vw] surface-raised flex flex-col',
          className,
        )}
      >
        <header className="flex items-start justify-between border-b border-line px-5 py-4">
          <div>
            <p className="text-mono text-fg-subtle">Inspect</p>
            <h2 className="font-display text-lg text-fg">{title}</h2>
            {subtitle ? (
              <p className="text-xs text-fg-muted mt-0.5">{subtitle}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-mono text-fg-subtle hover:text-fg"
          >
            close
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">{children}</div>
      </aside>
    </div>
  );
};
