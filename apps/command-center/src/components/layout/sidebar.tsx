'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { KernelSeal } from '@/components/brand/kernel-seal';
import { TenantSelector } from '@/components/layout/tenant-selector';
import { UserMenu } from '@/components/layout/user-menu';
import { NAVIGATION } from '@/lib/navigation';
import { cn } from '@/lib/cn';

/**
 * Left sidebar \u2014 240px fixed, panel-raised background.
 *
 * Layout, top to bottom:
 *   \u2022 KernelSeal + "Operious" wordmark
 *   \u2022 Tenant selector
 *   \u2022 Primary navigation (10 entries)
 *   \u2022 User menu (anchored at bottom)
 *
 * Active route is signalled by a 4px gold accent bar on the left edge and
 * ink-primary text. Hover is a tint shift; no motion gimmicks.
 */
export const Sidebar = () => {
  const pathname = usePathname();
  return (
    <aside
      className={cn(
        'flex h-screen w-[240px] shrink-0 flex-col',
        'border-r border-line bg-bg-raised',
      )}
    >
      <header className="px-4 py-5">
        <Link
          href="/operations"
          className={cn(
            'flex items-center gap-2.5 rounded-sm px-1 py-1',
            'transition-colors hover:bg-bg-inset/60',
          )}
        >
          <KernelSeal size={28} />
          <div>
            <p className="font-display text-lg leading-none text-fg">
              Operious
            </p>
            <p className="mt-0.5 font-mono text-2xs uppercase tracking-widest text-fg-dim">
              command center
            </p>
          </div>
        </Link>
      </header>

      <div className="px-3 pb-3">
        <TenantSelector />
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        <p className="px-3 pb-1.5 text-mono text-fg-dim">workspace</p>
        <ul className="space-y-0.5">
          {NAVIGATION.map((entry) => {
            const active =
              pathname === entry.href ||
              (entry.href !== '/operations' &&
                pathname?.startsWith(entry.href));
            const Icon = entry.icon;
            return (
              <li key={entry.href} className="relative">
                {active ? (
                  <span
                    aria-hidden
                    className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r bg-accent"
                  />
                ) : null}
                <Link
                  href={entry.href}
                  className={cn(
                    'flex items-center gap-2.5 rounded-sm px-3 py-1.5',
                    'text-sm transition-colors',
                    active
                      ? 'bg-bg-inset/80 text-fg'
                      : 'text-fg-subtle hover:bg-bg-inset/60 hover:text-fg',
                  )}
                >
                  <Icon
                    className={cn(
                      'h-4 w-4 shrink-0',
                      active ? 'text-accent' : 'text-fg-dim',
                    )}
                  />
                  <span className="flex-1 truncate font-sans">
                    {entry.label}
                  </span>
                  <kbd
                    className={cn(
                      'rounded-sm border px-1 font-mono text-2xs',
                      active
                        ? 'border-line-strong bg-bg-raised text-fg-dim'
                        : 'border-transparent bg-transparent text-transparent group-hover:text-fg-dim',
                    )}
                  >
                    G{entry.shortcut.toUpperCase()}
                  </kbd>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t border-line px-3 py-3">
        <UserMenu />
      </div>
    </aside>
  );
};
