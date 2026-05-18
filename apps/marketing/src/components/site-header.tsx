import Link from 'next/link';
import { Button } from '@operious/ui';

export const SiteHeader = () => (
  <header className="sticky top-0 z-50 border-b border-line bg-bg/80 backdrop-blur">
    <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
      <Link href="/" className="flex items-center gap-2">
        <span className="font-mono text-2xs uppercase tracking-widest text-fg-subtle">
          operious.ai
        </span>
        <span className="rounded-sm border border-line-subtle bg-bg-inset px-1.5 py-0.5 font-mono text-2xs text-fg-muted">
          v0
        </span>
      </Link>
      <nav className="hidden items-center gap-8 md:flex">
        {[
          { href: '#architecture', label: 'Architecture' },
          { href: '#governance', label: 'Governance' },
          { href: '#multilingual', label: 'Multilingual' },
          { href: '#command-center', label: 'Command Center' },
        ].map((entry) => (
          <Link
            key={entry.href}
            href={entry.href}
            className="font-mono text-2xs uppercase tracking-wider text-fg-muted transition-colors hover:text-fg"
          >
            {entry.label}
          </Link>
        ))}
      </nav>
      <Link href="#pilot">
        <Button variant="primary" size="sm">
          Request Pilot
        </Button>
      </Link>
    </div>
  </header>
);
