import Link from 'next/link';
import { Lockup } from './brand/lockup';

interface Group {
  readonly heading: string;
  readonly items: ReadonlyArray<{ readonly label: string; readonly href: string }>;
}

const GROUPS: ReadonlyArray<Group> = [
  {
    heading: 'Features',
    items: [
      { label: 'Operational Kernel', href: '#kernel' },
      { label: 'Governance Substrate', href: '#kernel' },
      { label: 'Trace Inspector', href: '#products' },
      { label: 'Cognition Hub', href: '#products' },
      { label: 'Channel Boundaries', href: '#kernel' },
      { label: 'Topology Configurator', href: '#kernel' },
      { label: 'Authority Context System', href: '#kernel' },
      { label: 'Replay Engine', href: '#trust' },
    ],
  },
  {
    heading: 'Solutions',
    items: [
      { label: 'Hardware Operations', href: '#solutions' },
      { label: 'Financial Services', href: '#solutions' },
      { label: 'Healthcare Operations', href: '#solutions' },
      { label: 'Telecommunications', href: '#solutions' },
      { label: 'Logistics & Supply Chain', href: '#solutions' },
      { label: 'Public Sector', href: '#solutions' },
      { label: 'Custom Domains', href: '#contact' },
    ],
  },
  {
    heading: 'Resources',
    items: [
      { label: 'Documentation', href: '#editorial' },
      { label: 'Engineering Articles', href: '#editorial' },
      { label: 'Newsletter', href: '#newsletter' },
      { label: 'FAQs', href: '#faq' },
      { label: 'Architecture Overview', href: '#kernel' },
      { label: 'Security & Compliance', href: '#faq' },
      { label: 'Status Page', href: '#trust' },
    ],
  },
  {
    heading: 'Popular Topics',
    items: [
      { label: 'How Governance Substrate Works', href: '#kernel' },
      { label: 'Cryptographic Decision Lineage', href: '#trust' },
      { label: 'Tenant Isolation Doctrine', href: '#kernel' },
      { label: 'Why Fail-Closed Defaults Matter', href: '#trust' },
      { label: 'Organizational Cognition Patterns', href: '#products' },
      { label: 'Replay-Safe Execution', href: '#trust' },
      { label: 'Multilingual Operational Boundaries', href: '#kernel' },
    ],
  },
];

const COMPANY_LINKS = [
  { label: 'About', href: '#kernel' },
  { label: 'Careers', href: 'mailto:career@operious.com' },
  { label: 'Contact', href: '#contact' },
  { label: 'Press', href: 'mailto:info@operious.com' },
  { label: 'Partners', href: 'mailto:info@operious.com' },
];

const EMAILS = ['info@operious.com', 'ops@operious.com', 'career@operious.com'];

export const SiteFooter = () => (
  <footer className="ambient-dark relative overflow-hidden bg-dark-canvas text-dark-ink">
    <div className="relative mx-auto max-w-hero px-6 pb-12 pt-24 md:px-16 md:pt-32">
      <div className="flex flex-col gap-4 border-b border-dark-line pb-12 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4">
          <Lockup variant="dark" sealSize={48} animated={false} />
        </div>
        <p className="eyebrow text-dark-ink-muted">DETERMINISTIC ENTERPRISE OPERATIONS</p>
      </div>

      <div className="grid gap-10 py-12 md:grid-cols-2 lg:grid-cols-5">
        {GROUPS.map((group) => (
          <div key={group.heading}>
            <p className="eyebrow text-gold-highlight">{group.heading.toUpperCase()}</p>
            <ul className="mt-5 space-y-3">
              {group.items.map((item) => (
                <li key={item.label}>
                  <Link
                    href={item.href}
                    data-cursor="interactive"
                    className="body-s text-dark-ink-muted transition-colors duration-[160ms] hover:text-dark-ink"
                  >
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}

        <div>
          <p className="eyebrow text-gold-highlight">COMPANY</p>
          <ul className="mt-5 space-y-3">
            {COMPANY_LINKS.map((item) => (
              <li key={item.label}>
                <Link
                  href={item.href}
                  data-cursor="interactive"
                  className="body-s text-dark-ink-muted transition-colors duration-[160ms] hover:text-dark-ink"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>

          <div className="mt-8">
            <p className="eyebrow text-gold-highlight">CONTACTS</p>
            <ul className="mt-4 space-y-2">
              {EMAILS.map((email) => (
                <li key={email}>
                  <a
                    href={`mailto:${email}`}
                    data-cursor="interactive"
                    className="body-s text-dark-ink-muted transition-colors duration-[160ms] hover:text-dark-ink"
                  >
                    {email}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4 border-t border-dark-line pt-6 md:flex-row md:items-center md:justify-between">
        <p className="eyebrow text-dark-ink-muted">
          © 2026 Operious AI. All operational guarantees reserved.
        </p>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 eyebrow text-dark-ink-muted">
          <Link href="#faq" className="hover:text-dark-ink">Privacy Policy</Link>
          <Link href="#faq" className="hover:text-dark-ink">Terms of Service</Link>
          <Link href="#faq" className="hover:text-dark-ink">Security</Link>
          <Link href="#trust" className="hover:text-dark-ink">Trust Center</Link>
        </div>
        <span className="inline-flex items-center gap-2 rounded-full border border-success/30 bg-success/10 px-3 py-1 eyebrow text-success">
          <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-success" />
          All substrates operational
        </span>
      </div>
    </div>
  </footer>
);

export default SiteFooter;
