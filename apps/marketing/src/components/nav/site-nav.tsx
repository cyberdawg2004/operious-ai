'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { Lockup } from '../brand/lockup';

interface NavItem {
  readonly label: string;
  readonly href: string;
  readonly description?: string;
}
interface NavGroup {
  readonly id: string;
  readonly label: string;
  readonly columnHeading: string;
  readonly items: ReadonlyArray<NavItem>;
}

const NAV_GROUPS: ReadonlyArray<NavGroup> = [
  {
    id: 'solutions',
    label: 'Solutions',
    columnHeading: 'By industry',
    items: [
      {
        label: 'Hardware & Consumer Electronics',
        href: '#solutions',
        description: 'RMA, warranty triage, refund authorization with cryptographic policy compliance.',
      },
      {
        label: 'Financial Services & Insurance',
        href: '#solutions',
        description: 'KYC exception handling, claims triage, dispute resolution with full audit lineage.',
      },
      {
        label: 'Healthcare Operations',
        href: '#solutions',
        description: 'Prior auth, claims appeals, and patient intake within HIPAA-aligned tenant boundaries.',
      },
      {
        label: 'Telecommunications',
        href: '#solutions',
        description: 'Service provisioning exceptions, billing dispute resolution, deterministic SLA tracking.',
      },
      {
        label: 'Logistics & Supply Chain',
        href: '#solutions',
        description: 'Carrier exception routing, customs documentation triage, multi-jurisdictional workflows.',
      },
      {
        label: 'Public Sector Operations',
        href: '#solutions',
        description: 'Permit processing, eligibility determination, and procedural audit reconstruction.',
      },
    ],
  },
  {
    id: 'products',
    label: 'Products',
    columnHeading: 'By capability',
    items: [
      {
        label: 'Operational Kernel',
        href: '#kernel',
        description: 'The deterministic substrate underlying every Operious deployment.',
      },
      {
        label: 'Command Center',
        href: '#products',
        description: 'The operator interface for managers, auditors, and compliance officers.',
      },
      {
        label: 'Governance Substrate',
        href: '#kernel',
        description: 'The mathematical policy enforcement layer.',
      },
      {
        label: 'Trace Inspector',
        href: '#products',
        description: 'Forensic decision reconstruction for any historical event.',
      },
      {
        label: 'Cognition Hub',
        href: '#products',
        description: 'Governed organizational knowledge evolution.',
      },
      {
        label: 'Channel Boundaries',
        href: '#kernel',
        description: 'Multilingual ingress adapters with frozen boundary envelopes.',
      },
    ],
  },
  {
    id: 'platform',
    label: 'Platform',
    columnHeading: 'By architecture layer',
    items: [
      {
        label: 'Architecture Overview',
        href: '#kernel',
        description: 'A guided walk through every substrate layer.',
      },
      {
        label: 'Substrate Model',
        href: '#kernel',
        description: 'How tenant isolation is enforced by mathematical contract.',
      },
      {
        label: 'Governance Doctrine',
        href: '#trust',
        description: 'Why empty policy chains return deny — fail-closed semantics.',
      },
      {
        label: 'Replay & Audit',
        href: '#trust',
        description: 'Cryptographic determinism and event-fabric lineage.',
      },
      {
        label: 'Security & Compliance',
        href: '#faq',
        description: 'Tenant isolation, RLS, encryption-at-rest per tenant.',
      },
      {
        label: 'Integrations',
        href: '#faq',
        description: 'Email, WhatsApp, Lark, voice, and webhook ingress.',
      },
    ],
  },
  {
    id: 'resources',
    label: 'Resources',
    columnHeading: 'For operators',
    items: [
      {
        label: 'Documentation',
        href: '#editorial',
        description: 'Full technical reference for substrate operators.',
      },
      {
        label: 'Articles',
        href: '#editorial',
        description: 'Editorial writing on governed AI execution.',
      },
      {
        label: 'Newsletter',
        href: '#newsletter',
        description: 'Weekly intelligence on governed execution.',
      },
      {
        label: 'FAQs',
        href: '#faq',
        description: 'Questions frequently considered by enterprise procurement.',
      },
      {
        label: 'Engineering Blog',
        href: '#editorial',
        description: 'Behind the substrate — engineering doctrine notes.',
      },
      {
        label: 'Case Studies',
        href: '#editorial',
        description: 'Anonymized customer narratives from regulated environments.',
      },
    ],
  },
];

