'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@operious/ui';
import { useLocale } from '@/locale/provider';
import { LocaleSwitcher } from '@/components/locale-switcher';

interface NavEntry {
  readonly href: string;
  readonly key: 'operations' | 'traces' | 'cognition' | 'topology';
}

const NAV: readonly NavEntry[] = [
  { href: '/operations', key: 'operations' },
  { href: '/traces', key: 'traces' },
  { href: '/cognition', key: 'cognition' },
  { href: '/topology', key: 'topology' },
];

export const Sidebar = () => {
  const pathname = usePathname();
  const { t } = useLocale();
  return (
    <aside className="flex h-screen w-64 flex-col border-r border-line bg-bg-subtle">
      <div className="border-b border-line px-5 py-5">
        <p className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
          operious
        </p>
        <p className="mt-1 font-display text-lg text-fg">{t.app.title}</p>
        <p className="mt-1 text-xs text-fg-muted">{t.app.tagline}</p>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map((entry) => {
          const active = pathname?.startsWith(entry.href);
          return (
            <Link
              key={entry.href}
              href={entry.href}
              className={cn(
                'flex items-center justify-between rounded-sm px-3 py-2 font-mono text-2xs uppercase tracking-wider transition-colors',
                active
                  ? 'bg-bg-raised text-fg border border-line-strong'
                  : 'text-fg-muted hover:bg-bg-raised/60 hover:text-fg border border-transparent',
              )}
            >
              <span>{t.nav[entry.key]}</span>
              {active ? <span className="h-1.5 w-1.5 rounded-full bg-accent" /> : null}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-line px-5 py-4 space-y-3">
        <LocaleSwitcher />
        <p className="text-2xs text-fg-dim font-mono uppercase tracking-wider">
          {t.common.authorityNotice}
        </p>
      </div>
    </aside>
  );
};
