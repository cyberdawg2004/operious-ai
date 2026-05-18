import type { Metadata } from 'next';
import './globals.css';
import { SiteHeader } from '@/components/site-header';
import { SiteFooter } from '@/components/site-footer';

export const metadata: Metadata = {
  title: 'Operious AI — Governed Organizational Cognition Infrastructure',
  description:
    'Deterministic operational runtime infrastructure for the modern enterprise. Governed memory evolution. Replay-safe operational cognition. Inspectable authority.',
  metadataBase: new URL('https://operious.ai'),
  openGraph: {
    title: 'Operious AI',
    description: 'Governed Organizational Cognition Infrastructure.',
    type: 'website',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="bg-bg">
      <body className="min-h-screen bg-bg text-fg">
        <SiteHeader />
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