export const SiteNav = () => {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const closeTimer = useRef<number | null>(null);

  useEffect(() => {
    // Spec: navigation gains its surfaced background past 80px of scroll.
    const onScroll = () => setScrolled(window.scrollY > 80);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(null);
        setMobileOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const handleEnter = (id: string) => {
    if (closeTimer.current) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setOpen(id);
  };
  const handleLeave = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setOpen(null), 120);
  };

  return (
    <header
      className={[
        // Sticky, 72px tall, transitions at 80px scroll into surfaced state.
        'sticky top-0 z-50 transition-[background-color,border-color,backdrop-filter] duration-300 ease-out',
        scrolled
          ? 'bg-canvas/85 backdrop-blur-md border-b border-line-subtle'
          : 'bg-transparent border-b border-transparent',
      ].join(' ')}
      onMouseLeave={handleLeave}
    >
      <div className="mx-auto flex h-[72px] max-w-hero items-center justify-between px-6 md:px-12">
        <Link href="/" className="group flex items-center" aria-label="Operious — home">
          <Lockup variant="light" sealSize={32} animated />
        </Link>

        <nav
          className="hidden items-center gap-8 lg:flex"
          aria-label="Primary"
        >
          {NAV_GROUPS.map((group) => (
            <div
              key={group.id}
              className="relative"
              onMouseEnter={() => handleEnter(group.id)}
            >
              <button
                type="button"
                aria-haspopup="true"
                aria-expanded={open === group.id}
                onFocus={() => handleEnter(group.id)}
                data-cursor="interactive"
                onClick={() =>
                  setOpen((current) => (current === group.id ? null : group.id))
                }
                className={[
                  'h-[72px] body-s transition-colors duration-[160ms]',
                  open === group.id
                    ? 'text-ink-primary'
                    : 'text-ink-body hover:text-ink-primary',
                ].join(' ')}
              >
                {group.label}
              </button>
            </div>
          ))}
        </nav>

        <div className="hidden items-center gap-4 lg:flex">
          <Link
            href="#contact"
            data-cursor="interactive"
            className="body-s text-ink-body transition-colors duration-[160ms] hover:text-ink-primary"
          >
            Sign In
          </Link>
          <Link
            href="#contact"
            data-cursor="interactive"
            className="rounded-sm border border-gold/70 px-3 py-2 body-s text-ink-primary transition-colors duration-[160ms] hover:border-gold hover:bg-gold/5"
          >
            Register
          </Link>
          <Link
            href="#contact"
            data-cursor="interactive"
            className="rounded-sm bg-ink-primary px-3 py-2 body-s text-canvas-surface transition-colors duration-[160ms] hover:bg-ink-body"
          >
            Contact Us
          </Link>
        </div>

        <button
          type="button"
          className="lg:hidden inline-flex h-10 w-10 items-center justify-center rounded-md border border-line text-ink-primary"
          aria-label="Open navigation"
          aria-expanded={mobileOpen}
          onClick={() => setMobileOpen((value) => !value)}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden>
            <path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </button>
      </div>

      {/* Desktop dropdown — opens 12px below nav (top-[84px]) per spec. */}
      {open ? (
        <div
          className="hidden lg:block absolute inset-x-0 top-[84px] mx-6 rounded-md border border-line-subtle bg-canvas-surface shadow-dropdown"
          onMouseEnter={() => handleEnter(open)}
        >
          <div className="mx-auto max-w-hero px-6 py-6">
            <div className="grid gap-x-12 gap-y-3 md:grid-cols-3">
              <div className="md:col-span-1">
                <p className="eyebrow text-gold">
                  {NAV_GROUPS.find((g) => g.id === open)?.columnHeading}
                </p>
                <p className="heading-m text-ink-primary mt-3">
                  {NAV_GROUPS.find((g) => g.id === open)?.label}
                </p>
                <p className="body-s text-ink-secondary mt-2 max-w-xs">
                  Each surface in this group is constitutionally isolated and
                  operates against the same governance substrate.
                </p>
              </div>
              <div className="md:col-span-2 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
                {NAV_GROUPS.find((g) => g.id === open)?.items.map((item) => (
                  <Link
                    key={item.label}
                    href={item.href}
                    data-cursor="interactive"
                    className="group rounded-sm p-3 transition-colors duration-[160ms] hover:bg-canvas-raised"
                  >
                    <p className="body-s text-ink-primary">{item.label}</p>
                    {item.description ? (
                      <p className="caption text-ink-secondary mt-1 leading-relaxed">
                        {item.description}
                      </p>
                    ) : null}
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Mobile drawer */}
      {mobileOpen ? (
        <div className="lg:hidden border-t border-line-subtle bg-canvas-surface">
          <div className="mx-auto max-w-7xl px-6 py-6 space-y-6">
            {NAV_GROUPS.map((group) => (
              <details key={group.id} className="group">
                <summary className="flex cursor-pointer items-center justify-between text-base font-medium text-ink-primary">
                  {group.label}
                  <span className="text-ink-tertiary group-open:rotate-180 transition-transform">
                    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
                      <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.6" />
                    </svg>
                  </span>
                </summary>
                <ul className="mt-3 space-y-2 pl-1">
                  {group.items.map((item) => (
                    <li key={item.label}>
                      <Link
                        href={item.href}
                        className="block py-1.5 text-sm text-ink-body hover:text-ink-primary"
                        onClick={() => setMobileOpen(false)}
                      >
                        {item.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
            <div className="flex flex-col gap-2 pt-2 border-t border-line-subtle">
              <Link
                href="#contact"
                className="rounded-md border border-gold/70 px-4 py-2.5 text-center text-sm font-medium text-ink-primary"
              >
                Register
              </Link>
              <Link
                href="#contact"
                className="rounded-md bg-ink-primary px-4 py-2.5 text-center text-sm font-medium text-canvas-surface"
              >
                Contact Us
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
};

export default SiteNav;
